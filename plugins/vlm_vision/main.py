# plugins/vlm_vision/main.py
"""VLM 语义视觉插件入口"""
from bt_plugins.base import BasePlugin
from plugins.vlm_vision.nodes import (
    VLMAssertNode,
    VLMLocateNode,
    VLMReadNode,
    clear_cache,
)


class VLMVisionPlugin(BasePlugin):
    """VLM 语义视觉插件"""

    def on_load(self):
        self._loaded = True
        self.log("info", "VLM 语义视觉插件已加载")

    def on_unload(self):
        self._loaded = False
        clear_cache()
        self.log("info", "VLM 语义视觉插件已卸载")

    def on_start(self):
        self._started = True
        clear_cache()
        self.log("info", "VLM 语义视觉插件已启动（缓存已重置）")

    def on_stop(self):
        self._started = False
        self.log("info", "VLM 语义视觉插件已停止")

    def get_nodes(self):
        return {
            "VLMLocateNode": VLMLocateNode,
            "VLMAssertNode": VLMAssertNode,
            "VLMReadNode": VLMReadNode,
        }

    def get_node_schemas(self):
        return {
            "VLMLocateNode": [
                {"key": "question", "label": "要定位什么（自然语言）",
                 "type": "text", "default": "画面中的红色圆环靶心"},
                {"key": "region", "label": "检测区域 x1,y1,x2,y2（留空为全屏）",
                 "type": "text", "default": ""},
                {"key": "coord_mode", "label": "坐标模式",
                 "type": "select", "default": "abs",
                 "options": ["abs", "norm1000", "ratio"]},
                {"key": "confidence_min", "label": "最低置信度",
                 "type": "number", "default": 0.6},
                {"key": "cache_ttl_ms", "label": "缓存有效期(ms)，0 不缓存",
                 "type": "number", "default": 2000},
                {"key": "max_calls_per_run", "label": "单次运行调用上限(0=不限)",
                 "type": "number", "default": 10},
                {"key": "timeout_ms", "label": "请求超时(ms)",
                 "type": "number", "default": 15000},
                {"key": "retry", "label": "解析失败重试次数",
                 "type": "number", "default": 1},
                {"key": "fallback_color", "label": "兜底颜色 #RRGGBB（留空则失败）",
                 "type": "text", "default": ""},
                {"key": "position_key", "label": "坐标写入的黑板键",
                 "type": "text", "default": "last_detection_position"},
                {"key": "base_url", "label": "VLM 端点（留空用全局配置）",
                 "type": "text", "default": ""},
                {"key": "api_key", "label": "VLM 密钥（留空用全局配置）",
                 "type": "text", "default": ""},
                {"key": "model", "label": "VLM 模型名（留空用全局配置）",
                 "type": "text", "default": ""},
            ],
            "VLMAssertNode": [
                {"key": "question", "label": "断言问题（是非问答）",
                 "type": "text", "default": "画面中是否出现错误提示弹窗"},
                {"key": "expect", "label": "期望结果",
                 "type": "select", "default": "yes", "options": ["yes", "no"]},
                {"key": "region", "label": "检测区域 x1,y1,x2,y2",
                 "type": "text", "default": ""},
                {"key": "confidence_min", "label": "最低置信度",
                 "type": "number", "default": 0.0},
                {"key": "cache_ttl_ms", "label": "缓存有效期(ms)",
                 "type": "number", "default": 2000},
                {"key": "max_calls_per_run", "label": "单次运行调用上限(0=不限)",
                 "type": "number", "default": 10},
                {"key": "timeout_ms", "label": "请求超时(ms)",
                 "type": "number", "default": 15000},
                {"key": "base_url", "label": "VLM 端点（留空用全局配置）",
                 "type": "text", "default": ""},
                {"key": "api_key", "label": "VLM 密钥（留空用全局配置）",
                 "type": "text", "default": ""},
                {"key": "model", "label": "VLM 模型名（留空用全局配置）",
                 "type": "text", "default": ""},
            ],
            "VLMReadNode": [
                {"key": "question", "label": "要读取什么",
                 "type": "text", "default": "画面左上角显示的得分数字"},
                {"key": "region", "label": "读取区域 x1,y1,x2,y2",
                 "type": "text", "default": ""},
                {"key": "write_to", "label": "写入的黑板变量名",
                 "type": "text", "default": "vlm_text"},
                {"key": "cache_ttl_ms", "label": "缓存有效期(ms)",
                 "type": "number", "default": 1000},
                {"key": "max_calls_per_run", "label": "单次运行调用上限(0=不限)",
                 "type": "number", "default": 10},
                {"key": "timeout_ms", "label": "请求超时(ms)",
                 "type": "number", "default": 15000},
                {"key": "base_url", "label": "VLM 端点（留空用全局配置）",
                 "type": "text", "default": ""},
                {"key": "api_key", "label": "VLM 密钥（留空用全局配置）",
                 "type": "text", "default": ""},
                {"key": "model", "label": "VLM 模型名（留空用全局配置）",
                 "type": "text", "default": ""},
            ],
        }

    def get_node_display_info(self):
        return {
            "VLMLocateNode": {
                "display_name": "VLM 定位",
                "description": "用自然语言描述目标，由多模态模型给出坐标并写黑板；"
                               "带缓存、预算闸与颜色兜底",
                "category": "plugin",
                "icon": "🎯",
            },
            "VLMAssertNode": {
                "display_name": "VLM 断言",
                "description": "语义是非判断（如是否出现错误弹窗），适合状态迁移点",
                "category": "plugin",
                "icon": "❓",
            },
            "VLMReadNode": {
                "display_name": "VLM 读取",
                "description": "读取画面中的字段文本并写入黑板变量",
                "category": "plugin",
                "icon": "📖",
            },
        }
