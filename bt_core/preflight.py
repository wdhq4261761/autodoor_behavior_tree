"""运行前静态预检

在不依赖 GUI 的前提下，对树数据（JSON 反序列化后的 dict）做纯函数校验，
在节点注册（含插件）完成后调用，尽早暴露会导致运行失败的问题。
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .registry import NodeRegistry

# 节点类型 -> (config 中的资源路径键, 资源中文描述)
_RESOURCE_KEYS: Dict[str, tuple] = {
    "ImageConditionNode": ("template_path", "模板图片"),
    "SubtreeNode": ("subtree_path", "子树文件"),
    "ScriptNode": ("script_path", "脚本文件"),
    "TextInputNode": ("file_path", "输入文件"),
}


@dataclass(frozen=True)
class PreflightIssue:
    """单条预检问题"""

    level: str
    code: str
    message: str
    node_id: Optional[str] = None


@dataclass
class PreflightReport:
    """预检结果"""

    issues: List[PreflightIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.level == "error" for issue in self.issues)

    def add(self, level: str, code: str, message: str,
            node_id: Optional[str] = None) -> None:
        self.issues.append(PreflightIssue(
            level=level, code=code, message=message, node_id=node_id,
        ))

    def format_lines(self) -> List[str]:
        lines = []
        for issue in self.issues:
            prefix = "[错误]" if issue.level == "error" else "[警告]"
            line = f"{prefix} {issue.message}"
            if issue.node_id:
                line += f"（节点 {issue.node_id}）"
            lines.append(line)
        return lines


def _resolve_resource_path(path: str, project_root: Optional[str]) -> str:
    """按约定解析资源路径"""
    if path.startswith("./") and project_root:
        return os.path.normpath(os.path.join(project_root, path))
    if os.path.isabs(path):
        return path
    if project_root:
        return os.path.normpath(os.path.join(project_root, path))
    return os.path.abspath(path)


def validate_tree_data(tree_data: Any,
                       project_root: Optional[str] = None) -> PreflightReport:
    """校验树数据，返回预检报告

    Args:
        tree_data: 树数据字典（nodes/connections/root_node）
        project_root: 项目根目录，用于解析相对资源路径

    Returns:
        PreflightReport
    """
    report = PreflightReport()

    if not isinstance(tree_data, dict):
        report.add("error", "EMPTY_TREE", "树数据为空，无法运行")
        return report

    nodes = tree_data.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        report.add("error", "EMPTY_TREE", "树中没有节点，无法运行")
        return report

    root_id = tree_data.get("root_node")
    if not root_id or root_id not in nodes:
        report.add("error", "ROOT_MISSING", f"根节点无效: {root_id}", node_id=root_id)
        return report

    connections = tree_data.get("connections")
    if not isinstance(connections, list):
        connections = []

    children: Dict[str, List[str]] = {node_id: [] for node_id in nodes}
    parent_counts: Dict[str, int] = {node_id: 0 for node_id in nodes}

    for conn in connections:
        if not isinstance(conn, dict):
            report.add("error", "BAD_CONNECTION", "连线数据格式无效")
            continue
        parent_id = conn.get("parent_id")
        child_id = conn.get("child_id")
        if parent_id not in nodes or child_id not in nodes:
            node_id = parent_id if parent_id in nodes else child_id
            report.add(
                "error", "BAD_CONNECTION",
                f"连线引用了不存在的节点: {parent_id} -> {child_id}",
                node_id=node_id if node_id in nodes else None,
            )
            continue
        children[parent_id].append(child_id)
        parent_counts[child_id] += 1

    for node_id, count in parent_counts.items():
        if count > 1:
            report.add(
                "error", "MULTI_PARENT",
                f"节点被 {count} 个父节点引用",
                node_id=node_id,
            )

    for node_id, node_data in nodes.items():
        node_type = node_data.get("type") if isinstance(node_data, dict) else None
        if not node_type or NodeRegistry.get(node_type) is None:
            report.add(
                "error", "UNKNOWN_NODE_TYPE",
                f"未知节点类型: {node_type or '（缺失）'}",
                node_id=node_id,
            )
            continue

        resource_spec = _RESOURCE_KEYS.get(node_type)
        if not resource_spec:
            continue
        path_key, label = resource_spec

        config = node_data.get("config")
        if not isinstance(config, dict):
            config = {}
        path = config.get(path_key, "")
        if not isinstance(path, str) or not path.strip():
            report.add(
                "warning", "EMPTY_RESOURCE",
                f"未配置{label}路径",
                node_id=node_id,
            )
            continue
        if not os.path.exists(_resolve_resource_path(path, project_root)):
            report.add(
                "error", "MISSING_RESOURCE",
                f"{label}不存在: {path}",
                node_id=node_id,
            )

    _check_cycles(nodes, children, report)
    _check_reachable(root_id, nodes, children, report)

    return report


def _check_cycles(nodes: Dict[str, Any], children: Dict[str, List[str]],
                  report: PreflightReport) -> None:
    """三色 DFS 检测环"""
    white, gray, black = 0, 1, 2
    colors = {node_id: white for node_id in nodes}
    path: List[str] = []

    def dfs(node_id: str) -> bool:
        colors[node_id] = gray
        path.append(node_id)
        for child_id in children.get(node_id, []):
            if colors[child_id] == gray:
                start = path.index(child_id)
                cycle = " -> ".join(path[start:] + [child_id])
                report.add("error", "CYCLE", f"检测到循环引用: {cycle}", node_id=child_id)
                return True
            if colors[child_id] == white and dfs(child_id):
                return True
        path.pop()
        colors[node_id] = black
        return False

    for node_id in nodes:
        if colors[node_id] == white and dfs(node_id):
            return


def _check_reachable(root_id: str, nodes: Dict[str, Any],
                     children: Dict[str, List[str]],
                     report: PreflightReport) -> None:
    """从根节点出发检查可达性"""
    reachable = set()
    stack = [root_id]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(children.get(node_id, []))

    for node_id in nodes:
        if node_id not in reachable:
            report.add(
                "warning", "UNREACHABLE",
                "节点从根节点不可达",
                node_id=node_id,
            )
