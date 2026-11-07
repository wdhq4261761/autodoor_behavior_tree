# tests/test_llm_client.py
"""LLMClient 测试

环境说明:
    bt_utils/__init__.py 会 eager-import OCRManager / ScriptRecorder 等模块,
    它们依赖 rapidocr / pynput 等重型三方库。本测试仅关注 LLMClient 的
    API 调用逻辑,因此在导入前用 MagicMock 占位这些缺失的可选依赖。
"""
import os
import shutil
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import requests

# ------------------------------------------------------------------
# 在导入 LLMClient / SettingsManager 之前,为环境中缺失的可选重型依赖注入 Mock,
# 使 bt_utils/__init__.py 的 eager import 链不致中断。
# ------------------------------------------------------------------
_MISSING_OPTIONAL_DEPS = [
    "rapidocr",
    "pynput",
    "pynput.mouse",
    "pynput.keyboard",
    "cv2",
    "pyautogui",
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "win32clipboard",
    "win32event",
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


def _reset_settings_singleton():
    """彻底重置 SettingsManager 单例。

    SettingsManager 使用 @singleton 装饰器,其 ``_instance`` 存储在
    ``__new__`` 的闭包中,``reset_instance()`` 仅重置类属性,无法触及
    闭包变量。这里手动遍历闭包 cell 来完成真正的重置。
    """
    from config.settings_manager import SettingsManager

    # 先调用类方法重置类属性
    SettingsManager.reset_instance()

    # 再重置 __new__ 闭包中的 _instance 变量
    new_func = SettingsManager.__new__
    if hasattr(new_func, "__closure__") and new_func.__closure__:
        for cell in new_func.__closure__:
            try:
                val = cell.cell_contents
            except ValueError:
                # 空 cell,跳过
                continue
            if val is not None and isinstance(val, SettingsManager):
                # 取消可能挂起的延迟保存定时器,避免污染后续测试
                timer = getattr(val, "_save_timer", None)
                if timer is not None:
                    try:
                        timer.cancel()
                    except Exception:
                        pass
                cell.cell_contents = None


def _test_config_dir():
    """获取跨平台兼容的测试配置目录"""
    return os.path.join(tempfile.gettempdir(), "test_llm_config")


def test_llm_client_chat_text():
    """测试文本对话请求"""
    from bt_cli.ai.llm_client import LLMClient

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {"message": {"role": "assistant", "content": "你好，我是AI助手"}}
        ],
        "usage": {"total_tokens": 50}
    }
    mock_response.raise_for_status = MagicMock()

    with patch("bt_cli.ai.llm_client.requests.post", return_value=mock_response):
        client = LLMClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="gpt-4o",
        )
        result = client.chat(
            messages=[{"role": "user", "content": "你好"}],
        )

    assert result["content"] == "你好，我是AI助手"
    assert result["usage"]["total_tokens"] == 50
    assert result["model"] == "gpt-4o"


def test_llm_client_chat_with_image():
    """测试带图片的对话请求（VLM）"""
    from bt_cli.ai.llm_client import LLMClient

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {"message": {"role": "assistant", "content": '{"region": [100, 200, 300, 400]}'}}
        ],
        "usage": {"total_tokens": 100}
    }
    mock_response.raise_for_status = MagicMock()

    with patch("bt_cli.ai.llm_client.requests.post", return_value=mock_response):
        client = LLMClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="gpt-4o",
        )
        result = client.chat_with_image(
            text_prompt="分析截图中的按钮位置",
            image_base64="iVBORw0KGgoAAAANSUhEUg==",
            image_detail="high",
        )

    assert "region" in result["content"]


def test_llm_client_api_error():
    """测试 API 错误处理"""
    from bt_cli.ai.llm_client import LLMClient, LLMClientError

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")

    with patch("bt_cli.ai.llm_client.requests.post", return_value=mock_response):
        client = LLMClient(
            base_url="https://api.openai.com/v1",
            api_key="bad-key",
            model="gpt-4o",
        )
        with pytest.raises(LLMClientError):
            client.chat(messages=[{"role": "user", "content": "test"}])


def test_llm_client_from_config():
    """测试从 SettingsManager 配置创建客户端"""
    from bt_cli.ai.llm_client import LLMClient
    from config.settings_manager import SettingsManager

    _reset_settings_singleton()

    config_dir = _test_config_dir()
    shutil.rmtree(config_dir, ignore_errors=True)

    sm = SettingsManager(config_dir=config_dir)
    sm.set("ai.llm.base_url", "http://localhost:11434/v1")
    sm.set("ai.llm.api_key", "test-key")
    sm.set("ai.llm.model", "qwen2.5")

    client = LLMClient.from_config("llm")
    assert client.base_url == "http://localhost:11434/v1"
    assert client.api_key == "test-key"
    assert client.model == "qwen2.5"


def test_llm_client_json_object_auto_retry_without_response_format():
    """auto 模式下，模型不支持 json_object 时自动降级重试"""
    from bt_cli.ai.llm_client import LLMClient, LLMClientError

    # 第一次请求返回 400（json_object 不支持），第二次正常返回
    error_resp = MagicMock()
    error_resp.status_code = 400
    error_resp.text = ('{"error":{"code":"InvalidParameter",'
                       '"message":"The parameter `response_format.type` specified in the request '
                       'are not valid: `json_object` is not supported by this model.",'
                       '"param":"response_format.type","type":"BadRequest"}}')
    error_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("400 Bad Request")

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": '{"plan": "ok"}'}}],
        "usage": {"total_tokens": 10},
    }
    ok_resp.raise_for_status = MagicMock()

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return error_resp
        return ok_resp

    with patch("bt_cli.ai.llm_client.requests.post", side_effect=fake_post):
        client = LLMClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="local-model",
            json_mode="auto",
        )
        result = client.chat(
            messages=[{"role": "user", "content": "test"}],
            response_format={"type": "json_object"},
        )

    assert calls["n"] == 2
    assert result["content"] == '{"plan": "ok"}'


def test_llm_client_json_object_none_never_sends_response_format():
    """none 模式下不发送 response_format 参数"""
    from bt_cli.ai.llm_client import LLMClient

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}],
    }
    mock_response.raise_for_status = MagicMock()

    sent_payload = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent_payload.update(json or {})
        return mock_response

    with patch("bt_cli.ai.llm_client.requests.post", side_effect=fake_post):
        client = LLMClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="local-model",
            json_mode="none",
        )
        client.chat(
            messages=[{"role": "user", "content": "test"}],
            response_format={"type": "json_object"},
        )

    assert "response_format" not in sent_payload


def test_llm_client_json_object_auto_forwards_other_errors():
    """auto 模式下非 json_object 相关错误应原样抛出，不降级"""
    from bt_cli.ai.llm_client import LLMClient, LLMClientError

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = Exception("500 Internal Server Error")

    with patch("bt_cli.ai.llm_client.requests.post", return_value=mock_response):
        client = LLMClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="local-model",
            json_mode="auto",
        )
        with pytest.raises(LLMClientError):
            client.chat(
                messages=[{"role": "user", "content": "test"}],
                response_format={"type": "json_object"},
            )
