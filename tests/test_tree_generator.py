# tests/test_tree_generator.py
"""TreeGenerator + TreeValidator 测试

环境说明:
    bt_utils/__init__.py 会 eager-import OCRManager / ScriptRecorder 等模块,
    它们依赖 rapidocr / pynput 等重型三方库。本测试通过 mock LLMClient
    来隔离真实 API 调用,因此在导入前用 MagicMock 占位缺失的可选依赖,
    使潜在的 eager import 链不致中断。
"""
import pytest
import json
import sys
from unittest.mock import MagicMock, patch

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


def test_generate_valid_tree():
    """测试从节点结构生成 tree.json"""
    from bt_cli.ai.tree_generator import TreeGenerator

    structure = {
        "nodes": [
            {"id": "node_start", "type": "StartNode",
             "config": {"bind_window": False}, "children": ["node_seq"]},
            {"id": "node_seq", "type": "SequenceNode",
             "config": {"repeat_count": -1, "repeat_interval_ms": 1000},
             "children": ["node_delay"]},
            {"id": "node_delay", "type": "DelayNode",
             "config": {"duration_ms": 1000}, "children": []},
        ]
    }

    gen = TreeGenerator()
    tree_data = gen.generate(structure, canvas_name="测试流程")

    assert tree_data["version"] == "2.1"
    assert tree_data["format_type"] == "behavior_tree"
    assert tree_data["root_node"] == "node_start"
    assert "node_start" in tree_data["nodes"]
    assert "node_seq" in tree_data["nodes"]
    assert "node_delay" in tree_data["nodes"]
    assert len(tree_data["connections"]) == 2


def test_generate_layout_positions():
    """测试生成的节点有布局坐标"""
    from bt_cli.ai.tree_generator import TreeGenerator

    structure = {
        "nodes": [
            {"id": "node_start", "type": "StartNode",
             "config": {}, "children": ["node_seq"]},
            {"id": "node_seq", "type": "SequenceNode",
             "config": {}, "children": ["node_delay"]},
            {"id": "node_delay", "type": "DelayNode",
             "config": {}, "children": []},
        ]
    }

    gen = TreeGenerator()
    tree_data = gen.generate(structure)

    # 根节点 Y=50
    assert tree_data["nodes"]["node_start"]["position"]["y"] == 50
    # 第二层 Y=150
    assert tree_data["nodes"]["node_seq"]["position"]["y"] == 150
    # 第三层 Y=250
    assert tree_data["nodes"]["node_delay"]["position"]["y"] == 250


def test_validate_valid_tree():
    """测试校验通过的有效行为树"""
    from bt_cli.ai.tree_validator import TreeValidator

    tree_data = {
        "version": "2.1",
        "format_type": "behavior_tree",
        "root_node": "node_start",
        "nodes": {
            "node_start": {"id": "node_start", "type": "StartNode",
                           "name": "开始", "enabled": True, "config": {},
                           "position": {"x": 400, "y": 50}, "children": ["node_delay"]},
            "node_delay": {"id": "node_delay", "type": "DelayNode",
                           "name": "延时", "enabled": True, "config": {"duration_ms": 1000},
                           "position": {"x": 400, "y": 150}, "children": []},
        },
        "connections": [{"parent_id": "node_start", "child_id": "node_delay"}],
    }

    validator = TreeValidator()
    errors = validator.validate(tree_data)
    assert errors == []


def test_validate_missing_root():
    """测试缺少根节点"""
    from bt_cli.ai.tree_validator import TreeValidator

    tree_data = {
        "version": "2.1",
        "format_type": "behavior_tree",
        "root_node": "node_start",
        "nodes": {
            "node_delay": {"id": "node_delay", "type": "DelayNode",
                           "name": "延时", "enabled": True, "config": {},
                           "position": {"x": 400, "y": 50}, "children": []},
        },
        "connections": [],
    }

    validator = TreeValidator()
    errors = validator.validate(tree_data)
    assert any("root_node" in e.lower() or "根节点" in e for e in errors)


def test_validate_duplicate_ids():
    """测试重复节点 ID"""
    from bt_cli.ai.tree_validator import TreeValidator

    tree_data = {
        "version": "2.1",
        "root_node": "node_1",
        "nodes": {
            "node_1": {"id": "node_1", "type": "StartNode", "name": "", "enabled": True,
                       "config": {}, "position": {"x": 0, "y": 0}, "children": ["node_1"]},
        },
        "connections": [{"parent_id": "node_1", "child_id": "node_1"}],
    }

    validator = TreeValidator()
    errors = validator.validate(tree_data)
    # 自引用应被检测到
    assert len(errors) > 0


def test_validate_condition_without_children():
    """测试条件节点没有子节点"""
    from bt_cli.ai.tree_validator import TreeValidator

    tree_data = {
        "version": "2.1",
        "root_node": "node_start",
        "nodes": {
            "node_start": {"id": "node_start", "type": "StartNode", "name": "",
                           "enabled": True, "config": {}, "position": {"x": 0, "y": 0},
                           "children": ["node_cond"]},
            "node_cond": {"id": "node_cond", "type": "OCRConditionNode", "name": "",
                          "enabled": True, "config": {"region": [0,0,100,100], "keywords": "test"},
                          "position": {"x": 0, "y": 100}, "children": []},
        },
        "connections": [{"parent_id": "node_start", "child_id": "node_cond"}],
    }

    validator = TreeValidator()
    errors = validator.validate(tree_data)
    assert any("子节点" in e for e in errors)


def test_generate_and_validate_returns_empty_errors_for_valid_structure():
    """测试生成并校验返回空错误列表"""
    from bt_cli.ai.tree_generator import TreeGenerator

    structure = {
        "nodes": [
            {"id": "node_start", "type": "StartNode",
             "config": {"bind_window": False}, "children": ["node_seq"]},
            {"id": "node_seq", "type": "SequenceNode",
             "config": {"repeat_count": -1, "repeat_interval_ms": 1000},
             "children": ["node_delay"]},
            {"id": "node_delay", "type": "DelayNode",
             "config": {"duration_ms": 1000}, "children": []},
        ]
    }

    gen = TreeGenerator()
    tree_data, errors = gen.generate_and_validate(structure, canvas_name="测试流程")

    assert errors == []
    assert tree_data["root_node"] == "node_start"
    assert tree_data["version"] == "2.1"
    assert tree_data["format_type"] == "behavior_tree"


def test_validate_with_serializer_rejects_invalid_data():
    """测试 Serializer 深度校验拒绝无效数据

    通过 mock Serializer.deserialize 返回 None 根节点，
    模拟结构校验通过但反序列化失败的场景。
    """
    from bt_cli.ai.tree_validator import TreeValidator

    tree_data = {
        "version": "2.1",
        "format_type": "behavior_tree",
        "root_node": "node_start",
        "nodes": {
            "node_start": {"id": "node_start", "type": "StartNode",
                           "name": "开始", "enabled": True, "config": {},
                           "position": {"x": 400, "y": 50}, "children": ["node_delay"]},
            "node_delay": {"id": "node_delay", "type": "DelayNode",
                           "name": "延时", "enabled": True, "config": {"duration_ms": 1000},
                           "position": {"x": 400, "y": 150}, "children": []},
        },
        "connections": [{"parent_id": "node_start", "child_id": "node_delay"}],
    }

    validator = TreeValidator()
    # mock Serializer.deserialize 返回根节点为 None，模拟反序列化失败
    with patch("bt_core.serializer.Serializer.deserialize", return_value=(None, {}, {})):
        errors = validator.validate_with_serializer(tree_data)

    assert any("Serializer" in e or "反序列化" in e for e in errors)
