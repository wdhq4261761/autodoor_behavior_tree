# tests/test_plugin_integration.py
"""插件系统集成测试 — 验证示例插件可被加载并运行"""
import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bt_plugins.base import PluginContext, PluginInfo
from bt_plugins.loader import PluginLoader


def test_file_processor_plugin_loads():
    """测试文件处理插件可加载"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugin_dir = os.path.join(project_root, "plugins", "file_processor")

    if not os.path.isdir(plugin_dir):
        pytest.skip("file_processor 插件目录不存在")

    loader = PluginLoader(PluginContext())
    assert loader.load_plugin(plugin_dir), "插件加载失败"

    info = loader.get_plugin_info("file_processor")
    assert info is not None
    assert info.display_name == "文件处理"


def test_file_processor_plugin_starts():
    """测试文件处理插件可启动"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugin_dir = os.path.join(project_root, "plugins", "file_processor")

    if not os.path.isdir(plugin_dir):
        pytest.skip("file_processor 插件目录不存在")

    loader = PluginLoader(PluginContext())
    loader.load_plugin(plugin_dir)
    assert loader.start_plugin("file_processor")

    # 验证节点显示信息
    display_info = loader.get_registered_display_info()
    assert "file_processor.FileReadNode" in display_info
    assert display_info["file_processor.FileReadNode"]["display_name"] == "文件读取"

    # 验证 schema
    schemas = loader.get_registered_schemas()
    assert "file_processor.FileReadNode" in schemas

    loader.stop_plugin("file_processor")


def test_excel_automation_plugin_loads():
    """测试 Excel 插件可加载（依赖 openpyxl）"""
    pytest.importorskip("openpyxl")

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugin_dir = os.path.join(project_root, "plugins", "excel_automation")

    if not os.path.isdir(plugin_dir):
        pytest.skip("excel_automation 插件目录不存在")

    loader = PluginLoader(PluginContext())
    assert loader.load_plugin(plugin_dir), "插件加载失败"


def test_all_plugins_discovered_via_scan():
    """测试通过 scan 发现所有随仓库跟踪的插件

    scan 只读取 plugin.json，不导入插件依赖，因此所有入库插件都应被发现。
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugins_dir = os.path.join(project_root, "plugins")

    if not os.path.isdir(plugins_dir):
        pytest.skip("plugins 目录不存在")

    loader = PluginLoader(PluginContext())
    infos = loader.scan(plugins_dir)

    names = [info.name for info in infos]
    assert "file_processor" in names
    assert "uia_bridge" in names
    assert "vlm_vision" in names


def test_file_processor_node_info_registered():
    """测试 file_processor 节点信息和 schema 在启动后正确注册（带前缀）"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugin_dir = os.path.join(project_root, "plugins", "file_processor")

    if not os.path.isdir(plugin_dir):
        pytest.skip("file_processor 插件目录不存在")

    loader = PluginLoader(PluginContext())
    loader.load_plugin(plugin_dir)
    loader.start_plugin("file_processor")

    try:
        display_info = loader.get_registered_display_info()
        # 验证所有 3 个节点都注册了显示信息
        assert "file_processor.FileReadNode" in display_info
        assert "file_processor.FileWriteNode" in display_info
        assert "file_processor.FileMoveNode" in display_info
        assert display_info["file_processor.FileWriteNode"]["display_name"] == "文件写入"
        assert display_info["file_processor.FileMoveNode"]["display_name"] == "文件移动"

        # 验证 schema
        schemas = loader.get_registered_schemas()
        assert "file_processor.FileWriteNode" in schemas
        # FileWriteNode schema 应包含 4 个字段
        schema_keys = [item["key"] for item in schemas["file_processor.FileWriteNode"]]
        assert "file_path" in schema_keys
        assert "source_key" in schema_keys
        assert "encoding" in schema_keys
        assert "append" in schema_keys
    finally:
        loader.stop_plugin("file_processor")
