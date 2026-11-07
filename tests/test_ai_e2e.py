# tests/test_ai_e2e.py
"""AI 编排端到端集成测试

环境说明:
    bt_utils/__init__.py 会 eager-import OCRManager / ScriptRecorder 等模块,
    它们依赖 rapidocr / pynput 等重型三方库。本测试通过 mock LLMClient
    来隔离真实 API 调用,因此在导入前用 MagicMock 占位缺失的可选依赖,
    使潜在的 eager import 链不致中断。
"""
import pytest
import json
import os
import sys
import tempfile
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


def test_full_pipeline_plan_to_generate():
    """测试从意图分析到生成的完整流程（mock LLM）"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.intent_analyzer import IntentAnalyzer
    from bt_cli.ai.node_selector import NodeSelector
    from bt_cli.ai.tree_generator import TreeGenerator
    from bt_cli.ai.tree_validator import TreeValidator

    register_all_nodes()

    # Mock LLM 响应
    plan_response = {
        "content": json.dumps({
            "task_summary": "每秒点击一次鼠标",
            "loop": {"enabled": True, "interval_ms": 1000, "max_iterations": -1},
            "phases": [
                {"phase": "act", "action": "click", "position_source": "fixed",
                 "on_complete": "loop_back"}
            ],
            "window": {"bind": False, "title": "", "pid": None}
        }, ensure_ascii=False),
        "model": "gpt-4o", "usage": {},
    }

    structure_response = {
        "content": json.dumps({
            "nodes": [
                {"id": "node_start", "type": "StartNode",
                 "config": {"bind_window": False}, "children": ["node_loop"]},
                {"id": "node_loop", "type": "SequenceNode",
                 "config": {"repeat_count": -1, "repeat_interval_ms": 1000},
                 "children": ["node_click", "node_delay"]},
                {"id": "node_click", "type": "MouseClickNode",
                 "config": {"button": "left", "position": [500, 500],
                            "use_blackboard": False},
                 "children": []},
                {"id": "node_delay", "type": "DelayNode",
                 "config": {"duration_ms": 1000}, "children": []},
            ]
        }, ensure_ascii=False),
        "model": "gpt-4o", "usage": {},
    }

    with patch("bt_cli.ai.intent_analyzer.LLMClient") as mock1, \
         patch("bt_cli.ai.node_selector.LLMClient") as mock2:

        client1 = MagicMock()
        client1.chat.return_value = plan_response
        mock1.from_config.return_value = client1

        client2 = MagicMock()
        client2.chat.return_value = structure_response
        mock2.from_config.return_value = client2

        # 阶段①
        analyzer = IntentAnalyzer()
        plan = analyzer.analyze("每秒点击一次鼠标")
        assert plan["loop"]["enabled"] == True

        # 阶段②
        selector = NodeSelector()
        structure = selector.select(plan)
        assert len(structure["nodes"]) == 4

    # 阶段④（跳过③，使用已填充参数）
    gen = TreeGenerator()
    tree_data, errors = gen.generate_and_validate(structure)
    assert errors == []
    assert tree_data["root_node"] == "node_start"
    assert len(tree_data["nodes"]) == 4

    # Serializer 往返测试
    validator = TreeValidator()
    serializer_errors = validator.validate_with_serializer(tree_data)
    assert serializer_errors == []


def test_node_spec_exporter_covers_all_registered():
    """验证 NodeSpecExporter 覆盖所有已注册节点"""
    from bt_core.registry import register_all_nodes, NodeRegistry
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    registered = NodeRegistry.list_types()
    for node_type in registered:
        assert node_type in specs, f"NodeSpecExporter 缺少节点: {node_type}"


def test_iteration_engine_apply_and_validate():
    """测试迭代修正后行为树仍通过校验"""
    from bt_cli.ai.tree_generator import TreeGenerator
    from bt_cli.ai.tree_validator import TreeValidator
    from bt_cli.ai.iteration_engine import IterationEngine

    structure = {
        "nodes": [
            {"id": "node_start", "type": "StartNode",
             "config": {"bind_window": False}, "children": ["node_loop"]},
            {"id": "node_loop", "type": "SequenceNode",
             "config": {"repeat_count": 1}, "children": ["node_detect"]},
            {"id": "node_detect", "type": "OCRConditionNode",
             "config": {"region": [100, 200, 200, 250], "keywords": "test"},
             "children": ["node_click"]},
            {"id": "node_click", "type": "MouseClickNode",
             "config": {"button": "left", "position": [150, 225]},
             "children": []},
        ]
    }

    gen = TreeGenerator()
    tree_data = gen.generate(structure)

    # 应用修正
    engine = IterationEngine()
    fixes = [
        {"node_id": "node_detect", "param": "region",
         "new_value": [100, 200, 400, 400], "reason": "扩大区域"}
    ]
    fixed_tree = engine.apply_fixes(tree_data, fixes)

    # 验证修正后的树仍有效
    validator = TreeValidator()
    errors = validator.validate(fixed_tree)
    assert errors == []

    # 验证修正已应用
    assert fixed_tree["nodes"]["node_detect"]["config"]["region"] == [100, 200, 400, 400]
