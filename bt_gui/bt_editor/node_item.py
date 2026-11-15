import tkinter as tk
import tkinter.font as tkFont
from enum import Enum
import math

from ..theme import Theme
from bt_utils.json_io import load_json
from .constants import NODE_CATEGORY_MAP, NODE_DISPLAY_NAMES


class NodeExecutionStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    ABORTED = "aborted"


STATUS_COLORS = {
    NodeExecutionStatus.IDLE: None,
    NodeExecutionStatus.RUNNING: "#F59E0B",
    NodeExecutionStatus.SUCCESS: "#22C55E",
    NodeExecutionStatus.FAILURE: "#EF4444",
    NodeExecutionStatus.ABORTED: "#6B7280",
}

STATUS_ICONS = {
    NodeExecutionStatus.SUCCESS: "✓",
    NodeExecutionStatus.FAILURE: "✗",
    NodeExecutionStatus.RUNNING: "⋯",
    NodeExecutionStatus.ABORTED: "⊘",
}

PORT_RADIUS = 8


class NodeItem:
    def __init__(self, canvas: tk.Canvas, node_id: str, node_type: str, x: float, y: float, name: str = "", config: dict = None, enabled: bool = True, zoom: float = 1.0, pan_x: float = 0, pan_y: float = 0):
        self.canvas = canvas
        self.node_id = node_id
        self.node_type = node_type
        self.x = x
        self.y = y
        self.width = 140
        self.height = 56
        self.name = name
        self.config = config or {}
        self.enabled = enabled
        self.skip = bool(self.config.get("skip", False))
        self._zoom = zoom
        self._pan_x = pan_x
        self._pan_y = pan_y
        self._protected = (node_type == "StartNode")
        
        self._status = NodeExecutionStatus.IDLE
        self._selected = False
        self._flash_state = False
        self._flash_job = None
        self._status_visible = False
        self._canvas_items_exist = True  # Canvas图元存在标志（虚拟化时可能被删除）
        
        self._dark_colors = Theme.get_dark_colors()
        self._category = NODE_CATEGORY_MAP.get(node_type, "action")
        self._color_config = Theme.get_node_color(self._category)
        
        self._create_visuals()
    
    def set_zoom(self, zoom: float):
        self._zoom = zoom
    
    def set_pan(self, pan_x: float, pan_y: float):
        self._pan_x = pan_x
        self._pan_y = pan_y
    
    def _scale(self, value: float) -> float:
        return value * self._zoom
    
    def _transform_x(self, x: float) -> float:
        return x * self._zoom + self._pan_x
    
    def _transform_y(self, y: float) -> float:
        return y * self._zoom + self._pan_y
    
    def update_config(self, key: str, value) -> None:
        if key in ["name", "description", "enabled", "skip"]:
            old_value = getattr(self, key, None)
            setattr(self, key, value)
            if key == "skip":
                self.config[key] = bool(value)
            
            if key in ("name", "skip") and old_value != value:
                self.redraw()
        else:
            if self.config is None:
                self.config = {}
            self.config[key] = value
    
    def is_protected(self) -> bool:
        return self._protected
    
    def _create_visuals(self):
        shadow_offset = 3
        w = self._scale(self.width)
        h = self._scale(self.height)
        x = self._transform_x(self.x)
        y = self._transform_y(self.y)
        
        self.shadow = self.canvas.create_rectangle(
            x - w/2 + self._scale(shadow_offset),
            y - h/2 + self._scale(shadow_offset),
            x + w/2 + self._scale(shadow_offset),
            y + h/2 + self._scale(shadow_offset),
            fill="#000000",
            stipple="gray50",
            outline="",
            tags=("node_shadow", self.node_id)
        )
        
        self.rect = self.canvas.create_rectangle(
            x - w/2,
            y - h/2,
            x + w/2,
            y + h/2,
            fill=self._dark_colors['node_bg'],
            outline=self._dark_colors['node_border'],
            width=1,
            dash=(4, 3) if self.skip else None,
            tags=("node", self.node_id)
        )
        
        self.color_bar = self.canvas.create_rectangle(
            x - w/2,
            y - h/2,
            x - w/2 + self._scale(4),
            y + h/2,
            fill=self._color_config['bg'],
            outline="",
            tags=("node_color", self.node_id)
        )
        
        display_name = self._get_display_name()
        self.text = self.canvas.create_text(
            x + self._scale(10),
            y,
            text=display_name,
            fill=self._dark_colors['text_primary'],
            font=("Microsoft YaHei", max(8, int(10 * self._zoom)), "bold"),
            anchor="center",
            tags=("node_text", self.node_id)
        )
        
        status_radius = self._scale(10)
        self.status_bg = self.canvas.create_oval(
            x + w/2 - self._scale(24),
            y - status_radius,
            x + w/2 - self._scale(4),
            y + status_radius,
            fill=self._dark_colors['bg_tertiary'],
            outline="",
            tags=("node_status_bg", self.node_id),
            state='hidden'
        )
        
        self.status_icon = self.canvas.create_text(
            x + w/2 - self._scale(14),
            y,
            text="",
            fill=self._dark_colors['text_secondary'],
            font=("Arial", max(8, int(10 * self._zoom)), "bold"),
            tags=("node_icon", self.node_id),
            state='hidden'
        )
        
        port_radius = self._scale(PORT_RADIUS)
        self.input_port = self.canvas.create_oval(
            x - port_radius,
            y - h/2 - port_radius,
            x + port_radius,
            y - h/2 + port_radius,
            fill=self._dark_colors['bg_tertiary'],
            outline=self._dark_colors['border'],
            width=2,
            tags=("node_port_in", self.node_id, "port")
        )
        
        self.output_port = self.canvas.create_oval(
            x - port_radius,
            y + h/2 - port_radius,
            x + port_radius,
            y + h/2 + port_radius,
            fill=self._color_config['bg'],
            outline=self._dark_colors['border'],
            width=2,
            tags=("node_port_out", self.node_id, "port")
        )

        self._update_outline()

        # 恢复状态指示器（虚拟化后redraw时需恢复之前的状态）
        if self._status_visible:
            self.canvas.itemconfig(self.status_bg, state='normal')
            self.canvas.itemconfig(self.status_icon, state='normal')
        if self._status != NodeExecutionStatus.IDLE:
            icon = STATUS_ICONS.get(self._status, "")
            self.canvas.itemconfig(self.status_icon, text=icon)
            if self._status in (NodeExecutionStatus.SUCCESS, NodeExecutionStatus.FAILURE, NodeExecutionStatus.ABORTED):
                status_color = STATUS_COLORS[self._status]
                if status_color:
                    self.canvas.itemconfig(self.status_bg, fill=status_color)
                    self.canvas.itemconfig(self.status_icon, fill="#FFFFFF")
            elif self._status == NodeExecutionStatus.RUNNING:
                self.canvas.itemconfig(self.status_bg, fill=STATUS_COLORS[NodeExecutionStatus.RUNNING])
    
    def _get_display_name(self) -> str:
        if self.name and self.name.strip():
            base_name = self.name.strip()
        else:
            base_name = NODE_DISPLAY_NAMES.get(self.node_type, self.node_type)
        
        # 为StartNode添加特殊图标
        if self.node_type == "StartNode":
            base_name = "▶ " + base_name
        
        available_width = self.width - 48
        scaled_available_width = self._scale(available_width)
        
        font_size = max(8, int(10 * self._zoom))
        font = tkFont.Font(family="Microsoft YaHei", size=font_size, weight="bold")
        
        text_width = font.measure(base_name)
        
        if text_width <= scaled_available_width:
            return base_name
        
        ellipsis = "..."
        ellipsis_width = font.measure(ellipsis)
        target_width = scaled_available_width - ellipsis_width
        
        if target_width <= 0:
            return ellipsis
        
        left, right = 0, len(base_name)
        while left < right:
            mid = (left + right + 1) // 2
            test_text = base_name[:mid]
            test_width = font.measure(test_text)
            
            if test_width <= target_width:
                left = mid
            else:
                right = mid - 1
        
        return base_name[:left] + ellipsis
    
    def redraw(self):
        self.canvas.delete(self.node_id)
        self._canvas_items_exist = False
        self._create_visuals()
        self._canvas_items_exist = True
        # redraw后需重新应用选中/运行状态边框，因为_create_visuals中_update_outline
        # 受_canvas_items_exist守卫保护，在redraw期间为False会被跳过
        self._update_outline()
    
    def move_to(self, x: float, y: float):
        self.x = x
        self.y = y
        self.redraw()
    
    def get_bounds(self) -> tuple:
        return (
            self.x - self.width/2, self.y - self.height/2,
            self.x + self.width/2, self.y + self.height/2
        )
    
    def contains_point(self, x: float, y: float) -> bool:
        x1, y1, x2, y2 = self.get_bounds()
        return x1 <= x <= x2 and y1 <= y <= y2
    
    def get_input_port_pos(self) -> tuple:
        return (self.x, self.y - self.height/2)
    
    def get_output_port_pos(self) -> tuple:
        return (self.x, self.y + self.height/2)
    
    def is_on_input_port(self, x: float, y: float) -> bool:
        px, py = self.get_input_port_pos()
        dist = math.sqrt((x - px)**2 + (y - py)**2)
        return dist <= PORT_RADIUS + 4
    
    def is_on_output_port(self, x: float, y: float) -> bool:
        px, py = self.get_output_port_pos()
        dist = math.sqrt((x - px)**2 + (y - py)**2)
        return dist <= PORT_RADIUS + 4
    
    def set_selected(self, selected: bool):
        self._selected = selected
        if self._canvas_items_exist:
            self._update_outline()

    def highlight_port(self, port_type: str, highlight: bool = True):
        if not self._canvas_items_exist:
            return
        if port_type == "input":
            port = self.input_port
            color = self._dark_colors['node_selected'] if highlight else self._dark_colors['bg_tertiary']
        else:
            port = self.output_port
            color = self._dark_colors['node_selected'] if highlight else self._color_config['bg']

        self.canvas.itemconfig(port, outline=color, width=3 if highlight else 2)

    def set_status(self, status: NodeExecutionStatus):
        self._status = status

        if self._flash_job:
            self.canvas.after_cancel(self._flash_job)
            self._flash_job = None

        if status == NodeExecutionStatus.RUNNING:
            self._start_flashing()
        else:
            self._flash_state = False
            if self._canvas_items_exist:
                self._update_outline()

        if not self._canvas_items_exist:
            return

        icon = STATUS_ICONS.get(status, "")
        self.canvas.itemconfig(self.status_icon, text=icon)

        if status in (NodeExecutionStatus.SUCCESS, NodeExecutionStatus.FAILURE, NodeExecutionStatus.ABORTED):
            status_color = STATUS_COLORS[status]
            if status_color:
                self.canvas.itemconfig(self.status_bg, fill=status_color)
                self.canvas.itemconfig(self.status_icon, fill="#FFFFFF")
        elif status == NodeExecutionStatus.RUNNING:
            self.canvas.itemconfig(self.status_bg, fill=STATUS_COLORS[NodeExecutionStatus.RUNNING])
        else:
            self.canvas.itemconfig(self.status_bg, fill=self._dark_colors['bg_tertiary'])
            self.canvas.itemconfig(self.status_icon, fill=self._dark_colors['text_secondary'])

    def show_status_indicator(self):
        if not self._status_visible:
            self._status_visible = True
            if self._canvas_items_exist:
                self.canvas.itemconfig(self.status_bg, state='normal')
                self.canvas.itemconfig(self.status_icon, state='normal')

    def hide_status_indicator(self):
        if self._status_visible:
            self._status_visible = False
            if self._canvas_items_exist:
                self.canvas.itemconfig(self.status_bg, state='hidden')
                self.canvas.itemconfig(self.status_icon, state='hidden')

    def _start_flashing(self):
        self._flash_state = not self._flash_state
        if self._canvas_items_exist:
            self._update_outline()
        self._flash_job = self.canvas.after(400, self._start_flashing)

    def _update_outline(self):
        if not self._canvas_items_exist:
            return
        if self._status == NodeExecutionStatus.RUNNING:
            outline = "#F59E0B" if self._flash_state else "#FBBF24"
            width = 2
        elif self._selected:
            outline = self._dark_colors['node_selected']
            width = 2
        else:
            outline = self._dark_colors['node_border']
            width = 1

        self.canvas.itemconfig(self.rect, outline=outline, width=width,
                               dash=(4, 3) if self.skip and not self._selected else None)

    def reset_status(self):
        self._status = NodeExecutionStatus.IDLE
        if self._flash_job:
            self.canvas.after_cancel(self._flash_job)
            self._flash_job = None
        self._flash_state = False
        if self._canvas_items_exist:
            self._update_outline()
            self.canvas.itemconfig(self.status_icon, text="")
            self.canvas.itemconfig(self.status_bg, fill=self._dark_colors['bg_tertiary'])
        self.hide_status_indicator()


class SubtreeNodeItem(NodeItem):
    """子树节点视觉项

    特殊渲染：虚线边框、紫色色条、展开/折叠按钮
    预览机制：使用独立tag，redraw时自动重建预览
    """

    PREVIEW_NODE_WIDTH = 100
    PREVIEW_NODE_HEIGHT = 30
    PREVIEW_H_GAP = 20
    PREVIEW_V_GAP = 50
    PREVIEW_PADDING = 15

    def __init__(self, canvas: tk.Canvas, node_id: str, node_type: str,
                 x: float, y: float, name: str = "", config: dict = None,
                 enabled: bool = True, zoom: float = 1.0,
                 pan_x: float = 0, pan_y: float = 0):
        self._expanded = False
        self._preview_items: list = []
        self._subtree_raw_data = None
        self._is_preview = False
        self._is_readonly = False

        super().__init__(canvas, node_id, node_type, x, y, name, config,
                         enabled, zoom, pan_x, pan_y)

        self.height = 50

    def _create_visuals(self):
        shadow_offset = 3
        w = self._scale(self.width)
        h = self._scale(self.height)
        x = self._transform_x(self.x)
        y = self._transform_y(self.y)

        self.shadow = self.canvas.create_rectangle(
            x - w/2 + self._scale(shadow_offset),
            y - h/2 + self._scale(shadow_offset),
            x + w/2 + self._scale(shadow_offset),
            y + h/2 + self._scale(shadow_offset),
            fill="#000000",
            stipple="gray50",
            outline="",
            tags=("node_shadow", self.node_id)
        )

        self.rect = self.canvas.create_rectangle(
            x - w/2,
            y - h/2,
            x + w/2,
            y + h/2,
            fill=self._dark_colors['node_bg'],
            outline=self._dark_colors['node_border'],
            width=2,
            dash=(5, 3),
            tags=("node", self.node_id)
        )

        self.color_bar = self.canvas.create_rectangle(
            x - w/2,
            y - h/2,
            x - w/2 + self._scale(4),
            y + h/2,
            fill="#8B5CF6",
            outline="",
            tags=("node_color", self.node_id)
        )

        self._toggle_btn_bg = self.canvas.create_rectangle(
            x - w/2 + self._scale(8),
            y - self._scale(10),
            x - w/2 + self._scale(28),
            y + self._scale(10),
            fill=self._dark_colors['bg_tertiary'],
            outline=self._dark_colors['border'],
            width=1,
            tags=("subtree_toggle", self.node_id)
        )

        self._toggle_btn_text = self.canvas.create_text(
            x - w/2 + self._scale(18),
            y,
            text="▶" if not self._expanded else "▼",
            fill=self._dark_colors['text_primary'],
            font=("Arial", max(8, int(9 * self._zoom)), "bold"),
            anchor="center",
            tags=("subtree_toggle", self.node_id)
        )

        display_name = self._get_display_name()
        self.text = self.canvas.create_text(
            x + self._scale(8),
            y,
            text=display_name,
            fill=self._dark_colors['text_primary'],
            font=("Microsoft YaHei", max(8, int(10 * self._zoom)), "bold"),
            anchor="center",
            tags=("node_text", self.node_id)
        )

        status_radius = self._scale(10)
        self.status_bg = self.canvas.create_oval(
            x + w/2 - self._scale(24),
            y - status_radius,
            x + w/2 - self._scale(4),
            y + status_radius,
            fill=self._dark_colors['bg_tertiary'],
            outline="",
            tags=("node_status_bg", self.node_id),
            state='hidden'
        )

        self.status_icon = self.canvas.create_text(
            x + w/2 - self._scale(14),
            y,
            text="",
            fill=self._dark_colors['text_secondary'],
            font=("Arial", max(8, int(10 * self._zoom)), "bold"),
            tags=("node_icon", self.node_id),
            state='hidden'
        )

        port_radius = self._scale(PORT_RADIUS)
        self.input_port = self.canvas.create_oval(
            x - port_radius,
            y - h/2 - port_radius,
            x + port_radius,
            y - h/2 + port_radius,
            fill=self._dark_colors['bg_tertiary'],
            outline=self._dark_colors['border'],
            width=2,
            tags=("node_port_in", self.node_id, "port")
        )

        self.output_port = self.canvas.create_oval(
            x - port_radius,
            y + h/2 - port_radius,
            x + port_radius,
            y + h/2 + port_radius,
            fill="#8B5CF6",
            outline=self._dark_colors['border'],
            width=2,
            tags=("node_port_out", self.node_id, "port")
        )

        self._update_outline()

    def _get_folder_name(self) -> str:
        path = self.config.get("subtree_path", "") if self.config else ""
        if not path:
            return ""
        path = path.replace("\\", "/")
        if path.endswith("/"):
            path = path[:-1]
        return path.split("/")[-1] or ""

    def _resolve_subtree_path(self) -> str:
        """将相对路径解析为绝对路径"""
        import os
        path = self.config.get("subtree_path", "") if self.config else ""
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        project_root = self._get_project_root()
        if project_root:
            return os.path.normpath(os.path.join(project_root, path))
        return path

    def _get_project_root(self) -> str:
        """获取当前项目根目录"""
        try:
            app = self.canvas.winfo_toplevel()
            if hasattr(app, 'behavior_tree'):
                editor = app.behavior_tree
                if hasattr(editor, 'project_root') and editor.project_root:
                    return editor.project_root
        except Exception:
            pass
        return ""

    def _find_tree_file(self, project_dir: str) -> str:
        """在子树项目文件夹中查找行为树文件"""
        import os
        if not os.path.isdir(project_dir):
            return ""
        project_json = os.path.join(project_dir, "project.json")
        if os.path.exists(project_json):
            try:
                proj_data = load_json(project_json)
                main_tree = proj_data.get("main_tree", "tree.json")
                tree_path = os.path.join(project_dir, main_tree)
                if os.path.exists(tree_path):
                    return tree_path
            except Exception:
                pass
        tree_json = os.path.join(project_dir, "tree.json")
        if os.path.exists(tree_json):
            return tree_json
        try:
            json_files = [f for f in os.listdir(project_dir)
                          if f.endswith('.json') and f != 'project.json']
            if len(json_files) == 1:
                return os.path.join(project_dir, json_files[0])
        except Exception:
            pass
        return ""

    def is_on_toggle_btn(self, x: float, y: float) -> bool:
        """检查点击是否在展开/折叠按钮上"""
        btn_x = self.x - self.width/2 + 18
        btn_y = self.y
        btn_w = 20
        btn_h = 20
        return (btn_x - btn_w/2 <= x <= btn_x + btn_w/2 and
                btn_y - btn_h/2 <= y <= btn_y + btn_h/2)

    def redraw(self):
        """重写redraw：先删除旧预览，主节点重绘后，若已展开则重建预览"""
        try:
            self.canvas.delete(f"subtree_preview_{self.node_id}")
        except Exception:
            pass
        self._preview_items.clear()
        super().redraw()
        if self._expanded:
            self._expand_preview()

    def update_config(self, key: str, value) -> None:
        """更新配置项，子树路径变化时重置预览数据"""
        if key == "subtree_path":
            self._subtree_raw_data = None
            if self._expanded:
                self._collapse_preview()
                self._expanded = False
                try:
                    self.canvas.itemconfig(self._toggle_btn_text, text="▶")
                except Exception:
                    pass
        super().update_config(key, value)

    def toggle_preview(self):
        """切换预览状态"""
        if self._expanded:
            self._collapse_preview()
        else:
            self._expand_preview()
        self._expanded = not self._expanded
        try:
            self.canvas.itemconfig(self._toggle_btn_text,
                                   text="▼" if self._expanded else "▶")
        except Exception:
            pass

    def _expand_preview(self):
        """展开预览"""
        success = self._load_subtree_data()
        if success:
            self._draw_preview_nodes()
        else:
            self._draw_preview_placeholder()

    def _collapse_preview(self):
        """折叠预览"""
        for item_id in self._preview_items:
            try:
                self.canvas.delete(item_id)
            except Exception:
                pass
        self._preview_items.clear()
        try:
            self.canvas.delete(f"subtree_preview_{self.node_id}")
        except Exception:
            pass

    def _load_subtree_data(self):
        """加载子树数据"""
        import os
        if self._subtree_raw_data is not None:
            return True
        project_dir = self._resolve_subtree_path()
        if not project_dir or not os.path.isdir(project_dir):
            return False
        tree_file = self._find_tree_file(project_dir)
        if not tree_file or not os.path.exists(tree_file):
            return False
        try:
            self._subtree_raw_data = load_json(tree_file)
            return True
        except Exception:
            return False

    def _draw_preview_nodes(self):
        """绘制预览节点（只读缩略图），使用屏幕坐标"""
        if not self._subtree_raw_data:
            self._draw_preview_placeholder()
            return

        nodes_data = self._subtree_raw_data.get("nodes", {})
        root_id = self._subtree_raw_data.get("root_node")
        connections = self._subtree_raw_data.get("connections", [])

        if not nodes_data:
            self._draw_preview_placeholder()
            return

        positions = self._calc_preview_layout(nodes_data, root_id)

        if not positions:
            self._draw_preview_placeholder()
            return

        min_x = min(p[0] for p in positions.values())
        min_y = min(p[1] for p in positions.values())

        sx_base = self._transform_x(self.x)
        sy_base = self._transform_y(self.y)
        sh = self._scale(self.height)

        max_px = max(p[0] for p in positions.values())
        max_py = max(p[1] for p in positions.values())
        tree_center_x = (max_px + min_x) / 2

        offset_x = sx_base - self._scale(tree_center_x)
        offset_y = sy_base + sh / 2 + self._scale(self.PREVIEW_V_GAP) - self._scale(min_y)

        nw = self._scale(self.PREVIEW_NODE_WIDTH)
        nh = self._scale(self.PREVIEW_NODE_HEIGHT)
        preview_tag = f"subtree_preview_{self.node_id}"

        tree_width = max_px - min_x
        half_w = max(self._scale(self.width / 2), self._scale(tree_width / 2 + self.PREVIEW_PADDING + self.PREVIEW_NODE_WIDTH / 2))
        pad = self._scale(self.PREVIEW_PADDING)

        preview_bg_x1 = sx_base - half_w
        preview_bg_y1 = sy_base + sh / 2 + self._scale(self.PREVIEW_V_GAP / 2)
        preview_bg_x2 = sx_base + half_w
        preview_bg_y2 = offset_y + self._scale(max_py - min_y) + nh + pad

        bg_rect = self.canvas.create_rectangle(
            preview_bg_x1, preview_bg_y1, preview_bg_x2, preview_bg_y2,
            fill="#111827",
            outline="#8B5CF6",
            width=1,
            dash=(4, 4),
            tags=(preview_tag,)
        )
        self._preview_items.append(bg_rect)

        folder_name = self._get_folder_name()
        if folder_name:
            label = self.canvas.create_text(
                (preview_bg_x1 + preview_bg_x2) / 2,
                preview_bg_y1 + pad / 2 + self._scale(4),
                text=f"\U0001f4c1 {folder_name}",
                fill="#8B5CF6",
                font=("Microsoft YaHei", max(7, int(9 * self._zoom))),
                anchor="center",
                tags=(preview_tag,)
            )
            self._preview_items.append(label)

        preview_nodes = {}
        for nid, (nx, ny) in positions.items():
            node_info = nodes_data.get(nid, {})
            node_type = node_info.get("type", "Node")
            node_name = node_info.get("name", "") or node_type.replace("Node", "")

            px = self._scale(nx) + offset_x
            py = self._scale(ny) + offset_y

            cat = NODE_CATEGORY_MAP.get(node_type, "action")
            color_cfg = Theme.get_node_color(cat)

            rect = self.canvas.create_rectangle(
                px - nw / 2, py - nh / 2, px + nw / 2, py + nh / 2,
                fill=self._dark_colors['node_bg'],
                outline=color_cfg['bg'],
                width=1,
                tags=(preview_tag,)
            )
            self._preview_items.append(rect)

            bar = self.canvas.create_rectangle(
                px - nw / 2, py - nh / 2,
                px - nw / 2 + self._scale(3), py + nh / 2,
                fill=color_cfg['bg'],
                outline="",
                tags=(preview_tag,)
            )
            self._preview_items.append(bar)

            text = self.canvas.create_text(
                px, py,
                text=node_name[:8] + ("\u2026" if len(node_name) > 8 else ""),
                fill=self._dark_colors['text_primary'],
                font=("Microsoft YaHei", max(7, int(8 * self._zoom))),
                anchor="center",
                tags=(preview_tag,)
            )
            self._preview_items.append(text)

            preview_nodes[nid] = (px, py, nw, nh)

        for conn in connections:
            parent_id = conn.get("parent_id")
            child_id = conn.get("child_id")
            if parent_id in preview_nodes and child_id in preview_nodes:
                ppx, ppy, ppw, pph = preview_nodes[parent_id]
                cpx, cpy, cpw, cph = preview_nodes[child_id]

                start_x = ppx
                start_y = ppy + pph / 2
                end_x = cpx
                end_y = cpy - cph / 2
                mid_y = (start_y + end_y) / 2

                line = self.canvas.create_line(
                    start_x, start_y,
                    start_x, mid_y,
                    end_x, mid_y,
                    end_x, end_y,
                    fill=self._dark_colors.get('connection_line', '#666666'),
                    width=1,
                    smooth=True,
                    arrow=tk.LAST,
                    arrowshape=(6, 8, 3),
                    tags=(preview_tag,)
                )
                self._preview_items.append(line)

    def _draw_preview_placeholder(self):
        """绘制预览占位符（无数据时），使用屏幕坐标"""
        sx = self._transform_x(self.x)
        sy = self._transform_y(self.y)
        sw = self._scale(self.width)
        sh = self._scale(self.height)
        preview_tag = f"subtree_preview_{self.node_id}"

        bg_y1 = sy + sh / 2 + self._scale(5)
        bg_y2 = bg_y1 + self._scale(35)
        bg_x1 = sx - sw / 2
        bg_x2 = sx + sw / 2

        bg = self.canvas.create_rectangle(
            bg_x1, bg_y1, bg_x2, bg_y2,
            fill="#111827",
            outline="#8B5CF6",
            width=1,
            dash=(4, 4),
            tags=(preview_tag,)
        )
        self._preview_items.append(bg)

        text = self.canvas.create_text(
            sx, (bg_y1 + bg_y2) / 2,
            text="[!] 未配置子树路径",
            fill="#F59E0B",
            font=("Microsoft YaHei", max(8, int(9 * self._zoom))),
            anchor="center",
            tags=(preview_tag,)
        )
        self._preview_items.append(text)

    def _calc_preview_layout(self, nodes_data: dict, root_id: str) -> dict:
        """计算预览节点的布局位置"""
        if not root_id or root_id not in nodes_data:
            return {}

        children_map = {}
        for nid, ndata in nodes_data.items():
            children = ndata.get("children", [])
            child_ids = []
            for c in children:
                if isinstance(c, dict):
                    cid = c.get("id", "")
                else:
                    cid = c
                if cid:
                    child_ids.append(cid)
            if child_ids:
                children_map[nid] = child_ids
            if "child" in ndata:
                children_map.setdefault(nid, []).append(ndata["child"])

        positions = {}

        def subtree_width(nid):
            children = children_map.get(nid, [])
            if not children:
                return self.PREVIEW_NODE_WIDTH + self.PREVIEW_H_GAP
            return sum(subtree_width(c) for c in children)

        def layout(nid, x, y):
            positions[nid] = (x, y)
            children = children_map.get(nid, [])
            if children:
                total = sum(subtree_width(c) for c in children)
                cx = x - total / 2
                for child in children:
                    w = subtree_width(child)
                    layout(child, cx + w / 2, y + self.PREVIEW_NODE_HEIGHT + self.PREVIEW_V_GAP)
                    cx += w

        layout(root_id, 0, 0)
        return positions

    def is_readonly(self) -> bool:
        return self._is_readonly
