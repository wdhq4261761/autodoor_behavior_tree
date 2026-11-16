"""通用 OpenAI 兼容 API 客户端

支持任意 OpenAI 兼容 API（OpenAI / Azure / 通义千问 / 本地 Ollama 等）。
只需配置 base_url + api_key + model 即可切换模型。
"""
import json
import requests
from typing import Any, Dict, List, Optional


class LLMClientError(Exception):
    """LLM 客户端错误"""
    pass


class LLMClient:
    """通用 LLM/VLM API 客户端（OpenAI 兼容协议）"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout_ms: int = 30000, max_tokens: int = 4096,
                 json_mode: str = "auto"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_ms = timeout_ms
        self.max_tokens = max_tokens
        # json_mode: "auto"（自动降级）/ "json_object"（始终启用）/ "none"（禁用）
        self.json_mode = (json_mode or "auto").lower()

    @classmethod
    def from_config(cls, config_key: str = "llm") -> "LLMClient":
        """从 SettingsManager 配置创建客户端

        Args:
            config_key: "llm" 或 "vlm"，对应 ai.llm / ai.vlm 配置段
        """
        from config.settings_manager import get_settings_manager
        sm = get_settings_manager()

        return cls(
            base_url=sm.get(f"ai.{config_key}.base_url", "https://api.openai.com/v1"),
            api_key=sm.get(f"ai.{config_key}.api_key", ""),
            model=sm.get(f"ai.{config_key}.model", "gpt-4o"),
            timeout_ms=sm.get(f"ai.{config_key}.timeout_ms", 300000),
            max_tokens=sm.get(f"ai.{config_key}.max_tokens", 4096),
            json_mode=sm.get(f"ai.{config_key}.json_mode", "auto"),
        )

    def chat(self, messages: List[Dict[str, Any]],
             temperature: float = 0.7,
             response_format: Optional[Dict] = None) -> Dict[str, Any]:
        """发送文本对话请求

        Args:
            messages: 消息列表 [{"role": "system/user/assistant", "content": "..."}]
            temperature: 温度参数
            response_format: 响应格式（如 {"type": "json_object"}）

        Returns:
            {"content": str, "model": str, "usage": dict, "raw": dict}
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        resp_format = response_format
        # json_mode 为 "none" 时禁用 response_format
        if self.json_mode == "none":
            resp_format = None
        if resp_format:
            payload["response_format"] = resp_format

        try:
            resp = self._post("/chat/completions", payload)
        except LLMClientError as e:
            # auto 模式下，若模型不支持 json_object 则去除该参数重试一次
            if (self.json_mode == "auto" and resp_format
                    and resp_format.get("type") == "json_object"
                    and self._is_json_object_unsupported(e)):
                payload.pop("response_format", None)
                resp = self._post("/chat/completions", payload)
            else:
                raise
        choice = resp["choices"][0]
        content = choice["message"]["content"] or ""
        return {
            "content": self._strip_code_fence(content),
            "model": resp.get("model", self.model),
            "usage": resp.get("usage", {}),
            "raw": resp,
        }

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """剥离 LLM 返回内容中的 markdown 代码围栏（```json / ``` 等）

        部分模型即使指定了 json_object 仍会返回 ```json ... ``` 包裹的内容，
        直接 json.loads 会因首字符是反引号而失败。此函数提取围栏内的 JSON 文本。
        """
        if not isinstance(text, str):
            return text
        stripped = text.strip()
        fence = "```"
        if stripped.startswith(fence):
            # 去掉开头的 ``` 及紧随其后的语言标识（如 json）
            first_nl = stripped.find("\n")
            if first_nl == -1:
                end = stripped.find(fence, len(fence))
                return stripped[len(fence):end].strip() if end != -1 else stripped
            body = stripped[first_nl + 1:]
            end = body.rfind(fence)
            if end != -1:
                body = body[:end]
            return body.strip()
        return text

    @staticmethod
    def _is_json_object_unsupported(error: LLMClientError) -> bool:
        """判断错误是否为模型不支持 json_object"""
        msg = str(error).lower()
        return ("json_object" in msg and
                ("not supported" in msg or "not valid" in msg or "invalidparameter" in msg))

    def chat_with_image(self, text_prompt: str, image_base64: str,
                        image_detail: Optional[str] = None,
                        image_mime: str = "image/png",
                        system_prompt: str = "",
                        temperature: float = 0.3) -> Dict[str, Any]:
        """发送带图片的对话请求（VLM，OpenAI 兼容协议）

        Args:
            text_prompt: 文本提示
            image_base64: base64 编码的图片数据（不含 data: 前缀）
            image_detail: 图片精度 "low" / "high" / "auto；
                默认 None 表示不发送 detail 字段。该字段是 OpenAI 官方私有参数，
                智谱 / 通义 / Ollama / 部分中转网关等 OpenAI 兼容 VLM 可能不识别
                并直接返回 400/422，因此默认不发送；仅在需要精细控制
                （如使用 OpenAI 官方模型）时显式传入。
            image_mime: 图片 MIME 类型（如 image/png / image/jpeg / image/webp），
                必须与 image_base64 的真实数据格式一致，否则服务端解码失败。
            system_prompt: 系统提示词
            temperature: 温度参数

        Returns:
            {"content": str, "model": str, "usage": dict, "raw": dict}
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        image_url = {"url": f"data:{image_mime};base64,{image_base64}"}
        if image_detail:
            image_url["detail"] = image_detail
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": text_prompt},
                {"type": "image_url", "image_url": image_url},
            ],
        })

        response_format = None
        # 仅当显式配置 json_mode=json_object 时启用 JSON 输出约束；
        # 不支持的模型由 chat() 的 auto 降级逻辑自动去掉后重试。
        if self.json_mode == "json_object":
            response_format = {"type": "json_object"}

        try:
            return self.chat(messages, temperature=temperature,
                             response_format=response_format)
        except LLMClientError as e:
            # 非 OpenAI 网关可能不识别 detail 字段：移除后重试一次
            if image_detail and self._is_vision_detail_rejected(e):
                self._debug("[LLM] VLM 网关拒绝 detail 字段，降级为不发送重试")
                image_url.pop("detail", None)
                return self.chat(messages, temperature=temperature,
                                 response_format=response_format)
            raise

    @staticmethod
    def _is_vision_detail_rejected(error: LLMClientError) -> bool:
        """判断错误是否为网关不识别 image_url.detail 等扩展字段"""
        msg = str(error).lower()
        return ("400" in msg or "422" in msg) and any(
            k in msg for k in (
                "detail", "additional properties", "unknown field",
                "unexpected field", "not supported", "invalid parameter",
                "invalid request",
            )
        )

    def _post(self, path: str, payload: dict) -> dict:
        """发送 POST 请求

        Args:
            path: 端点路径，如 "/chat/completions"
            payload: 请求体

        当 base_url 已包含完整端点（如以 /chat/completions 或 /images/generations
        结尾）时，直接使用整个 base_url，避免重复拼接路径。
        """
        url = self.base_url if self.base_url.endswith(path) else f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        # 本地模型（Ollama / LM Studio 等）通常不配置 api_key，
        # 空 key 时不发送 Authorization 头，避免部分网关拒绝空 Bearer。
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._debug(f"[LLM] POST {url} | model={self.model} | timeout={self.timeout_ms}ms")
        try:
            resp = requests.post(
                url, json=payload, headers=headers,
                timeout=self.timeout_ms / 1000,
            )
            self._debug(f"[LLM] HTTP {resp.status_code} | body={resp.text[:300]}")
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            detail = f"{resp.status_code} {resp.text[:500]}"
            self._debug(f"[LLM] HTTPError {detail}")
            raise LLMClientError(f"API 返回错误: {detail}") from e
        except requests.exceptions.ConnectionError as e:
            self._debug(f"[LLM] ConnectionError 无法连接到 API: {url}")
            raise LLMClientError(f"无法连接到 API: {url}") from e
        except requests.exceptions.Timeout as e:
            self._debug(f"[LLM] Timeout ({self.timeout_ms}ms)")
            raise LLMClientError(f"API 请求超时 ({self.timeout_ms}ms)") from e
        except Exception as e:
            self._debug(f"[LLM] {type(e).__name__}: {e}")
            raise LLMClientError(f"API 请求失败: {e}") from e

    def _debug(self, message: str) -> None:
        """输出调试日志（LLM/VLM 请求链路）"""
        try:
            from bt_utils.log_manager import LogManager
            LogManager.debug_print(message)
        except Exception:
            try:
                print(message, flush=True)
            except Exception:
                pass

