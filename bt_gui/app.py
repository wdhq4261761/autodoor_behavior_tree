import customtkinter as ctk
import os
import sys
from tkinter import messagebox, StringVar

from .theme import Theme, init_theme
from .bt_editor import BehaviorTreeEditor
from .script_tab import ScriptTab
from .settings_tab import SettingsTab
from .plugin_panel import PluginStatusBarIndicator
from config.settings_manager import SettingsManager
from bt_utils.log_manager import LogManager
from bt_plugins.base import PluginContext
from bt_plugins.loader import PluginLoader


def _get_app_title() -> str:
    """获取应用标题，包含版本号"""
    try:
        from main import VERSION
        return f"autodoor - 行为树 {VERSION}"
    except ImportError:
        return "autodoor - 行为树"


class BehaviorTreeApp(ctk.CTk):
    
    def __init__(self):
        init_theme()
        
        super().__init__()
        
        self._dark_colors = Theme.get_dark_colors()
        self._keyfield_active = False
        
        self._settings = SettingsManager.get_instance()
        
        self.title(_get_app_title())
        
        saved_geometry = self._settings.get("session.window_geometry", "1280x800")
        self.geometry(saved_geometry)
        self.minsize(800, 600)
        
        self.configure(fg_color=self._dark_colors['bg_primary'])
        
        self._set_icon()
        
        self._create_ui()
        self._setup_shortcuts()

        self._restore_last_file()

        self._message_bus = None
        self._rest_server = None
        self._ws_server = None
        self._ws_loop = None
        self._init_message_bus_and_servers()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _restore_last_file(self):
        """恢复上次打开的文件和 Tab 列表"""
        open_tabs = self._settings.get_open_tabs()

        if open_tabs:
            from bt_utils.project_manager import ProjectManager
            restored_active_id = self._settings.get_active_tab_id()
            first_tab_id = None
            skipped_tabs = []

            for i, tab_info in enumerate(open_tabs):
                file_path = tab_info.get("file_path", "")
                project_root = tab_info.get("project_root", "")
                name = tab_info.get("name", "")

                # 原路径找不到 tree.json 时直接跳过，不导入空项目
                if not file_path or not os.path.exists(file_path):
                    skipped_tabs.append(name or file_path or project_root or "未知项目")
                    continue
                if project_root and not os.path.exists(project_root):
                    skipped_tabs.append(name or project_root or "未知项目")
                    continue

                if i == 0 or first_tab_id is None:
                    self.behavior_tree.load_tree(file_path)
                    if project_root and os.path.exists(project_root):
                        self.behavior_tree.project_root = project_root
                        self.behavior_tree.project_manager = ProjectManager(project_root)
                        self.behavior_tree.toolbar.set_project_path(project_root)
                        self.behavior_tree._check_and_prompt_name_consistency_on_open(project_root)
                        display_name = ProjectManager.resolve_project_name(project_root)
                    else:
                        display_name = name or os.path.splitext(os.path.basename(file_path))[0]
                    self.behavior_tree._update_tab_name(
                        self.behavior_tree.tab_manager.get_active_tab().tab_id, display_name
                    )
                    first_tab_id = self.behavior_tree.tab_manager.active_tab_id
                else:
                    if project_root and os.path.exists(project_root):
                        self.behavior_tree.import_project_to_new_tab(project_root)
                    else:
                        tab_id = self.behavior_tree._create_new_tab(
                            name or os.path.splitext(os.path.basename(file_path))[0],
                            project_root or None,
                            file_path
                        )
                        self.behavior_tree._load_tree_to_tab(tab_id, file_path)
                        self.behavior_tree.tab_manager.switch_tab(tab_id)
                        self.behavior_tree.tab_bar.set_active(tab_id)
                        instance = self.behavior_tree.tab_manager.get_tab(tab_id)
                        self.behavior_tree._on_tab_switched(tab_id, instance)

            # 所有保存的 Tab 都恢复失败时，关闭初始化时创建的默认空 Tab
            if first_tab_id is None:
                default_tab = self.behavior_tree.tab_manager.get_active_tab()
                if default_tab:
                    default_tab_id = default_tab.tab_id
                    if hasattr(default_tab, '_autosave_manager') and default_tab._autosave_manager:
                        default_tab._autosave_manager.stop()
                    self.behavior_tree.tab_manager.remove_tab(default_tab_id)

            if restored_active_id:
                active_instance = self.behavior_tree.tab_manager.get_tab(restored_active_id)
                if active_instance:
                    self.behavior_tree.tab_manager.switch_tab(restored_active_id)
                    self.behavior_tree.tab_bar.set_active(restored_active_id)
                    self.behavior_tree._on_tab_switched(restored_active_id, active_instance)

            # 有 Tab 恢复失败时弹窗提示用户
            if skipped_tabs:
                from tkinter import messagebox
                messagebox.showwarning(
                    "项目路径失效",
                    f"以下项目路径已失效，无法恢复：\n\n"
                    + "\n".join(f"  - {t}" for t in skipped_tabs)
                    + "\n\n请通过「打开项目」或「导入项目」重新定位。"
                )

            # 更新 settings，移除失效的 Tab
            if first_tab_id is None:
                self._settings.set_open_tabs([])
            elif skipped_tabs:
                valid_tabs = []
                for tab_id, instance in self.behavior_tree.tab_manager._trees.items():
                    if instance.file_path and os.path.exists(instance.file_path):
                        valid_tabs.append({
                            "tab_id": tab_id,
                            "name": instance.name,
                            "file_path": instance.file_path,
                            "project_root": instance.project_root or "",
                        })
                self._settings.set_open_tabs(valid_tabs)

            self._update_window_title()
        else:
            last_file = self._settings.get_last_file_path()
            if last_file and os.path.exists(last_file):
                try:
                    if hasattr(self, 'behavior_tree') and self.behavior_tree:
                        self.behavior_tree.load_tree(last_file)
                        self._update_window_title()
                except Exception:
                    pass
            else:
                # 无任何可恢复的项目，关闭初始化时创建的默认空 Tab
                default_tab = self.behavior_tree.tab_manager.get_active_tab()
                if default_tab:
                    default_tab_id = default_tab.tab_id
                    if hasattr(default_tab, '_autosave_manager') and default_tab._autosave_manager:
                        default_tab._autosave_manager.stop()
                    self.behavior_tree.tab_manager.remove_tab(default_tab_id)

    def _update_window_title(self):
        """更新窗口标题，显示项目名称和图标"""
        project_name = None
        project_icon = None
        if hasattr(self.behavior_tree, 'project_root') and self.behavior_tree.project_root:
            from bt_utils.project_manager import ProjectManager
            project_name = ProjectManager.resolve_project_name(self.behavior_tree.project_root)
            project_info = ProjectManager.read_project_info(self.behavior_tree.project_root)
            project_icon = project_info.get("icon")
        
        if project_name:
            try:
                from main import VERSION
                self.title(f"autodoor - 行为树 {VERSION} - {project_name}")
            except ImportError:
                self.title(f"autodoor - 行为树 - {project_name}")
        else:
            self.title(_get_app_title())
        
        if hasattr(self, '_app_icon_label'):
            if project_icon:
                try:
                    from PIL import Image, ImageTk
                    import os
                    icon_path = os.path.join(self.behavior_tree.project_root, project_icon)
                    if os.path.exists(icon_path):
                        image = Image.open(icon_path).resize((24, 24), Image.LANCZOS)
                        tk_image = ctk.CTkImage(image, size=(24, 24))
                        self._app_icon_label.configure(image=tk_image, text="")
                        self._app_icon_label.image = tk_image
                    else:
                        self._app_icon_label.configure(text=project_icon, image="")
                except Exception:
                    self._app_icon_label.configure(text=project_icon, image="")
            else:
                self._app_icon_label.configure(text='◉', image="")
    
    def _set_icon(self):
        """设置应用图标"""
        try:
            from bt_utils.resource_manager import get_resource_manager
            rm = get_resource_manager()
            icon_path = rm.get_icon_path()
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception as e:
            LogManager.debug_print(f"[WARN] 设置图标失败: {e}")
    
    def _create_ui(self):
        self._create_main_container()
    
    def _create_main_container(self):
        """创建主容器，包含顶部栏和内容区域"""
        self.main_container = ctk.CTkFrame(
            self,
            fg_color=self._dark_colors['bg_primary']
        )
        self.main_container.pack(fill='both', expand=True)

        self._create_top_bar()
        self._create_bottom_status_bar()
        self._create_content_area()

    def _create_bottom_status_bar(self):
        """创建底部状态栏（含插件状态指示器）"""
        self.bottom_status = ctk.CTkFrame(
            self.main_container,
            height=24,
            fg_color=self._dark_colors['bg_secondary'],
            corner_radius=0
        )
        self.bottom_status.pack(side='bottom', fill='x')
        self.bottom_status.pack_propagate(False)

        # 插件状态指示器（延迟到 _init_plugin_system 中创建）
        self._plugin_indicator = None

    def _show_plugin_panel(self):
        """切换到设置标签页的插件管理面板"""
        self._switch_tab('settings')
    
    def _create_top_bar(self):
        """创建顶部栏（包含标题、Tab按钮、操作按钮）"""
        self.top_bar = ctk.CTkFrame(
            self.main_container,
            height=Theme.DIMENSIONS['header_height'],
            fg_color=self._dark_colors['bg_secondary'],
            corner_radius=0
        )
        self.top_bar.pack(fill='x')
        self.top_bar.pack_propagate(False)
        
        top_bar_content = ctk.CTkFrame(self.top_bar, fg_color='transparent')
        top_bar_content.pack(fill='x', padx=Theme.DIMENSIONS['spacing_md'], 
                            pady=Theme.DIMENSIONS['spacing_sm'])
        
        left_section = ctk.CTkFrame(top_bar_content, fg_color='transparent')
        left_section.pack(side='left')
        
        self._app_icon_label = ctk.CTkLabel(
            left_section,
            text='◉',
            font=Theme.get_font('xl'),
            text_color=self._dark_colors['primary']
        )
        self._app_icon_label.pack(side='left', padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        ctk.CTkLabel(
            left_section,
            text='AutoDoor Behavior Tree',
            font=Theme.get_font('lg'),
            text_color=self._dark_colors['text_primary']
        ).pack(side='left')
        
        try:
            from main import VERSION
            ctk.CTkLabel(
                left_section,
                text=VERSION,
                font=Theme.get_font('xs'),
                text_color=self._dark_colors['primary'],
                fg_color=self._dark_colors['info_light'],
                corner_radius=4,
                padx=6,
                pady=1
            ).pack(side='left', padx=Theme.DIMENSIONS['spacing_sm'])
        except ImportError:
            pass

        # ============================================================
        # 登录 UI 暂不对外开放（注释保留，后端登录接口仍可用）
        # 如需恢复，取消下方注释即可
        # ============================================================
        # self._auth_btn = ctk.CTkButton(
        #     left_section,
        #     text="登录",
        #     width=60,
        #     height=28,
        #     font=Theme.get_font('xs'),
        #     fg_color=self._dark_colors['primary'],
        #     hover_color=self._dark_colors['primary_hover'],
        #     corner_radius=4,
        #     command=self._on_auth_click
        # )
        # self._auth_btn.pack(side='left', padx=Theme.DIMENSIONS['spacing_sm'])
        #
        # self._auth_status_var = StringVar(value="未登录")
        # self._auth_status_label = ctk.CTkLabel(
        #     left_section,
        #     textvariable=self._auth_status_var,
        #     font=Theme.get_font('xs'),
        #     text_color=self._dark_colors['text_muted']
        # )
        # self._auth_status_label.pack(side='left', padx=(0, Theme.DIMENSIONS['spacing_sm']))
        
        center_section = ctk.CTkFrame(top_bar_content, fg_color='transparent')
        center_section.pack(side='left', expand=True)
        
        self.tab_buttons_frame = ctk.CTkFrame(
            center_section,
            fg_color=self._dark_colors['bg_tertiary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.tab_buttons_frame.pack()
        
        self.tab_buttons = {}
        tab_config = [
            ('bt', '🌲 行为树编辑器'),
            ('script', '📝 脚本录制'),
            ('settings', '⚙ 设置'),
            ('plugins', '🔌 插件管理')
        ]
        
        for i, (tab_id, tab_text) in enumerate(tab_config):
            btn = ctk.CTkButton(
                self.tab_buttons_frame,
                text=tab_text,
                width=120,
                height=32,
                font=Theme.get_font('sm'),
                fg_color=self._dark_colors['primary'] if i == 0 else 'transparent',
                hover_color=self._dark_colors['primary_hover'] if i == 0 else self._dark_colors['border'],
                text_color=self._dark_colors['text_primary'],
                corner_radius=Theme.DIMENSIONS['button_corner_radius'],
                command=lambda tid=tab_id: self._switch_tab(tid)
            )
            btn.pack(side='left', padx=2, pady=2)
            self.tab_buttons[tab_id] = btn
        
        right_section = ctk.CTkFrame(top_bar_content, fg_color='transparent')
        right_section.pack(side='right')
        
        from bt_utils.version_checker import open_tool_intro, open_video_tutorial
        
        self.check_update_btn = ctk.CTkButton(
            right_section,
            text='检查更新',
            width=80,
            height=35,
            font=Theme.get_font('sm'),
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            command=self._check_for_updates
        )
        self.check_update_btn.pack(side='left', padx=Theme.DIMENSIONS['spacing_xs'])
        
        self.tool_intro_btn = ctk.CTkButton(
            right_section,
            text='使用文档',
            width=80,
            height=35,
            font=Theme.get_font('sm'),
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            command=open_tool_intro
        )
        self.tool_intro_btn.pack(side='left', padx=Theme.DIMENSIONS['spacing_xs'])
        
        self.video_tutorial_btn = ctk.CTkButton(
            right_section,
            text='视频教程',
            width=80,
            height=35,
            font=Theme.get_font('sm'),
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            command=open_video_tutorial
        )
        self.video_tutorial_btn.pack(side='left', padx=Theme.DIMENSIONS['spacing_xs'])
    
    def _switch_tab(self, tab_id: str):
        """切换Tab"""
        for tid, btn in self.tab_buttons.items():
            if tid == tab_id:
                btn.configure(
                    fg_color=self._dark_colors['primary'],
                    hover_color=self._dark_colors['primary_hover']
                )
            else:
                btn.configure(
                    fg_color='transparent',
                    hover_color=self._dark_colors['border']
                )
        
        for tid, frame in self.tab_frames.items():
            if tid == tab_id:
                frame.pack(fill='both', expand=True)
            else:
                frame.pack_forget()
    
    def _create_content_area(self):
        """创建内容区域"""
        self.content_frame = ctk.CTkFrame(
            self.main_container,
            fg_color=self._dark_colors['bg_primary']
        )
        self.content_frame.pack(fill='both', expand=True, padx=Theme.DIMENSIONS['spacing_sm'], 
                               pady=Theme.DIMENSIONS['spacing_sm'])
        
        self.tab_frames = {}
        
        bt_frame = ctk.CTkFrame(self.content_frame, fg_color='transparent')
        script_frame = ctk.CTkFrame(self.content_frame, fg_color='transparent')
        settings_frame = ctk.CTkFrame(self.content_frame, fg_color='transparent')
        plugins_frame = ctk.CTkFrame(self.content_frame, fg_color='transparent')

        self.tab_frames['bt'] = bt_frame
        self.tab_frames['script'] = script_frame
        self.tab_frames['settings'] = settings_frame
        self.tab_frames['plugins'] = plugins_frame
        
        self.behavior_tree = BehaviorTreeEditor(bt_frame, self)
        self.behavior_tree.pack(fill='both', expand=True)
        
        self.script_editor = ScriptTab(script_frame, self)
        self.script_editor.pack(fill='both', expand=True)
        
        self.settings = SettingsTab(settings_frame, self)
        self.settings.pack(fill='both', expand=True)
        
        saved_settings = self._settings.get_all_settings()
        if saved_settings:
            self.settings.load_settings(saved_settings)

        # 初始化插件系统：扫描内置插件目录并加载（不自动启动）
        self._plugin_loader = None
        self._init_plugin_system()

        bt_frame.pack(fill='both', expand=True)

    def _init_plugin_system(self):
        """初始化插件系统：创建上下文与加载器，扫描并加载内置插件和用户插件（不自动启动）"""
        import traceback
        try:
            import bt_plugins
            from bt_utils.resource_manager import get_user_plugin_dir
            builtin_dir = os.path.join(os.path.dirname(bt_plugins.__file__), 'builtin')
            # 用户插件目录（打包版 = exe 同级 plugins/，开发版 = 项目根 plugins/）
            user_plugin_dir = get_user_plugin_dir()

            plugin_context = PluginContext(settings=self._settings)
            self._plugin_loader = PluginLoader(plugin_context)

            # 扫描内置插件目录并逐个加载
            loaded_count = 0
            for info in self._plugin_loader.scan(builtin_dir):
                plugin_dir = os.path.join(builtin_dir, info.name)
                if self._plugin_loader.load_plugin(plugin_dir):
                    loaded_count += 1

            # 扫描用户插件目录并逐个加载
            if os.path.isdir(user_plugin_dir):
                for info in self._plugin_loader.scan(user_plugin_dir):
                    plugin_dir = os.path.join(user_plugin_dir, info.name)
                    if self._plugin_loader.load_plugin(plugin_dir):
                        loaded_count += 1

            # 恢复上次运行中被启动过的插件（autostart 持久化标记）
            started_count = self._plugin_loader.autostart_all()
            LogManager.debug_print(
                f"[Plugin] 插件系统初始化完成，已加载 {loaded_count} 个插件，"
                f"自动启动 {started_count} 个上次启用的插件"
            )

            # 将插件 loader 注入节点面板，使插件节点能动态显示
            if hasattr(self.behavior_tree, 'palette'):
                self.behavior_tree.palette.set_plugin_loader(self._plugin_loader)

            # 在独立的插件管理 Tab 页中创建 PluginPanel
            from .plugin_panel import PluginPanel
            self._plugin_panel = PluginPanel(
                self.tab_frames['plugins'], self._plugin_loader,
                on_plugins_changed=self._on_plugins_changed
            )
            self._plugin_panel.pack(fill="both", expand=True,
                                    padx=Theme.DIMENSIONS['spacing_md'],
                                    pady=Theme.DIMENSIONS['spacing_md'])

            # 创建插件状态指示器（底部状态栏）
            if hasattr(self, 'bottom_status') and self._plugin_loader:
                self._plugin_indicator = PluginStatusBarIndicator(
                    self.bottom_status,
                    self._plugin_loader,
                    on_click=self._show_plugin_panel
                )
                self._plugin_indicator.pack(side='left', padx=Theme.DIMENSIONS['spacing_md'])
        except Exception as e:
            error_msg = f"[ERROR] 插件系统初始化失败: {e}\n{traceback.format_exc()}"
            LogManager.debug_print(error_msg)
            # 同时写入启动错误日志文件，确保问题可追溯
            try:
                from main import write_log
                write_log(error_msg)
            except Exception:
                pass
            self._plugin_loader = None

    def _on_plugins_changed(self):
        """插件启停后触发：刷新节点面板中的插件节点分类"""
        try:
            if hasattr(self.behavior_tree, 'palette'):
                self.behavior_tree.palette.refresh_plugin_nodes()
            # 刷新底部状态栏插件指示器
            if hasattr(self, '_plugin_indicator') and self._plugin_indicator:
                self._plugin_indicator.refresh()
        except Exception as e:
            LogManager.debug_print(f"[WARN] 刷新节点面板插件节点失败: {e}")

    def _check_for_updates(self):
        """检查更新"""
        if hasattr(self, '_version_checker'):
            self._version_checker.check_for_updates(manual=True)
        else:
            from tkinter import messagebox
            messagebox.showinfo("检查更新", "版本检查器未初始化")
    
    def _on_auth_click(self):
        if hasattr(self, 'behavior_tree') and self.behavior_tree:
            login_manager = getattr(self.behavior_tree, '_login_manager', None)
            if login_manager and login_manager.is_authenticated():
                self.behavior_tree._on_logout_click()
            else:
                self.behavior_tree._on_login_click()
    
    def set_auth_status(self, authenticated: bool, username: str = ""):
        if hasattr(self, '_auth_btn') and hasattr(self, '_auth_status_var') and hasattr(self, '_auth_status_label'):
            if authenticated:
                self._auth_btn.configure(text="登出", fg_color=self._dark_colors['error'], hover_color='#DC2626')
                self._auth_status_var.set(username)
                self._auth_status_label.configure(text_color=Theme.COLORS['success'])
            else:
                self._auth_btn.configure(text="登录", fg_color=self._dark_colors['primary'], hover_color=self._dark_colors['primary_hover'])
                self._auth_status_var.set("未登录")
                self._auth_status_label.configure(text_color=self._dark_colors['text_muted'])
    
    def _get_current_tab(self) -> str:
        """获取当前Tab ID"""
        for tab_id, frame in self.tab_frames.items():
            if frame.winfo_ismapped():
                return tab_id
        return 'bt'
    
    def _setup_shortcuts(self):
        shortcuts = [
            ("<Control-z>", self._undo),
            ("<Control-y>", self._redo),
            ("<Control-Shift-Z>", self._redo),
            ("<Control-s>", self._save),
            ("<Control-Shift-S>", lambda: self._save(save_as=True)),
            ("<Control-o>", self._open),
            ("<Control-n>", self._new),
            ("<Delete>", self._delete),
            ("<BackSpace>", self._delete),
            ("<Control-c>", self._copy),
            ("<Control-v>", self._paste),
            ("<Control-x>", self._cut),
            ("<Control-d>", self._duplicate),
        ]
        
        for key, callback in shortcuts:
            self.bind(key, lambda e, cb=callback, k=key: self._handle_shortcut(e, cb, k))
    
    def _handle_shortcut(self, event, callback, key_name):
        if key_name in ("<Delete>", "<BackSpace>"):
            if self._keyfield_active:
                return "break"
        
        if callable(callback):
            callback()
        return "break"
    
    def set_keyfield_active(self, active: bool):
        self._keyfield_active = active
    
    def _undo(self):
        if hasattr(self.behavior_tree, 'undo'):
            self.behavior_tree.undo()
    
    def _redo(self):
        if hasattr(self.behavior_tree, 'redo'):
            self.behavior_tree.redo()
    
    def _save(self, save_as=False):
        current_tab = self._get_current_tab()
        if current_tab == 'bt':
            if hasattr(self.behavior_tree, 'save_tree'):
                self.behavior_tree.save_tree(save_as=save_as)
        elif current_tab == 'script':
            if hasattr(self.script_editor, '_save_script'):
                self.script_editor._save_script()
    
    def _open(self):
        current_tab = self._get_current_tab()
        if current_tab == 'bt':
            if hasattr(self.behavior_tree, 'load_tree'):
                self.behavior_tree.load_tree()
        elif current_tab == 'script':
            if hasattr(self.script_editor, '_load_script'):
                self.script_editor._load_script()
    
    def _new(self):
        current_tab = self._get_current_tab()
        if current_tab == 'bt':
            if hasattr(self.behavior_tree, 'new_tree'):
                self.behavior_tree.new_tree()
        elif current_tab == 'script':
            if hasattr(self.script_editor, '_new_script'):
                self.script_editor._new_script()
    
    def _delete(self):
        if self._is_focused_on_input_widget():
            return
        current_tab = self._get_current_tab()
        if current_tab == 'bt':
            if hasattr(self.behavior_tree, '_delete_selected'):
                self.behavior_tree._delete_selected()
    
    def _is_focused_on_input_widget(self) -> bool:
        """检查当前焦点是否在输入控件上"""
        focused = self.focus_get()
        if focused:
            widget_type = str(type(focused).__name__)
            if widget_type in ("CTkEntry", "Entry", "CTkTextbox", "Text"):
                return True
        return False
    
    def _copy(self):
        if self._is_focused_on_input_widget():
            return
        current_tab = self._get_current_tab()
        if current_tab == 'bt':
            if hasattr(self.behavior_tree, '_copy_selected'):
                self.behavior_tree._copy_selected()
    
    def _paste(self):
        if self._is_focused_on_input_widget():
            return
        current_tab = self._get_current_tab()
        if current_tab == 'bt':
            if hasattr(self.behavior_tree, '_paste_selected'):
                self.behavior_tree._paste_selected()
    
    def _cut(self):
        if self._is_focused_on_input_widget():
            return
        current_tab = self._get_current_tab()
        if current_tab == 'bt':
            if hasattr(self.behavior_tree, '_cut_selected'):
                self.behavior_tree._cut_selected()
    
    def _duplicate(self):
        if self._is_focused_on_input_widget():
            return
        current_tab = self._get_current_tab()
        if current_tab == 'bt':
            if hasattr(self.behavior_tree, '_duplicate_selected'):
                self.behavior_tree._duplicate_selected()
    
    def _save_state(self):
        current_geometry = self.geometry()
        self._settings.set("session.window_geometry", current_geometry)
        
        if hasattr(self, 'settings') and self.settings:
            settings_data = self.settings.get_settings()
            self._settings.set("alarm_sound_path", settings_data.get("alarm_sound_path", ""), auto_save=False)
            self._settings.set("alarm_volume", settings_data.get("alarm_volume", 70), auto_save=False)
            self._settings.set("default_project_path", settings_data.get("default_project_path", ""), auto_save=False)
            if "shortcuts" in settings_data:
                shortcuts = settings_data["shortcuts"]
                self._settings.set("shortcuts.start", shortcuts.get("start", "F10"), auto_save=False)
                self._settings.set("shortcuts.stop", shortcuts.get("stop", "F12"), auto_save=False)
                self._settings.set("shortcuts.record", shortcuts.get("record", "F11"), auto_save=False)
                self._settings.set("shortcuts.tab_shortcuts", shortcuts.get("tab_shortcuts", []), auto_save=False)
        
        if hasattr(self, 'behavior_tree') and self.behavior_tree:
            if hasattr(self.behavior_tree, 'tab_manager'):
                tabs_info = []
                for tab_id, instance in self.behavior_tree.tab_manager._trees.items():
                    if instance.file_path and os.path.exists(instance.file_path):
                        tabs_info.append({
                            "tab_id": tab_id,
                            "name": instance.name,
                            "file_path": instance.file_path,
                            "project_root": instance.project_root or "",
                        })
                self._settings.set_open_tabs(tabs_info)
                active_tab = self.behavior_tree.tab_manager.get_active_tab()
                if active_tab:
                    self._settings.set_active_tab_id(active_tab.tab_id)
    
    def _restart_with_methods(self, keyboard_method: str, mouse_method: str, as_admin: bool) -> bool:
        from bt_utils.app_restarter import restart_app

        if hasattr(self, 'behavior_tree') and self.behavior_tree:
            engine = getattr(self.behavior_tree, 'engine', None)
            if engine and getattr(engine, 'is_running', lambda: False)():
                messagebox.showwarning(
                    "无法重启",
                    "行为树正在运行中，请先停止运行再切换输入方式。"
                )
                return False

        self._settings.set("input.keyboard_method", keyboard_method)
        self._settings.set("input.mouse_method", mouse_method)
        self._save_state()
        self._settings.save_settings()

        success = restart_app(as_admin=as_admin)

        if success:
            self.destroy()
            sys.exit(0)
        else:
            self._settings.set("input.keyboard_method", "pyautogui")
            self._settings.set("input.mouse_method", "pyautogui")
            messagebox.showwarning(
                "重启失败",
                "无法以管理员身份重启应用，输入方式已恢复为 PyAutoGUI。"
            )
            return False

    def _init_message_bus_and_servers(self):
        """根据配置启动消息总线和服务端"""
        bus_config = self._settings.get("message_bus", {})
        if not bus_config.get("enabled", False):
            return

        from bt_bus.message_bus import MessageBus
        from bt_bus.thread_pool import SharedThreadPool

        SharedThreadPool.reset_instance()
        MessageBus.reset_instance()
        bus = MessageBus()
        bus.start()
        self._message_bus = bus

        # 启动 REST 服务端
        rest_config = self._settings.get("rest_server", {})
        if rest_config.get("enabled", False):
            import threading
            import uvicorn
            from bt_servers.rest_server import RESTServer
            from bt_servers.config import ServerConfig

            server_config = ServerConfig(
                host=rest_config.get("host", "127.0.0.1"),
                port=rest_config.get("port", 8080),
            )
            rest = RESTServer(message_bus=bus, config=server_config)
            self._rest_server = rest

            def _run_rest():
                try:
                    rest.start()
                    uvicorn.run(rest.app, host=server_config.host,
                                port=server_config.port, log_level="warning")
                except Exception as e:
                    LogManager.debug_print(f"[ERROR] REST 服务端启动失败: {e}")

            thread = threading.Thread(target=_run_rest, daemon=True)
            thread.start()

        # 启动 WebSocket 服务端
        ws_config = self._settings.get("websocket_server", {})
        if ws_config.get("enabled", False):
            import threading
            import asyncio
            from bt_servers.websocket_server import WebSocketServer

            ws = WebSocketServer(
                host=ws_config.get("host", "127.0.0.1"),
                port=ws_config.get("port", 8765),
            )
            ws.attach_bus(bus)
            self._ws_server = ws
            self._ws_loop = None

            def _run_ws():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    self._ws_loop = loop
                    loop.run_until_complete(ws.start())
                    loop.run_forever()
                except Exception as e:
                    LogManager.debug_print(f"[ERROR] WebSocket 服务端启动失败: {e}")

            thread = threading.Thread(target=_run_ws, daemon=True)
            thread.start()

    def _on_close(self):
        # 停止所有已启动的插件
        if hasattr(self, '_plugin_loader') and self._plugin_loader:
            try:
                self._plugin_loader.stop_all()
            except Exception as e:
                LogManager.debug_print(f"[WARN] 停止插件失败: {e}")

        # 清理消息总线和服务端
        if self._ws_server is not None:
            import asyncio
            try:
                if self._ws_loop is not None and self._ws_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._ws_server.stop(), self._ws_loop
                    ).result(timeout=5)
                else:
                    asyncio.run(self._ws_server.stop())
            except Exception as e:
                LogManager.debug_print(f"[WARN] 停止 WebSocket 服务端失败: {e}")
        if self._rest_server is not None:
            try:
                self._rest_server.stop()
            except Exception as e:
                LogManager.debug_print(f"[WARN] 停止 REST 服务端失败: {e}")
        # 清理 WebSocket 客户端节点连接池
        try:
            from bt_nodes.network.websocket_node import WebSocketNode
            WebSocketNode.close_all_connections()
        except Exception as e:
            LogManager.debug_print(f"[WARN] 清理 WebSocket 连接池失败: {e}")
        if self._message_bus is not None:
            try:
                self._message_bus.stop()
            except Exception as e:
                LogManager.debug_print(f"[WARN] 停止消息总线失败: {e}")

        self._save_state()
        
        if hasattr(self, 'behavior_tree') and self.behavior_tree:
            if hasattr(self.behavior_tree, 'property_panel'):
                self.behavior_tree.property_panel.cleanup_preview_images()
            
            if hasattr(self.behavior_tree, 'tab_manager'):
                for tab_id, instance in list(self.behavior_tree.tab_manager._trees.items()):
                    if instance.modified:
                        result = messagebox.askyesnocancel(
                            "未保存的改动",
                            f"项目 \"{instance.name}\" 有未保存的改动。\n\n是否保存？"
                        )
                        if result is None:
                            return
                        elif result:
                            self.behavior_tree._save_tab(tab_id)
            else:
                file_path = self.behavior_tree.file_path
                if file_path:
                    self._settings.set_last_file_path(file_path)
                
                if hasattr(self.behavior_tree, '_modified') and self.behavior_tree._modified:
                    result = messagebox.askyesnocancel(
                        "未保存的改动",
                        "当前项目有未保存的改动。\n\n是否保存？"
                    )
                    
                    if result is None:
                        return
                    elif result:
                        self.behavior_tree.save_tree()
            
            self.behavior_tree.destroy()
        
        self._settings.save_settings()
        self.destroy()


def create_app() -> BehaviorTreeApp:
    return BehaviorTreeApp()
