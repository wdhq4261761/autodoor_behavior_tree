# tests/test_node_selector.py
"""NodeSelector 测试

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
# 在导入 NodeSelector 之前,为环境中缺失的可选重型依赖注入 Mock,
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


def test_select_returns_valid_structure():
    """测试节点选型返回有效的节点结构"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_selector import NodeSelector

    register_all_nodes()

    mock_llm_response = {
        "content": json.dumps({
            "nodes": [
                {"id": "node_start", "type": "StartNode",
                 "config": {"bind_window": False, "window_title": ""},
                 "children": ["node_loop"]},
                {"id": "node_loop", "type": "SequenceNode",
                 "config": {"repeat_count": -1, "repeat_interval_ms": 60000},
                 "children": ["node_detect", "node_delay"]},
                {"id": "node_detect", "type": "ImageConditionNode",
                 "config": {"region": [], "template_path": "", "threshold": 80},
                 "children": ["node_click"],
                 "empty_params": ["region", "template_path"]},
                {"id": "node_click", "type": "MouseClickNode",
                 "config": {"use_blackboard": True, "button": "left"},
                 "children": []},
                {"id": "node_delay", "type": "DelayNode",
                 "config": {"duration_ms": 60000},
                 "children": []}
            ]
        }, ensure_ascii=False),
        "model": "gpt-4o",
        "usage": {},
    }

    plan = {
        "task_summary": "定时检测登录按钮并点击",
        "loop": {"enabled": True, "interval_ms": 60000, "max_iterations": -1},
        "phases": [
            {"phase": "detect", "method": "image_or_ocr", "target_description": "登录按钮"},
            {"phase": "act", "action": "click", "position_source": "from_detection"}
        ],
        "window": {"bind": False, "title": "", "pid": None}
    }

    with patch("bt_cli.ai.node_selector.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        selector = NodeSelector()
        result = selector.select(plan)

    assert "nodes" in result
    assert len(result["nodes"]) == 5
    assert result["nodes"][0]["type"] == "StartNode"
    assert result["nodes"][2]["empty_params"] == ["region", "template_path"]


def test_select_validates_node_types():
    """测试选型结果中的节点类型都存在于 Registry"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_selector import NodeSelector, NodeSelectionError

    register_all_nodes()

    mock_llm_response = {
        "content": json.dumps({
            "nodes": [
                {"id": "node_start", "type": "StartNode",
                 "config": {}, "children": ["node_bad"]},
                {"id": "node_bad", "type": "NonExistentNode",
                 "config": {}, "children": []}
            ]
        }),
        "model": "gpt-4o",
        "usage": {},
    }

    plan = {"task_summary": "test", "loop": {"enabled": False}, "phases": [], "window": {}}

    with patch("bt_cli.ai.node_selector.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        selector = NodeSelector()
        with pytest.raises(NodeSelectionError):
            selector.select(plan)


def test_select_handles_llm_error():
    """测试 LLM 请求异常时抛出 NodeSelectionError"""
    from bt_cli.ai.node_selector import NodeSelector, NodeSelectionError

    plan = {"task_summary": "test", "loop": {"enabled": False}, "phases": [], "window": {}}

    with patch("bt_cli.ai.node_selector.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("connection refused")
        mock_client_cls.from_config.return_value = mock_client

        selector = NodeSelector()
        with pytest.raises(NodeSelectionError, match="LLM 请求失败"):
            selector.select(plan)


def test_select_handles_invalid_json():
    """测试 LLM 返回无效 JSON 时抛出 NodeSelectionError"""
    from bt_cli.ai.node_selector import NodeSelector, NodeSelectionError

    plan = {"task_summary": "test", "loop": {"enabled": False}, "phases": [], "window": {}}

    mock_llm_response = {
        "content": "not a json string",
        "model": "gpt-4o",
        "usage": {},
    }

    with patch("bt_cli.ai.node_selector.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        selector = NodeSelector()
        with pytest.raises(NodeSelectionError, match="JSON 无效"):
            selector.select(plan)


def test_select_rejects_root_not_startnode():
    """测试根节点非 StartNode 时抛出异常"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_selector import NodeSelector, NodeSelectionError

    register_all_nodes()

    mock_llm_response = {
        "content": json.dumps({
            "nodes": [
                {"id": "node_1", "type": "SequenceNode",
                 "config": {}, "children": []}
            ]
        }),
        "model": "gpt-4o",
        "usage": {},
    }

    plan = {"task_summary": "test", "loop": {"enabled": False}, "phases": [], "window": {}}

    with patch("bt_cli.ai.node_selector.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        selector = NodeSelector()
        with pytest.raises(NodeSelectionError):
            selector.select(plan)


def test_select_rejects_duplicate_ids():
    """测试节点 ID 重复时抛出异常"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_selector import NodeSelector, NodeSelectionError

    register_all_nodes()

    mock_llm_response = {
        "content": json.dumps({
            "nodes": [
                {"id": "dup", "type": "StartNode",
                 "config": {}, "children": []},
                {"id": "dup", "type": "DelayNode",
                 "config": {}, "children": []}
            ]
        }),
        "model": "gpt-4o",
        "usage": {},
    }

    plan = {"task_summary": "test", "loop": {"enabled": False}, "phases": [], "window": {}}

    with patch("bt_cli.ai.node_selector.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        selector = NodeSelector()
        with pytest.raises(NodeSelectionError):
            selector.select(plan)


def test_select_rejects_invalid_children_ref():
    """测试 children 引用不存在的 ID 时抛出异常"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_selector import NodeSelector, NodeSelectionError

    register_all_nodes()

    mock_llm_response = {
        "content": json.dumps({
            "nodes": [
                {"id": "node_start", "type": "StartNode",
                 "config": {}, "children": ["ghost_node"]}
            ]
        }),
        "model": "gpt-4o",
        "usage": {},
    }

    plan = {"task_summary": "test", "loop": {"enabled": False}, "phases": [], "window": {}}

    with patch("bt_cli.ai.node_selector.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        selector = NodeSelector()
        with pytest.raises(NodeSelectionError):
            selector.select(plan)


def test_select_rejects_missing_id():
    """测试节点缺少 id 字段时抛出异常而非 KeyError"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_selector import NodeSelector, NodeSelectionError

    register_all_nodes()

    mock_llm_response = {
        "content": json.dumps({
            "nodes": [
                {"type": "StartNode", "config": {}, "children": []},
                {"id": "node_2", "type": "DelayNode", "config": {}, "children": []}
            ]
        }),
        "model": "gpt-4o",
        "usage": {},
    }

    plan = {"task_summary": "test", "loop": {"enabled": False}, "phases": [], "window": {}}

    with patch("bt_cli.ai.node_selector.LLMClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_llm_response
        mock_client_cls.from_config.return_value = mock_client

        selector = NodeSelector()
        with pytest.raises(NodeSelectionError):
            selector.select(plan)
