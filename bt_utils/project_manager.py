import os
import json
import shutil
from datetime import datetime
from typing import Dict, Any
from bt_utils.path_resolver import PathResolver
from bt_utils.json_io import load_json
from bt_utils.resource_importer import ResourceImporter
from bt_core.constants import ProjectConstants, get_app_version

class ProjectManager:
    """项目管理器"""

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.path_resolver = PathResolver(project_root)
        self.resource_importer = ResourceImporter(project_root)

    # ===== 项目名解析统一入口（SSOT）=====

    @staticmethod
    def resolve_project_name(project_root: str) -> str:
        """项目名解析的唯一入口（SSOT）。

        权威源：文件夹名（os.path.basename(project_root)）。
        所有调用方必须使用此方法，禁止直接 os.path.basename。

        Args:
            project_root: 项目根目录绝对路径

        Returns:
            项目名（文件夹名），无路径时返回 "未命名"
        """
        if not project_root:
            return "未命名"
        basename = os.path.basename(project_root.rstrip(os.sep))
        return basename if basename else "未命名"

    @staticmethod
    def read_project_info_name(project_root: str) -> str:
        """读取 project.json 中存储的 project_info.name（仅用于一致性校验）。

        Args:
            project_root: 项目根目录绝对路径

        Returns:
            project_info.name 字符串；文件不存在或读取失败返回空串
        """
        meta_path = os.path.join(project_root, ProjectConstants.PROJECT_META_FILE)
        if os.path.exists(meta_path):
            try:
                meta = load_json(meta_path)
                return meta.get("project_info", {}).get("name", "").strip()
            except (ValueError, OSError):
                pass
        return ""

    @staticmethod
    def read_project_info(project_root: str) -> dict:
        """读取 project.json 中存储的完整 project_info。

        Args:
            project_root: 项目根目录绝对路径

        Returns:
            project_info 字典；文件不存在或读取失败返回空字典
        """
        meta_path = os.path.join(project_root, ProjectConstants.PROJECT_META_FILE)
        if os.path.exists(meta_path):
            try:
                meta = load_json(meta_path)
                return meta.get("project_info", {})
            except (ValueError, OSError):
                pass
        return {}

    @staticmethod
    def check_name_consistency(project_root: str) -> Dict[str, Any]:
        """检查文件夹名与 project_info.name 是否一致。

        Args:
            project_root: 项目根目录绝对路径

        Returns:
            dict: {
                "consistent": bool,         # 是否一致（info_name 为空视为一致）
                "folder_name": str,         # 文件夹名（权威源）
                "project_info_name": str,   # project.json 中的 name
            }
        """
        folder_name = ProjectManager.resolve_project_name(project_root)
        info_name = ProjectManager.read_project_info_name(project_root)
        return {
            "consistent": (not info_name) or (info_name == folder_name),
            "folder_name": folder_name,
            "project_info_name": info_name,
        }

    @staticmethod
    def update_project_info_name(project_root: str, new_name: str) -> bool:
        """更新 project.json 中的 project_info.name（不动文件夹名）。

        供 Tab 双击重命名和一致性同步使用。

        Args:
            project_root: 项目根目录绝对路径
            new_name: 新的项目显示名

        Returns:
            是否更新成功
        """
        meta_path = os.path.join(project_root, ProjectConstants.PROJECT_META_FILE)
        if not os.path.exists(meta_path):
            return False
        try:
            meta = load_json(meta_path)
            if "project_info" not in meta:
                meta["project_info"] = {}
            meta["project_info"]["name"] = new_name
            meta["project_info"]["modified_at"] = datetime.now().isoformat()
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
            return True
        except (ValueError, OSError):
            return False

    def create_project(self, name: str, description: str = "") -> None:
        """
        创建新项目

        Args:
            name: 项目名称
            description: 项目描述
        """
        os.makedirs(self.project_root, exist_ok=True)

        for dir_path in ProjectConstants.PROJECT_INIT_DIRS:
            os.makedirs(os.path.join(self.project_root, dir_path), exist_ok=True)

        project_config = {
            "version": ProjectConstants.PROJECT_FORMAT_VERSION,
            "format_type": ProjectConstants.PROJECT_FORMAT_TYPE,
            "project_info": {
                "name": name,
                "description": description,
                "author": "",
                "created_at": datetime.now().isoformat(),
                "modified_at": datetime.now().isoformat(),
                "app_version": get_app_version()
            },
            "main_tree": ProjectConstants.MAIN_TREE_FILE,
        }

        with open(os.path.join(self.project_root, ProjectConstants.PROJECT_META_FILE), 'w', encoding='utf-8') as f:
            json.dump(project_config, f, indent=2, ensure_ascii=False)

        tree_data = {
            "version": ProjectConstants.TREE_FORMAT_VERSION,
            "format_type": ProjectConstants.TREE_FORMAT_TYPE,
            "root_node": None,
            "nodes": {},
            "connections": []
        }

        with open(os.path.join(self.project_root, ProjectConstants.MAIN_TREE_FILE), 'w', encoding='utf-8') as f:
            json.dump(tree_data, f, indent=2, ensure_ascii=False)
    
    def load_project(self) -> Dict[str, Any]:
        """
        加载项目配置

        Returns:
            项目配置字典
        """
        project_file = os.path.join(self.project_root, ProjectConstants.PROJECT_META_FILE)

        if not os.path.exists(project_file):
            raise FileNotFoundError(f"项目配置文件不存在: {project_file}")

        return load_json(project_file)

    def save_project(self, tree_data: Dict[str, Any]) -> None:
        """
        保存项目

        Args:
            tree_data: 行为树数据
        """
        tree_file = os.path.join(self.project_root, ProjectConstants.MAIN_TREE_FILE)

        self._create_backup()

        with open(tree_file, 'w', encoding='utf-8') as f:
            json.dump(tree_data, f, indent=2, ensure_ascii=False)

        project_config = self.load_project()
        project_config["project_info"]["modified_at"] = datetime.now().isoformat()

        with open(os.path.join(self.project_root, ProjectConstants.PROJECT_META_FILE), 'w', encoding='utf-8') as f:
            json.dump(project_config, f, indent=2, ensure_ascii=False)

    def validate_project(self) -> bool:
        """
        验证项目完整性

        Returns:
            项目是否有效
        """
        required_files = [ProjectConstants.PROJECT_META_FILE, ProjectConstants.MAIN_TREE_FILE]

        for filename in required_files:
            if not os.path.exists(os.path.join(self.project_root, filename)):
                return False

        return True

    def _create_backup(self) -> None:
        """创建备份文件"""
        tree_file = os.path.join(self.project_root, ProjectConstants.MAIN_TREE_FILE)
        
        if not os.path.exists(tree_file):
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(
            self.project_root,
            f"tree_backup_{timestamp}.json"
        )
        
        shutil.copy2(tree_file, backup_file)
        
        self._clean_old_backups()
    
    def _clean_old_backups(self, keep_count: int = 5) -> None:
        """清理旧备份文件"""
        backup_files = []
        
        for filename in os.listdir(self.project_root):
            if filename.startswith("tree_backup_") and filename.endswith(".json"):
                backup_files.append(os.path.join(self.project_root, filename))
        
        backup_files.sort(key=os.path.getmtime, reverse=True)
        
        for old_backup in backup_files[keep_count:]:
            os.remove(old_backup)
