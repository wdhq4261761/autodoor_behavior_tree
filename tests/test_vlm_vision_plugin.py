"""vlm_vision 插件的单元测试。

全部使用假客户端与假截图，不访问网络、不依赖真实屏幕，
重点验证：缓存命中、预算闸、坐标换算、失败显式返回。
"""
from __future__ import annotations

import json

import pytest
from PIL import Image

from bt_core.config import NodeConfig
from bt_core.context import ExecutionContext
from bt_core.nodes import NodeStatus
from plugins.vlm_vision import nodes as vn


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
class TestExtractJson:
    def test_plain_json(self):
        assert vn._extract_json('{"found": true, "x": 1}')["x"] == 1

    def test_with_code_fence(self):
        text = '```json\n{"found": false}\n```'
        assert vn._extract_json(text)["found"] is False

    def test_with_leading_prose(self):
        text = '好的，结果是：{"found": true, "x": 5} 以上。'
        assert vn._extract_json(text)["x"] == 5

    def test_invalid_returns_none(self):
        assert vn._extract_json("完全不是 JSON") is None

    def test_empty_returns_none(self):
        assert vn._extract_json("") is None


class TestToPixel:
    def test_abs_mode(self):
        assert vn._to_pixel(120, 80, 400, 300, "abs") == (120, 80)

    def test_ratio_mode(self):
        assert vn._to_pixel(0.5, 0.5, 400, 300, "ratio") == (200, 150)

    def test_norm1000_mode(self):
        assert vn._to_pixel(500, 500, 1000, 1000, "norm1000") == (500, 500)

    def test_out_of_bounds_returns_none(self):
        assert vn._to_pixel(9999, 10, 400, 300, "abs") is None

    def test_invalid_value_returns_none(self):
        assert vn._to_pixel("abc", 10, 400, 300, "abs") is None


class TestRegionParse:
    def test_list(self):
        assert vn._parse_region([1, 2, 3, 4]) == (1, 2, 3, 4)

    def test_string(self):
        assert vn._parse_region("1,2,3,4") == (1, 2, 3, 4)

    def test_none(self):
        assert vn._parse_region(None) is None

    def test_empty_string(self):
        assert vn._parse_region("") is None


class TestCache:
    def setup_method(self):
        vn.clear_cache()

    def test_put_and_get(self):
        vn._cache_put("k", {"v": 1}, 5000)
        assert vn._cache_get("k") == {"v": 1}

    def test_expired_returns_none(self):
        vn._cache_put("k", {"v": 1}, 1)
        import time
        time.sleep(0.01)
        assert vn._cache_get("k") is None

    def test_zero_ttl_not_cached(self):
        vn._cache_put("k", {"v": 1}, 0)
        assert vn._cache_get("k") is None


class TestBudget:
    def test_within_limit(self):
        ctx = ExecutionContext(project_root=".")
        assert vn._budget_take(ctx, 2) is True
        assert vn._budget_take(ctx, 2) is True

    def test_exceeds_limit(self):
        ctx = ExecutionContext(project_root=".")
        vn._budget_take(ctx, 1)
        assert vn._budget_take(ctx, 1) is False

    def test_zero_means_unlimited(self):
        ctx = ExecutionContext(project_root=".")
        for _ in range(50):
            assert vn._budget_take(ctx, 0) is True


# ---------------------------------------------------------------------------
# 节点行为
# ---------------------------------------------------------------------------
class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.timeout_ms = 1000
        self.max_tokens = 128

    def chat_with_image(self, **kwargs):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return {"content": content, "model": "fake", "usage": {}, "raw": {}}


def _patch(monkeypatch, payload):
    """替换截图来源与 VLM 客户端，返回假客户端实例。"""
    img = Image.new("RGB", (400, 300), (20, 20, 20))
    monkeypatch.setattr(vn, "_capture", lambda ctx, region: (img, (100, 50, 500, 350)))
    client = FakeClient(payload)
    monkeypatch.setattr(vn, "_resolve_client", lambda cfg: client)
    vn.clear_cache()
    return client


class TestVLMLocateNode:
    def test_success_writes_blackboard(self, monkeypatch):
        _patch(monkeypatch, {"found": True, "x": 120, "y": 80,
                             "confidence": 0.95, "reason": "ok"})
        cfg = NodeConfig.from_dict({
            "question": "红色靶心", "confidence_min": 0.5,
            "cache_ttl_ms": 5000, "retry": 0,
        })
        node = vn.VLMLocateNode(node_id="loc", config=cfg)
        ctx = ExecutionContext(project_root=".")

        assert node._execute_action(ctx) == NodeStatus.SUCCESS
        # region 偏移 (100,50) 应加到模型坐标上
        assert ctx.blackboard.get("last_detection_x") == 220
        assert ctx.blackboard.get("last_detection_y") == 130
        assert ctx.blackboard.get("last_detection_position") == (220, 130)

    def test_not_found_returns_failure(self, monkeypatch):
        _patch(monkeypatch, {"found": False, "reason": "画面中无此目标"})
        cfg = NodeConfig.from_dict({"question": "红色靶心", "retry": 0})
        node = vn.VLMLocateNode(node_id="loc", config=cfg)
        assert node._execute_action(ExecutionContext(project_root=".")) == NodeStatus.FAILURE

    def test_vlm_error_returns_failure_not_success(self, monkeypatch):
        """核心约束：VLM 不可用时必须显式失败，不能静默通过。"""
        _patch(monkeypatch, RuntimeError("404 UnsupportedModel"))
        cfg = NodeConfig.from_dict({"question": "红色靶心", "retry": 0})
        node = vn.VLMLocateNode(node_id="loc", config=cfg)
        assert node._execute_action(ExecutionContext(project_root=".")) == NodeStatus.FAILURE

    def test_cache_hit_avoids_second_call(self, monkeypatch):
        client = _patch(monkeypatch, {"found": True, "x": 10, "y": 10,
                                      "confidence": 0.9})
        cfg = NodeConfig.from_dict({
            "question": "红色靶心", "cache_ttl_ms": 60000, "retry": 0,
        })
        node = vn.VLMLocateNode(node_id="loc", config=cfg)
        ctx = ExecutionContext(project_root=".")

        node._execute_action(ctx)
        node._execute_action(ctx)
        assert client.calls == 1, f"缓存未生效，实际调用 {client.calls} 次"

    def test_budget_exhausted_blocks_call(self, monkeypatch):
        client = _patch(monkeypatch, {"found": True, "x": 10, "y": 10,
                                      "confidence": 0.9})
        cfg = NodeConfig.from_dict({
            "question": "红色靶心", "cache_ttl_ms": 0,
            "max_calls_per_run": 1, "retry": 0,
        })
        node = vn.VLMLocateNode(node_id="loc", config=cfg)
        ctx = ExecutionContext(project_root=".")

        assert node._execute_action(ctx) == NodeStatus.SUCCESS
        assert node._execute_action(ctx) == NodeStatus.FAILURE
        assert client.calls == 1

    def test_fallback_color_used_when_vlm_fails(self, monkeypatch):
        """配置兜底颜色后，VLM 失败应改走颜色检测而不是直接失败。"""
        img = Image.new("RGB", (400, 300), (20, 20, 20))
        from PIL import ImageDraw
        ImageDraw.Draw(img).rectangle([40, 40, 90, 90], fill=(226, 59, 59))

        monkeypatch.setattr(vn, "_capture", lambda ctx, region: (img, (0, 0, 400, 300)))
        monkeypatch.setitem(vn._CACHE, "__never__", (0, None))
        monkeypatch.setattr(
            vn, "_resolve_client",
            lambda cfg: FakeClient(RuntimeError("timeout")),
        )
        vn.clear_cache()

        cfg = NodeConfig.from_dict({
            "question": "红色方块", "retry": 0,
            "fallback_color": "#e23b3b", "cache_ttl_ms": 0,
        })
        node = vn.VLMLocateNode(node_id="loc", config=cfg)
        ctx = ExecutionContext(project_root=".")

        assert node._execute_action(ctx) == NodeStatus.SUCCESS
        assert ctx.blackboard.get("last_detection_x") is not None

    def test_low_confidence_rejected(self, monkeypatch):
        _patch(monkeypatch, {"found": True, "x": 10, "y": 10, "confidence": 0.2})
        cfg = NodeConfig.from_dict({
            "question": "x", "confidence_min": 0.8,
            "cache_ttl_ms": 0, "retry": 0,
        })
        node = vn.VLMLocateNode(node_id="loc", config=cfg)
        assert node._execute_action(ExecutionContext(project_root=".")) == NodeStatus.FAILURE


class TestVLMAssertNode:
    def test_expect_yes_matches(self, monkeypatch):
        _patch(monkeypatch, {"answer": True, "confidence": 0.9})
        cfg = NodeConfig.from_dict({
            "question": "是否有弹窗", "expect": "yes",
            "cache_ttl_ms": 0, "retry": 0,
        })
        node = vn.VLMAssertNode(node_id="a", config=cfg)
        assert node._check_condition(ExecutionContext(project_root=".")) is True

    def test_expect_no_inverts(self, monkeypatch):
        _patch(monkeypatch, {"answer": False, "confidence": 0.9})
        cfg = NodeConfig.from_dict({
            "question": "是否有弹窗", "expect": "no",
            "cache_ttl_ms": 0, "retry": 0,
        })
        node = vn.VLMAssertNode(node_id="a", config=cfg)
        assert node._check_condition(ExecutionContext(project_root=".")) is True

    def test_error_returns_false(self, monkeypatch):
        _patch(monkeypatch, RuntimeError("401"))
        cfg = NodeConfig.from_dict({"question": "x", "retry": 0})
        node = vn.VLMAssertNode(node_id="a", config=cfg)
        assert node._check_condition(ExecutionContext(project_root=".")) is False


class TestVLMReadNode:
    def test_reads_value_to_blackboard(self, monkeypatch):
        _patch(monkeypatch, {"value": "493", "confidence": 0.9})
        cfg = NodeConfig.from_dict({
            "question": "得分", "write_to": "score",
            "cache_ttl_ms": 0, "retry": 0,
        })
        node = vn.VLMReadNode(node_id="r", config=cfg)
        ctx = ExecutionContext(project_root=".")
        assert node._execute_action(ctx) == NodeStatus.SUCCESS
        assert ctx.blackboard.get("score") == "493"
