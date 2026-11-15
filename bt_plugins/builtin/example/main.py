"""示例插件 — 展示插件开发的基本模式，并提供一个可配置的问候节点"""

from bt_plugins.base import BasePlugin
from bt_core.nodes import ActionNode
from bt_core.status import NodeStatus
from bt_utils.log_manager import LogManager


class HelloNode(ActionNode):
    """示例节点 — 向黑板写入问候消息"""

    NODE_TYPE = "HelloNode"

    def _execute_action(self, context):
        name = self.config.get("name", "World")
        message = f"Hello, {name}!"
        context.blackboard.set("greeting", message)
        LogManager.instance().log_success(
            node_type="问候节点",
            node_name=self.name,
            message=message,
        )
        return NodeStatus.SUCCESS


class ExamplePlugin(BasePlugin):
    """示例插件"""

    def on_load(self):
        """加载时初始化"""
        self._loaded = True
        self.log("info", "示例插件已加载")

    def on_unload(self):
        """卸载时清理"""
        self._loaded = False
        self.log("info", "示例插件已卸载")

    def on_start(self):
        """启动时注册"""
        self._started = True
        self.log("info", "示例插件已启动")

    def on_stop(self):
        """停止时注销"""
        self._started = False
        self.log("info", "示例插件已停止")

    def get_nodes(self):
        return {
            "HelloNode": HelloNode,
        }

    def get_node_schemas(self):
        return {
            "HelloNode": [
                {"key": "name", "label": "名称", "type": "text", "default": "World"},
            ],
        }

    def get_node_display_info(self):
        return {
            "HelloNode": {
                "display_name": "问候节点",
                "description": "向黑板写入问候消息",
                "category": "plugin",
                "icon": "👋",
            },
        }
