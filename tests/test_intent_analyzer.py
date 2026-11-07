# tests/test_intent_analyzer.py
"""IntentAnalyzer 测试

环境说明:
    bt_utils/__init__.py 会 eager-import OCRManager / ScriptRecorder 等模块,
    它们依赖 rapidocr / pynput 等重型三方库。本测试通过 mock LLMClient
    来隔离真实 API 调用,因此在导入前用 MagicMock 占位缺失的可选依赖,
    使潜在的 eager import 链不致中断。
"""
import json
import sys
from unittest.mock import patch, MagicMock

import pytest

# ------------------------------------------------------------------
# 在导入 IntentAnalyzer 之前,为环境中缺失的可选重型依赖注入 Mock,
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
    "pyperclip",
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


def test_analyze_returns_valid_plan():
    """测试意图分析返回有效的任务计划"""
    from bt_cli.ai.intent_analyzer import IntentAnalyzer

    mock_llm_response = {
        "content": json.dumps({
            "task_summary": "定时检测登录按钮并点击",
            "loop": {"enabled": True, "interval_ms": 60000, "max_iterations": -1},
            "phases": [
                {"phase": "detect", "method": "image_or_ocr", "target_description": "登录按钮",
                 "on_success": "proceed_to_click"},
                {"phase": "act", "action": "click", "position_source": "from_detection",
                 "on_complete": "loop_back"}
            ],
            "window": {"bind": False, "title": "", "pid": None}
        }, ensure_ascii=False),
        "model": "gpt-4o",
        "usage": {"total_tokens": 100},
    }

    with patch("bt_cli.ai.intent_analyzer.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        analyzer = IntentAnalyzer()
        result = analyzer.analyze("每分钟检查登录按钮并点击")

    assert result["task_summary"] == "定时检测登录按钮并点击"
    assert result["loop"]["enabled"] is True
    assert result["loop"]["interval_ms"] == 60000
    assert len(result["phases"]) == 2
    assert result["phases"][0]["phase"] == "detect"
    assert result["phases"][1]["phase"] == "act"


def test_analyze_handles_llm_error():
    """测试 LLM 错误处理"""
    from bt_cli.ai.intent_analyzer import IntentAnalyzer, IntentAnalysisError

    with patch("bt_cli.ai.intent_analyzer.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.side_effect = Exception("API error")
        mock_client_cls.from_config.return_value = mock_client

        analyzer = IntentAnalyzer()
        with pytest.raises(IntentAnalysisError):
            analyzer.analyze("测试描述")


def test_analyze_handles_invalid_json():
    """测试无效 JSON 响应处理"""
    from bt_cli.ai.intent_analyzer import IntentAnalyzer, IntentAnalysisError

    mock_llm_response = {
        "content": "这不是JSON格式的回复",
        "model": "gpt-4o",
        "usage": {},
    }

    with patch("bt_cli.ai.intent_analyzer.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        analyzer = IntentAnalyzer()
        with pytest.raises(IntentAnalysisError):
            analyzer.analyze("测试描述")
