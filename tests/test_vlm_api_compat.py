"""VLM / OpenAI 兼容 API 客户端回归测试

覆盖 VLM 视觉请求的兼容性修复点：
1. 空 api_key 时不发送 Authorization 头（本地模型无需鉴权）
2. 默认不发送 OpenAI 私有 detail 字段，避免非 OpenAI 网关 400/422
3. 图片 data URI 使用真实 MIME 类型
4. detail 被网关拒绝时自动降级重试
5. json_mode=json_object 配置对 VLM 请求实际生效
"""
import copy
import json
from unittest.mock import MagicMock, patch

import pytest
import requests


def _make_response(status_code, body=None, text=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text if text is not None else json.dumps(body if body is not None else {})
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} {resp.text}", response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = body if body is not None else {}
    return resp


def _ok_body(content="ok"):
    return {
        "choices": [{"message": {"content": content}}],
        "model": "m",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _import_client():
    from bt_cli.ai.llm_client import LLMClient
    return LLMClient


def _call_args(mock_call):
    """提取 requests.post 调用的 (url, payload)；深拷贝避免后续原地修改影响断言"""
    args, kwargs = mock_call
    return args[0], copy.deepcopy(kwargs["json"])


def test_empty_api_key_sends_no_auth_header():
    """空 api_key 时请求不应携带 Authorization 头"""
    LLMClient = _import_client()
    client = LLMClient(base_url="http://localhost:11434/v1", api_key="", model="qwen2.5vl")

    resp = _make_response(200, _ok_body())
    with patch("bt_cli.ai.llm_client.requests.post", return_value=resp) as m:
        client.chat([{"role": "user", "content": "hi"}])

    _, kwargs = m.call_args
    assert "Authorization" not in kwargs["headers"]


def test_api_key_sends_bearer_header():
    """配置 api_key 时发送 Bearer 头"""
    LLMClient = _import_client()
    client = LLMClient(base_url="https://api.openai.com/v1", api_key="sk-test", model="gpt-4o")

    resp = _make_response(200, _ok_body())
    with patch("bt_cli.ai.llm_client.requests.post", return_value=resp) as m:
        client.chat([{"role": "user", "content": "hi"}])

    _, kwargs = m.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"


def test_chat_with_image_default_no_detail_and_real_mime():
    """默认不发送 detail 字段；data URI 使用传入的真实 MIME"""
    LLMClient = _import_client()
    client = LLMClient(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                       api_key="k", model="qwen-vl-plus")

    resp = _make_response(200, _ok_body())
    with patch("bt_cli.ai.llm_client.requests.post", return_value=resp) as m:
        client.chat_with_image(
            text_prompt="看图", image_base64="QUJD", image_mime="image/jpeg"
        )

    url, payload = _call_args(m.call_args)
    user_content = payload["messages"][-1]["content"]
    img = user_content[1]
    assert img["image_url"]["url"].startswith("data:image/jpeg;base64,QUJD")
    assert "detail" not in img["image_url"]
    assert url == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def test_chat_with_image_detail_rejected_falls_back():
    """detail 被网关拒绝时应自动去掉 detail 重试成功"""
    LLMClient = _import_client()
    client = LLMClient(base_url="https://api.example.com/v1", api_key="k", model="vlm")

    fail_resp = _make_response(
        400,
        text="400 Bad Request: Additional properties are not allowed "
             "('detail' was unexpected)",
    )
    ok_resp = _make_response(200, _ok_body())

    # 在每次 post 发生时立即深拷贝请求体，避免后续原地修改影响断言
    captured = []

    def fake_post(url, **kwargs):
        captured.append(copy.deepcopy(kwargs["json"]))
        return fail_resp if len(captured) == 1 else ok_resp

    with patch("bt_cli.ai.llm_client.requests.post", side_effect=fake_post) as m:
        result = client.chat_with_image(
            text_prompt="看图", image_base64="QUJD",
            image_detail="high", image_mime="image/png",
        )

    assert result["content"] == "ok"
    assert m.call_count == 2
    img1 = captured[0]["messages"][-1]["content"][1]
    img2 = captured[1]["messages"][-1]["content"][1]
    assert "detail" in img1["image_url"]
    assert "detail" not in img2["image_url"]


def test_json_mode_object_applies_response_format():
    """json_mode=json_object 时 VLM 请求应带 response_format"""
    LLMClient = _import_client()
    client = LLMClient(base_url="https://api.example.com/v1", api_key="k",
                       model="vlm", json_mode="json_object")

    resp = _make_response(200, _ok_body(content='{"suggestions": []}'))
    with patch("bt_cli.ai.llm_client.requests.post", return_value=resp) as m:
        client.chat_with_image(text_prompt="看图", image_base64="QUJD")

    _, payload = _call_args(m.call_args)
    assert payload["response_format"] == {"type": "json_object"}


def test_vlm_analyzer_mime_detection():
    """截图 MIME 探测：PNG/JPEG/BMP/WEBP 及未知回退"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer

    detect = VLMAnalyzer._detect_mime
    assert detect(b"\x89PNG\r\n\x1a\n...") == "image/png"
    assert detect(b"\xff\xd8\xff\xe0...") == "image/jpeg"
    assert detect(b"BM\x36\x00...") == "image/bmp"
    assert detect(b"RIFF\x00\x00\x00\x00WEBP...") == "image/webp"
    assert detect(b"GIF89a...") == "image/png"  # 未识别回退


def test_vlm_analyzer_parse_json_with_surrounding_text():
    """VLM 返回内容夹杂说明文字时应提取出 JSON 对象"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer

    data = VLMAnalyzer._parse_json_object(
        '好的，以下是分析结果：{"suggestions": [{"node_id": "n1"}]} 请查收。'
    )
    assert data["suggestions"][0]["node_id"] == "n1"


def test_vlm_analyzer_empty_content_raises_clear_error():
    """VLM 返回空内容（模型不支持图片/被网关过滤）时给出明确诊断而非 JSON 报错"""
    from bt_cli.ai.llm_client import LLMClient
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer, VLMAnalysisError

    vlm_client = MagicMock(spec=LLMClient)
    vlm_client.base_url = "https://api.example.com/v1"
    vlm_client.model = "agnes-2.5-flash"
    vlm_client.chat_with_image.return_value = {"content": ""}

    analyzer = VLMAnalyzer(vlm_client=vlm_client)
    analyzer._debug = lambda *a, **k: None
    analyzer._extract_empty_params = lambda structure: [{"node_id": "n1"}]
    analyzer._encode_image = lambda path: ("image/png", "QUJD")
    analyzer._load_prompt = lambda: "system"
    analyzer._build_user_prompt = lambda fill, ctx: "看图给建议"

    with pytest.raises(VLMAnalysisError) as exc:
        analyzer.analyze("shot.png", {"nodes": []}, "上下文")

    assert "返回内容为空" in str(exc.value)
    assert "视觉" in str(exc.value)
    vlm_client.chat_with_image.assert_called_once()
