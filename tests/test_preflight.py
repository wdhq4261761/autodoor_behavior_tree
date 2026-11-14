"""静态预检模块测试

验证 validate_tree_data 在运行前对树数据做纯静态检查：
结构错误（空树/根缺失/连线/多父/环）、未知节点类型、资源缺失，
以及警告类问题（孤立节点、资源路径为空）。
"""
import pytest

from bt_core.registry import NodeRegistry, register_all_nodes
from bt_core.nodes import SequenceNode


@pytest.fixture(scope="module", autouse=True)
def _register_nodes():
    """注册内置节点（与真实运行前的注册流程一致）"""
    register_all_nodes()


def _node(type_name, config=None):
    data = {"type": type_name}
    if config is not None:
        data["config"] = config
    return data


def _tree(nodes, connections=None, root_node="root"):
    return {
        "root_node": root_node,
        "nodes": nodes,
        "connections": connections or [],
    }


def _codes(report):
    return [issue.code for issue in report.issues]


def _conn(parent_id, child_id):
    return {"parent_id": parent_id, "child_id": child_id}


def test_empty_tree_reports_error():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data({"nodes": {}, "connections": []})

    assert "EMPTY_TREE" in _codes(report)
    assert report.has_errors is True


def test_none_tree_reports_error_without_exception():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(None)

    assert "EMPTY_TREE" in _codes(report)
    assert report.has_errors is True


def test_root_missing_reports_error():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree({"root": _node("SequenceNode")}, root_node="ghost"))

    assert "ROOT_MISSING" in _codes(report)


def test_unknown_node_type_reports_error_with_node_id():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree({"root": _node("NoSuchNode")}))

    unknown = [i for i in report.issues if i.code == "UNKNOWN_NODE_TYPE"]
    assert unknown and unknown[0].node_id == "root"


def test_node_without_type_reports_unknown():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree({"root": {"config": {}}}))

    assert "UNKNOWN_NODE_TYPE" in _codes(report)


def test_multi_parent_reports_error():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree(
        {
            "root": _node("SequenceNode"),
            "a": _node("SequenceNode"),
            "b": _node("SequenceNode"),
            "c": _node("SequenceNode"),
        },
        [
            _conn("root", "a"),
            _conn("root", "b"),
            _conn("a", "c"),
            _conn("b", "c"),
        ],
    ))

    multi = [i for i in report.issues if i.code == "MULTI_PARENT"]
    assert multi and multi[0].node_id == "c"


def test_cycle_reports_error():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree(
        {"root": _node("SequenceNode"), "a": _node("SequenceNode")},
        [_conn("root", "a"), _conn("a", "root")],
    ))

    assert "CYCLE" in _codes(report)


def test_unreachable_node_is_warning_only():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree(
        {"root": _node("SequenceNode"), "orphan": _node("SequenceNode")},
    ))

    assert "UNREACHABLE" in _codes(report)
    assert report.has_errors is False


def test_bad_connection_reports_error():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree(
        {"root": _node("SequenceNode")},
        [_conn("root", "ghost")],
    ))

    assert "BAD_CONNECTION" in _codes(report)
    assert report.has_errors is True


def test_missing_template_reports_error(tmp_path):
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(
        _tree({"root": _node("ImageConditionNode", {"template_path": "missing.png"})}),
        project_root=str(tmp_path),
    )

    missing = [i for i in report.issues if i.code == "MISSING_RESOURCE"]
    assert missing and missing[0].node_id == "root"


def test_existing_template_no_missing_resource(tmp_path):
    from bt_core.preflight import validate_tree_data

    (tmp_path / "tpl.png").write_bytes(b"png")

    report = validate_tree_data(
        _tree({"root": _node("ImageConditionNode", {"template_path": "./tpl.png"})}),
        project_root=str(tmp_path),
    )

    assert "MISSING_RESOURCE" not in _codes(report)
    assert report.has_errors is False


def test_missing_subtree_reports_error(tmp_path):
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(
        _tree({"root": _node("SubtreeNode", {"subtree_path": "sub/tree.json"})}),
        project_root=str(tmp_path),
    )

    assert "MISSING_RESOURCE" in _codes(report)


@pytest.mark.parametrize(
    "type_name, key",
    [
        ("ImageConditionNode", "template_path"),
        ("SubtreeNode", "subtree_path"),
        ("ScriptNode", "script_path"),
        ("TextInputNode", "file_path"),
    ],
)
def test_missing_resource_per_node_type(tmp_path, type_name, key):
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(
        _tree({"root": _node(type_name, {key: "nope.dat"})}),
        project_root=str(tmp_path),
    )

    assert "MISSING_RESOURCE" in _codes(report)


def test_empty_template_path_is_warning():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree({"root": _node("ImageConditionNode", {})}))

    assert "EMPTY_RESOURCE" in _codes(report)
    assert report.has_errors is False


def test_config_none_is_treated_as_empty_dict():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree({"root": {"type": "ImageConditionNode", "config": None}}))

    assert "EMPTY_RESOURCE" in _codes(report)
    assert report.has_errors is False


def test_config_non_dict_does_not_raise():
    from bt_core.preflight import validate_tree_data

    report = validate_tree_data(_tree({"root": {"type": "ImageConditionNode", "config": ["bad"]}}))

    assert isinstance(report.issues, list)


def test_format_lines_contains_prefixes():
    from bt_core.preflight import PreflightReport

    report = PreflightReport()
    report.add("error", "EMPTY_TREE", "树为空", node_id="root")
    report.add("warning", "UNREACHABLE", "孤立节点")

    lines = report.format_lines()
    assert any("[错误]" in line for line in lines)
    assert any("[警告]" in line for line in lines)
    assert any("（节点 root）" in line for line in lines)


def test_plugin_node_not_reported_as_unknown():
    from bt_core.preflight import validate_tree_data

    NodeRegistry.register("demo.PluginNode", SequenceNode)
    try:
        report = validate_tree_data(_tree({"root": _node("demo.PluginNode")}))
        assert "UNKNOWN_NODE_TYPE" not in _codes(report)
    finally:
        NodeRegistry.unregister("demo.PluginNode")
