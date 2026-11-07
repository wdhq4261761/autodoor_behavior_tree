"""VLM 语义视觉插件 — 节点实现

设计原则（对应方案 v3 第 1 章）：

* **默认关闭**：节点不在主循环里高频使用，是否启用由配置决定；
* **按需开启**：适合状态迁移点、测试回归、确需语义判断的分支；
* **调用可审计**：每次调用记录耗时/缓存命中/预算消耗；
* **结果可缓存**：以画面感知哈希为键，同一画面不重复请求；
* **失败可降级**：超时或解析失败时按配置回退到颜色检测，最终仍失败则
  显式返回 FAILURE，绝不静默通过。

三个节点：

``VLMLocateNode``  自然语言定位目标，写黑板坐标（与 ColorConditionNode 兼容）
``VLMAssertNode``  是非断言，返回 True/False
``VLMReadNode``    读取画面中的字段文本，写入黑板
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
from typing import Any, Dict, Optional, Tuple

from bt_core.config import NodeConfig
from bt_core.nodes import ActionNode, ConditionNode, NodeStatus
from bt_utils.image_processor import ImageProcessor
from bt_utils.log_manager import LogManager


# ---------------------------------------------------------------------------
# 进程内缓存：{(phash, prompt_hash): (expire_ts_ms, payload)}
# ---------------------------------------------------------------------------
_CACHE: Dict[str, Tuple[float, Any]] = {}
_CACHE_MAX_ENTRIES = 64

_SYSTEM_PROMPT = (
    "你是屏幕视觉分析器。只输出一个 JSON 对象，不要输出任何解释、"
    "不要使用 Markdown 代码块。坐标以输入图片左上角为原点，单位为像素。"
)


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _parse_region(value) -> Optional[Tuple[int, int, int, int]]:
    """解析 region：支持 None / [x1,y1,x2,y2] / "x1,y1,x2,y2"。"""
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return tuple(int(v) for v in value)
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("，", ",").split(",") if p.strip()]
        if len(parts) == 4:
            return tuple(int(float(p)) for p in parts)
    return None


def _encode_image(img) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json(text: str) -> Optional[dict]:
    """从模型输出中提取 JSON 对象，兼容代码块与前后闲话。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None


def _cache_get(key: str) -> Optional[Any]:
    item = _CACHE.get(key)
    if not item:
        return None
    expire_at, payload = item
    if time.time() * 1000 >= expire_at:
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: str, payload: Any, ttl_ms: int) -> None:
    if ttl_ms <= 0:
        return
    if len(_CACHE) >= _CACHE_MAX_ENTRIES:
        now = time.time() * 1000
        for k in [k for k, (exp, _) in _CACHE.items() if exp <= now]:
            _CACHE.pop(k, None)
        while len(_CACHE) >= _CACHE_MAX_ENTRIES:
            _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[key] = (time.time() * 1000 + ttl_ms, payload)


def clear_cache() -> None:
    _CACHE.clear()


def _budget_take(context, limit: int) -> bool:
    """按单次运行消耗调用预算，超限返回 False。

    计数放在黑板上，天然随每次运行重置，不需要额外的生命周期钩子。
    """
    if limit <= 0:
        return True  # 0 表示不限制
    used = context.blackboard.get("_vlm_calls", 0) or 0
    if used >= limit:
        return False
    context.blackboard.set("_vlm_calls", used + 1)
    return True


def _resolve_client(node_config: NodeConfig):
    """节点级配置优先；未给则回落到全局 ai.vlm。"""
    from bt_cli.ai.llm_client import LLMClient

    base_url = str(node_config.get("base_url", "") or "").strip()
    model = str(node_config.get("model", "") or "").strip()
    timeout_ms = node_config.get_int("timeout_ms", 15000)

    if base_url and model:
        return LLMClient(
            base_url=base_url,
            api_key=str(node_config.get("api_key", "") or ""),
            model=model,
            timeout_ms=timeout_ms,
            max_tokens=node_config.get_int("max_tokens", 512),
        )

    client = LLMClient.from_config("vlm")
    if not client.base_url or not client.model:
        raise RuntimeError(
            "VLM 未配置：请在节点上指定 base_url/model，"
            "或在 config.json 的 ai.vlm 段配置"
        )
    # from_config 默认超时很长（300s），运行期必须收窄
    client.timeout_ms = timeout_ms
    client.max_tokens = node_config.get_int("max_tokens", 512)
    return client


def _capture(context, region_value):
    region = _parse_region(region_value)
    img = context.get_screenshot(region)
    if img is None:
        return None, None
    return img, region


def _compute_key(img, prompt: str) -> str:
    phash = ImageProcessor.compute_phash(img)
    digest = hashlib.md5(prompt.encode("utf-8")).hexdigest()[:12]
    return f"{phash}:{digest}"


def _log(node, level: str, message: str) -> None:
    LogManager.debug_print(f"[VLM][{node.NODE_TYPE}] {message}")


def _to_pixel(value_x, value_y, width: int, height: int,
              mode: str) -> Optional[Tuple[int, int]]:
    """把模型返回的坐标换算成截图内像素坐标。"""
    try:
        x = float(value_x)
        y = float(value_y)
    except (TypeError, ValueError):
        return None

    if mode == "ratio":
        x, y = x * width, y * height
    elif mode == "norm1000":
        x, y = x / 1000.0 * width, y / 1000.0 * height
    # abs：按像素直接用

    if not (0 <= x <= width and 0 <= y <= height):
        return None
    return int(round(x)), int(round(y))


# ---------------------------------------------------------------------------
# VLMLocateNode
# ---------------------------------------------------------------------------
class VLMLocateNode(ActionNode):
    """用自然语言描述定位目标，写黑板坐标。

    输出与 ``ColorConditionNode`` 完全一致（``last_detection_x`` /
    ``last_detection_y``），因此可以直接接 ExpressionNode + OffsetMoveNode +
    ClickHereNode 的既有链路。
    """

    NODE_TYPE = "VLMLocateNode"

    def _execute_action(self, context) -> NodeStatus:
        try:
            img, region = _capture(context, self.config.get("region", None))
            if img is None:
                return self._fail("截图失败")

            question = str(self.config.get("question", "") or "").strip()
            if not question:
                return self._fail("未配置 question（要定位什么）")

            ttl = self.config.get_int("cache_ttl_ms", 2000)
            prompt = self._build_prompt(question, img.size)
            key = _compute_key(img, prompt)

            payload = _cache_get(key)
            hit = payload is not None

            if not hit:
                limit = self.config.get_int("max_calls_per_run", 10)
                if not _budget_take(context, limit):
                    return self._fallback(
                        context, region, img,
                        f"已达单次运行调用上限 {limit}，改用兜底策略"
                    )
                payload = self._invoke(context, img, prompt)
                if payload is None:
                    return self._fallback(context, region, img, "VLM 调用或解析失败")
                _cache_put(key, payload, ttl)

            if not payload.get("found"):
                reason = payload.get("reason", "未找到目标")
                LogManager.instance().log_failure(
                    node_type="VLM定位节点", node_name=self.name,
                    reason=f"未找到: {reason}",
                )
                return NodeStatus.FAILURE

            point = _to_pixel(
                payload.get("x"), payload.get("y"),
                img.width, img.height,
                str(self.config.get("coord_mode", "abs") or "abs"),
            )
            if point is None:
                return self._fallback(context, region, img, "模型返回坐标非法")

            confidence = float(payload.get("confidence", 0) or 0)
            threshold = self.config.get_float("confidence_min", 0.6)
            if confidence < threshold:
                return self._fallback(
                    context, region, img,
                    f"置信度 {confidence:.2f} 低于阈值 {threshold:.2f}"
                )

            screen = (point[0] + region[0], point[1] + region[1]) if region else point
            self._save_position(context, screen)

            LogManager.instance().log_success(
                node_type="VLM定位节点", node_name=self.name
            )
            _log(self, "info",
                 f"{'缓存命中' if hit else '实时调用'} -> {screen} conf={confidence:.2f}")
            return NodeStatus.SUCCESS

        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"VLMLocateNode '{self.name}'")
            return self._fail(f"执行异常: {e}")

    def _build_prompt(self, question: str, size) -> str:
        return (
            f"图片尺寸 {size[0]}x{size[1]} 像素。\n"
            f"任务：{question}\n"
            "请只输出 JSON："
            '{"found": true/false, "x": 中心点x, "y": 中心点y, '
            '"confidence": 0到1, "reason": "简短理由"}\n'
            "坐标必须是相对本图片左上角的像素值。找不到目标时 found 为 false。"
        )

    def _invoke(self, context, img, prompt) -> Optional[dict]:
        retries = self.config.get_int("retry", 1)
        last_error = ""
        for attempt in range(retries + 1):
            try:
                client = _resolve_client(self.config)
                started = time.time()
                result = client.chat_with_image(
                    text_prompt=prompt,
                    image_base64=_encode_image(img),
                    image_detail=str(self.config.get("image_detail", "high")),
                    system_prompt=_SYSTEM_PROMPT,
                    temperature=0.0,
                )
                elapsed = int((time.time() - started) * 1000)
                payload = _extract_json(result.get("content", ""))
                if payload is not None:
                    _log(self, "info", f"调用成功 {elapsed}ms")
                    return payload
                last_error = "JSON 解析失败"
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
            if attempt < retries:
                _log(self, "warn", f"第 {attempt + 1} 次失败（{last_error}），重试")
                time.sleep(0.2)

        _log(self, "error", f"VLM 调用失败: {last_error}")
        return None

    def _fallback(self, context, region, img, reason: str) -> NodeStatus:
        """降级：配置了 fallback_color 时改用颜色检测，否则显式失败。"""
        color = str(self.config.get("fallback_color", "") or "").strip()
        if color:
            try:
                found, point = ImageProcessor.find_color(
                    img,
                    _parse_hex_color(color),
                    tolerance=self.config.get_int("fallback_tolerance", 50),
                    min_pixels=self.config.get_int("fallback_min_pixels", 8),
                )
                if found:
                    screen = (point[0] + region[0], point[1] + region[1]) if region else point
                    self._save_position(context, screen)
                    _log(self, "warn", f"{reason}；已降级为颜色检测 -> {screen}")
                    LogManager.instance().log_success(
                        node_type="VLM定位节点", node_name=self.name
                    )
                    return NodeStatus.SUCCESS
            except Exception as e:
                reason = f"{reason}；颜色兜底亦失败: {e}"

        return self._fail(reason)

    def _fail(self, reason: str) -> NodeStatus:
        LogManager.instance().log_failure(
            node_type="VLM定位节点", node_name=self.name, reason=reason
        )
        _log(self, "error", reason)
        return NodeStatus.FAILURE

    def _save_position(self, context, screen) -> None:
        key = str(self.config.get("position_key", "") or "last_detection_position")
        via = str(self.config.get("position_value_mode", "scalar") or "scalar")

        if via == "scalar":
            context.blackboard.set("last_detection_x", screen[0])
            context.blackboard.set("last_detection_y", screen[1])
        if self.config.get_bool("save_position", True):
            context.blackboard.set(key, screen)


def _parse_hex_color(text: str) -> Tuple[int, int, int]:
    s = text.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


# ---------------------------------------------------------------------------
# VLMAssertNode
# ---------------------------------------------------------------------------
class VLMAssertNode(ConditionNode):
    """语义是非断言：例如「是否出现错误弹窗」。

    只用于状态迁移点或低频确认，不要放在每轮循环里。
    """

    NODE_TYPE = "VLMAssertNode"

    def _check_condition(self, context) -> bool:
        try:
            img, region = _capture(context, self.config.get("region", None))
            if img is None:
                self._log_condition_result(False, "截图失败")
                return False

            question = str(self.config.get("question", "") or "").strip()
            if not question:
                self._log_condition_result(False, "未配置 question")
                return False

            expect = str(self.config.get("expect", "yes") or "yes").lower()
            prompt = self._build_prompt(question, img.size)
            key = _compute_key(img, prompt)

            payload = _cache_get(key)
            if payload is None:
                limit = self.config.get_int("max_calls_per_run", 10)
                if not _budget_take(context, limit):
                    self._log_condition_result(
                        False, f"已达单次运行调用上限 {limit}"
                    )
                    return False

                payload = _invoke_vlm(self.config, img, prompt, "VLM断言节点")
                if payload is None:
                    self._log_condition_result(False, "VLM 调用或解析失败")
                    return False
                _cache_put(key, payload, self.config.get_int("cache_ttl_ms", 2000))

            actual = bool(payload.get("answer", payload.get("found", False)))
            confidence = float(payload.get("confidence", 1.0) or 0)
            threshold = self.config.get_float("confidence_min", 0.0)

            if confidence < threshold:
                self._log_condition_result(
                    False, f"置信度 {confidence:.2f} 低于阈值 {threshold:.2f}"
                )
                return False

            if expect == "yes":
                ok = actual
            elif expect == "no":
                ok = not actual
            else:
                ok = actual

            self._log_condition_result(
                ok, f"expect={expect} actual={actual} conf={confidence:.2f}"
            )
            return ok

        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"VLMAssertNode '{self.name}'")
            self._log_condition_result(False, f"执行异常: {e}")
            return False

    def _build_prompt(self, question: str, size) -> str:
        return (
            f"图片尺寸 {size[0]}x{size[1]} 像素。\n"
            f"问题：{question}\n"
            "请只输出 JSON："
            '{"answer": true/false, "confidence": 0到1, "reason": "简短理由"}'
        )


# ---------------------------------------------------------------------------
# VLMReadNode
# ---------------------------------------------------------------------------
class VLMReadNode(ActionNode):
    """读取画面中的字段文本，写入黑板。"""

    NODE_TYPE = "VLMReadNode"

    def _execute_action(self, context) -> NodeStatus:
        try:
            img, _ = _capture(context, self.config.get("region", None))
            if img is None:
                return self._fail("截图失败")

            question = str(self.config.get("question", "") or "").strip()
            if not question:
                return self._fail("未配置 question（要读取什么）")

            write_to = str(self.config.get("write_to", "") or "").strip()
            if not write_to:
                return self._fail("未配置 write_to（写入哪个黑板变量）")

            prompt = (
                f"图片尺寸 {img.size[0]}x{img.size[1]} 像素。\n"
                f"任务：{question}\n"
                "请只输出 JSON："
                '{"value": "读到的内容", "confidence": 0到1}\n'
                "读不到时 value 为空字符串。"
            )
            key = _compute_key(img, prompt)

            payload = _cache_get(key)
            if payload is None:
                limit = self.config.get_int("max_calls_per_run", 10)
                if not _budget_take(context, limit):
                    return self._fail(f"已达单次运行调用上限 {limit}")
                payload = _invoke_vlm(self.config, img, prompt, "VLM读取节点")
                if payload is None:
                    return self._fail("VLM 调用或解析失败")
                _cache_put(key, payload, self.config.get_int("cache_ttl_ms", 2000))

            value = payload.get("value")
            if value is None:
                return self._fail("模型未返回 value 字段")

            context.blackboard.set(write_to, value)
            LogManager.instance().log_success(
                node_type="VLM读取节点", node_name=self.name
            )
            _log(self, "info", f"{write_to} = {value!r}")
            return NodeStatus.SUCCESS

        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"VLMReadNode '{self.name}'")
            return self._fail(f"执行异常: {e}")

    def _fail(self, reason: str) -> NodeStatus:
        LogManager.instance().log_failure(
            node_type="VLM读取节点", node_name=self.name, reason=reason
        )
        _log(self, "error", reason)
        return NodeStatus.FAILURE


# ---------------------------------------------------------------------------
# 共享调用
# ---------------------------------------------------------------------------
def _invoke_vlm(node_config: NodeConfig, img, prompt: str,
                tag: str) -> Optional[dict]:
    retries = node_config.get_int("retry", 1)
    last_error = ""
    for attempt in range(retries + 1):
        try:
            client = _resolve_client(node_config)
            started = time.time()
            result = client.chat_with_image(
                text_prompt=prompt,
                image_base64=_encode_image(img),
                image_detail=str(node_config.get("image_detail", "high")),
                system_prompt=_SYSTEM_PROMPT,
                temperature=0.0,
            )
            elapsed = int((time.time() - started) * 1000)
            payload = _extract_json(result.get("content", ""))
            if payload is not None:
                LogManager.debug_print(f"[VLM][{tag}] 调用成功 {elapsed}ms")
                return payload
            last_error = "JSON 解析失败"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        if attempt < retries:
            LogManager.debug_print(
                f"[VLM][{tag}] 第 {attempt + 1} 次失败（{last_error}），重试"
            )
            time.sleep(0.2)

    LogManager.debug_print(f"[VLM][{tag}] 调用失败: {last_error}")
    return None
