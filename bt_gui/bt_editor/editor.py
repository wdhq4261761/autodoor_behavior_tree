import customtkinter as ctk
from tkinter import messagebox
import json
import os
import platform
from pathlib import Path
from typing import Optional, Dict, Any, List

from ..theme import Theme
from .canvas import BehaviorTreeCanvas
from .palette import NodePalette
from .property import PropertyPanel
from .toolbar import EditorToolbar
from .constants import NODE_DISPLAY_NAMES
from .log_panel import LogPanel
from .undo_redo import (
    CommandManager, AddNodeCommand, AddNodesCommand, RemoveNodeCommand,
    RemoveNodesCommand, MoveNodeCommand, MoveNodesCommand, AddConnectionCommand,
    RemoveConnectionCommand
)
from .gui_tab_manager import GuiTabManager
from .tab_bar import TabBar
from bt_utils.log_manager import LogManager
from bt_utils.json_io import load_json
from bt_core.engine import BehaviorTreeEngine
from bt_core.context import ExecutionContext
from bt_core.serializer import Serializer
from bt_core.status import NodeStatus
from bt_core.tree_instance import TreeInstance
from bt_core.blackboard import Blackboard
from bt_utils.auto_save import AutoSaveManager
from bt_utils.crash_recovery import CrashRecoveryHandler
from bt_utils.global_hotkey import GlobalHotkeyManager
from bt_utils.auth.login_manager import LoginManager


def _get_user_data_dir() -> Path:
    """获取平台适用的用户数据目录"""
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", os.path.expanduser("~")))
    else:
        base = Path.home()
    
    data_dir = base / "autodoor_behavior_tree" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class BehaviorTreeEditor(ctk.CTkFrame):
    _tab_counter = 0
    AUTOSAVE_INTERVAL = 60000
    BACKUP_DIR = str(_get_user_data_dir() / "backup")
    RECOVERY_DIR = str(_get_user_data_dir() / "recovery")

    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        self._fallback_file_path: Optional[str] = None
        self._node_counter = 0
        self._modified = False
        
        self._fallback_engine: Optional[BehaviorTreeEngine] = None
        self._fallback_context: Optional[ExecutionContext] = None
        self._is_running = False
        
        self.project_manager = None
        self._fallback_project_root = None
        self._fallback_project_manager = None
        
        self._dark_colors = Theme.get_dark_colors()
        self.configure(fg_color=self._dark_colors['bg_primary'], corner_radius=0)
        
        self._fallback_canvas = None
        self._fallback_command_manager = CommandManager()
        
        self.tab_manager = GuiTabManager()
        self.tab_manager.on_tab_switched = self._on_tab_switched
        self.tab_manager.on_tab_status_changed = self._on_tab_status_changed
        self.tab_manager.on_tab_removed = self._on_tab_removed
        self.tab_manager.on_tab_start_request = self._handle_tab_run
        self.tab_manager.on_tab_stop_request = self._handle_tab_stop
        
        self._clipboard_data = None
        
        self._hotkey_manager = GlobalHotkeyManager.get_instance()
        
        self._login_manager = LoginManager()
        
        self._create_ui()
        self._bind_events()
        
        self._check_crash_recovery()
        
        self._init_auto_login()
    
    def _create_ui(self):
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True)
        
        self._create_toolbar()
        self._create_tab_bar()
        self._create_main_area()
    
    def _create_tab_bar(self):
        self.tab_bar = TabBar(
            self.main_container,
            on_tab_switch=self._handle_tab_switch,
            on_tab_close=self._handle_tab_close,
            on_tab_run=self._handle_tab_run,
            on_tab_stop=self._handle_tab_stop,
            on_import=self._handle_import_project,
            on_tab_rename=self._handle_tab_rename,
            on_tab_is_running=self._handle_tab_is_running,
        )
        self.tab_bar.pack(fill="x")
    
    def _handle_tab_switch(self, tab_id: str):
        self.tab_manager.switch_tab(tab_id)
        self.tab_bar.set_active(tab_id)
    
    def _handle_tab_close(self, tab_id: str):
        instance = self.tab_manager.get_tab(tab_id)
        if not instance:
            return
        
        if instance.is_running:
            if not messagebox.askyesno("确认", "行为树正在运行，是否停止并关闭？"):
                return
            self._handle_tab_stop(tab_id)
        
        if instance.modified:
            result = messagebox.askyesnocancel("保存", f"项目 \"{instance.name}\" 有未保存的改动。\n\n是否保存？")
            if result is None:
                return
            if result:
                self._save_tab(tab_id)
        
        if hasattr(instance, '_autosave_manager') and instance._autosave_manager:
            instance._autosave_manager.stop()
            instance._autosave_manager.save_now()
        
        if instance.canvas:
            instance.canvas.place_forget()
            instance.canvas.destroy()
        
        self.tab_manager.remove_tab(tab_id)
        
        remaining_tab = self.tab_manager.get_active_tab()
        if remaining_tab:
            self.tab_bar.set_active(remaining_tab.tab_id)
            self._on_tab_switched(remaining_tab.tab_id, remaining_tab)
        else:
            self._fallback_project_root = None
            self._fallback_file_path = None
            self._fallback_project_manager = None
            self._update_title("未命名")
            self.toolbar.set_project_path(None)
            self.toolbar.set_running(False)
    
    def _handle_tab_run(self, tab_id: str, skip_sound: bool = False) -> bool:
        instance = self.tab_manager.get_tab(tab_id)
        if not instance or instance.is_running:
            return False
        
        if instance.canvas:
            instance.canvas.show_all_status_indicators()
        
        tree_data = instance.canvas.get_tree_data() if instance.canvas else {}
        if not tree_data or not tree_data.get("nodes"):
            messagebox.showwarning("警告", "行为树为空，无法运行")
            return False

        from bt_core.preflight import validate_tree_data
        report = validate_tree_data(tree_data, instance.project_root)
        if report.issues:
            lines = report.format_lines()
            detail = "\n".join(lines[:12])
            if len(lines) > 12:
                detail += f"\n…（其余 {len(lines) - 12} 条已省略）"
            if report.has_errors:
                if not messagebox.askyesno(
                        "运行前检查",
                        detail + "\n\n发现错误，仍要继续运行吗？",
                        default="no"):
                    return False
            else:
                LogManager.debug_print("[Preflight] " + "；".join(lines[:5]))
        from bt_core.serializer import Serializer
        result = Serializer.deserialize(tree_data)
        if isinstance(result, tuple):
            root_node = result[0]
        else:
            root_node = result
        
        if not root_node:
            messagebox.showwarning("警告", "行为树为空，无法运行")
            return False
        
        from bt_core.engine import BehaviorTreeEngine
        from bt_core.context import ExecutionContext
        
        LogManager.instance().set_stopped(False, tab_name=instance.name)
        
        engine = BehaviorTreeEngine(root_node)
        # 应用全局 tick 间隔（设置中为毫秒，引擎为秒）控制整体运行频率
        try:
            from config.settings_manager import SettingsManager
            tick_ms = int(SettingsManager.get_instance().get("behavior_tree.tick_interval", 33))
            if tick_ms > 0:
                engine._tick_interval = tick_ms / 1000.0
        except (ValueError, TypeError):
            pass
        engine._on_status_change = lambda status, node_status=None: self._on_tab_engine_status_change(tab_id, status, node_status)
        
        context = ExecutionContext(project_root=instance.project_root)
        context._on_node_status = lambda node_id, status, tid=tab_id: self._on_node_status(node_id, status, tid)
        context.set_tab_manager(self.tab_manager, tab_id)
        context.set_message_bus(getattr(self.app, '_message_bus', None))
        
        instance.engine = engine
        instance.context = context
        
        engine.start(context)
        self.tab_manager.update_tab_status(tab_id, True)
        
        if not skip_sound:
            self._play_start_sound()
        return True
    
    def _handle_tab_stop(self, tab_id: str, skip_sound: bool = False) -> bool:
        instance = self.tab_manager.get_tab(tab_id)
        if not instance or not instance.is_running:
            return False
        
        LogManager.instance().set_stopped(True, tab_name=instance.name)
        LogManager.instance().clear_tab_entries(instance.name)
        LogManager.instance().log_info(
            node_type="系统",
            node_name="",
            message="用户停止运行",
            tab_name=instance.name
        )
        
        if instance.engine:
            instance.engine.stop()
        
        self.tab_manager.update_tab_status(tab_id, False)
        
        from bt_utils.input_controller_factory import InputController
        InputController.release_all()
        
        if instance.canvas:
            instance.canvas.after(100, lambda: instance.canvas.clear_all_node_status() if instance.canvas else None)
            instance.canvas.after(200, lambda: self._restore_canvas_focus_for_tab(tab_id))
        
        if not skip_sound:
            self._play_stop_sound()
        return True
    
    def _restore_canvas_focus_for_tab(self, tab_id: str):
        """恢复指定tab的画布焦点"""
        instance = self.tab_manager.get_tab(tab_id)
        if instance and instance.canvas:
            try:
                instance.canvas.canvas.focus_set()
            except Exception:
                pass
    
    def _on_tab_engine_status_change(self, tab_id: str, status: str, node_status=None):
        instance = self.tab_manager.get_tab(tab_id)
        if not instance:
            return
        
        if status in ["completed", "stopped"]:
            self.tab_manager.update_tab_status(tab_id, False)
            self._play_stop_sound()
            
            from bt_utils.input_controller_factory import InputController
            InputController.release_all()
            
            if instance.canvas:
                instance.canvas.after(100, lambda: instance.canvas.clear_all_node_status() if instance.canvas else None)
    
    def _handle_import_project(self):
        from tkinter import filedialog
        folder_path = filedialog.askdirectory(title="选择行为树项目文件夹")
        if not folder_path:
            return
        self.import_project_to_new_tab(folder_path)

    def _handle_tab_is_running(self, tab_id: str) -> bool:
        """检查 Tab 对应的项目是否正在运行行为树（供 TabBar 决定是否允许重命名）"""
        instance = self.tab_manager.get_tab(tab_id)
        if not instance:
            return False
        return bool(getattr(instance, 'is_running', False))

    def _handle_tab_rename(self, tab_id: str, new_name: str) -> bool:
        """Tab 双击重命名回调：仅修改 project_info.name，不动文件夹名。

        核心约束：
        - 不修改文件夹名（客户端永不修改文件夹名）
        - 仅写入 project.json 的 project_info.name
        - 更新 TreeInstance.name 和 Tab 显示
        - 更新窗口标题
        - 持久化 settings.json

        Args:
            tab_id: Tab ID
            new_name: 新名称

        Returns:
            是否重命名成功
        """
        instance = self.tab_manager.get_tab(tab_id)
        if not instance:
            return False

        # 必须有 project_root（未保存项目禁止重命名）
        if not instance.project_root or not os.path.exists(instance.project_root):
            messagebox.showwarning("提示", "项目尚未保存，无法重命名。请先保存项目。")
            return False

        # 项目运行中禁止重命名（双击入口已检查，这里二次防御）
        if getattr(instance, 'is_running', False):
            messagebox.showinfo("提示", "项目运行中，无法重命名。请先停止运行。")
            return False

        from bt_utils.project_manager import ProjectManager

        # 调用统一接口更新 project.json 的 project_info.name
        ok = ProjectManager.update_project_info_name(instance.project_root, new_name)
        if not ok:
            messagebox.showerror("错误", f"更新 project.json 失败，请检查文件权限。")
            return False

        # 更新 TreeInstance.name（仅显示用，权威源仍是文件夹名）
        instance.name = new_name

        # 更新 Tab 标签
        self.tab_bar.update_tab_name(tab_id, new_name)

        # 更新窗口标题
        if hasattr(self.app, '_update_window_title'):
            self.app._update_window_title()

        # 持久化 settings.json
        if hasattr(self.app, '_save_tabs_state'):
            try:
                self.app._save_tabs_state()
            except Exception:
                pass

        # 日志提示
        try:
            from bt_utils.log_manager import LogManager
            LogManager.debug_print(
                f"[Rename] 已修改项目显示名为 '{new_name}'。"
                f"注意：文件夹名未改变，下次打开时若与文件夹名不一致会提示同步。"
            )
        except Exception:
            pass

        return True
    
    def _save_tab(self, tab_id: str):
        instance = self.tab_manager.get_tab(tab_id)
        if not instance or not instance.canvas:
            return
        
        tree_data = instance.canvas.get_tree_data()
        
        if instance.project_root:
            from bt_utils.resource_service import ResourceService
            tree_data = ResourceService.save_with_cleanup(tree_data, instance.project_root)
            instance.canvas.load_tree(tree_data)
            
            if instance.project_manager:
                instance.project_manager.save_project(tree_data)
            else:
                from bt_utils.project_manager import ProjectManager
                pm = ProjectManager(instance.project_root)
                pm.save_project(tree_data)
        elif instance.file_path:
            save_path = instance.file_path
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(tree_data, f, ensure_ascii=False, indent=2)
        else:
            messagebox.showerror("错误", "无法保存：未指定文件路径或项目目录")
            return
        
        if hasattr(instance, '_autosave_manager') and instance._autosave_manager:
            instance._autosave_manager.clear_autosaves()
        
        instance.modified = False
        self._modified = False
    
    def import_project_to_new_tab(self, project_path: str) -> Optional[str]:
        from bt_utils.project_manager import ProjectManager
        folder_name = ProjectManager.resolve_project_name(project_path)

        for existing_id, existing_instance in self.tab_manager._trees.items():
            if existing_instance.project_root and os.path.samefile(existing_instance.project_root, project_path):
                from tkinter import messagebox
                messagebox.showinfo("提示", f"项目 '{folder_name}' 已在 Tab 中打开")
                self.tab_manager.switch_tab(existing_id)
                self.tab_bar.set_active(existing_id)
                return existing_id

        # 导入项目时一致性校验：文件夹名 vs project_info.name
        # 覆盖场景：用户修改了文件夹名后重新导入、启动恢复 Tab 时
        self._check_and_prompt_name_consistency_on_open(project_path)
        # 校验可能修改了 project_info.name，重新以文件夹名（权威源）为准
        folder_name = ProjectManager.resolve_project_name(project_path)

        tab_id = self._create_new_tab(folder_name, project_path)
        
        tree_file = os.path.join(project_path, "tree.json")
        if os.path.exists(tree_file):
            self._load_tree_to_tab(tab_id, tree_file)
        
        self.tab_manager.switch_tab(tab_id)
        self.tab_bar.set_active(tab_id)
        instance = self.tab_manager.get_tab(tab_id)
        self._on_tab_switched(tab_id, instance)
        
        return tab_id
    
    def _load_tree_to_tab(self, tab_id: str, tree_file: str):
        instance = self.tab_manager.get_tab(tab_id)
        if not instance or not instance.canvas:
            return
        
        try:
            data = load_json(tree_file)
            instance.canvas.load_tree(data)
            instance.file_path = tree_file
        except Exception as e:
            messagebox.showerror("错误", f"加载行为树失败: {e}")
    
    def _create_new_tab(self, name: str, project_root: str = None, 
                        file_path: str = None) -> str:
        context = ExecutionContext(project_root=project_root)
        context.set_message_bus(getattr(self.app, '_message_bus', None))
        engine = BehaviorTreeEngine(None)
        command_manager = CommandManager()
        
        pm = None
        if project_root:
            from bt_utils.project_manager import ProjectManager
            try:
                pm = ProjectManager(project_root)
            except Exception:
                pm = None
        
        BehaviorTreeEditor._tab_counter += 1
        tab_id = f"tab_{BehaviorTreeEditor._tab_counter}"
        
        new_canvas = BehaviorTreeCanvas(
            self.canvas_frame,
            self.app,
            on_node_select=self._on_node_select,
            on_node_move=self._on_node_move,
            on_nodes_move=self._on_nodes_move,
            on_connection_add=self._on_connection_add,
            on_node_deselect=self._on_node_deselect,
            property_panel=self.property_panel
        )
        new_canvas.place(in_=self.canvas_frame, x=0, y=0, relwidth=1, relheight=1)
        new_canvas.lower()
        
        instance = TreeInstance(
            name=name,
            engine=engine,
            context=context,
            blackboard=context.blackboard,
            tab_id=tab_id,
            canvas=new_canvas,
            file_path=file_path,
            project_root=project_root,
            modified=False,
            command_manager=command_manager,
            project_manager=pm
        )
        
        autosave_manager = self._create_autosave_for_tab(instance)
        instance._autosave_manager = autosave_manager
        
        self.tab_manager.add_tab(tab_id, instance)
        self.tab_bar.add_tab(tab_id, name)
        
        autosave_manager.start()
        
        return tab_id
    
    def _create_toolbar(self):
        self.toolbar = EditorToolbar(
            self.main_container,
            self.app,
            on_save=self.save_tree,
            on_export=self.export_tree,
            on_import=self.import_tree,
            on_new_project=self._on_new_project_dialog,
            on_open_project=self._on_open_project_dialog,
            on_undo=self.undo,
            on_redo=self.redo,
            on_clear=lambda: self.clear_canvas(confirm=True),
            on_reset_view=self.reset_view,
            on_start=self._start_running,
            on_stop=self._stop_running,
            on_open_folder=self._open_project_folder,
            )
        self.toolbar.pack(fill="x")
    
    def _create_main_area(self):
        self.main_area = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.main_area.pack(fill="both", expand=True)
        
        self._create_palette()
        self._create_canvas()
        self._create_property_panel()
        
        self._create_log_panel()
    
    def _create_log_panel(self):
        self.log_panel = LogPanel(self.main_container)
        self.log_panel.pack(fill="x", side="bottom")
    
    def _create_palette(self):
        self.palette = NodePalette(
            self.main_area,
            on_node_add=self._on_node_add_from_palette
        )
        self.palette.pack(side="left", fill="y")
    
    def _create_canvas(self):
        self.canvas_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.canvas_frame.pack(side="left", fill="both", expand=True)
        
        self._fallback_canvas = BehaviorTreeCanvas(
            self.canvas_frame,
            self.app,
            on_node_select=self._on_node_select,
            on_node_move=self._on_node_move,
            on_nodes_move=self._on_nodes_move,
            on_connection_add=self._on_connection_add,
            on_node_deselect=self._on_node_deselect,
            property_panel=None
        )
        self._fallback_canvas.place(in_=self.canvas_frame, x=0, y=0, relwidth=1, relheight=1)
        
        self.property_panel = PropertyPanel(
            self.main_area,
            self.app,
            on_change=self._on_property_change
        )
        self.property_panel.pack(side="right", fill="y")
        
        self._fallback_canvas.property_panel = self.property_panel
        
        self._init_first_tab()
        
        self._init_autosave()
        self._start_autosave()
    
    def _init_first_tab(self):
        BehaviorTreeEditor._tab_counter += 1
        tab_id = f"tab_{BehaviorTreeEditor._tab_counter}"

        context = ExecutionContext(project_root=self._fallback_project_root)
        context.set_message_bus(getattr(self.app, '_message_bus', None))
        engine = BehaviorTreeEngine(None)
        command_manager = CommandManager()

        instance = TreeInstance(
            name=self._get_project_name(),
            engine=engine,
            context=context,
            blackboard=context.blackboard,
            tab_id=tab_id,
            canvas=self._fallback_canvas,
            file_path=self._fallback_file_path,
            project_root=self._fallback_project_root,
            modified=False,
            command_manager=command_manager,
            project_manager=self._fallback_project_manager
        )

        autosave_manager = self._create_autosave_for_tab(instance)
        instance._autosave_manager = autosave_manager

        self.tab_manager.add_tab(tab_id, instance)
        self.tab_bar.add_tab(tab_id, instance.name)

        autosave_manager.start()
    
    def _create_autosave_for_tab(self, instance: TreeInstance) -> AutoSaveManager:
        """为 Tab 创建 AutoSaveManager"""
        return AutoSaveManager(
            get_data_func=instance.canvas.get_tree_data if instance.canvas else lambda: {},
            on_save_callback=self._on_autosave_complete,
            autosave_dir=self.BACKUP_DIR,
            get_file_path_func=lambda inst=instance: inst.file_path
        )
    
    def _get_project_name(self) -> str:
        from bt_utils.project_manager import ProjectManager
        if self._fallback_project_root:
            return ProjectManager.resolve_project_name(self._fallback_project_root)
        return "未命名"
    
    def _update_tab_name(self, tab_id: str, name: str):
        """更新 Tab 名称"""
        instance = self.tab_manager.get_tab(tab_id)
        if instance:
            instance.name = name
            self.tab_bar.update_tab_name(tab_id, name)
            self._update_title(name)
    
    def _create_property_panel(self):
        pass

    def _bind_events(self):
        self._init_ui_dispatcher()
        self._bind_run_shortcuts()
    
    def _init_ui_dispatcher(self):
        from bt_utils.ui_dispatcher import UIUpdateDispatcher
        self._dispatcher = UIUpdateDispatcher()
        self._dispatcher.attach(self)
        self._dispatcher.start_polling()
    
    def _bind_run_shortcuts(self):
        """绑定运行快捷键（从设置读取）- 使用全局热键"""
        start_key = "F10"
        stop_key = "F12"
        record_key = "F11"
        
        try:
            from config.settings_manager import SettingsManager
            settings_manager = SettingsManager.get_instance()
            start_key = settings_manager.get("shortcuts.start", "F10")
            stop_key = settings_manager.get("shortcuts.stop", "F12")
            record_key = settings_manager.get("shortcuts.record", "F11")
        except Exception:
            pass
        
        self._start_shortcut = start_key
        self._stop_shortcut = stop_key
        self._record_shortcut = record_key
        self._tab_shortcut_keys = []  # 单树快捷键注册列表
        
        def start_callback():
            self._start_running()
        
        def stop_callback():
            self._stop_running()
        
        self._hotkey_manager.register(start_key, start_callback)
        self._hotkey_manager.register(stop_key, stop_callback)
        self._hotkey_manager.register(record_key, self._toggle_recording)
        
        # 注册单树快捷键
        self._register_tab_shortcuts()
        
        self._hotkey_manager.start()
    
    def _toggle_recording(self):
        """切换录制状态"""
        try:
            if hasattr(self.app, 'script_editor') and hasattr(self.app.script_editor, 'toggle_recording'):
                self.app.script_editor.toggle_recording()
        except Exception as e:
            LogManager.debug_print(f"[WARN] 切换录制状态失败: {e}")
    
    def update_run_shortcuts(self, start_key: str, stop_key: str, record_key: str = None):
        """更新运行快捷键"""
        if hasattr(self, '_start_shortcut') and self._start_shortcut:
            self._hotkey_manager.unregister(self._start_shortcut)
        if hasattr(self, '_stop_shortcut') and self._stop_shortcut:
            self._hotkey_manager.unregister(self._stop_shortcut)
        if hasattr(self, '_record_shortcut') and self._record_shortcut and record_key:
            self._hotkey_manager.unregister(self._record_shortcut)
        
        self._hotkey_manager.register(start_key, self._start_running)
        self._hotkey_manager.register(stop_key, self._stop_running)
        
        self._start_shortcut = start_key
        self._stop_shortcut = stop_key
        
        if record_key:
            self._hotkey_manager.register(record_key, self._toggle_recording)
            self._record_shortcut = record_key
    
    def _register_tab_shortcuts(self):
        """从设置中注册单树快捷键"""
        # 先注销已有的单树快捷键
        for key in self._tab_shortcut_keys:
            self._hotkey_manager.unregister(key)
        self._tab_shortcut_keys.clear()
        
        try:
            from config.settings_manager import SettingsManager
            settings_manager = SettingsManager.get_instance()
            tab_shortcuts = settings_manager.get("shortcuts.tab_shortcuts", [])
            
            for ts in tab_shortcuts:
                hotkey = ts.get("hotkey", "").strip()
                if not hotkey:
                    continue
                tab_name = ts.get("tab_name", "").strip()
                # 使用闭包绑定 tab_name
                callback = lambda tn=tab_name: self._toggle_tab(tn)
                self._hotkey_manager.register(hotkey, callback)
                self._tab_shortcut_keys.append(hotkey)
        except Exception:
            pass
    
    def update_tab_shortcuts(self, tab_shortcuts: list):
        """更新单树快捷键绑定（由设置页面调用）"""
        # 先注销已有的单树快捷键
        for key in self._tab_shortcut_keys:
            self._hotkey_manager.unregister(key)
        self._tab_shortcut_keys.clear()
        
        for ts in tab_shortcuts:
            hotkey = ts.get("hotkey", "").strip()
            if not hotkey:
                continue
            tab_name = ts.get("tab_name", "").strip()
            callback = lambda tn=tab_name: self._toggle_tab(tn)
            self._hotkey_manager.register(hotkey, callback)
            self._tab_shortcut_keys.append(hotkey)
    
    def _toggle_tab(self, tab_name: str):
        """切换指定行为树的运行/停止状态"""
        if not tab_name:
            return
        
        # 按 tab_name 查找对应的 tab_id
        target_tab_id = None
        for tid, instance in self.tab_manager._trees.items():
            if instance.name == tab_name:
                target_tab_id = tid
                break
        
        if not target_tab_id:
            return
        
        instance = self.tab_manager.get_tab(target_tab_id)
        if not instance:
            return
        
        if instance.is_running:
            self._handle_tab_stop(target_tab_id)
        else:
            self._handle_tab_run(target_tab_id)
    
    def _on_node_add_from_palette(self, node_type: str):
        self._node_counter += 1
        node_id = f"node_{self._node_counter}"
        
        while node_id in self.canvas.nodes:
            self._node_counter += 1
            node_id = f"node_{self._node_counter}"
        
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        x = (canvas_width / 2 - self.canvas.pan_x) / self.canvas.zoom
        y = (canvas_height / 3 - self.canvas.pan_y) / self.canvas.zoom
        
        offset = 0
        for existing_node in self.canvas.nodes.values():
            if abs(existing_node.x - x) < 160 and abs(existing_node.y - y) < 70:
                offset += 80
        
        x += offset
        
        name = NODE_DISPLAY_NAMES.get(node_type, node_type)
        
        """为特定节点类型生成默认配置"""
        node_config = {}
        if node_type == "AlarmNode":
            from bt_utils.resource_manager import ResourceManager
            from config.settings_manager import SettingsManager
            
            default_sound = ResourceManager().get_alarm_sound_path()
            default_volume = SettingsManager().get("alarm_volume", 70)
            
            node_config = {
                "sound_path": default_sound,
                "volume": default_volume,
                "wait_complete": True,
                "repeat_count": 0,
                "interval_ms": 0
            }
        elif node_type == "DelayNode":
            node_config = {
                "duration_ms": 1000
            }
        
        command = AddNodeCommand(
            canvas=self.canvas,
            node_id=node_id,
            node_type=node_type,
            x=x,
            y=y,
            node_data={'name': name, 'config': node_config}
        )
        command.description = f"添加{name}"
        
        self.command_manager.execute(command)
        self._update_toolbar()
        self._set_modified(True)
    
    def _on_node_select(self, node_id: str, node_type: str):
        node = self.canvas.nodes.get(node_id)
        if node:
            node_config = node.config if hasattr(node, 'config') else {}
            
            node_data = {
                "id": node_id,
                "type": node_type,
                "name": node.name,
                "config": node_config,
                "enabled": node.enabled,
                "skip": getattr(node, 'skip', bool((node_config or {}).get('skip', False)))
            }
            self.property_panel.load_node(node_id, node_type, node_data)
    
    def _on_node_deselect(self):
        self.property_panel.save_and_clear()
    
    def _on_node_move(self, node_id: str, old_x: float, old_y: float, new_x: float, new_y: float):
        command = MoveNodeCommand(
            canvas=self.canvas,
            node_id=node_id,
            old_x=old_x,
            old_y=old_y,
            new_x=new_x,
            new_y=new_y
        )
        self.command_manager.undo_stack.append(command)
        self._update_toolbar()
        self._set_modified(True)
    
    def _on_nodes_move(self, old_positions: Dict[str, tuple], new_positions: Dict[str, tuple]):
        command = MoveNodesCommand(
            canvas=self.canvas,
            node_ids=list(new_positions.keys()),
            old_positions=old_positions,
            new_positions=new_positions
        )
        self.command_manager.undo_stack.append(command)
        self._update_toolbar()
        self._set_modified(True)
    
    def _on_connection_add(self, parent_id: str, child_id: str):
        command = AddConnectionCommand(
            canvas=self.canvas,
            parent_id=parent_id,
            child_id=child_id
        )
        self.command_manager.undo_stack.append(command)
        self._update_toolbar()
        self._set_modified(True)
    
    def _on_property_change(self, node_id: str, key: str, value: Any):
        if node_id not in self.canvas.nodes:
            return
        
        node = self.canvas.nodes[node_id]
        
        if node.config is None:
            node.config = {}
        
        node.config[key] = value
        
        if key in ["name", "enabled", "skip"]:
            setattr(node, key, value)
            if key == "name":
                self.canvas.redraw_node(node_id)
            elif key == "skip":
                node.config[key] = bool(value)
                node.skip = bool(value)
                self.canvas.redraw_node(node_id)
        
        self._set_modified(True)
    
    def _check_protected_nodes(self, node_ids: List[str]) -> tuple:
        """检查节点是否受保护
        
        Args:
            node_ids: 要检查的节点ID列表
        
        Returns:
            (可删除节点列表, 受保护节点列表)
        """
        deletable = []
        protected = []
        
        for node_id in node_ids:
            node_item = self.canvas.nodes.get(node_id)
            if node_item and node_item.is_protected():
                protected.append(node_id)
            else:
                deletable.append(node_id)
        
        return deletable, protected
    
    def _show_protected_warning(self, protected_count: int) -> None:
        """显示受保护节点警告
        
        Args:
            protected_count: 受保护节点数量
        """
        if protected_count > 0:
            messagebox.showwarning("无法删除", "开始节点不可删除")
    
    def _delete_selected(self):
        """删除选中的节点或连接"""
        if self.canvas.selected_nodes:
            node_ids = list(self.canvas.selected_nodes)
            self._delete_nodes_with_check(node_ids)
        elif self.canvas.selected_node:
            self._delete_nodes_with_check([self.canvas.selected_node])
        elif self.canvas.selected_connections:
            self._delete_connections(list(self.canvas.selected_connections))
        elif self.canvas.selected_connection:
            self._delete_connection(self.canvas.selected_connection)
    
    def _delete_nodes_with_check(self, node_ids: List[str]) -> None:
        """删除节点（带保护检查）
        
        Args:
            node_ids: 要删除的节点ID列表
        """
        deletable, protected = self._check_protected_nodes(node_ids)
        self._show_protected_warning(len(protected))
        
        if not deletable:
            return
        
        if len(deletable) == 1:
            command = RemoveNodeCommand(canvas=self.canvas, node_id=deletable[0])
        else:
            command = RemoveNodesCommand(canvas=self.canvas, node_ids=deletable)
        
        self.command_manager.execute(command)
        self._update_toolbar()
        self._set_modified(True)
    
    def _delete_connection(self, connection: tuple) -> None:
        """删除连接
        
        Args:
            connection: (parent_id, child_id) 元组
        """
        parent_id, child_id = connection
        command = RemoveConnectionCommand(
            canvas=self.canvas,
            parent_id=parent_id,
            child_id=child_id
        )
        self.command_manager.execute(command)
        self.canvas.selected_connection = None
        self._update_toolbar()
        self._set_modified(True)
    
    def _delete_connections(self, connections: List[tuple]) -> None:
        """批量删除连接
        
        Args:
            connections: 连接列表,每个元素为 (parent_id, child_id) 元组
        """
        for connection in connections:
            parent_id, child_id = connection
            command = RemoveConnectionCommand(
                canvas=self.canvas,
                parent_id=parent_id,
                child_id=child_id
            )
            self.command_manager.execute(command)
        self.canvas.selected_connections = []
        self.canvas.selected_connection = None
        self._update_toolbar()
        self._set_modified(True)
    
    def _delete_node(self, node_id: str):
        """删除单个节点（兼容旧接口）"""
        self._delete_nodes_with_check([node_id])
    
    def _delete_nodes(self, node_ids: List[str]):
        """删除多个节点（兼容旧接口）"""
        self._delete_nodes_with_check(node_ids)
    
    def _copy_selected(self):
        if self.canvas.selected_nodes:
            result = self.canvas._copy_selected_nodes_to_clipboard()
            self._clipboard_data = result
        elif self.canvas.selected_node:
            result = self.canvas._copy_selected_nodes_to_clipboard()
            self._clipboard_data = result
    
    def _paste_selected(self, paste_x: float = None, paste_y: float = None):
        if not self._clipboard_data:
            return
        
        from copy import deepcopy
        
        clipboard_data = self._clipboard_data
        nodes_data = clipboard_data.get('nodes', [])
        relative_positions = clipboard_data.get('relative_positions', {})
        connections = clipboard_data.get('connections', [])
        
        if not nodes_data:
            return
        
        if paste_x is not None and paste_y is not None:
            paste_offset_x, paste_offset_y = self._calculate_paste_offset_at(
                relative_positions, paste_x, paste_y)
        else:
            paste_offset_x, paste_offset_y = self._calculate_paste_offset(relative_positions)
        
        if len(nodes_data) == 1:
            node_data = nodes_data[0]
            self._node_counter += 1
            new_id = f"node_{self._node_counter}"
            
            while new_id in self.canvas.nodes:
                self._node_counter += 1
                new_id = f"node_{self._node_counter}"
            
            rel_x, rel_y = relative_positions.get(node_data['id'], (0, 0))
            
            command = AddNodeCommand(
                canvas=self.canvas,
                node_id=new_id,
                node_type=node_data['type'],
                x=rel_x + paste_offset_x,
                y=rel_y + paste_offset_y,
                node_data={
                    'name': node_data.get('name', ''),
                    'config': deepcopy(node_data.get('config', {})),
                    'enabled': node_data.get('enabled', True)
                }
            )
            command.description = f"粘贴 {node_data.get('name', '节点')}"
            self.command_manager.execute(command)
            
            self._select_new_nodes([new_id])
            self._set_modified(True)
            self._update_toolbar()
        else:
            id_map = {}
            new_nodes_data = []
            
            for node_data in nodes_data:
                old_id = node_data['id']
                self._node_counter += 1
                new_id = f"node_{self._node_counter}"
                
                while new_id in self.canvas.nodes:
                    self._node_counter += 1
                    new_id = f"node_{self._node_counter}"
                
                id_map[old_id] = new_id
                
                rel_x, rel_y = relative_positions.get(old_id, (0, 0))
                
                new_nodes_data.append({
                    'id': new_id,
                    'type': node_data['type'],
                    'x': rel_x + paste_offset_x,
                    'y': rel_y + paste_offset_y,
                    'name': node_data.get('name', ''),
                    'config': deepcopy(node_data.get('config', {})),
                    'enabled': node_data.get('enabled', True)
                })
            
            new_connections = []
            for old_parent, old_child in connections:
                new_parent = id_map.get(old_parent)
                new_child = id_map.get(old_child)
                if new_parent and new_child:
                    new_connections.append((new_parent, new_child))
            
            command = AddNodesCommand(
                canvas=self.canvas,
                nodes_data=new_nodes_data,
                connections=new_connections,
                description=f"粘贴 {len(new_nodes_data)} 个节点"
            )
            self.command_manager.execute(command)
            
            new_ids = [n['id'] for n in new_nodes_data]
            self._select_new_nodes(new_ids)
            
            self._set_modified(True)
            self._update_toolbar()
    
    def _calculate_paste_offset(self, relative_positions: Dict[str, tuple] = None) -> tuple:
        canvas_width = self.canvas.canvas.winfo_width() or 800
        canvas_height = self.canvas.canvas.winfo_height() or 600
        
        screen_center_x = canvas_width / 2
        screen_center_y = canvas_height / 2
        
        canvas_center_x = (screen_center_x - self.canvas.pan_x) / self.canvas.zoom
        canvas_center_y = (screen_center_y - self.canvas.pan_y) / self.canvas.zoom
        
        offset_x = canvas_center_x
        offset_y = canvas_center_y
        
        if not relative_positions:
            return offset_x, offset_y
        
        paste_width = 0
        paste_height = 0
        for rel_x, rel_y in relative_positions.values():
            paste_width = max(paste_width, rel_x)
            paste_height = max(paste_height, rel_y)
        
        paste_width += 160
        paste_height += 70
        
        node_width = 160
        node_height = 70
        offset_increment = 80
        max_attempts = 50
        
        for attempt in range(max_attempts):
            has_overlap = False
            
            paste_left = offset_x
            paste_top = offset_y
            paste_right = offset_x + paste_width
            paste_bottom = offset_y + paste_height
            
            for existing_node in self.canvas.nodes.values():
                node_left = existing_node.x
                node_top = existing_node.y
                node_right = existing_node.x + node_width
                node_bottom = existing_node.y + node_height
                
                if (paste_left < node_right and paste_right > node_left and
                    paste_top < node_bottom and paste_bottom > node_top):
                    has_overlap = True
                    break
            
            if not has_overlap:
                break
            
            offset_x += offset_increment
            offset_y += offset_increment
        
        return offset_x, offset_y
    
    def _calculate_paste_offset_at(self, relative_positions: Dict[str, tuple] = None,
                                    target_x: float = 0, target_y: float = 0) -> tuple:
        offset_x = target_x
        offset_y = target_y
        
        if relative_positions:
            min_rel_x = min(rel_x for rel_x, _ in relative_positions.values()) if relative_positions else 0
            min_rel_y = min(rel_y for _, rel_y in relative_positions.values()) if relative_positions else 0
            offset_x = target_x - min_rel_x
            offset_y = target_y - min_rel_y
        
        return offset_x, offset_y
    
    def _select_new_nodes(self, node_ids: List[str]):
        """选中新节点"""
        self.canvas._deselect_all()
        
        for node_id in node_ids:
            if node_id in self.canvas.nodes:
                self.canvas.selected_nodes.append(node_id)
                self.canvas.nodes[node_id].set_selected(True)
        
        if self.canvas.selected_nodes:
            self.canvas.selected_node = self.canvas.selected_nodes[0]
            if len(self.canvas.selected_nodes) == 1:
                node = self.canvas.nodes[self.canvas.selected_node]
                if self.canvas.on_node_select:
                    self.canvas.on_node_select(self.canvas.selected_node, node.node_type)
    
    def _cut_selected(self):
        self._copy_selected()
        self._delete_selected()
    
    def _duplicate_selected(self):
        self._copy_selected()
        self._paste_selected()
    
    def undo(self):
        if self.command_manager.can_undo():
            self.command_manager.undo()
            self._update_toolbar()
            if not self.command_manager.can_undo():
                self._set_modified(False)
            else:
                self._set_modified(True)
    
    def redo(self):
        if self.command_manager.can_redo():
            self.command_manager.redo()
            self._update_toolbar()
            self._set_modified(True)
    
    def _update_toolbar(self):
        self.toolbar.update_undo_redo(
            self.command_manager.can_undo(),
            self.command_manager.can_redo(),
            self.command_manager.get_undo_description(),
            self.command_manager.get_redo_description()
        )
    
    def new_tree(self):
        """新建行为树项目"""
        if self._modified:
            result = messagebox.askyesnocancel(
                "未保存的改动",
                "当前项目有未保存的改动。\n\n是否保存？"
            )
            if result is None:
                return
            elif result:
                self.save_tree()
        
        self._on_new_project_dialog()
    
    def load_tree(self, file_path: Optional[str] = None, skip_clear: bool = False):
        if not file_path:
            from tkinter import filedialog
            file_path = filedialog.askopenfilename(
                title="打开行为树",
                filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")]
            )
        
        if not file_path:
            return
        
        try:
            data = load_json(file_path)
            
            if not skip_clear:
                self.clear_canvas()
            self.canvas.load_tree(data)
            self.file_path = file_path
            self._set_modified(False)
            
            project_root = self._find_project_root(file_path)
            
            if project_root:
                self.project_root = project_root
                from bt_utils.project_manager import ProjectManager
                self.project_manager = ProjectManager(self.project_root)
                self.toolbar.set_project_path(self.project_root)

                project_name = ProjectManager.resolve_project_name(project_root)
                active_tab = self.tab_manager.get_active_tab()
                if active_tab:
                    self._update_tab_name(active_tab.tab_id, project_name)
            else:
                self.project_root = None
                self.project_manager = None
                self.toolbar.set_file_path(file_path)
                
                file_name = os.path.splitext(os.path.basename(file_path))[0]
                active_tab = self.tab_manager.get_active_tab()
                if active_tab:
                    self._update_tab_name(active_tab.tab_id, file_name)
            
            from config.settings_manager import SettingsManager
            SettingsManager.get_instance().set_last_file_path(file_path)
            
        except Exception as e:
            messagebox.showerror("错误", f"加载文件失败: {str(e)}")
    
    def _find_project_root(self, file_path: str) -> Optional[str]:
        """向上查找项目根目录
        
        Args:
            file_path: 当前文件路径
            
        Returns:
            项目根目录路径，如果未找到则返回 None
        """
        current_dir = os.path.dirname(file_path)
        
        while current_dir:
            project_json_path = os.path.join(current_dir, "project.json")
            if os.path.exists(project_json_path):
                return current_dir
            
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:
                break
            current_dir = parent_dir
        
        return None
    
    def _import_old_script(self, script_path: str):
        """导入旧脚本及其关联的资源
        
        Args:
            script_path: 旧脚本文件路径
        """
        try:
            script_data = load_json(script_path)
            
            script_dir = os.path.dirname(script_path)
            
            updated_data = self._migrate_resources(script_data, script_dir)
            
            self.project_manager.save_project(updated_data)
            
            self.canvas.load_tree(updated_data)
            
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("错误", f"导入旧脚本失败: {str(e)}")
    
    def _migrate_resources(self, data: dict, script_dir: str) -> dict:
        """迁移脚本中的资源引用
        
        Args:
            data: 脚本数据
            script_dir: 脚本所在目录
            
        Returns:
            更新后的脚本数据
        """
        from bt_utils.resource_service import ResourceService
        
        if "nodes" not in data:
            return data
        
        nodes = data["nodes"]
        items = nodes.items() if isinstance(nodes, dict) else enumerate(nodes)
        
        for node_key, node in items:
            if "config" not in node:
                continue
            
            config = node["config"]
            
            for key, value in list(config.items()):
                if not isinstance(value, str):
                    continue
                
                if not ResourceService.is_resource_path(value):
                    continue
                
                absolute_path = self._resolve_old_path(value, script_dir)
                
                if not absolute_path or not os.path.exists(absolute_path):
                    continue
                
                abs_project_root = os.path.abspath(self.project_root)
                abs_source_path = os.path.abspath(absolute_path)
                
                if ResourceService.is_path_in_project(abs_source_path, abs_project_root):
                    continue
                
                resource_type = self._detect_resource_type(key, value)
                
                try:
                    new_relative_path = ResourceService.import_single_file_to_project(
                        absolute_path,
                        self.project_root,
                        resource_type
                    )
                    if new_relative_path:
                        config[key] = new_relative_path
                except Exception as e:
                    LogManager.debug_print(f"导入资源失败 {absolute_path}: {e}")
        
        return data
    
    def _is_resource_path(self, path: str) -> bool:
        """判断是否为资源路径
        
        Args:
            path: 路径字符串
            
        Returns:
            是否为资源路径
        """
        if not path:
            return False
        
        resource_extensions = [
            '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff',
            '.wav', '.mp3', '.ogg', '.flac',
            '.py', '.bat', '.cmd', '.sh',
            '.json', '.yaml', '.yml', '.txt', '.csv'
        ]
        
        path_lower = path.lower()
        return any(path_lower.endswith(ext) for ext in resource_extensions)
    
    def _resolve_old_path(self, path: str, script_dir: str) -> str:
        """解析旧脚本中的资源路径
        
        Args:
            path: 资源路径
            script_dir: 脚本所在目录
            
        Returns:
            绝对路径
        """
        if os.path.isabs(path):
            return path
        
        if path.startswith('./'):
            relative_path = path[2:]
        else:
            relative_path = path
        
        absolute_path = os.path.join(script_dir, relative_path)
        return os.path.normpath(absolute_path)
    
    def _detect_resource_type(self, key: str, path: str) -> str:
        """检测资源类型
        
        Args:
            key: 配置键名
            path: 资源路径
            
        Returns:
            资源类型（与ResourceImporter兼容）
        """
        key_lower = key.lower()
        
        if key_lower == 'code_path':
            return 'code'
        elif key_lower == 'script_path':
            return 'script'
        elif key_lower == 'template_path':
            return 'image'
        elif key_lower == 'sound_path':
            return 'audio'
        
        path_lower = path.lower()
        
        if any(path_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff']):
            return 'image'
        elif any(path_lower.endswith(ext) for ext in ['.wav', '.mp3', '.ogg', '.flac']):
            return 'audio'
        elif any(path_lower.endswith(ext) for ext in ['.py', '.bat', '.cmd', '.sh', '.ps1']):
            return 'script'
        else:
            if 'image' in key_lower or 'template' in key_lower or 'screenshot' in key_lower:
                return 'image'
            elif 'sound' in key_lower or 'audio' in key_lower or 'alarm' in key_lower:
                return 'audio'
            elif 'code' in key_lower:
                return 'code'
            elif 'script' in key_lower:
                return 'script'
            else:
                return 'data'
    
    def save_tree(self, file_path: Optional[str] = None, save_as: bool = False):
        if self.project_root and self.project_manager and not save_as:
            tree_data = self.canvas.get_tree_data()
            
            from bt_utils.resource_service import ResourceService
            tree_data = ResourceService.save_with_cleanup(tree_data, self.project_root)
            self.canvas.load_tree(tree_data)
            
            self.project_manager.save_project(tree_data)
            
            active_tab = self.tab_manager.get_active_tab()
            if active_tab and hasattr(active_tab, '_autosave_manager') and active_tab._autosave_manager:
                active_tab._autosave_manager.clear_autosaves()
            
            if self.file_path:
                from config.settings_manager import SettingsManager
                SettingsManager.get_instance().set_last_file_path(self.file_path)
            
            self._set_modified(False)
            return
        
        if not self.project_root or save_as:
            # 无项目上下文（如 AI 生成的临时树）：把当前画布上的树
            # 保存进新建的项目，而不是清空画布新建空白项目
            self._convert_to_project()
            return
        
        if not file_path:
            from tkinter import filedialog
            from config.settings_manager import SettingsManager
            
            settings = SettingsManager.get_instance()
            default_path = settings.get("default_project_path", "")
            
            if not default_path or not os.path.exists(default_path):
                default_path = SettingsManager.get_default_workspace_path()
                
                try:
                    os.makedirs(default_path, exist_ok=True)
                except Exception:
                    default_path = ""
            
            initial_dir = default_path if default_path else None
            initial_file = None
            
            if self.file_path and os.path.exists(self.file_path):
                initial_dir = os.path.dirname(self.file_path)
                initial_file = os.path.basename(self.file_path)
            
            file_path = filedialog.asksaveasfilename(
                title="保存行为树",
                initialdir=initial_dir,
                initialfile=initial_file,
                defaultextension=".json",
                filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")]
            )
        
        if not file_path:
            return
        
        try:
            data = self.canvas.get_tree_data()
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            self.file_path = file_path
            self._set_modified(False)
            self.toolbar.set_file_path(file_path)
            
            active_tab = self.tab_manager.get_active_tab()
            if active_tab and hasattr(active_tab, '_autosave_manager') and active_tab._autosave_manager:
                active_tab._autosave_manager.clear_autosaves()
            
            from config.settings_manager import SettingsManager
            SettingsManager.get_instance().set_last_file_path(file_path)
            
        except Exception as e:
            messagebox.showerror("错误", f"保存文件失败: {str(e)}")
    
    def export_tree(self):
        """导出行为树项目为 ZIP 文件"""
        from tkinter import filedialog, messagebox
        
        if not self.file_path:
            messagebox.showwarning("提示", "请先保存项目")
            return
        
        project_root = None
        
        if self.project_root and os.path.exists(self.project_root):
            project_root = self.project_root
        else:
            script_dir = os.path.dirname(self.file_path)
            project_json_path = os.path.join(script_dir, "project.json")
            
            if os.path.exists(project_json_path):
                project_root = script_dir
        
        if not project_root:
            result = messagebox.askyesno(
                "提示",
                "当前脚本不在项目文件夹中。\n\n"
                "导出功能需要项目文件夹结构。\n\n"
                "是否要将当前脚本保存为新的项目？\n"
                "（将创建项目文件夹结构并保存当前行为树）"
            )
            
            if result:
                self._convert_to_project()
            return
        
        tree_data = self.canvas.get_tree_data()
        
        from bt_utils.resource_service import ResourceService
        tree_data = ResourceService.save_with_cleanup(tree_data, project_root)
        self.canvas.load_tree(tree_data)
        
        if self.project_manager:
            self.project_manager.save_project(tree_data)
        else:
            tree_path = os.path.join(project_root, "tree.json")
            with open(tree_path, 'w', encoding='utf-8') as f:
                json.dump(tree_data, f, ensure_ascii=False, indent=2)

        from bt_utils.project_manager import ProjectManager
        project_name = ProjectManager.resolve_project_name(project_root)
        default_filename = f"{project_name}.zip"

        # 导出 ZIP 前一致性校验：文件夹名 vs project_info.name
        cancel_export = self._check_and_prompt_name_consistency_on_export(project_root)
        if cancel_export:
            return
        
        from config.settings_manager import SettingsManager
        settings = SettingsManager.get_instance()
        
        initial_dir = None
        last_export_path = settings.get_last_export_path()
        
        if last_export_path and os.path.exists(os.path.dirname(last_export_path)):
            initial_dir = os.path.dirname(last_export_path)
        elif project_root:
            initial_dir = os.path.dirname(project_root)
        
        output_path = filedialog.asksaveasfilename(
            title="导出项目",
            initialdir=initial_dir,
            initialfile=default_filename,
            defaultextension=".zip",
            filetypes=[("ZIP文件", "*.zip"), ("所有文件", "*.*")]
        )
        
        if not output_path:
            return
        
        if not output_path.lower().endswith('.zip'):
            output_path = output_path + '.zip'
        
        try:
            from bt_utils.package_exporter import PackageExporter
            exporter = PackageExporter(project_root)
            zip_path = exporter.export_to_zip(output_path)
            
            settings.set_last_export_path(output_path)
            
            messagebox.showinfo("成功", f"项目已导出到:\n{zip_path}")
            
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {str(e)}")
    
    def import_tree(self):
        """从 ZIP 文件导入项目"""
        from tkinter import filedialog, messagebox
        from bt_utils.package_importer import PackageImporter
        from config.settings_manager import SettingsManager
        
        settings = SettingsManager.get_instance()
        
        last_export_path = settings.get_last_export_path()
        initial_dir = None
        if last_export_path and os.path.exists(os.path.dirname(last_export_path)):
            initial_dir = os.path.dirname(last_export_path)
        
        zip_path = filedialog.askopenfilename(
            title="选择项目压缩包",
            initialdir=initial_dir,
            filetypes=[("ZIP文件", "*.zip"), ("所有文件", "*.*")]
        )
        
        if not zip_path:
            return
        
        importer = PackageImporter()
        
        is_valid, error_msg = importer.validate_package(zip_path)
        if not is_valid:
            messagebox.showerror("错误", f"无效的项目压缩包:\n{error_msg}")
            return
        
        project_name = importer.get_project_name(zip_path)
        if not project_name:
            project_name = os.path.splitext(os.path.basename(zip_path))[0]
        
        workspace_path = SettingsManager.get_default_workspace_path()
        
        try:
            os.makedirs(workspace_path, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"无法创建工作区目录:\n{str(e)}")
            return
        
        target_project_path = os.path.join(workspace_path, project_name)
        
        if os.path.exists(target_project_path):
            result = messagebox.askyesnocancel(
                "项目已存在",
                f"工作区中已存在同名项目 '{project_name}'。\n\n"
                f"是否覆盖现有项目？\n"
                f"• 选择「是」将删除现有项目并导入新项目\n"
                f"• 选择「否」将自动重命名新项目\n"
                f"• 选择「取消」将终止导入"
            )
            
            if result is None:
                return
            elif result:
                success, error_msg, imported_path = importer.import_from_zip(
                    zip_path, 
                    workspace_path, 
                    overwrite=True
                )
            else:
                new_name = importer.generate_new_name(project_name, workspace_path)
                success, error_msg, imported_path = importer.import_from_zip(
                    zip_path, 
                    workspace_path, 
                    overwrite=False,
                    new_name=new_name
                )
        else:
            success, error_msg, imported_path = importer.import_from_zip(
                zip_path, 
                workspace_path, 
                overwrite=False
            )
        
        if not success:
            messagebox.showerror("错误", f"导入项目失败:\n{error_msg}")
            return
        
        try:
            self.open_project(imported_path)
            
            settings.set_last_export_path(zip_path)
            
            imported_name = os.path.basename(imported_path)
            messagebox.showinfo("成功", f"项目 '{imported_name}' 导入成功！\n\n项目位置:\n{imported_path}")
            
        except Exception as e:
            messagebox.showerror("错误", f"打开导入的项目失败:\n{str(e)}")
    
    def _convert_to_project(self):
        """将当前脚本转换为项目文件夹"""
        from tkinter import messagebox
        from bt_gui.dialogs.new_project_dialog import NewProjectDialog
        
        dialog = NewProjectDialog(self.app)
        self.app.wait_window(dialog)
        
        if dialog.result:
            try:
                name = dialog.result["name"]
                location = dialog.result["location"]
                description = dialog.result.get("description", "")
                
                self.project_root = os.path.join(location, name)
                
                from bt_utils.project_manager import ProjectManager
                self.project_manager = ProjectManager(self.project_root)
                self.project_manager.create_project(name, description)
                
                tree_data = self.canvas.get_tree_data()
                # 与正常保存路径一致：把树引用的子树/模板等资源一并清理并复制进新项目，
                # 避免 AI 临时树转项目后资源引用失效
                from bt_utils.resource_service import ResourceService
                tree_data = ResourceService.save_with_cleanup(tree_data, self.project_root)
                self.canvas.load_tree(tree_data)
                self.project_manager.save_project(tree_data)
                
                self.file_path = os.path.join(self.project_root, "tree.json")
                self._update_title(name)
                self._set_modified(False)

                active_tab = self.tab_manager.get_active_tab()
                if active_tab and hasattr(active_tab, '_autosave_manager') and active_tab._autosave_manager:
                    active_tab._autosave_manager.clear_autosaves()

                self.toolbar.set_project_path(self.project_root)
                
                messagebox.showinfo("成功", f"项目 '{name}' 创建成功，当前行为树已保存到项目中")
                
            except Exception as e:
                messagebox.showerror("错误", f"转换项目失败: {str(e)}")
    
    def clear_canvas(self, confirm: bool = False):
        if confirm and self.canvas.nodes:
            if not messagebox.askyesno("确认", "确定要清空画布吗？"):
                return
        
        self.canvas.clear_canvas()
        self.command_manager.clear()
        self._update_toolbar()
        self._set_modified(False)
    
    def reset_view(self):
        self.canvas.reset_view()
    
    def _open_project_folder(self):
        """打开项目文件夹"""
        import platform
        
        folder_path = None
        
        if self.project_root:
            if os.path.exists(self.project_root):
                folder_path = self.project_root
            else:
                self.project_root = None
        
        if not folder_path and self.file_path:
            if os.path.exists(self.file_path):
                folder_path = os.path.dirname(self.file_path)
            else:
                self.file_path = None
        
        if not folder_path:
            messagebox.showwarning("提示", "请先保存项目")
            return
        
        try:
            folder_path = os.path.abspath(folder_path)
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":
                import subprocess
                subprocess.run(["open", folder_path])
            else:
                import subprocess
                subprocess.run(["xdg-open", folder_path])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件夹: {str(e)}")
    
    def _start_running(self):
        if self._is_running:
            return
        
        started_count = 0
        for tab_id in list(self.tab_manager._trees.keys()):
            instance = self.tab_manager.get_tab(tab_id)
            if instance and not instance.is_running:
                self._handle_tab_run(tab_id)
                started_count += 1
        
        if started_count > 0:
            self._is_running = True
            self.toolbar.set_running(True)

    def _stop_running(self):
        # ★ 通知DD输入控制器停止所有操作
        try:
            from bt_utils.dd_input import DDVirtualInput
            DDVirtualInput.request_stop()
        except Exception:
            pass
        
        stopped_count = 0
        for tab_id in list(self.tab_manager._trees.keys()):
            instance = self.tab_manager.get_tab(tab_id)
            if instance and instance.is_running:
                self._handle_tab_stop(tab_id)
                stopped_count += 1
        
        self._is_running = False
        self.toolbar.set_running(False)
    
    def _play_start_sound(self):
        try:
            from bt_utils.alarm import AlarmPlayer
            player = AlarmPlayer()
            player.play_start_sound()
        except Exception:
            pass

    def _play_stop_sound(self):
        try:
            from bt_utils.alarm import AlarmPlayer
            player = AlarmPlayer()
            player.play_stop_sound()
        except Exception:
            pass

    def _on_node_status(self, node_id: str, status: str, tab_id: str = None):
        from .node_item import NodeExecutionStatus
        status_map = {
            "running": NodeExecutionStatus.RUNNING,
            "success": NodeExecutionStatus.SUCCESS,
            "failure": NodeExecutionStatus.FAILURE,
            "aborted": NodeExecutionStatus.ABORTED,
            "idle": NodeExecutionStatus.IDLE,
        }
        node_status = status_map.get(status, NodeExecutionStatus.IDLE)
        
        # 如果指定了 tab_id，只更新对应 tab 的画布
        if tab_id:
            instance = self.tab_manager.get_tab(tab_id)
            if instance and instance.canvas and node_id in instance.canvas.nodes:
                instance.canvas.set_node_status(node_id, node_status)
            return
        
        # 兼容旧调用：未指定 tab_id 时遍历所有 tab 查找
        for tid, instance in self.tab_manager._trees.items():
            if instance.canvas and node_id in instance.canvas.nodes:
                instance.canvas.set_node_status(node_id, node_status)
                return

    def _set_modified(self, modified: bool):
        self._modified = modified
        active_tab = self.tab_manager.get_active_tab()
        if active_tab:
            active_tab.modified = modified
        if modified:
            self.on_content_changed()
    
    def get_tree_data(self) -> Dict[str, Any]:
        return self.canvas.get_tree_data()

    def get_start_node(self):
        for node_id, node in self.canvas.nodes.items():
            if node.node_type == "StartNode":
                from bt_core.config import NodeConfig
                config = NodeConfig(name=getattr(node, 'name', ''))
                node_config = node.config if hasattr(node, 'config') else {}
                for key, value in node_config.items():
                    config.set(key, value)
                from bt_core.nodes import StartNode
                return StartNode(node_id=node_id, config=config)
        return None
    
    def set_tree_data(self, data: Dict[str, Any]):
        self.canvas.load_tree(data)
    
    def _init_autosave(self):
        pass
    
    def _start_autosave(self):
        pass
    
    def _on_autosave_complete(self, success: bool):
        if not success:
            LogManager.debug_print("[WARN] 自动保存失败")
    
    def on_content_changed(self):
        active_tab = self.tab_manager.get_active_tab()
        if active_tab and hasattr(active_tab, '_autosave_manager') and active_tab._autosave_manager:
            active_tab._autosave_manager.on_content_changed()
    
    def _check_crash_recovery(self):
        if not hasattr(self, '_crash_recovery_handler'):
            return
        
        self._crash_recovery_handler.cleanup_old_crash_files(keep_days=7)
        
        if not self._crash_recovery_handler.has_crash_recovery():
            return
        
        crash_info = self._crash_recovery_handler.get_latest_crash_info()
        if not crash_info:
            return
        
        result = messagebox.askyesno(
            "崩溃恢复",
            f"检测到上次未正常关闭的会话:\n"
            f"时间: {crash_info.get('crash_time', '未知')}\n"
            f"异常: {crash_info.get('crash_type', '未知')}\n\n"
            f"是否恢复该会话？"
        )
        
        if result:
            data = self._crash_recovery_handler.load_crash_file(crash_info["path"])
            if data:
                self.canvas.load_tree(data)
                self._set_modified(True)
                
                metadata = data.get("metadata", {})
                saved_file_path = metadata.get("file_path")
                if saved_file_path and os.path.exists(saved_file_path):
                    self.file_path = saved_file_path
                    project_root = self._find_project_root(saved_file_path)
                    if project_root:
                        self.project_root = project_root
                        from bt_utils.project_manager import ProjectManager
                        self.project_manager = ProjectManager(self.project_root)
                        self.toolbar.set_project_path(self.project_root)
                    else:
                        self.toolbar.set_file_path(saved_file_path)
                else:
                    self.toolbar.set_file_path(None)
                
                LogManager.debug_print("[OK] 已自动恢复上次未保存的会话")
        
        self._crash_recovery_handler.delete_crash_file(crash_info["path"])
    
    @property
    def canvas(self):
        """代理到当前活动 Tab 的画布"""
        tab = self.tab_manager.get_active_tab()
        return tab.canvas if tab else self._fallback_canvas
    
    @canvas.setter
    def canvas(self, value):
        self._fallback_canvas = value
    
    @property
    def engine(self):
        """代理到当前活动 Tab 的引擎"""
        tab = self.tab_manager.get_active_tab()
        return tab.engine if tab else self._fallback_engine
    
    @engine.setter
    def engine(self, value):
        self._fallback_engine = value
        if hasattr(self, 'tab_manager'):
            tab = self.tab_manager.get_active_tab()
            if tab:
                tab.engine = value
    
    @property
    def context(self):
        """代理到当前活动 Tab 的上下文"""
        tab = self.tab_manager.get_active_tab()
        return tab.context if tab else self._fallback_context
    
    @context.setter
    def context(self, value):
        self._fallback_context = value
        if hasattr(self, 'tab_manager'):
            tab = self.tab_manager.get_active_tab()
            if tab:
                tab.context = value
    
    @property
    def project_root(self):
        """代理到当前活动 Tab 的项目根目录"""
        tab = self.tab_manager.get_active_tab()
        return tab.project_root if tab else self._fallback_project_root
    
    @project_root.setter
    def project_root(self, value):
        self._fallback_project_root = value
        if hasattr(self, 'tab_manager'):
            tab = self.tab_manager.get_active_tab()
            if tab:
                tab.project_root = value
    
    @property
    def file_path(self):
        """代理到当前活动 Tab 的文件路径"""
        tab = self.tab_manager.get_active_tab()
        return tab.file_path if tab else self._fallback_file_path
    
    @file_path.setter
    def file_path(self, value):
        self._fallback_file_path = value
        if hasattr(self, 'tab_manager'):
            tab = self.tab_manager.get_active_tab()
            if tab:
                tab.file_path = value
    
    @property
    def command_manager(self):
        """代理到当前活动 Tab 的命令管理器"""
        tab = self.tab_manager.get_active_tab()
        return tab.command_manager if tab else self._fallback_command_manager
    
    @command_manager.setter
    def command_manager(self, value):
        self._fallback_command_manager = value
        if hasattr(self, 'tab_manager'):
            tab = self.tab_manager.get_active_tab()
            if tab:
                tab.command_manager = value
    
    @property
    def project_manager(self):
        tab = self.tab_manager.get_active_tab()
        return tab.project_manager if tab else self._fallback_project_manager
    
    @project_manager.setter
    def project_manager(self, value):
        self._fallback_project_manager = value
        if hasattr(self, 'tab_manager'):
            tab = self.tab_manager.get_active_tab()
            if tab:
                tab.project_manager = value
    
    def _on_tab_switched(self, tab_id: str, instance: TreeInstance):
        if not instance or not instance.canvas:
            return
        
        current_tab = self.tab_manager.get_active_tab()
        if current_tab and current_tab.canvas:
            selected = list(current_tab.canvas.selected_nodes) if current_tab.canvas.selected_nodes else []
            current_tab.selected_node_id = selected[0] if selected else None
        
        self._fallback_project_root = instance.project_root
        self._fallback_file_path = instance.file_path
        self._fallback_project_manager = instance.project_manager
        
        instance.canvas.tkraise()
        
        self.property_panel.save_and_clear()
        
        if instance.selected_node_id and instance.canvas:
            if instance.selected_node_id in instance.canvas.nodes:
                instance.canvas._select_node(instance.selected_node_id)
        
        self._update_title(instance.name)
        self.toolbar.set_project_path(instance.project_root)
        self.toolbar.set_running(instance.is_running)
        
        if instance.command_manager:
            self.toolbar.update_undo_redo(
                can_undo=instance.command_manager.can_undo(),
                can_redo=instance.command_manager.can_redo()
            )
    
    def _on_tab_status_changed(self, tab_id: str, running: bool):
        self.tab_bar.set_running(tab_id, running)
        
        any_running = False
        for tid, inst in self.tab_manager._trees.items():
            if inst.is_running:
                any_running = True
                break
        
        self._is_running = any_running
        self.toolbar.set_running(any_running)
    
    def _on_tab_removed(self, tab_id: str):
        """Tab 移除回调"""
        self.tab_bar.remove_tab(tab_id)
    
    def new_project(self, name: str, location: str, description: str = "", script_path: str = None):
        from bt_utils.project_manager import ProjectManager
        
        project_root = os.path.join(location, name)
        pm = ProjectManager(project_root)
        pm.create_project(name, description)
        
        active_tab = self.tab_manager.get_active_tab()
        need_new_tab = (active_tab is not None and 
                       (active_tab.modified or active_tab.project_root)) or active_tab is None
        
        if need_new_tab:
            tab_id = self._create_new_tab(name, project_root)
            self.tab_manager.switch_tab(tab_id)
            self.tab_bar.set_active(tab_id)
            instance = self.tab_manager.get_tab(tab_id)
            self._on_tab_switched(tab_id, instance)
        else:
            self.canvas.clear_canvas(force=True)
        
        self.project_root = project_root
        self.project_manager = pm
        
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width <= 0:
            canvas_width = 800
        if canvas_height <= 0:
            canvas_height = 600
        
        x = canvas_width / 2
        y = canvas_height * 0.2
        
        self.canvas.add_node(
            node_id="node_start",
            node_type="StartNode",
            x=x,
            y=y,
            name="开始",
            config={},
            enabled=True
        )
        
        if script_path and os.path.exists(script_path):
            self._import_old_script(script_path)
        else:
            tree_data = self.canvas.get_tree_data()
            pm.save_project(tree_data)
        
        self._update_title(name)
        
        self._set_modified(False)
        self.file_path = os.path.join(self.project_root, "tree.json")
        
        self.toolbar.set_project_path(self.project_root)
    
    def open_project(self, project_root: str):
        from bt_utils.project_manager import ProjectManager

        for existing_id, existing_instance in self.tab_manager._trees.items():
            if existing_instance.project_root and os.path.samefile(existing_instance.project_root, project_root):
                self.tab_manager.switch_tab(existing_id)
                self.tab_bar.set_active(existing_id)
                instance = self.tab_manager.get_tab(existing_id)
                self._on_tab_switched(existing_id, instance)
                return

        pm = ProjectManager(project_root)

        if not pm.validate_project():
            raise ValueError("项目文件不完整或损坏")

        config = pm.load_project()
        # 项目名以文件夹名为权威源（SSOT），project_info.name 仅作元数据
        project_name = ProjectManager.resolve_project_name(project_root)

        # 打开项目时一致性校验：文件夹名 vs project_info.name
        self._check_and_prompt_name_consistency_on_open(project_root)

        active_tab = self.tab_manager.get_active_tab()
        need_new_tab = (active_tab is not None and 
                       (active_tab.modified or active_tab.project_root)) or active_tab is None
        
        if need_new_tab:
            tab_id = self._create_new_tab(project_name, project_root)
            self.tab_manager.switch_tab(tab_id)
            self.tab_bar.set_active(tab_id)
            instance = self.tab_manager.get_tab(tab_id)
            self._on_tab_switched(tab_id, instance)
        
        self.project_root = project_root
        self.project_manager = pm
        
        tree_file = os.path.join(project_root, "tree.json")
        self.load_tree(tree_file, skip_clear=need_new_tab)
        
        self._update_title(project_name)
        
        active_tab = self.tab_manager.get_active_tab()
        if active_tab:
            self._update_tab_name(active_tab.tab_id, project_name)
        
        self.file_path = tree_file
        
        self.toolbar.set_project_path(self.project_root)
        
        from config.settings_manager import SettingsManager
        SettingsManager.get_instance().set_last_file_path(tree_file)

    def _check_and_prompt_name_consistency_on_open(self, project_root: str) -> None:
        """打开项目时校验文件夹名与 project_info.name 是否一致。

        不一致时弹窗提示，让用户选择：
          ① 同步 project_info.name 为文件夹名（推荐）
          ② 忽略，本次按文件夹名显示（不修改文件）

        系统永远不会自动修改文件夹名。
        """
        from bt_utils.project_manager import ProjectManager
        check = ProjectManager.check_name_consistency(project_root)
        if check["consistent"]:
            return
        folder_name = check["folder_name"]
        info_name = check["project_info_name"]
        result = messagebox.askyesno(
            "项目名称不一致",
            f"检测到名称不一致：\n\n"
            f"  文件夹名：{folder_name}\n"
            f"  项目名称：{info_name}\n\n"
            f"系统将以文件夹名 '{folder_name}' 作为项目名称。\n"
            f"是否同步更新 项目名称 为 '{folder_name}'？\n\n"
            f"（是 = 同步 项目名称；否 = 仅本次按文件夹名显示，不修改文件）",
            icon=messagebox.WARNING,
        )
        if result:
            ok = ProjectManager.update_project_info_name(project_root, folder_name)
            if ok:
                try:
                    from bt_utils.log_manager import LogManager
                    LogManager.debug_print(
                        f"[Sync] 打开项目时同步 project_info.name: '{info_name}' -> '{folder_name}'"
                    )
                except Exception:
                    pass
            else:
                messagebox.showerror("错误", f"更新 project.json 失败，请检查文件权限。")
        else:
            try:
                from bt_utils.log_manager import LogManager
                LogManager.debug_print(
                    f"[Sync] 用户选择不同步，本次以文件夹名 '{folder_name}' 显示"
                )
            except Exception:
                pass

    def _check_and_prompt_name_consistency_on_export(self, project_root: str) -> bool:
        """导出 ZIP 前校验文件夹名与 project_info.name 是否一致。

        不一致时弹窗提示，让用户选择：
          ① 同步 project_info.name 为文件夹名后继续导出（推荐）
          ② 取消导出（用户可手动修改文件夹名后再次导出）

        系统永远不会自动修改文件夹名。

        Returns:
            True 表示取消导出；False 表示继续导出
        """
        from bt_utils.project_manager import ProjectManager
        check = ProjectManager.check_name_consistency(project_root)
        if check["consistent"]:
            return False
        folder_name = check["folder_name"]
        info_name = check["project_info_name"]
        result = messagebox.askyesnocancel(
            "项目名称不一致",
            f"导出前检测到名称不一致：\n\n"
            f"  文件夹名：{folder_name}\n"
            f"  项目名称：{info_name}\n\n"
            f"导出 ZIP 将以文件夹名 '{folder_name}' 作为项目名。\n"
            f"是否同步更新 项目名称 为 '{folder_name}' 后继续导出？\n\n"
            f"（是 = 同步并继续导出；否 = 直接导出不同步；取消 = 取消导出）",
            icon=messagebox.WARNING,
        )
        if result is None:
            # 取消
            return True
        if result:
            # 是：同步
            ok = ProjectManager.update_project_info_name(project_root, folder_name)
            if not ok:
                messagebox.showerror("错误", f"更新 project.json 失败，请检查文件权限。")
                return True
            try:
                from bt_utils.log_manager import LogManager
                LogManager.debug_print(
                    f"[Sync] 导出前同步 project_info.name: '{info_name}' -> '{folder_name}'"
                )
            except Exception:
                pass
        # 否：直接导出不同步
        return False

    def save_project(self):
        """保存项目"""
        if not self.project_manager:
            raise RuntimeError("未打开项目")
        
        tree_data = self.canvas.get_tree_data()
        
        if self.project_root:
            from bt_utils.resource_service import ResourceService
            tree_data = ResourceService.save_with_cleanup(tree_data, self.project_root)
            self.canvas.load_tree(tree_data)
        
        self.project_manager.save_project(tree_data)
        
        self._set_modified(False)
    
    def export_project(self, output_path: str = None):
        """导出项目"""
        if not self.project_manager:
            raise RuntimeError("未打开项目")
        
        from bt_utils.package_exporter import PackageExporter
        exporter = PackageExporter(self.project_root)
        return exporter.export_to_zip(output_path)
    
    def _on_new_project_dialog(self):
        """显示新建项目对话框"""
        from bt_gui.dialogs.new_project_dialog import NewProjectDialog
        
        dialog = NewProjectDialog(self.app)
        self.app.wait_window(dialog)
        
        if dialog.result:
            try:
                name = dialog.result["name"]
                location = dialog.result["location"]
                description = dialog.result.get("description", "")
                script_path = dialog.result.get("script_path")
                
                self.new_project(name, location, description, script_path)
                
                from tkinter import messagebox
                if script_path:
                    messagebox.showinfo("成功", f"项目 '{name}' 创建成功\n已导入旧脚本及其资源")
                else:
                    messagebox.showinfo("成功", f"项目 '{name}' 创建成功")
                
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("错误", f"创建项目失败: {str(e)}")
    
    def _on_open_project_dialog(self):
        """显示打开项目对话框"""
        from tkinter import filedialog, messagebox
        from config.settings_manager import SettingsManager
        
        settings_manager = SettingsManager()
        default_path = settings_manager.get("default_project_path", "")
        
        if not default_path or not os.path.exists(default_path):
            default_path = SettingsManager.get_default_workspace_path()
            
            try:
                os.makedirs(default_path, exist_ok=True)
            except Exception:
                default_path = ""
        
        project_root = filedialog.askdirectory(
            title="选择项目文件夹",
            initialdir=default_path if default_path else None
        )
        
        if project_root:
            try:
                self.open_project(project_root)
            except Exception as e:
                messagebox.showerror("错误", f"打开项目失败: {str(e)}")
    
    def _update_title(self, project_name: str):
        """更新窗口标题"""
        try:
            from main import VERSION
            self.winfo_toplevel().title(f"autodoor - 行为树 {VERSION} - {project_name}")
        except ImportError:
            self.winfo_toplevel().title(f"autodoor - 行为树 - {project_name}")
    
    def _init_auto_login(self):
        try:
            if self._login_manager.auto_login():
                username = self._login_manager.get_current_user() or ""
                LogManager.debug_print(f"[Auth] 自动登录成功: {username}")
        except Exception as e:
            LogManager.debug_print(f"[Auth] 自动登录失败: {e}")
    
    def _on_login_click(self):
        from bt_gui.auth.login_dialog import LoginDialog
        
        def on_login_success(username):
            display_name = self._login_manager.get_current_user() or username
            LogManager.debug_print(f"[Auth] 登录成功: {username} -> {display_name}")
        
        dialog = LoginDialog(
            self.app,
            login_manager=self._login_manager,
            on_success=on_login_success,
        )
        self.app.wait_window(dialog)
    
    def _on_logout_click(self):
        self._login_manager.logout()
        LogManager.debug_print("[Auth] 已登出")
    
    def get_login_manager(self):
        return self._login_manager
    
    def destroy(self):
        if hasattr(self, 'tab_manager'):
            for tab_id, instance in list(self.tab_manager._trees.items()):
                if hasattr(instance, '_autosave_manager') and instance._autosave_manager:
                    instance._autosave_manager.stop()
                    instance._autosave_manager.save_now()
                if instance.is_running:
                    self._handle_tab_stop(tab_id)
        
        if hasattr(self, '_crash_recovery_handler'):
            self._crash_recovery_handler.uninstall()
        
        if hasattr(self, '_hotkey_manager'):
            self._hotkey_manager.stop()
        
        if hasattr(self, 'log_panel') and self.log_panel:
            self.log_panel.destroy()
        
        super().destroy()
