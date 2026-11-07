"""插件加载器 — 扫描、加载、管理插件生命周期

负责：
1. 扫描插件目录，发现 plugin.json
2. 动态导入插件模块，实例化插件类
3. 管理插件生命周期：load → start → stop → unload
4. 将插件提供的节点/适配器/服务注册到主系统注册中心
5. 卸载时反向注销，保证插件可热插拔

节点注册自动加前缀 ``{plugin_name}.{node_type}``，避免插件间命名冲突。
所有插件回调用 try/except 包裹，单个插件异常不影响主进程。
"""
import importlib.util
import json
import os
import sys
import threading
from typing import Dict, List, Optional, Type

from .base import BasePlugin, PluginContext, PluginInfo


class PluginLoader:
    """插件加载器 — 扫描、加载、管理插件生命周期

    生命周期顺序：
        load_plugin → start_plugin → [运行中] → stop_plugin → unload_plugin
    """

    def __init__(self, context: PluginContext):
        self._context = context
        self._lock = threading.RLock()
        self._plugins: Dict[str, BasePlugin] = {}  # name → plugin instance
        self._plugin_infos: Dict[str, PluginInfo] = {}  # name → plugin info
        self._plugin_dirs: Dict[str, str] = {}  # name → plugin directory
        self._registered_nodes: Dict[str, str] = {}  # node_type → plugin_name
        self._registered_adapters: Dict[str, str] = {}  # adapter_name → plugin_name
        self._registered_services: Dict[str, str] = {}  # service_name → plugin_name
        self._plugin_modules: Dict[str, str] = {}  # name → module name in sys.modules
        # 插件节点 GUI 信息（display_info / schemas），key 为带前缀的 node_type
        self._registered_display_info: Dict[str, dict] = {}
        self._registered_schemas: Dict[str, list] = {}

    # ── 扫描 ──

    def scan(self, plugins_dir: str) -> List[PluginInfo]:
        """扫描目录下的子目录，每个含 plugin.json 的目录是一个插件"""
        infos: List[PluginInfo] = []
        if not os.path.isdir(plugins_dir):
            return infos
        for entry in sorted(os.listdir(plugins_dir)):
            plugin_dir = os.path.join(plugins_dir, entry)
            if not os.path.isdir(plugin_dir):
                continue
            manifest_path = os.path.join(plugin_dir, "plugin.json")
            if not os.path.isfile(manifest_path):
                continue
            info = self._read_manifest(manifest_path)
            if info is not None:
                infos.append(info)
        return infos

    def _read_manifest(self, path: str) -> Optional[PluginInfo]:
        """读取 plugin.json 并返回 PluginInfo"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[PluginLoader] 读取插件清单失败 {path}: {e}")
            return None
        # 校验必填字段
        required = ("name", "display_name", "version", "author", "description")
        for key in required:
            if key not in data:
                print(f"[PluginLoader] 插件清单缺少字段 {key}: {path}")
                return None
        return PluginInfo(
            name=data["name"],
            display_name=data["display_name"],
            version=data["version"],
            author=data["author"],
            description=data["description"],
            category=data.get("category", "general"),
            min_app_version=data.get("min_app_version", ""),
            dependencies=data.get("dependencies"),
        )

    # ── 加载/卸载 ──

    def load_plugin(self, plugin_dir: str) -> bool:
        """加载单个插件

        流程：读取清单 → 检查依赖 → 动态导入模块 → 实例化 → 注入上下文 → on_load
        任意步骤失败均回滚已注册的临时状态（如 sys.modules 中的模块），保证可重试。
        """
        with self._lock:
            manifest_path = os.path.join(plugin_dir, "plugin.json")
            if not os.path.isfile(manifest_path):
                print(f"[PluginLoader] 未找到 plugin.json: {plugin_dir}")
                return False

            info = self._read_manifest(manifest_path)
            if info is None:
                return False

            name = info.name
            if name in self._plugins:
                print(f"[PluginLoader] 插件已加载，跳过: {name}")
                return False

            # 检查依赖
            if info.dependencies:
                for dep in info.dependencies:
                    if dep not in self._plugins:
                        print(f"[PluginLoader] 插件 {name} 依赖 {dep} 未加载")
                        return False

            # 读取入口文件与类名（plugin.json 中的 entry/class 字段，不在 PluginInfo 中）
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    raw_manifest = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                print(f"[PluginLoader] 读取入口配置失败 {manifest_path}: {e}")
                return False
            entry_file = raw_manifest.get("entry", "main.py")
            class_name = raw_manifest.get("class", "")
            if not class_name:
                print(f"[PluginLoader] 插件清单未指定 class: {name}")
                return False

            entry_path = os.path.join(plugin_dir, entry_file)
            if not os.path.isfile(entry_path):
                print(f"[PluginLoader] 入口文件不存在: {entry_path}")
                return False

            # 插件内部普遍使用绝对包导入，例如：
            #     from plugins.vlm_vision.nodes import VLMLocateNode
            # 开发版之所以能用，是因为 cwd 恰好是项目根且被加入 sys.path；
            # 打包成 exe 后 cwd 是 exe 目录、且不在 sys.path 中，
            # 于是报 "No module named 'plugins'"。
            # 这里显式把 "plugins 所在目录的上一级" 加入 sys.path，
            # 使 plugins 作为命名空间包（PEP 420，无需 __init__.py）可被解析，
            # 开发版与打包版行为一致。
            try:
                _plugins_root = os.path.dirname(os.path.abspath(plugin_dir))
                _import_root = os.path.dirname(_plugins_root)
                if _import_root and _import_root not in sys.path:
                    sys.path.insert(0, _import_root)
            except Exception:
                pass

            # 动态导入模块（spec_from_file_location 按文件路径加载，不依赖 sys.path）
            module_name = f"bt_plugin_{name}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, entry_path)
                if spec is None or spec.loader is None:
                    print(f"[PluginLoader] 无法创建模块 spec: {entry_path}")
                    return False
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                # 导入失败需要回滚 sys.modules，避免残留半初始化模块
                sys.modules.pop(module_name, None)
                print(f"[PluginLoader] 导入插件模块失败 {name}: {e}")
                return False

            # 获取插件类并校验是否为 BasePlugin 子类
            plugin_class = getattr(module, class_name, None)
            if plugin_class is None:
                print(f"[PluginLoader] 模块中未找到类 {class_name}: {name}")
                sys.modules.pop(module_name, None)
                return False
            if not (isinstance(plugin_class, type) and issubclass(plugin_class, BasePlugin)):
                print(f"[PluginLoader] {class_name} 不是 BasePlugin 子类: {name}")
                sys.modules.pop(module_name, None)
                return False

            # 实例化插件
            try:
                plugin = plugin_class(info)
            except Exception as e:
                print(f"[PluginLoader] 实例化插件失败 {name}: {e}")
                sys.modules.pop(module_name, None)
                return False

            # 创建插件专属上下文（共享 loader 的 settings/bus/registry，但设置独立 plugin_name）
            plugin_context = PluginContext(
                settings=self._context._settings,
                message_bus=self._context._message_bus,
                adapter_manager=self._context._adapter_manager,
                service_registry=self._context._service_registry,
            )
            plugin_context.set_plugin_name(name)
            plugin.set_context(plugin_context)

            # 调用 on_load
            try:
                plugin.on_load()
            except Exception as e:
                print(f"[PluginLoader] on_load 失败 {name}: {e}")
                sys.modules.pop(module_name, None)
                return False

            # 存入字典
            self._plugins[name] = plugin
            self._plugin_infos[name] = info
            self._plugin_dirs[name] = plugin_dir
            self._plugin_modules[name] = module_name
            return True

    def unload_plugin(self, name: str) -> None:
        """卸载插件 — 先 stop 再 on_unload，清理内部状态与 sys.modules"""
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                return
            # 先停止（注销节点/适配器/服务）
            self.stop_plugin(name)
            # 调用 on_unload
            try:
                plugin.on_unload()
            except Exception as e:
                print(f"[PluginLoader] on_unload 失败 {name}: {e}")
            # 清理内部字典
            self._plugins.pop(name, None)
            self._plugin_infos.pop(name, None)
            self._plugin_dirs.pop(name, None)
            # 清理 sys.modules（释放模块引用，便于重新加载）
            module_name = self._plugin_modules.pop(name, None)
            if module_name and module_name in sys.modules:
                del sys.modules[module_name]

    # ── 启动/停止 ──

    def start_plugin(self, name: str) -> bool:
        """启动插件 — 调用 on_start 并注册节点/适配器/服务

        所有注册都记录到 _registered_* 字典，便于 stop 时反向注销。
        每步用 try/except 包裹，单步失败不影响后续注册。
        """
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                print(f"[PluginLoader] 插件未加载，无法启动: {name}")
                return False
            if plugin._started:
                return True  # 幂等：已启动直接返回

            # 调用 on_start
            try:
                plugin.on_start()
            except Exception as e:
                print(f"[PluginLoader] on_start 失败 {name}: {e}")
                return False

            # 注册节点 — 自动加插件名前缀 {plugin_name}.{node_type}，避免命名冲突
            try:
                from bt_core.registry import NodeRegistry
                nodes = plugin.get_nodes() or {}
                for node_type, node_class in nodes.items():
                    prefixed_type = f"{name}.{node_type}"
                    NodeRegistry.register(prefixed_type, node_class)
                    self._registered_nodes[prefixed_type] = name
            except Exception as e:
                print(f"[PluginLoader] 注册节点失败 {name}: {e}")

            # 收集插件节点的 GUI 显示信息 — key 与注册节点一致（带前缀）
            try:
                display_info = plugin.get_node_display_info() or {}
                for node_type, info in display_info.items():
                    prefixed_type = f"{name}.{node_type}"
                    self._registered_display_info[prefixed_type] = info
            except Exception as e:
                print(f"[PluginLoader] 收集节点显示信息失败 {name}: {e}")

            # 收集插件节点的属性面板 schema
            try:
                schemas = plugin.get_node_schemas() or {}
                prefixed_schemas: Dict[str, list] = {}
                for node_type, schema in schemas.items():
                    prefixed_type = f"{name}.{node_type}"
                    self._registered_schemas[prefixed_type] = schema
                    prefixed_schemas[prefixed_type] = schema
                # 同步注册到 GUI 属性面板（GUI 模式下可用，headless 模式忽略）
                if prefixed_schemas:
                    try:
                        from bt_gui.bt_editor.property import register_plugin_schemas
                        register_plugin_schemas(name, prefixed_schemas)
                    except ImportError:
                        pass  # Headless 模式下 GUI 模块不可用，正常
            except Exception as e:
                print(f"[PluginLoader] 收集节点 schema 失败 {name}: {e}")

            # 注册适配器 — AdapterManager 是单例，优先用 context 中的实例，否则取单例
            try:
                adapters = plugin.get_adapters() or {}
                if adapters:
                    am = self._context._adapter_manager
                    if am is None:
                        from bt_adapters.adapter_manager import AdapterManager
                        am = AdapterManager()
                    for adapter_name, adapter_class in adapters.items():
                        am.register_adapter(adapter_name, adapter_class)
                        self._registered_adapters[adapter_name] = name
            except Exception as e:
                print(f"[PluginLoader] 注册适配器失败 {name}: {e}")

            # 注册服务 — 通过 context._service_registry（未注入时仅记录归属）
            try:
                services = plugin.get_services() or {}
                if services:
                    sr = self._context._service_registry
                    if sr is not None:
                        for svc_name, svc in services.items():
                            sr.register(svc_name, svc)
                            self._registered_services[svc_name] = name
                    else:
                        for svc_name in services:
                            self._registered_services[svc_name] = name
            except Exception as e:
                print(f"[PluginLoader] 注册服务失败 {name}: {e}")

            return True

    def stop_plugin(self, name: str) -> None:
        """停止插件 — 调用 on_stop 并注销节点/适配器/服务

        每步用 try/except 包裹，单步失败不影响后续注销。
        """
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                return
            if not plugin._started:
                return

            # 调用 on_stop
            try:
                plugin.on_stop()
            except Exception as e:
                print(f"[PluginLoader] on_stop 失败 {name}: {e}")

            # 注销节点
            try:
                from bt_core.registry import NodeRegistry
                node_types = [nt for nt, pn in self._registered_nodes.items() if pn == name]
                for nt in node_types:
                    NodeRegistry.unregister(nt)
                    self._registered_nodes.pop(nt, None)
                    # 同步清理 GUI 信息
                    self._registered_display_info.pop(nt, None)
                    self._registered_schemas.pop(nt, None)
            except Exception as e:
                print(f"[PluginLoader] 注销节点失败 {name}: {e}")

            # 注销 GUI 属性面板 schema（GUI 模式下可用，headless 模式忽略）
            try:
                from bt_gui.bt_editor.property import unregister_plugin_schemas
                unregister_plugin_schemas(name)
            except ImportError:
                pass

            # 注销适配器 — 调用 AdapterManager.unregister_adapter 并清理内部记录
            try:
                adapter_names = [an for an, pn in self._registered_adapters.items() if pn == name]
                am = self._context._adapter_manager
                for an in adapter_names:
                    if am is not None and hasattr(am, 'unregister_adapter'):
                        am.unregister_adapter(an)
                    self._registered_adapters.pop(an, None)
            except Exception as e:
                print(f"[PluginLoader] 清理适配器记录失败 {name}: {e}")

            # 注销服务
            try:
                svc_names = [sn for sn, pn in self._registered_services.items() if pn == name]
                sr = self._context._service_registry
                for sn in svc_names:
                    if sr is not None:
                        sr.unregister(sn)
                    self._registered_services.pop(sn, None)
            except Exception as e:
                print(f"[PluginLoader] 注销服务失败 {name}: {e}")

    # ── 批量操作 ──

    def start_all(self) -> None:
        """批量启动所有已加载插件"""
        with self._lock:
            for name in list(self._plugins.keys()):
                self.start_plugin(name)

    def stop_all(self) -> None:
        """批量停止所有已加载插件"""
        with self._lock:
            for name in list(self._plugins.keys()):
                self.stop_plugin(name)

    # ── 查询 ──

    def get_plugin_info(self, name: str) -> Optional[PluginInfo]:
        """获取指定插件的元信息"""
        with self._lock:
            return self._plugin_infos.get(name)

    def list_plugins(self) -> List[PluginInfo]:
        """列出所有已加载插件的元信息"""
        with self._lock:
            return list(self._plugin_infos.values())

    def is_started(self, name: str) -> bool:
        """判断插件是否已启动"""
        with self._lock:
            plugin = self._plugins.get(name)
            return plugin is not None and plugin._started

    # ── 自动启动（持久化） ──

    #: 记录插件是否在下次应用启动时自动启动的 settings 键（位于 plugins.{name} 下）
    AUTOSTART_KEY = "autostart"

    def set_autostart(self, name: str, enabled: bool) -> None:
        """记录插件是否应在下次应用启动时自动启动

        写入 settings 的 ``plugins.{name}.autostart``，由 SettingsManager 持久化到
        config.json。settings 不可用（未注入或非 SettingsManager）时静默跳过，
        不影响启停操作本身。
        """
        settings = getattr(self._context, "_settings", None)
        if settings is None or not hasattr(settings, "set"):
            return
        try:
            settings.set(f"plugins.{name}.{self.AUTOSTART_KEY}", bool(enabled))
        except Exception as e:
            print(f"[PluginLoader] 保存插件自动启动状态失败 {name}: {e}")

    def is_autostart(self, name: str) -> bool:
        """查询插件是否被标记为自动启动（默认 False）"""
        settings = getattr(self._context, "_settings", None)
        if settings is None or not hasattr(settings, "get"):
            return False
        return bool(settings.get(f"plugins.{name}.{self.AUTOSTART_KEY}", False))

    def autostart_all(self) -> int:
        """启动所有标记为自动启动的插件，返回成功启动的数量

        用于 GUI 启动时恢复上次运行中被启动过的插件，避免每次手动点击"启动"。
        """
        count = 0
        with self._lock:
            for name in list(self._plugins.keys()):
                if self.is_autostart(name) and self.start_plugin(name):
                    count += 1
        return count

    def get_registered_display_info(self) -> Dict[str, dict]:
        """返回所有已启动插件提供的节点显示信息

        Returns:
            {prefixed_node_type: {"display_name": str, "description": str, "category": str, "icon": str}}
            key 形如 ``plugin_name.NodeType``，与 NodeRegistry 中注册的节点类型一致
        """
        with self._lock:
            return dict(self._registered_display_info)

    def get_registered_schemas(self) -> Dict[str, list]:
        """返回所有已启动插件提供的节点属性面板 schema

        Returns:
            {prefixed_node_type: [schema_item, ...]}
        """
        with self._lock:
            return dict(self._registered_schemas)

    def get_plugin_config_schema(self, name: str) -> dict:
        """返回指定插件的配置 schema（settings.json 中该插件的配置项）

        Args:
            name: 插件名

        Returns:
            插件的配置 schema 字典，形如 {"key": {"type": ..., "default": ..., "label": ...}}
            若插件不存在或未提供 schema，返回空字典
        """
        with self._lock:
            plugin = self._plugins.get(name)
            if not plugin:
                return {}
            try:
                return plugin.get_config_schema() or {}
            except Exception as e:
                print(f"[PluginLoader] 获取插件配置 schema 失败 {name}: {e}")
                return {}
