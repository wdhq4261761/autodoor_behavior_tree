import customtkinter as ctk
from tkinter import StringVar
from typing import Optional, Callable

from ..theme import Theme


class EditorToolbar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        app,
        on_save: Optional[Callable] = None,
        on_export: Optional[Callable] = None,
        on_import: Optional[Callable] = None,
        on_new_project: Optional[Callable] = None,
        on_open_project: Optional[Callable] = None,
        on_undo: Optional[Callable] = None,
        on_redo: Optional[Callable] = None,
        on_clear: Optional[Callable] = None,
        on_reset_view: Optional[Callable] = None,
        on_start: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
        on_open_folder: Optional[Callable] = None,
        **kwargs
    ):
        super().__init__(master, **kwargs)
        self.app = app
        self.on_save = on_save
        self.on_export = on_export
        self.on_import = on_import
        self.on_new_project = on_new_project
        self.on_open_project = on_open_project
        self.on_undo = on_undo
        self.on_redo = on_redo
        self.on_clear = on_clear
        self.on_reset_view = on_reset_view
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_open_folder = on_open_folder
        self.is_running = False
        
        self._dark_colors = Theme.get_dark_colors()
        self.configure(fg_color=self._dark_colors['header_bg'], corner_radius=0)
        self._create_ui()
    
    def _create_ui(self):
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=Theme.DIMENSIONS['spacing_sm'])
        
        left_section = ctk.CTkFrame(main_container, fg_color="transparent")
        left_section.pack(side="left")
        
        self._create_file_buttons(left_section)
        self._create_separator(left_section)
        self._create_edit_buttons(left_section)
        self._create_separator(left_section)
        self._create_run_buttons(left_section)
        
        self._create_path_display(main_container)
        
        right_section = ctk.CTkFrame(main_container, fg_color="transparent")
        right_section.pack(side="right")

        self._create_open_folder_button(right_section)
        self._create_reset_view_button(right_section)
    
    def _create_file_buttons(self, parent):
        file_frame = ctk.CTkFrame(parent, fg_color="transparent")
        file_frame.pack(side="left")
        
        btn_config = {
            'font': Theme.get_font('sm'),
            'height': Theme.DIMENSIONS['button_height'],
            'corner_radius': Theme.DIMENSIONS['button_corner_radius'],
        }
        
        ctk.CTkButton(
            file_frame,
            text="新建项目",
            width=70,
            fg_color=self._dark_colors['bg_tertiary'],
            hover_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            command=self._on_new_project_click,
            **btn_config
        ).pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
        
        ctk.CTkButton(
            file_frame,
            text="打开项目",
            width=70,
            fg_color=self._dark_colors['bg_tertiary'],
            hover_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            command=self._on_open_project_click,
            **btn_config
        ).pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
        
        ctk.CTkButton(
            file_frame,
            text="保存项目",
            width=70,
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            command=self._on_save_click,
            **btn_config
        ).pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
        
        ctk.CTkButton(
            file_frame,
            text="导出项目",
            width=70,
            fg_color=self._dark_colors['bg_tertiary'],
            hover_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            command=self._on_export_click,
            **btn_config
        ).pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
        
        ctk.CTkButton(
            file_frame,
            text="导入项目",
            width=70,
            fg_color=self._dark_colors['bg_tertiary'],
            hover_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            command=self._on_import_click,
            **btn_config
        ).pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
    
    def _create_edit_buttons(self, parent):
        edit_frame = ctk.CTkFrame(parent, fg_color="transparent")
        edit_frame.pack(side="left")
        
        btn_config = {
            'font': Theme.get_font('sm'),
            'height': Theme.DIMENSIONS['button_height'],
            'corner_radius': Theme.DIMENSIONS['button_corner_radius'],
            'width': 60,
            'fg_color': self._dark_colors['bg_tertiary'],
            'hover_color': self._dark_colors['border'],
            'text_color': self._dark_colors['text_primary'],
        }
        
        self.undo_btn = ctk.CTkButton(
            edit_frame,
            text="撤销",
            command=self._on_undo_click,
            state="disabled",
            **btn_config
        )
        self.undo_btn.pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
        
        self.redo_btn = ctk.CTkButton(
            edit_frame,
            text="回退",
            command=self._on_redo_click,
            state="disabled",
            **btn_config
        )
        self.redo_btn.pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
        
        self.clear_btn = ctk.CTkButton(
            edit_frame,
            text="清空",
            command=self._on_clear_click,
            **btn_config
        )
        self.clear_btn.pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
    
    def _create_separator(self, parent):
        sep = ctk.CTkFrame(
            parent,
            width=1,
            height=Theme.DIMENSIONS['button_height'],
            fg_color=self._dark_colors['border']
        )
        sep.pack(side="left", padx=Theme.DIMENSIONS['spacing_md'])
    
    def _create_run_buttons(self, parent):
        run_frame = ctk.CTkFrame(parent, fg_color="transparent")
        run_frame.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_md']))
        
        self.start_btn = ctk.CTkButton(
            run_frame,
            text="▶ 开始",
            width=60,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['button_height'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=Theme.COLORS['success'],
            hover_color='#16A34A',
            command=self._on_start_click
        )
        self.start_btn.pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
        
        self.stop_btn = ctk.CTkButton(
            run_frame,
            text="⏹ 停止",
            width=60,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['button_height'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=Theme.COLORS['error'],
            hover_color='#DC2626',
            command=self._on_stop_click,
            state="disabled"
        )
        self.stop_btn.pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
    
    def _create_path_display(self, parent):
        path_frame = ctk.CTkFrame(parent, fg_color="transparent")
        path_frame.pack(side="left", fill="x", expand=True, padx=(Theme.DIMENSIONS['spacing_md'], 0))
        
        self.file_path_var = StringVar(value="未保存")
        
        self.file_path_entry = ctk.CTkEntry(
            path_frame,
            textvariable=self.file_path_var,
            font=Theme.get_font('sm'),
            text_color=self._dark_colors['text_muted'],
            fg_color=self._dark_colors['bg_secondary'],
            border_width=0,
            height=Theme.DIMENSIONS['button_height'],
            state="readonly"
        )
        self.file_path_entry.pack(fill="x", expand=True)
    
    def _create_open_folder_button(self, parent):
        self.open_folder_btn = ctk.CTkButton(
            parent,
            text="打开文件",
            width=80,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['button_height'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=self._dark_colors['info'],
            hover_color=self._dark_colors['info_hover'],
            command=self._on_open_folder_click
        )
        self.open_folder_btn.pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])

    def _create_reset_view_button(self, parent):
        ctk.CTkButton(
            parent,
            text="重置视图",
            width=80,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['button_height'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            fg_color=self._dark_colors['bg_tertiary'],
            hover_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            command=self._on_reset_view_click
        ).pack(side="left", padx=Theme.DIMENSIONS['spacing_xs'])
    
    def _on_new_project_click(self):
        if self.on_new_project:
            self.on_new_project()
    
    def _on_open_project_click(self):
        if self.on_open_project:
            self.on_open_project()
    
    def _on_save_click(self):
        if self.on_save:
            self.on_save()
    
    def _on_export_click(self):
        if self.on_export:
            self.on_export()
    
    def _on_import_click(self):
        if self.on_import:
            self.on_import()
    
    def _on_undo_click(self):
        if self.on_undo:
            self.on_undo()
    
    def _on_redo_click(self):
        if self.on_redo:
            self.on_redo()
    
    def _on_clear_click(self):
        if self.on_clear:
            self.on_clear()
    
    def _on_reset_view_click(self):
        if self.on_reset_view:
            self.on_reset_view()
    
    def _on_open_folder_click(self):
        if self.on_open_folder:
            self.on_open_folder()
    
    def _on_start_click(self):
        if self.on_start:
            self.on_start()
    
    def _on_stop_click(self):
        if self.on_stop:
            self.on_stop()
    
    def update_undo_redo(self, can_undo: bool, can_redo: bool, 
                         undo_desc: Optional[str] = None, 
                         redo_desc: Optional[str] = None):
        self.undo_btn.configure(state="normal" if can_undo else "disabled")
        self.redo_btn.configure(state="normal" if can_redo else "disabled")
    
    def set_running(self, running: bool):
        self.is_running = running
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
    
    def set_status(self, text: str, color: Optional[str] = None):
        pass
    
    def set_file_path(self, file_path: Optional[str]):
        if file_path:
            import os
            self.file_path_var.set(os.path.basename(file_path))
        else:
            self.file_path_var.set("未保存")
    
    def set_project_path(self, project_root: Optional[str]):
        if project_root:
            self.file_path_var.set(project_root)
            self.file_path_entry.tooltip = project_root
        else:
            self.file_path_var.set("未保存")
            self.file_path_entry.tooltip = None
