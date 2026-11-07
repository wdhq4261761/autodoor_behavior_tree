# plugins/uia_bridge/main.py
"""UIA 控件桥插件入口"""
from bt_plugins.base import BasePlugin
from plugins.uia_bridge.nodes import UIASampleNode, UIAStateNode


class UIABridgePlugin(BasePlugin):
    """UIA 控件桥插件"""

    def on_load(self):
        self._loaded = True
        self.log("info", "UIA 控件桥插件已加载")

    def on_unload(self):
        self._loaded = False
        self.log("info", "UIA 控件桥插件已卸载")

    def on_start(self):
        self._started = True
        self.log("info", "UIA 控件桥插件已启动")

    def on_stop(self):
        self._started = False
        self.log("info", "UIA 控件桥插件已停止")

    def get_nodes(self):
        return {
            "UIASampleNode": UIASampleNode,
            "UIAStateNode": UIAStateNode,
        }

    def get_node_schemas(self):
        locate = [
            {"key": "hwnd", "label": "窗口句柄（优先，0 表示按标题查找）",
             "type": "number", "default": 0},
            {"key": "window_title", "label": "窗口标题（hwnd 为 0 时使用）",
             "type": "text", "default": ""},
            {"key": "window_class", "label": "窗口类名（hwnd 为 0 时使用）",
             "type": "text", "default": ""},
            {"key": "control_name", "label": "控件名称（Text）",
             "type": "text", "default": ""},
            {"key": "control_type", "label": "控件类型（Button/Edit/Text…）",
             "type": "text", "default": ""},
            {"key": "name_mode", "label": "名称匹配方式",
             "type": "select", "default": "exact",
             "options": ["exact", "contains", "regex"]},
            {"key": "nth", "label": "取第几个匹配项（从 0 开始）",
             "type": "number", "default": 0},
            {"key": "max_nodes", "label": "单次遍历控件数上限",
             "type": "number", "default": 3000},
        ]

        return {
            "UIASampleNode": locate + [
                {"key": "output_mode", "label": "输出坐标类型",
                 "type": "select", "default": "client",
                 "options": ["client", "screen"]},
                {"key": "position_key", "label": "坐标写入的黑板键（留空不写）",
                 "type": "text", "default": ""},
                {"key": "write_scalar", "label": "同时写 last_detection_x/y",
                 "type": "bool", "default": False},
                {"key": "write_manifest", "label": "写入 assets/manifest.json",
                 "type": "bool", "default": False},
                {"key": "manifest_path", "label": "manifest 路径",
                 "type": "text", "default": "assets/manifest.json"},
                {"key": "asset_name", "label": "素材名（留空用控件名）",
                 "type": "text", "default": ""},
                {"key": "semantic", "label": "语义说明",
                 "type": "text", "default": ""},
                {"key": "project", "label": "项目根目录",
                 "type": "text", "default": "."},
            ],
            "UIAStateNode": locate + [
                {"key": "expect", "label": "断言内容",
                 "type": "select", "default": "exists",
                 "options": ["exists", "enabled", "disabled", "visible"]},
            ],
        }

    def get_node_display_info(self):
        return {
            "UIASampleNode": {
                "display_name": "UIA 采样",
                "description": "枚举控件树，取控件矩形并输出屏幕/客户区相对坐标；"
                               "制作期跑一次即可，运行期不要高频调用",
                "category": "plugin",
                "icon": "🧭",
            },
            "UIAStateNode": {
                "display_name": "UIA 状态检查",
                "description": "判断控件是否存在/启用/禁用/可见，如确认按钮已可点击",
                "category": "plugin",
                "icon": "🔍",
            },
        }
