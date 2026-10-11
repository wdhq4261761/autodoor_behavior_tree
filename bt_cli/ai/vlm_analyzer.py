# bt_cli/ai/vlm_analyzer.py
"""阶段③ VLM 屏幕感知 — 分析截图为空参数生成建议值"""
import json
import os
import copy
import base64
from typing import Dict, Any, List

from bt_cli.ai.llm_client import LLMClient
from bt_cli.ai.resource_path import get_resource_path


class VLMAnalysisError(Exception):
    """VLM 分析错误"""
    pass


class VLMAnalyzer:
    """视觉大模型屏幕分析器

    分析截图，为行为树节点中的空参数（region/position/keywords 等）
    生成建议值。
    """

    PROMPT_FILE = get_resource_path(__file__, "prompts", "vlm_analysis.md")

    def __init__(self, vlm_client: LLMClient = None):
        self._vlm = vlm_client

    def analyze(self, screenshot_path: str, structure: Dict[str, Any],
                task_context: str) -> List[Dict[str, Any]]:
        """分析截图，为空参数生成建议值

        Args:
            screenshot_path: 截图文件路径
            structure: 节点结构（含 empty_params）
            task_context: 任务上下文描述

        Returns:
            建议值列表 [{"node_id", "param", "suggested_value", "confidence", "note"}]

        Raises:
            VLMAnalysisError: 分析失败
        """
        if self._vlm is None:
            self._vlm = LLMClient.from_config("vlm")

        # 提取待填充参数
        fill_requests = self._extract_empty_params(structure)
        if not fill_requests:
            return []

        # 编码截图（自动识别真实格式，避免 JPEG/BMP 被误传为 png 导致解码失败）
        image_mime, image_base64 = self._encode_image(screenshot_path)

        # 构建 prompt
        system_prompt = self._load_prompt()
        user_prompt = self._build_user_prompt(fill_requests, task_context)

        self._debug("[VLM] 开始屏幕感知分析")
        self._debug(
            f"[VLM] 配置: base_url={self._vlm.base_url} | model={self._vlm.model}"
        )
        self._debug(f"[VLM] 待填充参数数={len(fill_requests)} | 截图={screenshot_path}")
        self._debug(
            f"[VLM] 图片大小={len(image_base64)}字符(mime={image_mime}) | "
            f"user_prompt={user_prompt[:200]}"
        )

        try:
            result = self._vlm.chat_with_image(
                text_prompt=user_prompt,
                image_base64=image_base64,
                image_mime=image_mime,
                system_prompt=system_prompt,
            )
        except Exception as e:
            self._debug(f"[VLM] 请求失败: {e}")
            raise VLMAnalysisError(f"VLM 请求失败: {e}") from e

        self._debug(f"[VLM] 请求成功，原始返回内容: {(result.get('content') or '')[:300]}")

        raw_content = (result.get("content") or "").strip()
        if not raw_content:
            self._debug("[VLM] 返回内容为空")
            raise VLMAnalysisError(
                "VLM 返回内容为空：当前模型可能不支持图片输入，"
                "或回复被服务端过滤。请确认 VLM 配置的模型具备视觉能力，"
                "并检查 API Key 权限与 base_url 是否正确。"
            )

        try:
            data = self._parse_json_object(raw_content)
        except json.JSONDecodeError as e:
            self._debug(f"[VLM] JSON 解析失败: {e}")
            raise VLMAnalysisError(
                f"VLM 返回的 JSON 无效: {e}\n原始内容: {raw_content[:500]}"
            ) from e

        if not isinstance(data, dict):
            self._debug(f"[VLM] JSON 顶层非对象: {type(data).__name__}")
            raise VLMAnalysisError(
                f"VLM 返回的 JSON 应为对象，实际为 {type(data).__name__}: "
                f"{raw_content[:500]}"
            )

        suggestions = data.get("suggestions", [])

        self._debug(f"[VLM] 解析到建议值 {len(suggestions)} 条")
        return suggestions

    def fill_structure(self, structure: Dict[str, Any],
                       suggestions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """将建议值填入节点结构

        Args:
            structure: 节点结构
            suggestions: 建议值列表

        Returns:
            填充后的节点结构（深拷贝）
        """
        filled = copy.deepcopy(structure)

        # 创建查找索引
        nodes = filled.get("nodes", [])
        node_map = {n.get("id"): n for n in nodes if isinstance(n, dict)}

        for sug in suggestions:
            if not isinstance(sug, dict):
                continue
            node_id = sug.get("node_id")
            param = sug.get("param")
            value = sug.get("suggested_value")
            if node_id is None or param is None or value is None:
                continue

            if node_id in node_map:
                node = node_map[node_id]
                node.setdefault("config", {})[param] = value
                # 从 empty_params 中移除已填充的
                if "empty_params" in node:
                    node["empty_params"] = [
                        p for p in node["empty_params"] if p != param
                    ]

        return filled

    def _extract_empty_params(self, structure: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从节点结构中提取所有空参数"""
        requests = []
        for node in structure.get("nodes", []):
            if not isinstance(node, dict):
                continue
            for param in node.get("empty_params", []):
                requests.append({
                    "node_id": node.get("id", ""),
                    "param": param,
                    "node_type": node.get("type", ""),
                })
        return requests

    def _encode_image(self, image_path: str):
        """将图片编码为 base64，并探测真实 MIME 类型

        Returns:
            (mime_type, base64_string) 元组

        Raises:
            VLMAnalysisError: 文件读取失败
        """
        try:
            with open(image_path, "rb") as f:
                head = f.read(16)
                data = f.read()
        except (FileNotFoundError, IOError) as e:
            raise VLMAnalysisError(f"无法读取截图文件: {image_path}: {e}") from e

        mime = self._detect_mime(head)
        return mime, base64.b64encode(data).decode("utf-8")

    @staticmethod
    def _detect_mime(head: bytes) -> str:
        """根据文件头魔数识别图片 MIME 类型，未识别时回退 png"""
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
        if head[:2] == b"BM":
            return "image/bmp"
        return "image/png"

    @staticmethod
    def _parse_json_object(text: str) -> Any:
        """解析模型返回的 JSON；容忍前后夹杂说明文字（如 ```json 围栏已剥离、
        模型在对象前后附加解释性文本等场景）"""
        content = (text or "").strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # 提取第一个 { 到最后一个 } 之间的内容再次尝试
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = content[start:end + 1]
            return json.loads(candidate)
        raise json.JSONDecodeError("未找到有效的 JSON 对象", content, 0)

    def _build_user_prompt(self, fill_requests: List[Dict[str, Any]],
                           task_context: str) -> str:
        """构建用户提示词"""
        lines = [f"## 任务上下文\n{task_context}\n"]
        lines.append("## 需要填充的参数清单\n")
        for req in fill_requests:
            lines.append(f"- 节点 {req['node_id']} ({req['node_type']}): 参数 '{req['param']}'")
        lines.append("\n请分析截图，为以上参数提供建议值。")
        return "\n".join(lines)

    def _load_prompt(self) -> str:
        """加载系统提示词"""
        with open(self.PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read()

    def _debug(self, message: str) -> None:
        """输出 VLM 调试日志"""
        try:
            from bt_utils.log_manager import LogManager
            LogManager.debug_print(message)
        except Exception:
            try:
                print(message, flush=True)
            except Exception:
                pass

