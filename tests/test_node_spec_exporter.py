# tests/test_node_spec_exporter.py
"""NodeSpecExporter 测试

环境说明:
    bt_utils/__init__.py 会 eager-import OCRManager / ScriptRecorder 等模块,
    它们依赖 rapidocr / pynput 等重型三方库。bt_nodes/actions/text_input.py
    在模块级别 import pyperclip。本测试仅关注 NodeSpecExporter 的节点规格导出,
    因此在导入前用 MagicMock 占位这些缺失的可选依赖。
"""
import sys
from unittest.mock import MagicMock

# ------------------------------------------------------------------
# 在导入 bt_core / bt_nodes 之前,为环境中缺失的可选重型依赖注入 Mock,
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


def test_export_all_returns_registered_nodes():
    """验证导出所有已注册节点"""
    from bt_core.registry import register_all_nodes, NodeRegistry
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    # 核心节点必须存在
    assert "StartNode" in specs
    assert "SequenceNode" in specs
    assert "SelectorNode" in specs
    assert "MouseClickNode" in specs
    assert "DelayNode" in specs
    assert "OCRConditionNode" in specs
    assert "ImageConditionNode" in specs


def test_export_node_has_required_fields():
    """验证导出的节点规格包含必需字段"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    start_spec = specs["StartNode"]
    assert "node_type" in start_spec
    assert "category" in start_spec
    assert "base_class" in start_spec
    assert "parameters" in start_spec
    assert start_spec["node_type"] == "StartNode"


def test_export_categorizes_nodes():
    """验证节点分类正确"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    assert specs["SequenceNode"]["category"] == "composite"
    assert specs["MouseClickNode"]["category"] == "action"
    assert specs["OCRConditionNode"]["category"] == "condition"


def test_export_extract_parameters():
    """验证参数提取包含已知参数"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    delay_spec = specs["DelayNode"]
    params = delay_spec["parameters"]
    # DelayNode 应包含 duration_ms 参数
    param_names = [p["name"] for p in params]
    assert "duration_ms" in param_names


def test_export_node_descriptions():
    """验证节点描述提取"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    # 每个节点应有描述
    for node_type, spec in specs.items():
        assert "description" in spec
        assert isinstance(spec["description"], str)


def test_http_request_node_is_async():
    """验证 HTTPRequestNode 被正确标记为异步节点"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    assert "HTTPRequestNode" in specs
    assert specs["HTTPRequestNode"]["is_async"] is True

    # 其它普通节点不应被误判为异步
    assert specs["DelayNode"]["is_async"] is False
    assert specs["MouseClickNode"]["is_async"] is False


def test_condition_nodes_have_decorator_params():
    """验证条件节点包含装饰参数（invert 等）"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    for node_type in ("OCRConditionNode", "ImageConditionNode",
                      "ColorConditionNode", "VariableConditionNode"):
        params = specs[node_type]["parameters"]
        param_names = [p["name"] for p in params]
        assert "invert" in param_names, f"{node_type} 缺少 invert 装饰参数"
        assert "retry_count" in param_names, f"{node_type} 缺少 retry_count 装饰参数"


def test_action_nodes_have_decorator_params():
    """验证动作节点包含装饰参数（repeat_count 等）"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    for node_type in ("MouseClickNode", "DelayNode", "KeyPressNode"):
        params = specs[node_type]["parameters"]
        param_names = [p["name"] for p in params]
        assert "repeat_count" in param_names, f"{node_type} 缺少 repeat_count 装饰参数"
        assert "repeat_interval_ms" in param_names, (
            f"{node_type} 缺少 repeat_interval_ms 装饰参数")


def test_previously_missing_nodes_have_own_params():
    """验证此前缺失的 4 个节点拥有自身参数（而非仅有装饰参数）"""
    from bt_core.registry import register_all_nodes
    from bt_cli.ai.node_spec_exporter import NodeSpecExporter

    register_all_nodes()
    exporter = NodeSpecExporter()
    specs = exporter.export_all()

    # 各节点自身应包含的关键参数
    expected_own_params = {
        "StartTreeNode": "target_tree",
        "StopTreeNode": "target_tree",
        "APIConditionNode": "json_path",
        "WebSocketNode": "payload_key",
    }

    for node_type, own_param in expected_own_params.items():
        assert node_type in specs, f"{node_type} 未被导出"
        params = specs[node_type]["parameters"]
        param_names = [p["name"] for p in params]
        assert own_param in param_names, (
            f"{node_type} 缺少自身参数 {own_param}")

    # StartTreeNode / StopTreeNode 同样应包含装饰参数（动作节点）
    for node_type in ("StartTreeNode", "StopTreeNode"):
        param_names = [p["name"] for p in specs[node_type]["parameters"]]
        assert "repeat_count" in param_names, (
            f"{node_type} 缺少动作装饰参数 repeat_count")

    # WebSocketNode 自身参数数量应大于装饰参数数量，证明并非只有装饰参数
    action_decorator_count = 4  # _ACTION_DECORATOR_PARAMS 长度
    ws_params = specs["WebSocketNode"]["parameters"]
    assert len(ws_params) > action_decorator_count, (
        "WebSocketNode 参数数量不应仅等于装饰参数数量")

