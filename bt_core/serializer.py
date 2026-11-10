import json
import os
from typing import Dict, Any
from datetime import datetime

from .nodes import Node
from .constants import ProjectConstants, get_app_version

# 向后兼容：保留旧常量名，但指向统一常量
CURRENT_VERSION = ProjectConstants.TREE_FORMAT_VERSION


class Serializer:
    """行为树序列化器

    支持将行为树序列化为JSON/YAML/TEXT格式，
    以及从这些格式反序列化重建行为树。
    支持保存和恢复编辑器状态和画布配置。
    """

    @staticmethod
    def serialize(root_node: Node, metadata: Dict[str, Any] = None,
                  canvas_state: Dict[str, Any] = None,
                  editor_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """序列化行为树为字典

        Args:
            root_node: 根节点
            metadata: 元数据
            canvas_state: 画布状态 (viewport/grid等)
            editor_state: 编辑器状态 (selected_node/clipboard等)

        Returns:
            字典表示
        """
        nodes = {}
        connections = []

        def collect_nodes(node: Node):
            node_dict = node.to_dict()
            # 路径规范化：JSON 中存储的相对路径强制使用正斜杠，保证跨平台一致
            Serializer._normalize_node_paths(node_dict)
            nodes[node.node_id] = node_dict
            for child in node.children:
                connections.append({
                    "parent_id": node.node_id,
                    "child_id": child.node_id
                })
                collect_nodes(child)

        if root_node:
            collect_nodes(root_node)

        result = {
            "version": ProjectConstants.TREE_FORMAT_VERSION,
            "format_type": ProjectConstants.TREE_FORMAT_TYPE,
            "metadata": metadata or {
                "created_at": datetime.now().isoformat(),
                "modified_at": datetime.now().isoformat(),
                "app_version": get_app_version(),
            },
            "canvas": canvas_state or {},
            "root_node": root_node.node_id if root_node else None,
            "nodes": nodes,
            "connections": connections,
        }

        if editor_state:
            result["editor_state"] = editor_state

        return result

    @staticmethod
    def _normalize_node_paths(node_dict: Dict[str, Any]) -> None:
        """对节点 config 中的资源路径字段强制使用正斜杠（跨平台一致性）。

        规范化规则：
        - 仅处理 ProjectConstants.RESOURCE_PATH_KEYS 中声明的字段
        - 仅当值为非空字符串时处理；其它类型（None/数字/list 等）保持原样
        - 将反斜杠（os.sep on Windows）替换为正斜杠 '/'
        - 不改变路径前缀（如 './'）和大小写

        就地修改 node_dict["config"]。

        Args:
            node_dict: node.to_dict() 返回的字典
        """
        config = node_dict.get("config")
        if not isinstance(config, dict):
            return
        for key in ProjectConstants.RESOURCE_PATH_KEYS:
            value = config.get(key)
            if isinstance(value, str) and value:
                # 仅替换反斜杠为正斜杠，保留 './' 等前缀
                normalized = value.replace('\\', '/')
                if normalized != value:
                    config[key] = normalized

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> tuple:
        """从字典反序列化行为树

        Args:
            data: 字典数据

        Returns:
            (根节点, canvas_state, editor_state) 元组
        """
        from .registry import NodeRegistry

        # format_type 校验（向后兼容：未知值仅记录警告，不报错）
        format_type = data.get("format_type")
        if format_type and format_type != ProjectConstants.TREE_FORMAT_TYPE:
            # 历史文件可能是 behavior_tree_editor / behavior_tree_standalone / behavior_tree_with_subtrees
            # 统一兼容，不阻断加载
            import warnings
            warnings.warn(
                f"tree.json format_type='{format_type}'，当前标准为"
                f"'{ProjectConstants.TREE_FORMAT_TYPE}'，将按兼容模式加载",
                stacklevel=2,
            )

        nodes_data = data.get("nodes", {})
        connections = data.get("connections", [])
        root_id = data.get("root_node")
        canvas_state = data.get("canvas", {})
        editor_state = data.get("editor_state", {})

        if not root_id or not nodes_data:
            return None, canvas_state, editor_state

        nodes = {}
        for node_id, node_data in nodes_data.items():
            node = NodeRegistry.create_node(node_data)
            if node:
                nodes[node_id] = node

        for conn in connections:
            parent_id = conn["parent_id"]
            child_id = conn["child_id"]

            if parent_id in nodes and child_id in nodes:
                nodes[parent_id].add_child(nodes[child_id])

        return nodes.get(root_id), canvas_state, editor_state

    @staticmethod
    def deserialize_node_only(data: Dict[str, Any]) -> Node:
        """仅反序列化节点（兼容旧接口）

        Args:
            data: 字典数据

        Returns:
            根节点
        """
        node, _, _ = Serializer.deserialize(data)
        return node

    @staticmethod
    def save_to_file(root_node: Node, filepath: str, format: str = "json",
                     canvas_state: Dict[str, Any] = None,
                     editor_state: Dict[str, Any] = None) -> None:
        """保存行为树到文件

        Args:
            root_node: 根节点
            filepath: 文件路径
            format: 文件格式 (json/yaml/txt)
            canvas_state: 画布状态
            editor_state: 编辑器状态
        """
        data = Serializer.serialize(root_node, canvas_state=canvas_state, editor_state=editor_state)

        if format == "json":
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif format in ("yaml", "yml"):
            try:
                import yaml
                with open(filepath, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            except ImportError:
                raise ImportError("PyYAML is required for YAML format")
        elif format in ("txt", "bt"):
            text = Serializer._to_text_format(root_node)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text)

    @staticmethod
    def load_from_file(filepath: str) -> tuple:
        """从文件加载行为树

        Args:
            filepath: 文件路径

        Returns:
            (根节点, canvas_state, editor_state) 元组
        """
        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".json":
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            return Serializer.deserialize(data)
        elif ext in (".yaml", ".yml"):
            try:
                import yaml
                with open(filepath, 'r', encoding='utf-8-sig') as f:
                    data = yaml.safe_load(f)
                return Serializer.deserialize(data)
            except ImportError:
                raise ImportError("PyYAML is required for YAML format")
        elif ext in (".txt", ".bt"):
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                text = f.read()
            node = Serializer._from_text_format(text)
            return node, {}, {}

        return None, {}, {}

    @staticmethod
    def load_node_from_file(filepath: str) -> Node:
        """仅加载节点（兼容旧接口）

        Args:
            filepath: 文件路径

        Returns:
            根节点
        """
        node, _, _ = Serializer.load_from_file(filepath)
        return node

    @staticmethod
    def _to_text_format(node: Node, indent: int = 0) -> str:
        """转换为文本格式

        Args:
            node: 节点
            indent: 缩进层级

        Returns:
            文本表示
        """
        lines = []
        prefix = "  " * indent
        lines.append(f"{prefix}{node.NODE_TYPE}: {node.config.name}")

        for child in node.children:
            lines.append(Serializer._to_text_format(child, indent + 1))

        return "\n".join(lines)

    @staticmethod
    def _from_text_format(text: str) -> Node:
        """从文本格式解析

        Args:
            text: 文本内容

        Returns:
            根节点
        """
        import re
        from .registry import NodeRegistry

        lines = text.strip().split('\n')
        if not lines:
            return None

        root = None
        parent_stack = []

        for line in lines:
            if not line.strip() or line.strip().startswith(';'):
                continue

            match = re.match(r'^(\s*)(\w+)(?:\s*:\s*(.*))?', line)
            if not match:
                continue

            indent = len(match.group(1)) // 2
            node_type = match.group(2).strip()
            name = match.group(3).strip() if match.group(3) else ""

            config = {}
            current_line = line.lstrip()

            if current_line.startswith(';'):
                rest = current_line[1:].strip()
                if ':' in rest:
                    key_part, value_part = rest.split(':', 1)
                    key = key_part.strip()
                    value = value_part.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.lower() in ('true', 'false'):
                        value = value.lower() == 'true'
                    elif value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
                        value = int(value)
                    elif value.replace('.', '', 1).isdigit():
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                    config[key] = value

            node_data = {
                "id": f"node_{len(parent_stack)}_{indent}",
                "type": node_type,
                "name": name,
                "config": config
            }

            node = NodeRegistry.create_node(node_data)
            if node is None:
                continue

            while len(parent_stack) > indent + 1:
                parent_stack.pop()

            if parent_stack:
                parent_stack[-1].add_child(node)

            else:
                root = node
                parent_stack.append(node)

        return root

    @staticmethod
    def serialize_with_subtrees(root_node: Node,
                                  project_root: str = None,
                                  metadata: Dict[str, Any] = None,
                                  canvas_state: Dict[str, Any] = None,
                                  editor_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """序列化行为树（包含子树引用元数据）"""
        data = Serializer.serialize(root_node, metadata, canvas_state, editor_state)
        # 统一 format_type / version，不再使用独立值
        data["version"] = ProjectConstants.TREE_FORMAT_VERSION
        data["format_type"] = ProjectConstants.TREE_FORMAT_TYPE

        subtree_refs = {}
        Serializer._collect_subtree_refs(root_node, subtree_refs, project_root or os.getcwd())

        if subtree_refs:
            data["subtree_references"] = subtree_refs

        return data

    @staticmethod
    def _collect_subtree_refs(node: Node, refs: Dict[str, Any], project_root: str) -> None:
        """递归收集子树引用信息"""
        subtree_path = node.config.get("subtree_path", "") if hasattr(node, 'config') else ""
        if subtree_path:
            resolved_path = subtree_path
            if not os.path.isabs(resolved_path):
                resolved_path = os.path.join(project_root, resolved_path)

            refs[node.node_id] = {
                # 序列化到 JSON 的 path 强制正斜杠（跨平台一致）
                "path": subtree_path.replace('\\', '/'),
                # resolved_path 为运行时绝对路径，保留 OS 原生分隔符供本地文件检查使用
                "resolved_path": os.path.normpath(os.path.abspath(resolved_path)),
                "node_count": Serializer._count_nodes_in_file(resolved_path) if os.path.exists(resolved_path) else 0
            }

        for child in getattr(node, 'children', []):
            Serializer._collect_subtree_refs(child, refs, project_root)

    @staticmethod
    def _count_nodes_in_file(filepath: str) -> int:
        """计算文件中的节点数量"""
        try:
            node, _, _ = Serializer.load_from_file(filepath)
            return Serializer._count_nodes(node)
        except Exception:
            return 0

    @staticmethod
    def _count_nodes(node: Node) -> int:
        """递归计算节点数量"""
        count = 1
        for child in getattr(node, 'children', []):
            count += Serializer._count_nodes(child)
        return count
