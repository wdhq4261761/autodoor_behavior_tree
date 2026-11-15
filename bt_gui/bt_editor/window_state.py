"""把运行期节点产生的窗口状态同步回画布节点配置。

StartNode 在首次绑定窗口时把 ``window_size`` / ``window_maximized`` 写入运行期
配置；运行期树是反序列化出来的副本，必须回写到画布节点，保存工程后才能跨会话
生效。否则每次运行都会重新“首次记录”，永远无法触发尺寸还原。
"""
from typing import Any, Dict, List

WINDOW_STATE_KEYS = ("window_size", "window_maximized")


def collect_window_state(root_node) -> Dict[str, Dict[str, Any]]:
    """遍历运行期树，收集带有窗口状态键的节点配置。"""
    result: Dict[str, Dict[str, Any]] = {}
    stack = [root_node]
    seen = set()
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        config = getattr(node, "config", None)
        if config is not None:
            values = {key: config.get(key) for key in WINDOW_STATE_KEYS if key in config}
            node_id = getattr(node, "node_id", "")
            if values and node_id:
                result[node_id] = values
        stack.extend(getattr(node, "children", None) or [])
    return result


def apply_window_state(root_node, canvas_nodes) -> List[str]:
    """把运行期窗口状态写入画布节点配置，返回发生变化的节点 id。"""
    changed: List[str] = []
    for node_id, values in collect_window_state(root_node).items():
        target = canvas_nodes.get(node_id) if hasattr(canvas_nodes, "get") else None
        if target is None:
            continue
        target_config = getattr(target, "config", None)
        if not isinstance(target_config, dict):
            continue
        diff = False
        for key, value in values.items():
            if target_config.get(key) != value:
                target_config[key] = value
                diff = True
        if diff:
            changed.append(node_id)
    return changed
