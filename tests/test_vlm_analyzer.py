# tests/test_vlm_analyzer.py
"""VLMAnalyzer 测试

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
# 在导入 VLMAnalyzer 之前,为环境中缺失的可选重型依赖注入 Mock,
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


def test_analyze_returns_fill_suggestions():
    """测试 VLM 分析返回参数填充建议"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer

    mock_vlm_response = {
        "content": json.dumps({
            "suggestions": [
                {
                    "node_id": "node_detect",
                    "param": "region",
                    "suggested_value": [120, 300, 200, 340],
                    "confidence": 0.95,
                    "note": "检测到蓝色登录按钮"
                },
                {
                    "node_id": "node_click",
                    "param": "position",
                    "suggested_value": [160, 320],
                    "confidence": 0.90,
                    "note": "按钮中心位置"
                }
            ]
        }, ensure_ascii=False),
        "model": "gpt-4o",
        "usage": {},
    }

    structure = {
        "nodes": [
            {"id": "node_detect", "type": "ImageConditionNode",
             "config": {"region": [], "template_path": ""},
             "children": ["node_click"],
             "empty_params": ["region", "template_path"]},
            {"id": "node_click", "type": "MouseClickNode",
             "config": {"position": [], "use_blackboard": True},
             "children": [],
             "empty_params": ["position"]},
        ]
    }

    with patch("bt_cli.ai.vlm_analyzer.LLMClient") as mock_client_cls, \
         patch.object(VLMAnalyzer, "_encode_image",
                      return_value="mock_base64_data") as mock_encode:
        mock_client = MagicMock()
        mock_client.chat_with_image.return_value = mock_vlm_response
        mock_client_cls.from_config.return_value = mock_client

        analyzer = VLMAnalyzer()
        result = analyzer.analyze(
            screenshot_path="/tmp/test_screenshot.png",
            structure=structure,
            task_context="定时检测登录按钮并点击",
        )

    # _encode_image 被调用但不会真正读取文件
    mock_encode.assert_called_once_with("/tmp/test_screenshot.png")
    assert len(result) == 2
    assert result[0]["node_id"] == "node_detect"
    assert result[0]["param"] == "region"
    assert result[0]["suggested_value"] == [120, 300, 200, 340]
    assert result[0]["confidence"] == 0.95


def test_fill_structure_applies_suggestions():
    """测试将建议值填入节点结构"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer

    analyzer = VLMAnalyzer()

    structure = {
        "nodes": [
            {"id": "node_detect", "type": "ImageConditionNode",
             "config": {"region": [], "template_path": ""},
             "children": ["node_click"],
             "empty_params": ["region"]},
        ]
    }

    suggestions = [
        {"node_id": "node_detect", "param": "region",
         "suggested_value": [120, 300, 200, 340], "confidence": 0.95,
         "note": "检测到按钮"}
    ]

    filled = analyzer.fill_structure(structure, suggestions)
    assert filled["nodes"][0]["config"]["region"] == [120, 300, 200, 340]
    assert "region" not in filled["nodes"][0].get("empty_params", [])


def test_fill_structure_does_not_mutate_original():
    """测试 fill_structure 不修改原始结构（深拷贝）"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer

    analyzer = VLMAnalyzer()

    structure = {
        "nodes": [
            {"id": "node_detect", "type": "ImageConditionNode",
             "config": {"region": []},
             "children": [],
             "empty_params": ["region"]},
        ]
    }

    suggestions = [
        {"node_id": "node_detect", "param": "region",
         "suggested_value": [10, 20, 30, 40], "confidence": 0.8,
         "note": "区域"}
    ]

    filled = analyzer.fill_structure(structure, suggestions)
    # 原始结构不受影响
    assert structure["nodes"][0]["config"]["region"] == []
    assert "region" in structure["nodes"][0]["empty_params"]
    # 填充后的结构已更新
    assert filled["nodes"][0]["config"]["region"] == [10, 20, 30, 40]
    assert "region" not in filled["nodes"][0].get("empty_params", [])


def test_analyze_returns_empty_when_no_empty_params():
    """测试没有空参数时直接返回空列表，不调用 VLM"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer

    structure = {
        "nodes": [
            {"id": "node_1", "type": "DelayNode",
             "config": {"duration_ms": 1000},
             "children": []},
        ]
    }

    analyzer = VLMAnalyzer()
    result = analyzer.analyze(
        screenshot_path="/tmp/fake.png",
        structure=structure,
        task_context="无需填充参数",
    )

    assert result == []


def test_analyze_handles_llm_error():
    """测试 VLM 请求异常时抛出 VLMAnalysisError"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer, VLMAnalysisError

    structure = {
        "nodes": [
            {"id": "node_detect", "type": "ImageConditionNode",
             "config": {"region": []},
             "children": [],
             "empty_params": ["region"]},
        ]
    }

    with patch("bt_cli.ai.vlm_analyzer.LLMClient") as mock_client_cls, \
         patch.object(VLMAnalyzer, "_encode_image",
                      return_value="mock_base64_data"):
        mock_client = MagicMock()
        mock_client.chat_with_image.side_effect = RuntimeError("connection refused")
        mock_client_cls.from_config.return_value = mock_client

        analyzer = VLMAnalyzer()
        with pytest.raises(VLMAnalysisError, match="VLM 请求失败"):
            analyzer.analyze(
                screenshot_path="/tmp/test_screenshot.png",
                structure=structure,
                task_context="测试",
            )


def test_analyze_handles_invalid_json():
    """测试 VLM 返回无效 JSON 时抛出 VLMAnalysisError"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer, VLMAnalysisError

    mock_vlm_response = {
        "content": "这不是JSON格式的回复",
        "model": "gpt-4o",
        "usage": {},
    }

    structure = {
        "nodes": [
            {"id": "node_detect", "type": "ImageConditionNode",
             "config": {"region": []},
             "children": [],
             "empty_params": ["region"]},
        ]
    }

    with patch("bt_cli.ai.vlm_analyzer.LLMClient") as mock_client_cls, \
         patch.object(VLMAnalyzer, "_encode_image",
                      return_value="mock_base64_data"):
        mock_client = MagicMock()
        mock_client.chat_with_image.return_value = mock_vlm_response
        mock_client_cls.from_config.return_value = mock_client

        analyzer = VLMAnalyzer()
        with pytest.raises(VLMAnalysisError, match="JSON 无效"):
            analyzer.analyze(
                screenshot_path="/tmp/test_screenshot.png",
                structure=structure,
                task_context="测试",
            )


def test_analyze_handles_screenshot_not_found():
    """测试截图文件不存在时抛出 VLMAnalysisError"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer, VLMAnalysisError

    structure = {
        "nodes": [
            {"id": "node_detect", "type": "ImageConditionNode",
             "config": {"region": []},
             "children": [],
             "empty_params": ["region"]},
        ]
    }

    with patch("bt_cli.ai.vlm_analyzer.LLMClient") as mock_client_cls:
        mock_client_cls.from_config.return_value = MagicMock()

        analyzer = VLMAnalyzer()
        with pytest.raises(VLMAnalysisError, match="无法读取截图文件"):
            analyzer.analyze(
                screenshot_path="/nonexistent/path/screenshot.png",
                structure=structure,
                task_context="测试",
            )
