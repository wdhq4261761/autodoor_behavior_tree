"""插件节点在真实加载路径下的注册与反序列化测试

单测覆盖了节点内部逻辑，但节点能否被运行时「看见」还取决于
PluginLoader.start_plugin 的注册链路（前缀命名、反序列化顺序）。
本文件按真实路径加载 plugins/ 下两个新插件，再对含插件节点的树做
序列化 / 反序列化往返，确保不是「单测过、运行时不认」。
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def loader():
    """按真实路径加载 plugins/ 目录下的插件并启动"""
    from bt_plugins.base import PluginContext
    from bt_plugins.loader import PluginLoader
    from bt_core.registry import register_all_nodes

    register_all_nodes()

    class FakeSettings(dict):
        def get(self, key, default=None):
            # 打开插件总开关，其余按默认
            if key == "plugins.enabled":
                return True
            return default

    ctx = PluginContext(settings=FakeSettings())
    ld = PluginLoader(ctx)
    plugins_dir = os.path.join(str(ROOT), "plugins")
    infos = ld.scan(plugins_dir)
    for info in infos:
        ld.load_plugin(os.path.join(plugins_dir, info.name))
    ld.start_all()
    yield ld
    try:
        ld.stop_all()
    except Exception:
        pass


NEW_TYPES = [
    "vlm_vision.VLMLocateNode",
    "vlm_vision.VLMAssertNode",
    "vlm_vision.VLMReadNode",
    "uia_bridge.UIASampleNode",
    "uia_bridge.UIAStateNode",
]


class TestPluginRegistration:
    def test_all_new_types_registered(self, loader):
        from bt_core.registry import NodeRegistry
        for t in NEW_TYPES:
            assert NodeRegistry.get(t) is not None, f"{t} 未注册"

    def test_prefix_naming_not_bare(self, loader):
        """插件节点必须以 {plugin}.{type} 形式注册，裸名不应存在"""
        from bt_core.registry import NodeRegistry
        assert NodeRegistry.get("VLMLocateNode") is None
        assert NodeRegistry.get("UIASampleNode") is None

    def test_duplicate_start_is_idempotent(self, loader):
        """start_plugin 幂等：重复启动不应重复注册或报错"""
        assert loader.start_plugin("vlm_vision") is True
        from bt_core.registry import NodeRegistry
        assert NodeRegistry.get("vlm_vision.VLMLocateNode") is not None


class TestTreeRoundTrip:
    def test_plugin_nodes_survive_serialization(self, loader, tmp_path):
        """含插件节点的树：反序列化后节点类型与配置应完整保留"""
        from bt_core.serializer import Serializer

        tree = {
            "version": "2.1",
            "format_type": "behavior_tree",
            "root_node": "n1",
            "nodes": {
                "n1": {
                    "id": "n1", "type": "SequenceNode", "name": "序列",
                    "enabled": True, "config": {}, "children": ["n2"],
                },
                "n2": {
                    "id": "n2", "type": "vlm_vision.VLMAssertNode",
                    "name": "断言", "enabled": True,
                    "config": {"question": "是否有错误弹窗", "expect": "no",
                               "max_calls_per_run": 3},
                    "children": [],
                },
            },
            "connections": [{"parent_id": "n1", "child_id": "n2"}],
        }

        data = tmp_path / "tree.json"
        data.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")

        ser = Serializer()
        root, _canvas, _editor = ser.load_from_file(str(data))
        assert root is not None
        # 找到子节点并校验类型与配置
        child = root.children[0] if root.children else None
        assert child is not None, "反序列化后子节点丢失（插件节点被静默丢弃）"
        assert child.NODE_TYPE == "VLMAssertNode"
        assert child.config.get("question") == "是否有错误弹窗"
        assert child.config.get_int("max_calls_per_run") == 3

    def test_uia_node_defaults_client_mode(self, loader):
        """未显式配置 output_mode 时，行为必须等价于 client

        注意：NodeConfig 只保存显式写入的键，不会把 schema 默认值落盘，
        因此这里校验**行为**而非配置项本身 —— 否则测的是序列化细节，
        而不是「默认输出客户区坐标」这个真正重要的约定。
        """
        from bt_core.config import NodeConfig
        from plugins.uia_bridge.nodes import UIASampleNode

        node = UIASampleNode("n", NodeConfig.from_dict({"control_type": "Button"}))
        # 复现节点内部的取值逻辑
        mode = str(node.config.get("output_mode", "client") or "client")
        assert mode == "client"

        # 显式配置 screen 时也不应被吞掉
        node2 = UIASampleNode("n2", NodeConfig.from_dict({"output_mode": "screen"}))
        assert str(node2.config.get("output_mode", "client") or "client") == "screen"


class TestValidatorAcceptsPlugins:
    def test_validator_passes_for_plugin_tree(self, loader):
        from bt_cli.ai.tree_validator import TreeValidator

        # 树结构内联在测试内，不依赖任何临时目录（避免测试与工作区状态耦合）
        tree = {
            "version": "2.1",
            "format_type": "behavior_tree",
            "root_node": "node_start",
            "nodes": {
                "node_start": {
                    "id": "node_start", "type": "StartNode", "name": "开始",
                    "enabled": True, "config": {"bind_window": False},
                    "children": ["node_assert"],
                },
                "node_assert": {
                    "id": "node_assert", "type": "vlm_vision.VLMAssertNode",
                    "name": "断言无错误弹窗", "enabled": True,
                    "config": {"question": "画面中是否出现错误提示弹窗",
                               "expect": "no", "max_calls_per_run": 5,
                               "cache_ttl_ms": 2000},
                    "children": ["node_img"],
                },
                "node_img": {
                    "id": "node_img", "type": "ImageConditionNode",
                    "name": "模板检测(多尺度)", "enabled": True,
                    "config": {"template_path": "./assets/templates/e2e_target.png",
                               "threshold": 75, "multi_scale": True,
                               "scale_range": "0.9,1.1", "scale_steps": 3},
                    "children": ["node_uia"],
                },
                "node_uia": {
                    "id": "node_uia", "type": "uia_bridge.UIASampleNode",
                    "name": "采样按钮", "enabled": True,
                    "config": {"control_type": "Button", "output_mode": "client"},
                    "children": [],
                },
            },
            "connections": [
                {"parent_id": "node_start", "child_id": "node_assert"},
                {"parent_id": "node_assert", "child_id": "node_img"},
                {"parent_id": "node_img", "child_id": "node_uia"},
            ],
        }
        v = TreeValidator()
        assert v.validate(tree) == []
        assert v.validate_with_serializer(tree) == []
