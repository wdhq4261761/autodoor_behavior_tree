# tests/test_iteration_engine.py
"""IterationEngine 测试

环境说明:
    bt_utils/__init__.py 会 eager-import OCRManager / ScriptRecorder 等模块,
    它们依赖 rapidocr / pynput 等重型三方库。本测试通过 mock LLMClient
    来隔离真实 API 调用,因此在导入前用 MagicMock 占位缺失的可选依赖,
    使潜在的 eager import 链不致中断。
"""
import pytest
import json
import sys
from unittest.mock import patch, MagicMock

# ------------------------------------------------------------------
# 在导入前,为环境中缺失的可选重型依赖注入 Mock
# ------------------------------------------------------------------
_MISSING_OPTIONAL_DEPS = [
    "rapidocr", "pynput", "pynput.mouse", "pynput.keyboard",
    "cv2", "pyautogui", "win32api", "win32con", "win32gui",
    "win32process", "win32clipboard", "win32event", "pyperclip",
]
for _name in _MISSING_OPTIONAL_DEPS:
    if _name in sys.modules:
        continue
    try:
        # 只有"确实无法导入"的模块才注入 Mock。
        # 原实现只判断 sys.modules，会在纯净环境或不同执行顺序下，
        # 把已安装的 cv2 / rapidocr 等真实模块替换成 MagicMock 并永久驻留，
        # 导致后续测试拿到 MagicMock 而大面积失败（表现为解包得到 0 个值）。
        __import__(_name)
    except ImportError:
        sys.modules[_name] = MagicMock()


def test_analyze_failure_returns_suggestions():
    """测试失败分析返回修正建议"""
    from bt_cli.ai.iteration_engine import IterationEngine

    mock_llm_response = {
        "content": json.dumps({
            "analysis": "OCR识别失败，可能区域过小",
            "fixes": [
                {
                    "node_id": "node_detect",
                    "param": "region",
                    "new_value": [100, 200, 400, 400],
                    "reason": "扩大检测区域以提高识别率"
                }
            ],
            "confidence": 0.85
        }, ensure_ascii=False),
        "model": "gpt-4o",
        "usage": {},
    }

    test_report = {
        "success": False,
        "node_statuses": {
            "node_start": "success",
            "node_detect": "failure",
            "node_click": "skipped",
        },
        "logs": ["[FAILURE] node_detect: OCR识别失败"],
        "blackboard": {},
    }

    tree_data = {
        "nodes": {
            "node_detect": {"type": "OCRConditionNode", "config": {"region": [100, 200, 200, 250]}},
        }
    }

    with patch("bt_cli.ai.iteration_engine.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        engine = IterationEngine()
        result = engine.analyze_failure(test_report, tree_data, "测试任务")

    assert "analysis" in result
    assert len(result["fixes"]) == 1
    assert result["fixes"][0]["node_id"] == "node_detect"


def test_apply_fixes_modifies_tree():
    """测试应用修正建议到行为树"""
    from bt_cli.ai.iteration_engine import IterationEngine

    engine = IterationEngine()

    tree_data = {
        "nodes": {
            "node_detect": {"id": "node_detect", "type": "OCRConditionNode",
                           "config": {"region": [100, 200, 200, 250], "keywords": "test"},
                           "children": []},
        }
    }

    fixes = [
        {"node_id": "node_detect", "param": "region",
         "new_value": [100, 200, 400, 400], "reason": "扩大区域"}
    ]

    fixed_tree = engine.apply_fixes(tree_data, fixes)
    assert fixed_tree["nodes"]["node_detect"]["config"]["region"] == [100, 200, 400, 400]


def test_apply_fixes_does_not_mutate_original():
    """测试 apply_fixes 不修改原始数据（深拷贝）"""
    from bt_cli.ai.iteration_engine import IterationEngine

    engine = IterationEngine()
    tree_data = {
        "nodes": {
            "node_1": {"id": "node_1", "type": "DelayNode",
                       "config": {"duration_ms": 1000}, "children": []},
        }
    }
    fixes = [
        {"node_id": "node_1", "param": "duration_ms",
         "new_value": 2000, "reason": "增加延时"}
    ]
    fixed_tree = engine.apply_fixes(tree_data, fixes)
    # 原始数据不受影响
    assert tree_data["nodes"]["node_1"]["config"]["duration_ms"] == 1000
    # 修正后的数据已更新
    assert fixed_tree["nodes"]["node_1"]["config"]["duration_ms"] == 2000


def test_analyze_failure_llm_error():
    """测试 LLM 请求异常时抛出 IterationError"""
    from bt_cli.ai.iteration_engine import IterationEngine, IterationError

    test_report = {"success": False, "node_statuses": {}, "logs": ["error"], "blackboard": {}}
    tree_data = {"nodes": {}}

    with patch("bt_cli.ai.iteration_engine.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("connection refused")
        mock_client_cls.from_config.return_value = mock_client

        engine = IterationEngine()
        with pytest.raises(IterationError, match="LLM 请求失败"):
            engine.analyze_failure(test_report, tree_data, "测试")


def test_analyze_failure_invalid_json():
    """测试 LLM 返回无效 JSON 时抛出 IterationError"""
    from bt_cli.ai.iteration_engine import IterationEngine, IterationError

    mock_llm_response = {
        "content": "这不是JSON格式",
        "model": "gpt-4o",
        "usage": {},
    }

    test_report = {"success": False, "node_statuses": {}, "logs": ["error"], "blackboard": {}}
    tree_data = {"nodes": {}}

    with patch("bt_cli.ai.iteration_engine.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        engine = IterationEngine()
        with pytest.raises(IterationError, match="JSON 无效"):
            engine.analyze_failure(test_report, tree_data, "测试")


def test_apply_fixes_skips_invalid_fix():
    """测试 apply_fixes 跳过不规范的 fix 条目"""
    from bt_cli.ai.iteration_engine import IterationEngine

    engine = IterationEngine()
    tree_data = {
        "nodes": {
            "node_1": {"id": "node_1", "type": "DelayNode",
                       "config": {"duration_ms": 1000}, "children": []},
        }
    }
    fixes = [
        {"node_id": "node_1", "param": "duration_ms", "new_value": 2000},
        {"node_id": "nonexistent", "param": "x", "new_value": 1},  # 不存在的节点
        {"param": "missing_node_id"},  # 缺少 node_id
        "not_a_dict",  # 不是字典
    ]
    fixed_tree = engine.apply_fixes(tree_data, fixes)
    # 只有第一个 fix 被应用
    assert fixed_tree["nodes"]["node_1"]["config"]["duration_ms"] == 2000
