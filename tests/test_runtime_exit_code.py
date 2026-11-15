import json

from bt_core.context import ExecutionContext
from bt_core.headless import HeadlessRunner
from bt_core.nodes import Node
from bt_core.status import NodeStatus
from bt_plugins.builtin.example.main import HelloNode


class _FixedStatusNode(Node):
    """测试用根节点：每次 tick 返回固定状态。"""

    NODE_TYPE = "FixedStatusNode"

    def __init__(self, status):
        super().__init__("fixed")
        self._fixed_status = status

    def tick(self, context):
        return self._fixed_status


def test_hello_node_logs_and_succeeds():
    node = HelloNode("hello")
    node.config.set("name", "回归测试")
    context = ExecutionContext()
    assert node.tick(context) == NodeStatus.SUCCESS
    assert context.blackboard.get("greeting") == "Hello, 回归测试!"


def _write_tree(tmp_path):
    path = tmp_path / "tree.json"
    path.write_text(
        json.dumps({"root_node": "root", "nodes": {}, "connections": []}),
        encoding="utf-8",
    )
    return str(path)


def test_headless_returns_one_when_root_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(HeadlessRunner, "_start_service_layer", lambda self, settings: None)
    monkeypatch.setattr(
        "bt_core.serializer.Serializer.deserialize",
        staticmethod(lambda data: _FixedStatusNode(NodeStatus.FAILURE)),
    )
    code = HeadlessRunner().run(_write_tree(tmp_path), check_preflight=False)
    assert code == 1


def test_headless_returns_zero_when_root_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(HeadlessRunner, "_start_service_layer", lambda self, settings: None)
    monkeypatch.setattr(
        "bt_core.serializer.Serializer.deserialize",
        staticmethod(lambda data: _FixedStatusNode(NodeStatus.SUCCESS)),
    )
    code = HeadlessRunner().run(_write_tree(tmp_path), check_preflight=False)
    assert code == 0
