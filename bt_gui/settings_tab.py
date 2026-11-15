import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os

from .theme import Theme
from .widgets import CardFrame, AnimatedButton, create_section_title, create_divider
from bt_utils.resource_manager import ResourceManager

# 全局 tick 间隔（毫秒）预设与边界，与应用其它层保持一致
TICK_PRESETS_MS = (33, 100, 200, 500, 1000)
TICK_DEFAULT_MS = 33
TICK_MIN_MS = 33


class SettingsTab(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        
        self._dark_colors = Theme.get_dark_colors()
        self.configure(fg_color=self._dark_colors['bg_primary'], corner_radius=0)
        
        self._init_variables()
        self._create_ui()
    
    def _init_variables(self):
        default_alarm_sound = ResourceManager().get_alarm_sound_path()
        if not os.path.exists(default_alarm_sound):
            default_alarm_sound = ""
        
        self.alarm_sound_path = tk.StringVar(value=default_alarm_sound)
        self.alarm_volume = tk.IntVar(value=70)
        self.alarm_volume_str = tk.StringVar(value="70")
        
        default_project_path = self._get_default_project_path()
        self.default_project_path = tk.StringVar(value=default_project_path)
        
        self.start_shortcut_var = tk.StringVar(value="F10")
        self.stop_shortcut_var = tk.StringVar(value="F12")
        self.record_hotkey_var = tk.StringVar(value="F11")

        from config.settings_manager import SettingsManager
        settings = SettingsManager()
        self._current_keyboard_method = settings.get("input.keyboard_method", "pyautogui")
        self._current_mouse_method = settings.get("input.mouse_method", "pyautogui")

        # 全局运行频率（tick 间隔，毫秒）
        self.tick_interval_ms = tk.IntVar(value=TICK_DEFAULT_MS)
    
    def _get_default_project_path(self) -> str:
        """获取默认项目保存路径
        
        Returns:
            默认项目保存路径
        """
        from config.settings_manager import SettingsManager
        settings_manager = SettingsManager()
        saved_path = settings_manager.get("default_project_path", "")
        
        if saved_path and os.path.exists(saved_path):
            return saved_path
        
        return SettingsManager.get_default_workspace_path()
    
    def _create_ui(self):
        self._scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll_frame.pack(fill="both", expand=True, padx=Theme.DIMENSIONS['spacing_md'], pady=Theme.DIMENSIONS['spacing_md'])

        self._create_project_section(self._scroll_frame)
        self._create_run_section(self._scroll_frame)
        self._create_alarm_section(self._scroll_frame)
        self._create_shortcut_section(self._scroll_frame)
        self._create_input_method_section(self._scroll_frame)
        self._create_ai_section(self._scroll_frame)
    
    def _create_project_section(self, parent):
        project_frame = CardFrame(parent)
        project_frame.pack(fill="x", pady=(0, Theme.DIMENSIONS['spacing_md']))
        
        project_header = ctk.CTkFrame(project_frame, fg_color="transparent")
        project_header.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_md'], Theme.DIMENSIONS['spacing_sm']))
        create_section_title(project_header, "项目设置", level=1).pack(side="left")
        
        create_divider(project_frame)
        
        project_row = ctk.CTkFrame(project_frame, fg_color="transparent")
        project_row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_md']))
        
        ctk.CTkLabel(project_row, text="默认保存位置:", font=Theme.get_font("sm"), text_color=self._dark_colors['text_secondary']).pack(side="left")
        
        self.project_path_entry = ctk.CTkEntry(
            project_row, 
            textvariable=self.default_project_path, 
            height=28, 
            state="disabled",
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary']
        )
        self.project_path_entry.pack(side="left", fill="x", expand=True, padx=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_sm']))
        
        self.browse_project_btn = AnimatedButton(
            project_row, 
            text="浏览", 
            font=Theme.get_font("xs"), 
            width=50, 
            height=28,
            corner_radius=Theme.DIMENSIONS['button_corner_radius'], 
            fg_color=Theme.COLORS['primary'],
            hover_color=Theme.COLORS['primary_hover'],
            command=self._browse_project_path
        )
        self.browse_project_btn.pack(side="left")
    
    def _create_run_section(self, parent):
        """创建运行频率设置区域（控制整体 tick 频率）"""
        run_frame = CardFrame(parent)
        run_frame.pack(fill="x", pady=(0, Theme.DIMENSIONS['spacing_md']))

        run_header = ctk.CTkFrame(run_frame, fg_color="transparent")
        run_header.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_md'], Theme.DIMENSIONS['spacing_sm']))
        create_section_title(run_header, "运行设置", level=1).pack(side="left")

        create_divider(run_frame)

        run_desc = ctk.CTkFrame(run_frame, fg_color="transparent")
        run_desc.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'])
        ctk.CTkLabel(
            run_desc,
            text=f"tick 间隔越小，执行频率越高",
            font=Theme.get_font("xs"),
            text_color=self._dark_colors['text_muted']
        ).pack(side="left")

        run_row = ctk.CTkFrame(run_frame, fg_color="transparent")
        run_row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_md']))

        ctk.CTkLabel(run_row, text="tick 间隔(ms):", font=Theme.get_font("sm"), text_color=self._dark_colors['text_secondary']).pack(side="left")

        # 预设下拉：仅允许从预设值中选择，选择后立即保存应用
        preset_values = [str(v) for v in TICK_PRESETS_MS]
        from config.settings_manager import SettingsManager
        _current_tick = int(SettingsManager.get_instance().get(
            "behavior_tree.tick_interval", TICK_DEFAULT_MS))
        if _current_tick not in TICK_PRESETS_MS:
            _current_tick = TICK_DEFAULT_MS
        self.tick_preset_var = tk.StringVar(value=str(_current_tick))

        def _on_preset(*args):
            val = int(self.tick_preset_var.get())
            self.tick_interval_ms.set(val)
            SettingsManager.get_instance().set("behavior_tree.tick_interval", val, auto_save=True)
            self._tick_status_label.configure(
                text=f"已保存 ({val} ms)",
                text_color=self._dark_colors.get('success', '#22C55E')
            )

        self.tick_preset_var.trace_add("write", _on_preset)

        preset_menu = ctk.CTkOptionMenu(
            run_row,
            values=preset_values,
            variable=self.tick_preset_var,
            width=110,
            height=28,
            font=Theme.get_font("sm"),
            fg_color=self._dark_colors['bg_tertiary'],
            button_color=self._dark_colors['bg_tertiary'],
            button_hover_color=self._dark_colors.get('node_selected', '#3B82F6'),
            text_color=self._dark_colors['text_primary'],
            dropdown_fg_color=self._dark_colors['bg_tertiary'],
            dropdown_hover_color=self._dark_colors.get('node_selected', '#3B82F6'),
            dropdown_text_color=self._dark_colors['text_primary']
        )
        preset_menu.pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_sm']))

        self._tick_status_label = ctk.CTkLabel(
            run_row, text="", font=Theme.get_font("xs"),
            text_color=self._dark_colors['text_muted']
        )
        self._tick_status_label.pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], 0))
    
    def _create_alarm_section(self, parent):
        alarm_frame = CardFrame(parent)
        alarm_frame.pack(fill="x", pady=(0, Theme.DIMENSIONS['spacing_md']))
        
        alarm_header = ctk.CTkFrame(alarm_frame, fg_color="transparent")
        alarm_header.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_md'], Theme.DIMENSIONS['spacing_sm']))
        create_section_title(alarm_header, "报警设置", level=1).pack(side="left")
        
        create_divider(alarm_frame)
        
        alarm_row1 = ctk.CTkFrame(alarm_frame, fg_color="transparent")
        alarm_row1.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=Theme.DIMENSIONS['spacing_sm'])
        
        ctk.CTkLabel(alarm_row1, text="声音:", font=Theme.get_font("sm"), text_color=self._dark_colors['text_secondary']).pack(side="left")
        
        alarm_sound_entry = ctk.CTkEntry(
            alarm_row1, 
            textvariable=self.alarm_sound_path, 
            height=28, 
            state="disabled",
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary']
        )
        alarm_sound_entry.pack(side="left", fill="x", expand=True, padx=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_sm']))
        
        alarm_sound_btn = AnimatedButton(
            alarm_row1, 
            text="浏览", 
            font=Theme.get_font("xs"), 
            width=50, 
            height=28,
            corner_radius=Theme.DIMENSIONS['button_corner_radius'], 
            fg_color=Theme.COLORS['primary'],
            hover_color=Theme.COLORS['primary_hover'],
            command=self._browse_alarm_sound
        )
        alarm_sound_btn.pack(side="left")
        
        alarm_row2 = ctk.CTkFrame(alarm_frame, fg_color="transparent")
        alarm_row2.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_md']))
        
        ctk.CTkLabel(alarm_row2, text="音量:", font=Theme.get_font("sm"), text_color=self._dark_colors['text_secondary']).pack(side="left")
        
        def update_volume_display(*args):
            self.alarm_volume_str.set(str(self.alarm_volume.get()))
        
        self.alarm_volume.trace_add("write", update_volume_display)
        
        volume_slider = ctk.CTkSlider(
            alarm_row2, 
            from_=0, 
            to=100, 
            variable=self.alarm_volume, 
            width=200,
            progress_color=Theme.COLORS['primary'],
            button_color=Theme.COLORS['text_primary']
        )
        volume_slider.pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_sm']))
        
        volume_label = ctk.CTkLabel(
            alarm_row2, 
            textvariable=self.alarm_volume_str, 
            font=Theme.get_font("sm"), 
            width=40,
            text_color=self._dark_colors['text_primary']
        )
        volume_label.pack(side="left")
    
    def _create_shortcut_section(self, parent):
        shortcut_frame = CardFrame(parent)
        shortcut_frame.pack(fill="x", pady=(0, Theme.DIMENSIONS['spacing_md']))
        
        shortcut_header = ctk.CTkFrame(shortcut_frame, fg_color="transparent")
        shortcut_header.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_md'], Theme.DIMENSIONS['spacing_sm']))
        create_section_title(shortcut_header, "快捷键设置", level=1).pack(side="left")
        
        create_divider(shortcut_frame)
        
        shortcuts = [
            ("开始运行:", "F10", self.start_shortcut_var),
            ("停止运行:", "F12", self.stop_shortcut_var),
            ("录制按钮:", "F11", self.record_hotkey_var)
        ]
        
        for label, default, var in shortcuts:
            row = ctk.CTkFrame(shortcut_frame, fg_color="transparent")
            row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=Theme.DIMENSIONS['spacing_sm'])
            
            ctk.CTkLabel(row, text=label, font=Theme.get_font("sm"), text_color=self._dark_colors['text_secondary']).pack(side="left")
            
            entry = ctk.CTkEntry(
                row, 
                textvariable=var, 
                width=80, 
                height=24, 
                state="disabled",
                fg_color=self._dark_colors['bg_tertiary'],
                text_color=self._dark_colors['text_primary']
            )
            entry.pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_xs']))
            
            btn = AnimatedButton(
                row, 
                text="修改", 
                font=Theme.get_font("xs"), 
                width=40, 
                height=24, 
                corner_radius=Theme.DIMENSIONS['button_corner_radius'],
                fg_color=Theme.COLORS['primary'], 
                hover_color=Theme.COLORS['primary_hover']
            )
            btn.configure(command=lambda e=entry, b=btn: self._start_key_listening(e, b))
            btn.pack(side="left")
        
        ctk.CTkFrame(shortcut_frame, height=6, fg_color="transparent").pack()
        
        # ── 单树快捷键设置 ──
        create_divider(shortcut_frame)
        
        tab_shortcut_header = ctk.CTkFrame(shortcut_frame, fg_color="transparent")
        tab_shortcut_header.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_sm'], 0))
        create_section_title(tab_shortcut_header, "单树快捷键", level=2).pack(side="left")
        
        tab_shortcut_desc = ctk.CTkFrame(shortcut_frame, fg_color="transparent")
        tab_shortcut_desc.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'])
        ctk.CTkLabel(
            tab_shortcut_desc, text="为每个行为树绑定独立的启动/停止快捷键（同一快捷键切换运行状态）",
            font=Theme.get_font("xs"), text_color=self._dark_colors['text_muted']
        ).pack(side="left")
        
        # 单树快捷键列表容器
        self._tab_shortcut_rows = []
        self._tab_shortcut_container = ctk.CTkFrame(shortcut_frame, fg_color="transparent")
        self._tab_shortcut_container.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'])
        
        # 加载已有的单树快捷键配置
        from config.settings_manager import SettingsManager
        settings_manager = SettingsManager.get_instance()
        tab_shortcuts = settings_manager.get("shortcuts.tab_shortcuts", [
            {"hotkey": "F1"}, {"hotkey": "F2"}, {"hotkey": "F3"}
        ])
        for ts in tab_shortcuts:
            self._add_tab_shortcut_row(ts.get("hotkey", ""), ts.get("tab_name", ""))
        
        # 添加按钮
        add_btn_row = ctk.CTkFrame(shortcut_frame, fg_color="transparent")
        add_btn_row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_xs'], Theme.DIMENSIONS['spacing_md']))
        
        AnimatedButton(
            add_btn_row, text="+ 添加快捷键", font=Theme.get_font("xs"),
            width=100, height=26,
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=Theme.COLORS['primary'], hover_color=Theme.COLORS['primary_hover'],
            command=self._add_tab_shortcut_row
        ).pack(side="left")
        
        ctk.CTkFrame(shortcut_frame, height=6, fg_color="transparent").pack()
    
    def _create_input_method_section(self, parent):
        from bt_utils.input_manager import InputControllerManager
        from bt_utils.base_input import InputLevel
        from bt_utils.app_restarter import is_admin

        manager = InputControllerManager()
        available_methods = manager.get_available_methods()

        input_frame = CardFrame(parent)
        input_frame.pack(fill="x", pady=(0, Theme.DIMENSIONS['spacing_md']))

        input_header = ctk.CTkFrame(input_frame, fg_color="transparent")
        input_header.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(Theme.DIMENSIONS['spacing_md'], Theme.DIMENSIONS['spacing_sm']))
        create_section_title(input_header, "输入方式", level=1).pack(side="left")

        create_divider(input_frame)

        # 构建选项和映射
        self._method_key_to_label = {}
        self._method_label_to_key = {}
        method_options = []

        for method_key, method_info in available_methods.items():
            label = method_info['name']
            if not method_info["available"]:
                label += "（不可用）"
            self._method_key_to_label[method_key] = label
            self._method_label_to_key[label] = method_key
            method_options.append(label)

        # ── 键盘引擎 ComboBox ──
        kb_row = ctk.CTkFrame(input_frame, fg_color="transparent")
        kb_row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=Theme.DIMENSIONS['spacing_sm'])

        ctk.CTkLabel(kb_row, text="键盘引擎:", font=Theme.get_font("sm"), text_color=self._dark_colors['text_secondary']).pack(side="left")

        current_kb_label = self._method_key_to_label.get(self._current_keyboard_method, method_options[0])
        self._kb_combo_var = tk.StringVar(value=current_kb_label)

        self.keyboard_method_combo = ctk.CTkComboBox(
            kb_row,
            values=method_options,
            variable=self._kb_combo_var,
            command=self._on_keyboard_method_changed,
            font=Theme.get_font("sm"),
            width=300,
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
            button_color=Theme.COLORS['primary'],
            button_hover_color=Theme.COLORS['primary_hover'],
        )
        self.keyboard_method_combo.pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], 0))

        # ── 鼠标引擎 ComboBox ──
        ms_row = ctk.CTkFrame(input_frame, fg_color="transparent")
        ms_row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=Theme.DIMENSIONS['spacing_sm'])

        ctk.CTkLabel(ms_row, text="鼠标引擎:", font=Theme.get_font("sm"), text_color=self._dark_colors['text_secondary']).pack(side="left")

        current_ms_label = self._method_key_to_label.get(self._current_mouse_method, method_options[0])
        self._ms_combo_var = tk.StringVar(value=current_ms_label)

        self.mouse_method_combo = ctk.CTkComboBox(
            ms_row,
            values=method_options,
            variable=self._ms_combo_var,
            command=self._on_mouse_method_changed,
            font=Theme.get_font("sm"),
            width=300,
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
            button_color=Theme.COLORS['primary'],
            button_hover_color=Theme.COLORS['primary_hover'],
        )
        self.mouse_method_combo.pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], 0))

        # ── IB 子驱动选项（键盘或鼠标任一选择 IB 时显示） ──
        self._ib_sub_frame = ctk.CTkFrame(input_frame, fg_color="transparent")

        ib_sub_row = ctk.CTkFrame(self._ib_sub_frame, fg_color="transparent")
        ib_sub_row.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'])

        ctk.CTkLabel(ib_sub_row, text="IB驱动模式:", font=Theme.get_font("sm"),
                     text_color=self._dark_colors['text_secondary']).pack(side="left")

        ib_mode_labels = {
            "any_driver": "自动检测",
            "logitech": "Logitech LGS",
            "logitech_ghub_new": "Logitech G HUB (新版)",
            "razer": "Razer Synapse",
            "mou_class": "MouClassInputInjection",
            "send_input": "SendInput",
        }

        # 检测本机已安装的驱动
        try:
            from bt_utils.ib_input import detect_ib_driver_status
            driver_status = detect_ib_driver_status()
        except Exception:
            driver_status = {}

        ib_mode_options = []
        self._ib_mode_label_to_key = {}
        for mode_key, mode_label in ib_mode_labels.items():
            status = driver_status.get(mode_key, {})
            installed = status.get("installed", None)
            if installed is True:
                display = f"{mode_label}（已安装）"
            elif installed is False:
                display = f"{mode_label}（未安装）"
            else:
                display = mode_label
            ib_mode_options.append(display)
            self._ib_mode_label_to_key[display] = mode_key

        from config.settings_manager import SettingsManager
        current_ib_mode = SettingsManager.get_instance().get("input.ib_send_mode", "any_driver")
        current_ib_label = ib_mode_labels.get(current_ib_mode, "自动检测")
        for opt in ib_mode_options:
            if opt.startswith(current_ib_label):
                current_ib_label = opt
                break

        self._ib_mode_var = tk.StringVar(value=current_ib_label)

        self._ib_mode_combo = ctk.CTkComboBox(
            ib_sub_row,
            values=ib_mode_options,
            variable=self._ib_mode_var,
            command=self._on_ib_mode_changed,
            font=Theme.get_font("sm"),
            width=260,
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
            button_color=Theme.COLORS['primary'],
            button_hover_color=Theme.COLORS['primary_hover'],
        )
        self._ib_mode_combo.pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], 0))

        # IB PID 输入（仅 MCII 模式需要）
        self._ib_pid_frame = ctk.CTkFrame(input_frame, fg_color="transparent")

        ib_pid_row = ctk.CTkFrame(self._ib_pid_frame, fg_color="transparent")
        ib_pid_row.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'])

        ctk.CTkLabel(ib_pid_row, text="目标进程PID:", font=Theme.get_font("sm"),
                     text_color=self._dark_colors['text_secondary']).pack(side="left")

        current_pid = SettingsManager.get_instance().get("input.ib_target_pid", 0)
        self._ib_pid_var = tk.StringVar(value=str(current_pid))

        self._ib_pid_entry = ctk.CTkEntry(
            ib_pid_row,
            textvariable=self._ib_pid_var,
            width=80,
            height=24,
            font=Theme.get_font("sm"),
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
        )
        self._ib_pid_entry.pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], 0))

        ctk.CTkLabel(ib_pid_row, text="（仅MCII模式需要）", font=Theme.get_font("xs"),
                     text_color=self._dark_colors['text_secondary']).pack(side="left", padx=(Theme.DIMENSIONS['spacing_xs'], 0))

        # 根据当前引擎决定是否显示子选项
        self._update_ib_sub_frame_visibility()

        # 状态信息
        status_row = ctk.CTkFrame(input_frame, fg_color="transparent")
        status_row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(0, Theme.DIMENSIONS['spacing_sm']))

        kb_name = available_methods.get(self._current_keyboard_method, {}).get("name", self._current_keyboard_method)
        ms_name = available_methods.get(self._current_mouse_method, {}).get("name", self._current_mouse_method)
        admin_status = "管理员" if is_admin() else "普通用户"
        status_text = f"当前状态: 键盘={kb_name}, 鼠标={ms_name} ({admin_status})"
        self._status_label = ctk.CTkLabel(
            status_row,
            text=status_text,
            font=Theme.get_font("xs"),
            text_color=self._dark_colors['primary']
        )
        self._status_label.pack(anchor="w")

        # 警告
        warn_row = ctk.CTkFrame(input_frame, fg_color="transparent")
        warn_row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(0, Theme.DIMENSIONS['spacing_md']))

        ctk.CTkLabel(
            warn_row,
            text="⚠ 切换输入方式后需要重启应用才能生效",
            font=Theme.get_font("xs"),
            text_color=self._dark_colors['warning']
        ).pack(anchor="w")

    def _update_ib_sub_frame_visibility(self):
        """根据键盘/鼠标引擎是否选择 IB 来决定 IB 子选项的显示"""
        show_ib = (self._current_keyboard_method == "ib" or self._current_mouse_method == "ib")
        if show_ib:
            self._ib_sub_frame.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(0, Theme.DIMENSIONS['spacing_sm']))
            current_ib_mode_key = self._ib_mode_label_to_key.get(self._ib_mode_var.get(), "any_driver")
            if current_ib_mode_key == "mou_class":
                self._ib_pid_frame.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(0, Theme.DIMENSIONS['spacing_sm']))
            else:
                self._ib_pid_frame.pack_forget()
        else:
            self._ib_sub_frame.pack_forget()
            self._ib_pid_frame.pack_forget()

    def _on_ib_mode_changed(self, choice=None):
        """IB 子驱动模式切换"""
        mode_key = self._ib_mode_label_to_key.get(choice, "any_driver")

        # 保存到设置
        from config.settings_manager import SettingsManager
        SettingsManager.get_instance().set("input.ib_send_mode", mode_key, auto_save=True)

        # MCII 模式显示 PID 输入
        if mode_key == "mou_class":
            self._ib_pid_frame.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=(0, Theme.DIMENSIONS['spacing_sm']))
        else:
            self._ib_pid_frame.pack_forget()

    def _on_keyboard_method_changed(self, choice=None):
        """键盘引擎切换"""
        new_method = self._method_label_to_key.get(choice, self._current_keyboard_method)
        if new_method == self._current_keyboard_method:
            return
        self._handle_method_change("keyboard", new_method)

    def _on_mouse_method_changed(self, choice=None):
        """鼠标引擎切换"""
        new_method = self._method_label_to_key.get(choice, self._current_mouse_method)
        if new_method == self._current_mouse_method:
            return
        self._handle_method_change("mouse", new_method)

    def _handle_method_change(self, which: str, new_method: str):
        """处理引擎切换逻辑"""
        from bt_utils.input_manager import InputControllerManager

        manager = InputControllerManager()
        methods = manager.get_available_methods()
        method_info = methods.get(new_method, {})

        if method_info.get("requires_admin", False):
            result = messagebox.askyesno(
                "切换输入方式",
                f"{method_info.get('name', new_method)}需要管理员权限才能正常工作。\n"
                "切换后应用将以管理员身份重新启动。\n\n"
                "是否立即重启？",
                icon='warning'
            )
            if result:
                self._save_ib_pid()
                if hasattr(self.app, '_restart_with_methods'):
                    kb = new_method if which == "keyboard" else self._current_keyboard_method
                    ms = new_method if which == "mouse" else self._current_mouse_method
                    self.app._restart_with_methods(kb, ms, as_admin=True)
            else:
                if which == "keyboard":
                    self._kb_combo_var.set(self._method_key_to_label.get(self._current_keyboard_method, ""))
                else:
                    self._ms_combo_var.set(self._method_key_to_label.get(self._current_mouse_method, ""))
        else:
            result = messagebox.askyesno(
                "切换输入方式",
                f"切换到 {method_info.get('name', new_method)}后，应用将重新启动。\n\n"
                "是否立即重启？",
                icon='question'
            )
            if result:
                self._save_ib_pid()
                if hasattr(self.app, '_restart_with_methods'):
                    kb = new_method if which == "keyboard" else self._current_keyboard_method
                    ms = new_method if which == "mouse" else self._current_mouse_method
                    self.app._restart_with_methods(kb, ms, as_admin=False)
            else:
                if which == "keyboard":
                    self._kb_combo_var.set(self._method_key_to_label.get(self._current_keyboard_method, ""))
                else:
                    self._ms_combo_var.set(self._method_key_to_label.get(self._current_mouse_method, ""))

    def _save_ib_pid(self):
        """保存 IB 目标进程 PID"""
        try:
            pid_str = self._ib_pid_var.get()
            pid = int(pid_str) if pid_str.isdigit() else 0
            from config.settings_manager import SettingsManager
            SettingsManager.get_instance().set("input.ib_target_pid", pid, auto_save=True)
        except Exception:
            pass
    
    def _browse_project_path(self):
        folder_path = filedialog.askdirectory(
            title="选择默认项目保存位置"
        )
        if folder_path:
            self.default_project_path.set(folder_path)
            self._ensure_workspace_exists()
    
    def _ensure_workspace_exists(self):
        """确保workspace文件夹存在"""
        workspace_path = self.default_project_path.get()
        if workspace_path:
            try:
                os.makedirs(workspace_path, exist_ok=True)
            except Exception as e:
                messagebox.showerror("错误", f"无法创建workspace文件夹: {str(e)}")
    
    def _browse_alarm_sound(self):
        file_path = filedialog.askopenfilename(
            title="选择报警声音文件",
            filetypes=[("音频文件", "*.mp3 *.wav *.ogg"), ("所有文件", "*.*")]
        )
        if file_path:
            self.alarm_sound_path.set(file_path)
    
    def _start_key_listening(self, entry, btn):
        btn.set_override_fg(Theme.COLORS['warning'])
        btn.configure(text="请按键...")
        
        try:
            # 暂停全局热键，避免捕获按键时触发已有快捷键
            from bt_utils.global_hotkey import GlobalHotkeyManager
            hotkey_mgr = GlobalHotkeyManager.get_instance()
            was_running = hotkey_mgr.is_running()
            if was_running:
                hotkey_mgr.stop()
            
            from pynput import keyboard
            from bt_utils.key_name_resolver import resolve_key_name
        except ImportError as e:
            btn.clear_override_fg()
            btn.configure(text="修改")
            from tkinter import messagebox
            messagebox.showerror("错误", f"快捷键监听模块加载失败: {e}")
            return
        
        _pressed_modifiers = set()
        
        # 修饰键名称集合（包含 resolve_key_name 返回的各种变体）
        _modifier_names = {
            'ctrl', 'ctrl_l', 'ctrl_r', 'ctrlleft', 'ctrlright',
            'alt', 'alt_l', 'alt_r', 'altleft', 'altright',
            'shift', 'shift_l', 'shift_r', 'shiftleft', 'shiftright',
            'cmd', 'cmd_l', 'cmd_r', 'win', 'win_l', 'win_r'
        }
        
        def _normalize_modifier(name):
            """将修饰键变体统一为标准名"""
            if name in ('ctrl', 'ctrl_l', 'ctrl_r', 'ctrlleft', 'ctrlright'):
                return 'ctrl'
            elif name in ('alt', 'alt_l', 'alt_r', 'altleft', 'altright'):
                return 'alt'
            elif name in ('shift', 'shift_l', 'shift_r', 'shiftleft', 'shiftright'):
                return 'shift'
            elif name in ('cmd', 'cmd_l', 'cmd_r', 'win', 'win_l', 'win_r'):
                return 'cmd'
            return None
        
        def on_press(key):
            key_name = resolve_key_name(key)
            if not key_name:
                return
            
            # 修饰键只记录，不停止监听
            if key_name in _modifier_names:
                mod = _normalize_modifier(key_name)
                if mod:
                    _pressed_modifiers.add(mod)
                return
            
            # 非修饰键：组合修饰键形成组合键名
            parts = sorted(_pressed_modifiers) + [key_name]
            display_name = "+".join(p.upper() if len(p) > 1 else p for p in parts)
            try:
                self.after(0, lambda: self._apply_settings_captured_key(entry, btn, display_name))
            except Exception:
                pass
            return False
        
        def on_release(key):
            key_name = resolve_key_name(key)
            if key_name and key_name in _modifier_names:
                mod = _normalize_modifier(key_name)
                if mod:
                    _pressed_modifiers.discard(mod)
        
        self._settings_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._settings_listener.start()
        
        def reset_listening():
            self._stop_settings_listener()
            # 恢复全局热键
            if was_running:
                hotkey_mgr.start()
            try:
                btn.configure(text="修改")
                btn.clear_override_fg()
            except Exception:
                pass
        
        self._settings_timeout = self.after(10000, reset_listening)
    
    def _add_tab_shortcut_row(self, hotkey: str = "", tab_name: str = ""):
        """添加一行单树快捷键配置"""
        row_frame = ctk.CTkFrame(self._tab_shortcut_container, fg_color="transparent")
        row_frame.pack(fill="x", pady=2)
        
        # 快捷键输入框
        hotkey_var = tk.StringVar(value=hotkey)
        hotkey_entry = ctk.CTkEntry(
            row_frame, textvariable=hotkey_var,
            width=80, height=24, state="disabled",
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary']
        )
        hotkey_entry.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        # 修改快捷键按钮
        capture_btn = AnimatedButton(
            row_frame, text="修改", font=Theme.get_font("xs"),
            width=40, height=24,
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=Theme.COLORS['primary'], hover_color=Theme.COLORS['primary_hover']
        )
        capture_btn.configure(command=lambda e=hotkey_entry, b=capture_btn: self._start_key_listening(e, b))
        capture_btn.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_sm']))
        
        # 目标行为树下拉框
        tree_names = self._get_available_tree_names()
        if tab_name and tab_name not in tree_names:
            tree_names.insert(0, tab_name)
        
        tree_var = tk.StringVar(value=tab_name)
        tree_var.trace_add("write", lambda *args: self._update_editor_shortcuts())
        tree_combo = ctk.CTkOptionMenu(
            row_frame, variable=tree_var, values=tree_names,
            width=150, height=24,
            font=Theme.get_font("xs"),
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
            button_color=Theme.COLORS['primary'],
            button_hover_color=Theme.COLORS['primary_hover']
        )
        tree_combo.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        # 通过内部 Menu 的 postcommand 在菜单弹出前刷新选项
        try:
            internal_menu = tree_combo._dropdown_menu
            if internal_menu:
                internal_menu.configure(postcommand=lambda c=tree_combo: self._refresh_tree_combo(c))
        except Exception:
            # 回退方案：绑定点击事件刷新
            tree_combo.bind("<ButtonPress-1>", lambda e, c=tree_combo: self._refresh_tree_combo(c))
        
        # 清空按钮
        clear_btn = AnimatedButton(
            row_frame, text="清空", font=Theme.get_font("xs"),
            width=36, height=24,
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=self._dark_colors['bg_tertiary'],
            hover_color=self._dark_colors['bg_elevated']
        )
        clear_btn.configure(command=lambda v=tree_var: v.set(""))
        clear_btn.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        # 删除按钮
        remove_btn = AnimatedButton(
            row_frame, text="×", font=Theme.get_font("xs"),
            width=24, height=24,
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=self._dark_colors['bg_tertiary'],
            hover_color=Theme.COLORS['error']
        )
        remove_btn.configure(command=lambda f=row_frame: self._remove_tab_shortcut_row(f))
        remove_btn.pack(side="left")
        
        self._tab_shortcut_rows.append({
            "frame": row_frame,
            "hotkey_var": hotkey_var,
            "tree_var": tree_var,
            "tree_combo": tree_combo
        })
    
    def _remove_tab_shortcut_row(self, frame):
        """删除一行单树快捷键配置"""
        self._tab_shortcut_rows = [r for r in self._tab_shortcut_rows if r["frame"] != frame]
        frame.destroy()
        self._update_editor_shortcuts()
    
    def _get_available_tree_names(self) -> list:
        """获取当前已加载的行为树名称列表"""
        try:
            if hasattr(self.app, 'behavior_tree') and hasattr(self.app.behavior_tree, 'tab_manager'):
                tab_manager = self.app.behavior_tree.tab_manager
                return [inst.name for inst in tab_manager._trees.values()]
        except Exception:
            pass
        return []
    
    def _refresh_tree_combo(self, combo):
        """刷新行为树下拉框选项"""
        tree_names = self._get_available_tree_names()
        current = combo.get()
        combo.configure(values=tree_names)
        # 始终恢复之前选中的值（包括空值），防止 CTkOptionMenu 自动选择第一项
        combo.set(current)
    
    def _apply_settings_captured_key(self, entry, btn, key_name):
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, key_name)
        entry.configure(state="disabled")
        
        btn.configure(text="修改")
        btn.clear_override_fg()
        
        self._stop_settings_listener()
        
        # 恢复全局热键
        from bt_utils.global_hotkey import GlobalHotkeyManager
        hotkey_mgr = GlobalHotkeyManager.get_instance()
        hotkey_mgr.start()
        self._update_editor_shortcuts()
    
    def _stop_settings_listener(self):
        if hasattr(self, '_settings_listener') and self._settings_listener:
            try:
                self._settings_listener.stop()
            except Exception:
                pass
            self._settings_listener = None
        if hasattr(self, '_settings_timeout') and self._settings_timeout:
            self.after_cancel(self._settings_timeout)
            self._settings_timeout = None
    
    def _update_editor_shortcuts(self):
        """更新编辑器的快捷键绑定"""
        try:
            from config.settings_manager import SettingsManager
            
            start_key = self.start_shortcut_var.get()
            stop_key = self.stop_shortcut_var.get()
            record_key = self.record_hotkey_var.get()
            
            settings_manager = SettingsManager.get_instance()
            settings_manager.set("shortcuts.start", start_key, auto_save=False)
            settings_manager.set("shortcuts.stop", stop_key, auto_save=False)
            settings_manager.set("shortcuts.record", record_key, auto_save=False)
            
            # 保存单树快捷键
            tab_shortcuts = []
            for row in self._tab_shortcut_rows:
                hotkey = row["hotkey_var"].get().strip()
                tab_name = row["tree_var"].get().strip()
                entry = {"hotkey": hotkey}
                if tab_name:
                    entry["tab_name"] = tab_name
                tab_shortcuts.append(entry)
            settings_manager.set("shortcuts.tab_shortcuts", tab_shortcuts, auto_save=True)
            
            if hasattr(self.app, 'behavior_tree') and hasattr(self.app.behavior_tree, 'update_run_shortcuts'):
                self.app.behavior_tree.update_run_shortcuts(start_key, stop_key, record_key)
            
            # 更新单树快捷键绑定
            if hasattr(self.app, 'behavior_tree') and hasattr(self.app.behavior_tree, 'update_tab_shortcuts'):
                self.app.behavior_tree.update_tab_shortcuts(tab_shortcuts)
        except Exception:
            pass
    
    def get_settings(self):
        tab_shortcuts = []
        for row in self._tab_shortcut_rows:
            hotkey = row["hotkey_var"].get().strip()
            tab_name = row["tree_var"].get().strip()
            entry = {"hotkey": hotkey}
            if tab_name:
                entry["tab_name"] = tab_name
            tab_shortcuts.append(entry)
        
        return {
            "alarm_sound_path": self.alarm_sound_path.get(),
            "alarm_volume": self.alarm_volume.get(),
            "default_project_path": self.default_project_path.get(),
            "tick_interval_ms": self.tick_interval_ms.get(),
            "shortcuts": {
                "start": self.start_shortcut_var.get(),
                "stop": self.stop_shortcut_var.get(),
                "record": self.record_hotkey_var.get(),
                "tab_shortcuts": tab_shortcuts
            },
            "keyboard_method": self._current_keyboard_method,
            "mouse_method": self._current_mouse_method,
        }
    
    def load_settings(self, settings):
        default_alarm_sound = ResourceManager().get_alarm_sound_path()
        if not os.path.exists(default_alarm_sound):
            default_alarm_sound = ""
        
        default_project_path = self._get_default_project_path()
        
        if "alarm_sound_path" in settings and settings["alarm_sound_path"]:
            if os.path.exists(settings["alarm_sound_path"]):
                self.alarm_sound_path.set(settings["alarm_sound_path"])
            else:
                self.alarm_sound_path.set(default_alarm_sound)
        else:
            self.alarm_sound_path.set(default_alarm_sound)
        
        if "alarm_volume" in settings:
            self.alarm_volume.set(settings["alarm_volume"])
            self.alarm_volume_str.set(str(settings["alarm_volume"]))
        
        if "default_project_path" in settings and settings["default_project_path"]:
            if os.path.exists(settings["default_project_path"]):
                self.default_project_path.set(settings["default_project_path"])
            else:
                self.default_project_path.set(default_project_path)
        else:
            self.default_project_path.set(default_project_path)
        
        self._ensure_workspace_exists()

        if "tick_interval_ms" in settings:
            try:
                val = int(settings["tick_interval_ms"])
                if val > 0:
                    self.tick_interval_ms.set(val)
                    if val in TICK_PRESETS_MS:
                        self.tick_preset_var.set(str(val))
            except (ValueError, TypeError):
                pass
        else:
            from config.settings_manager import SettingsManager
            saved = int(SettingsManager.get_instance().get("behavior_tree.tick_interval", TICK_DEFAULT_MS))
            if saved not in TICK_PRESETS_MS:
                saved = TICK_DEFAULT_MS
            self.tick_interval_ms.set(saved)
            self.tick_preset_var.set(str(saved))
        
        if "shortcuts" in settings:
            shortcuts = settings["shortcuts"]
            if "start" in shortcuts:
                self.start_shortcut_var.set(shortcuts["start"])
            if "stop" in shortcuts:
                self.stop_shortcut_var.set(shortcuts["stop"])
            if "record" in shortcuts:
                self.record_hotkey_var.set(shortcuts["record"])
            if "tab_shortcuts" in shortcuts:
                # 清除现有行
                for row in self._tab_shortcut_rows:
                    row["frame"].destroy()
                self._tab_shortcut_rows.clear()
                # 加载配置
                for ts in shortcuts["tab_shortcuts"]:
                    self._add_tab_shortcut_row(ts.get("hotkey", ""), ts.get("tab_name", ""))
        
        if "input" in settings:
            input_settings = settings["input"]
            if "keyboard_method" in input_settings:
                self._current_keyboard_method = input_settings["keyboard_method"]
                if hasattr(self, '_kb_combo_var') and hasattr(self, '_method_key_to_label'):
                    label = self._method_key_to_label.get(input_settings["keyboard_method"], "")
                    if label:
                        self._kb_combo_var.set(label)
            if "mouse_method" in input_settings:
                self._current_mouse_method = input_settings["mouse_method"]
                if hasattr(self, '_ms_combo_var') and hasattr(self, '_method_key_to_label'):
                    label = self._method_key_to_label.get(input_settings["mouse_method"], "")
                    if label:
                        self._ms_combo_var.set(label)

    def _create_ai_section(self, parent):
        """创建 AI 配置区域"""
        from config.settings_manager import SettingsManager

        sm = SettingsManager.get_instance()

        ai_frame = CardFrame(parent)
        ai_frame.pack(fill="x", pady=(0, Theme.DIMENSIONS['spacing_md']))

        ai_header = ctk.CTkFrame(ai_frame, fg_color="transparent")
        ai_header.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'],
                        pady=(Theme.DIMENSIONS['spacing_md'], Theme.DIMENSIONS['spacing_sm']))
        create_section_title(ai_header, "AI 模型配置", level=1).pack(side="left")

        ctk.CTkLabel(
            ai_header,
            text="配置 LLM/VLM 接口，供 DSH 编排、CLI AI 命令与视觉插件使用",
            font=Theme.get_font("xs"),
            text_color=self._dark_colors['text_muted'],
        ).pack(side="left", padx=(Theme.DIMENSIONS['spacing_sm'], 0))

        create_divider(ai_frame)

        # --- LLM 配置 ---
        llm_section = ctk.CTkFrame(ai_frame, fg_color="transparent")
        llm_section.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'],
                          pady=(Theme.DIMENSIONS['spacing_sm'], 0))

        ctk.CTkLabel(
            llm_section,
            text="LLM（文本模型 — 意图分析、节点选型、JSON 生成）",
            font=Theme.get_font("sm"),
            text_color=self._dark_colors['text_primary'],
        ).pack(anchor="w", pady=(0, 5))

        # base_url
        llm_url_row = ctk.CTkFrame(llm_section, fg_color="transparent")
        llm_url_row.pack(fill="x", pady=2)
        ctk.CTkLabel(
            llm_url_row, text="API 地址:", width=70,
            font=Theme.get_font("sm"),
            text_color=self._dark_colors['text_secondary'],
        ).pack(side="left")
        self._ai_llm_url_var = tk.StringVar(
            value=sm.get("ai.llm.base_url", "https://api.openai.com/v1"))
        ctk.CTkEntry(
            llm_url_row, textvariable=self._ai_llm_url_var,
            height=28, fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

        # api_key
        llm_key_row = ctk.CTkFrame(llm_section, fg_color="transparent")
        llm_key_row.pack(fill="x", pady=2)
        ctk.CTkLabel(
            llm_key_row, text="API Key:", width=70,
            font=Theme.get_font("sm"),
            text_color=self._dark_colors['text_secondary'],
        ).pack(side="left")
        self._ai_llm_key_var = tk.StringVar(
            value=sm.get("ai.llm.api_key", ""))
        ctk.CTkEntry(
            llm_key_row, textvariable=self._ai_llm_key_var,
            height=28, show="*",
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

        # model
        llm_model_row = ctk.CTkFrame(llm_section, fg_color="transparent")
        llm_model_row.pack(fill="x", pady=2)
        ctk.CTkLabel(
            llm_model_row, text="模型:", width=70,
            font=Theme.get_font("sm"),
            text_color=self._dark_colors['text_secondary'],
        ).pack(side="left")
        self._ai_llm_model_var = tk.StringVar(
            value=sm.get("ai.llm.model", "gpt-4o"))
        ctk.CTkEntry(
            llm_model_row, textvariable=self._ai_llm_model_var,
            height=28, fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

        create_divider(ai_frame)

        # --- VLM 配置 ---
        vlm_section = ctk.CTkFrame(ai_frame, fg_color="transparent")
        vlm_section.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'],
                          pady=(Theme.DIMENSIONS['spacing_sm'], 0))

        ctk.CTkLabel(
            vlm_section,
            text="VLM（视觉模型 — 屏幕截图分析、参数自动填充）",
            font=Theme.get_font("sm"),
            text_color=self._dark_colors['text_primary'],
        ).pack(anchor="w", pady=(0, 5))

        ctk.CTkLabel(
            vlm_section,
            text="留空则跳过屏幕感知阶段，使用 LLM 生成的结构直接生成行为树",
            font=Theme.get_font("xs"),
            text_color=self._dark_colors['text_muted'],
        ).pack(anchor="w", pady=(0, 5))

        # base_url
        vlm_url_row = ctk.CTkFrame(vlm_section, fg_color="transparent")
        vlm_url_row.pack(fill="x", pady=2)
        ctk.CTkLabel(
            vlm_url_row, text="API 地址:", width=70,
            font=Theme.get_font("sm"),
            text_color=self._dark_colors['text_secondary'],
        ).pack(side="left")
        self._ai_vlm_url_var = tk.StringVar(
            value=sm.get("ai.vlm.base_url", "https://api.openai.com/v1"))
        ctk.CTkEntry(
            vlm_url_row, textvariable=self._ai_vlm_url_var,
            height=28, fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

        # api_key
        vlm_key_row = ctk.CTkFrame(vlm_section, fg_color="transparent")
        vlm_key_row.pack(fill="x", pady=2)
        ctk.CTkLabel(
            vlm_key_row, text="API Key:", width=70,
            font=Theme.get_font("sm"),
            text_color=self._dark_colors['text_secondary'],
        ).pack(side="left")
        self._ai_vlm_key_var = tk.StringVar(
            value=sm.get("ai.vlm.api_key", ""))
        ctk.CTkEntry(
            vlm_key_row, textvariable=self._ai_vlm_key_var,
            height=28, show="*",
            fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

        # model
        vlm_model_row = ctk.CTkFrame(vlm_section, fg_color="transparent")
        vlm_model_row.pack(fill="x", pady=2)
        ctk.CTkLabel(
            vlm_model_row, text="模型:", width=70,
            font=Theme.get_font("sm"),
            text_color=self._dark_colors['text_secondary'],
        ).pack(side="left")
        self._ai_vlm_model_var = tk.StringVar(
            value=sm.get("ai.vlm.model", "gpt-4o"))
        ctk.CTkEntry(
            vlm_model_row, textvariable=self._ai_vlm_model_var,
            height=28, fg_color=self._dark_colors['bg_tertiary'],
            text_color=self._dark_colors['text_primary'],
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

        # --- 保存按钮 ---
        btn_row = ctk.CTkFrame(ai_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'],
                      pady=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_md']))

        AnimatedButton(
            btn_row, text="保存 AI 配置",
            font=Theme.get_font("sm"), width=120, height=30,
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=Theme.COLORS['primary'],
            hover_color=Theme.COLORS['primary_hover'],
            command=self._save_ai_settings,
        ).pack(side="left")

        self._ai_status_label = ctk.CTkLabel(
            btn_row, text="",
            font=Theme.get_font("xs"),
            text_color=self._dark_colors['text_muted'],
        )
        self._ai_status_label.pack(side="left", padx=10)

    def _save_ai_settings(self):
        """保存 AI 配置"""
        from config.settings_manager import SettingsManager
        sm = SettingsManager.get_instance()

        sm.set("ai.enabled", True, auto_save=False)
        sm.set("ai.llm.base_url", self._ai_llm_url_var.get().strip(), auto_save=False)
        sm.set("ai.llm.api_key", self._ai_llm_key_var.get().strip(), auto_save=False)
        sm.set("ai.llm.model", self._ai_llm_model_var.get().strip(), auto_save=False)
        sm.set("ai.vlm.base_url", self._ai_vlm_url_var.get().strip(), auto_save=False)
        sm.set("ai.vlm.api_key", self._ai_vlm_key_var.get().strip(), auto_save=False)
        sm.set("ai.vlm.model", self._ai_vlm_model_var.get().strip(), auto_save=True)

        has_llm = bool(self._ai_llm_key_var.get().strip())
        has_vlm = bool(self._ai_vlm_key_var.get().strip())
        if has_llm and has_vlm:
            status = "已保存 — LLM + VLM 均已配置"
            color = self._dark_colors.get('success', '#22C55E')
        elif has_llm:
            status = "已保存 — 仅 LLM（VLM 未配置，将跳过屏幕感知）"
            color = self._dark_colors.get('warning', '#F59E0B')
        else:
            status = "已保存 — 未配置 API Key，AI 功能不可用"
            color = self._dark_colors.get('error', '#EF4444')
        self._ai_status_label.configure(text=status, text_color=color)
