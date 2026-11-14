"""插件管理面板 — 提供 GUI 界面管理插件的加载、启动、停止

组件结构：
    PluginCard    — 单个插件的卡片组件（状态指示 + 信息 + 启停按钮）
    PluginPanel   — 插件管理面板（按钮栏 + 可滚动插件列表 + 状态栏）
"""
import os
import customtkinter as ctk
from tkinter import filedialog

from .theme import Theme
from bt_plugins.loader import PluginLoader
from bt_utils.resource_manager import ensure_user_plugin_dir


class PluginCard(ctk.CTkFrame):
    """单个插件的卡片组件"""

    def __init__(self, master, plugin_info, is_started, on_start, on_stop,
                 plugin_loader=None, **kwargs):
        super().__init__(master, **kwargs)
        self.plugin_info = plugin_info
        self._on_start = on_start
        self._on_stop = on_stop
        self._loader = plugin_loader
        self._dark_colors = Theme.get_dark_colors()

        # 错误状态
        self._error_message = ""
        self._error_tooltip = None

        # 配置编辑器
        self._config_editor = None

        self.configure(
            fg_color=self._dark_colors['bg_tertiary'],
            corner_radius=Theme.DIMENSIONS.get('button_corner_radius', 8)
        )

        # 状态指示器
        status_color = self._dark_colors.get('success', '#22C55E') if is_started else self._dark_colors.get('text_muted', '#9CA3AF')
        self.status_dot = ctk.CTkLabel(
            self, text="●", text_color=status_color,
            font=Theme.get_font('base')
        )
        self.status_dot.pack(side="left", padx=(8, 4), pady=8)

        # 绑定悬停事件用于错误提示
        self.status_dot.bind("<Enter>", self._show_error_tooltip)
        self.status_dot.bind("<Leave>", self._hide_error_tooltip)

        # 信息区域
        info_frame = ctk.CTkFrame(self, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, pady=4)

        self.name_label = ctk.CTkLabel(
            info_frame,
            text=f"{plugin_info.display_name}  v{plugin_info.version}",
            font=Theme.get_font('sm'),
            text_color=self._dark_colors['text_primary'],
            anchor="w"
        )
        self.name_label.pack(fill="x")

        self.desc_label = ctk.CTkLabel(
            info_frame,
            text=f"{plugin_info.description}  作者: {plugin_info.author}",
            font=Theme.get_font('xs'),
            text_color=self._dark_colors['text_muted'],
            anchor="w"
        )
        self.desc_label.pack(fill="x")

        # 操作按钮
        self.start_btn = ctk.CTkButton(
            self, text="启动", width=60, height=28,
            font=Theme.get_font('xs'),
            command=self._handle_start
        )
        self.start_btn.pack(side="right", padx=(4, 8), pady=8)

        self.stop_btn = ctk.CTkButton(
            self, text="停止", width=60, height=28,
            font=Theme.get_font('xs'),
            fg_color=self._dark_colors.get('error', '#EF4444'),
            hover_color='#DC2626',
            command=self._handle_stop
        )
        self.stop_btn.pack(side="right", padx=(0, 4), pady=8)

        # 配置展开/收起按钮
        self._config_toggle = ctk.CTkButton(
            self, text="⚙", width=28, height=28,
            font=Theme.get_font('xs'),
            fg_color="transparent",
            hover_color=self._dark_colors.get('border', '#334155'),
            command=self._toggle_config
        )
        self._config_toggle.pack(side="right", padx=(0, 4), pady=8)

        # 配置编辑器容器（默认隐藏）
        self._config_frame = ctk.CTkFrame(self, fg_color="transparent")

        self._update_button_state(is_started)

    def _update_button_state(self, is_started):
        """根据启动状态更新按钮可用性"""
        if is_started:
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
        else:
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")

    def _handle_start(self):
        if self._on_start:
            self._on_start(self.plugin_info.name)

    def _handle_stop(self):
        if self._on_stop:
            self._on_stop(self.plugin_info.name)

    def update_status(self, is_started):
        """外部调用：更新状态显示"""
        if not self._error_message:  # 错误状态下不覆盖红色
            status_color = self._dark_colors.get('success', '#22C55E') if is_started else self._dark_colors.get('text_muted', '#9CA3AF')
            self.status_dot.configure(text_color=status_color)
        self._update_button_state(is_started)

    # ── 配置编辑器 ──

    def _toggle_config(self):
        """切换配置编辑器显示"""
        if self._config_editor is None:
            schema = self._get_plugin_schema()
            if not schema:
                return
            self._config_editor = PluginConfigEditor(
                self._config_frame,
                schema=schema,
                plugin_name=self.plugin_info.name,
                on_change=self._on_config_changed
            )
            self._config_editor.pack(fill="x", padx=12, pady=4)
            self._config_frame.pack(fill="x")
            self._config_toggle.configure(text="▲")
        else:
            self._config_frame.pack_forget()
            if self._config_editor is not None:
                self._config_editor.destroy()
                self._config_editor = None
            self._config_toggle.configure(text="⚙")

    def _get_plugin_schema(self):
        """获取插件的配置 schema"""
        if self._loader is not None and hasattr(self._loader, 'get_plugin_config_schema'):
            return self._loader.get_plugin_config_schema(self.plugin_info.name) or {}
        return {}

    def _on_config_changed(self, plugin_name, key, values):
        """配置变更回调 — 保存到 settings"""
        try:
            from config.settings_manager import get_settings_manager
            settings = get_settings_manager()
            for k, v in values.items():
                settings.set(f"plugins.{plugin_name}.{k}", v)
        except Exception as e:
            print(f"[PluginCard] 保存插件配置失败: {e}")

    # ── 错误状态 ──

    def set_error(self, message: str):
        """设置错误状态"""
        self._error_message = message
        self.status_dot.configure(text_color=self._dark_colors.get('error', '#EF4444'))
        self.configure(border_width=1, border_color=self._dark_colors.get('error', '#EF4444'))

    def clear_error(self):
        """清除错误状态"""
        self._error_message = ""
        self.configure(border_width=0)

    def _show_error_tooltip(self, event):
        """显示错误提示"""
        if not self._error_message:
            return
        if self._error_tooltip is not None:
            return
        try:
            x = self.winfo_rootx() + 12
            y = self.winfo_rooty() + 20
            self._error_tooltip = ctk.CTkToplevel(self)
            self._error_tooltip.wm_overrideredirect(True)
            self._error_tooltip.wm_geometry(f"+{x}+{y}")
            ctk.CTkLabel(
                self._error_tooltip,
                text=self._error_message,
                fg_color=self._dark_colors.get('error', '#EF4444'),
                text_color="white",
                corner_radius=4,
                padx=8,
                pady=4,
                wraplength=300,
                font=Theme.get_font('xs')
            ).pack()
        except Exception:
            self._error_tooltip = None

    def _hide_error_tooltip(self, event):
        """隐藏错误提示"""
        if self._error_tooltip is not None:
            try:
                self._error_tooltip.destroy()
            except Exception:
                pass
            self._error_tooltip = None


class PluginPanel(ctk.CTkFrame):
    """插件管理面板

    提供：
    - 顶部按钮栏：加载插件 / 刷新 / 全部启动 / 全部停止
    - 中间可滚动插件列表，每个插件一张 PluginCard
    - 底部状态标签（插件总数与已启动数）

    可选参数 on_plugins_changed: 插件启停后触发的回调（用于刷新节点面板等）
    """

    def __init__(self, master, plugin_loader: PluginLoader, list_height: int = 240,
                 on_plugins_changed=None, **kwargs):
        super().__init__(master, **kwargs)
        self._loader = plugin_loader
        self._dark_colors = Theme.get_dark_colors()
        self._plugin_cards = {}  # name → PluginCard
        self._list_height = list_height
        self._on_plugins_changed = on_plugins_changed  # 插件启停回调

        self.configure(
            fg_color=self._dark_colors['bg_secondary'],
            corner_radius=8
        )

        self._create_ui()
        self._refresh_list()

    def _create_ui(self):
        """构建面板界面"""
        # 顶部标题栏
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=12, pady=(8, 4))

        title = ctk.CTkLabel(
            header_frame, text="插件管理",
            font=Theme.get_font('base'),
            text_color=self._dark_colors['text_primary']
        )
        title.pack(side="left")

        # 插件目录提示行：告诉用户插件放在哪里，并提供一键打开
        path_frame = ctk.CTkFrame(self, fg_color="transparent")
        path_frame.pack(fill="x", padx=12, pady=(0, 2))
        self._plugin_dir = ensure_user_plugin_dir()
        path_label = ctk.CTkLabel(
            path_frame,
            text=f"插件目录：{self._plugin_dir}",
            font=Theme.get_font('xs'),
            text_color=self._dark_colors['text_muted'],
            anchor="w"
        )
        path_label.pack(side="left", fill="x", expand=True)
        open_dir_btn = ctk.CTkButton(
            path_frame, text="打开目录", width=70, height=22,
            font=Theme.get_font('xs'),
            command=self._on_open_plugin_dir
        )
        open_dir_btn.pack(side="right", padx=(4, 0))

        # 按钮栏
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=4)

        self.load_btn = ctk.CTkButton(
            btn_frame, text="加载插件", width=80, height=28,
            font=Theme.get_font('xs'),
            command=self._on_load
        )
        self.load_btn.pack(side="left", padx=(0, 4))

        self.refresh_btn = ctk.CTkButton(
            btn_frame, text="刷新", width=60, height=28,
            font=Theme.get_font('xs'),
            command=self._on_refresh
        )
        self.refresh_btn.pack(side="left", padx=4)

        self.start_all_btn = ctk.CTkButton(
            btn_frame, text="全部启动", width=80, height=28,
            font=Theme.get_font('xs'),
            command=self._on_start_all
        )
        self.start_all_btn.pack(side="right", padx=(4, 0))

        self.stop_all_btn = ctk.CTkButton(
            btn_frame, text="全部停止", width=80, height=28,
            font=Theme.get_font('xs'),
            fg_color=self._dark_colors.get('error', '#EF4444'),
            hover_color='#DC2626',
            command=self._on_stop_all
        )
        self.stop_all_btn.pack(side="right", padx=4)

        # 插件列表区域（可滚动，固定高度避免嵌套滚动失控）
        self.scroll_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            label_text="",
            height=self._list_height
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=12, pady=(4, 8))

        # 底部状态标签
        self.status_label = ctk.CTkLabel(
            self, text="",
            font=Theme.get_font('xs'),
            text_color=self._dark_colors['text_muted']
        )
        self.status_label.pack(fill="x", padx=12, pady=(0, 8))

    def _refresh_list(self):
        """刷新插件列表：销毁旧卡片并按当前 loader 状态重建"""
        # 清除现有卡片
        for card in self._plugin_cards.values():
            card.destroy()
        self._plugin_cards.clear()

        # 重新创建
        infos = self._loader.list_plugins()
        for info in infos:
            is_started = self._loader.is_started(info.name)
            card = PluginCard(
                self.scroll_frame,
                info,
                is_started,
                on_start=self._start_plugin,
                on_stop=self._stop_plugin,
                plugin_loader=self._loader
            )
            card.pack(fill="x", padx=4, pady=2)
            self._plugin_cards[info.name] = card

        self._update_status_label()

    def _on_load(self):
        """通过目录选择器加载单个插件"""
        dir_path = filedialog.askdirectory(title="选择插件目录")
        if dir_path:
            if self._loader.load_plugin(dir_path):
                self._refresh_list()
                self.status_label.configure(text="插件加载成功")
            else:
                self.status_label.configure(text="插件加载失败")

    def _on_refresh(self):
        """刷新列表"""
        self._refresh_list()

    def _on_open_plugin_dir(self):
        """在资源管理器中打开插件目录"""
        try:
            os.startfile(self._plugin_dir)
        except OSError as e:
            self.status_label.configure(text=f"打开插件目录失败: {e}")

    def _on_start_all(self):
        """启动所有已加载插件，并持久化其自动启动状态"""
        self._loader.start_all()
        self._persist_all_autostart(started_only=True)
        self._refresh_list()
        self._notify_plugins_changed()

    def _on_stop_all(self):
        """停止所有已启动插件，并清除其自动启动状态"""
        self._loader.stop_all()
        self._persist_all_autostart(started_only=False)
        self._refresh_list()
        self._notify_plugins_changed()

    def _persist_all_autostart(self, started_only):
        """批量持久化插件的自动启动状态

        started_only=True 时按实际启动结果记录（避免把启动失败的插件也标记为自动启动），
        否则一律清除自动启动标记。
        """
        try:
            for info in self._loader.list_plugins():
                enabled = self._loader.is_started(info.name) if started_only else False
                self._loader.set_autostart(info.name, enabled)
        except Exception as e:
            print(f"[PluginPanel] 保存插件自动启动状态失败: {e}")

    def _start_plugin(self, name):
        """启动单个插件并更新对应卡片"""
        try:
            success = self._loader.start_plugin(name)
            if success:
                # 记住该插件已启用，下次启动应用时自动启动
                self._loader.set_autostart(name, True)
                card = self._find_card(name)
                if card:
                    card.clear_error()
                    card.update_status(True)
                self._update_status_label()
                self._notify_plugins_changed()
            else:
                card = self._find_card(name)
                if card:
                    card.set_error("插件启动失败，请查看日志")
        except Exception as e:
            card = self._find_card(name)
            if card:
                card.set_error(str(e))

    def _find_card(self, name):
        """查找指定插件名对应的 PluginCard"""
        return self._plugin_cards.get(name)

    def _stop_plugin(self, name):
        """停止单个插件并更新对应卡片"""
        self._loader.stop_plugin(name)
        # 取消自动启动标记，下次启动应用时不再自动启用
        self._loader.set_autostart(name, False)
        card = self._find_card(name)
        if card:
            card.clear_error()
            card.update_status(False)
        self._update_status_label()
        self._notify_plugins_changed()

    def _notify_plugins_changed(self):
        """通知外部（如节点面板）刷新插件节点"""
        if self._on_plugins_changed:
            try:
                self._on_plugins_changed()
            except Exception as e:
                # 回调失败不影响插件管理本身
                print(f"[PluginPanel] 插件变更回调失败: {e}")

    def _update_status_label(self):
        """根据当前 loader 状态更新底部状态文本"""
        infos = self._loader.list_plugins()
        started = sum(1 for info in infos if self._loader.is_started(info.name))
        self.status_label.configure(text=f"共 {len(infos)} 个插件，{started} 个已启动")


class PluginConfigEditor(ctk.CTkFrame):
    """插件配置编辑器 — 根据 get_config_schema() 动态渲染配置项

    支持 bool / select / number / text 四种类型，
    变更时通过 on_change 回调通知外部保存。
    """

    def __init__(self, master, schema: dict, plugin_name: str,
                 on_change=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._schema = schema or {}
        self._plugin_name = plugin_name
        self._on_change = on_change
        self._widgets = {}   # key → widget
        self._vars = {}      # key → variable

        self._dark_colors = Theme.get_dark_colors()
        self._create_ui()

    def _create_ui(self):
        """根据 schema 渲染配置项"""
        if not self._schema:
            ctk.CTkLabel(
                self,
                text="（此插件无配置项）",
                font=Theme.get_font('xs'),
                text_color=self._dark_colors['text_muted']
            ).pack(pady=8)
            return

        for key, spec in self._schema.items():
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(
                row,
                text=spec.get("label", key),
                font=Theme.get_font('sm'),
                text_color=self._dark_colors['text_primary'],
                width=120,
                anchor="w"
            ).pack(side="left", padx=(0, 8))

            widget = self._create_widget_for_type(row, key, spec)
            if widget:
                widget.pack(side="left", fill="x", expand=True)

    def _create_widget_for_type(self, parent, key, spec):
        """根据 type 创建对应的 widget"""
        spec_type = spec.get("type", "text")
        default = spec.get("default")

        if spec_type == "bool":
            var = ctk.StringVar(value="1" if default else "0")
            self._vars[key] = var
            widget = ctk.CTkSwitch(
                parent,
                variable=var,
                onvalue="1", offvalue="0",
                command=lambda: self._on_value_changed(key)
            )
        elif spec_type == "select":
            options = spec.get("options", [])
            var = ctk.StringVar(value=default if default in options else (options[0] if options else ""))
            self._vars[key] = var
            widget = ctk.CTkOptionMenu(
                parent,
                variable=var,
                values=options,
                command=lambda v: self._on_value_changed(key, v)
            )
        elif spec_type == "number":
            var = ctk.StringVar(value=str(default if default is not None else 0))
            self._vars[key] = var
            widget = ctk.CTkEntry(
                parent,
                textvariable=var,
                width=80
            )
            widget.bind("<FocusOut>", lambda e: self._on_value_changed(key))
        else:  # text
            var = ctk.StringVar(value=str(default if default is not None else ""))
            self._vars[key] = var
            widget = ctk.CTkEntry(
                parent,
                textvariable=var
            )
            widget.bind("<FocusOut>", lambda e: self._on_value_changed(key))

        self._widgets[key] = widget
        return widget

    def _on_value_changed(self, key, value=None):
        """配置项变更回调"""
        if self._on_change:
            self._on_change(self._plugin_name, key, self.get_values())

    def get_values(self) -> dict:
        """获取所有配置项的当前值"""
        result = {}
        for key, var in self._vars.items():
            raw = var.get()
            spec = self._schema.get(key, {})
            spec_type = spec.get("type", "text")
            if spec_type == "bool":
                result[key] = raw == "1" or raw is True or raw == "True"
            elif spec_type == "number":
                try:
                    result[key] = int(raw)
                except (ValueError, TypeError):
                    result[key] = 0
            else:
                result[key] = raw
        return result

    def set_values(self, values: dict):
        """设置配置项的值"""
        for key, value in values.items():
            if key in self._vars:
                spec = self._schema.get(key, {})
                spec_type = spec.get("type", "text")
                if spec_type == "bool":
                    self._vars[key].set("1" if value else "0")
                else:
                    self._vars[key].set(str(value))


class PluginStatusBarIndicator(ctk.CTkFrame):
    """状态栏插件状态指示器 — 显示已启动插件数量，点击打开插件管理面板"""

    def __init__(self, master, plugin_loader, on_click=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._loader = plugin_loader
        self._on_click = on_click

        self._dark_colors = Theme.get_dark_colors()

        self._status_label = ctk.CTkLabel(
            self,
            text=self.get_status_text(),
            font=Theme.get_font('xs'),
            text_color=self._dark_colors['text_muted'],
            cursor="hand2" if on_click else "arrow"
        )
        self._status_label.pack(side="left", padx=4, pady=2)

        if on_click:
            self._status_label.bind("<Button-1>", lambda e: on_click())
            self.bind("<Button-1>", lambda e: on_click())

    def get_status_text(self) -> str:
        """获取状态文本"""
        try:
            infos = self._loader.list_plugins() if self._loader else []
            total = len(infos)
            if total == 0:
                return "插件: 0/0 已启动"
            started = sum(1 for info in infos if self._loader.is_started(info.name))
            return f"插件: {started}/{total} 已启动"
        except Exception:
            return "插件: -"

    def refresh(self):
        """刷新状态显示"""
        self._status_label.configure(text=self.get_status_text())
