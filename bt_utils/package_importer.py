import os
import zipfile
import shutil
from typing import Optional, Tuple
from datetime import datetime


class PackageImporter:
    """项目导入器"""
    
    REQUIRED_FILES = ["project.json", "tree.json"]
    
    def __init__(self):
        pass
    
    def validate_package(self, zip_path: str) -> Tuple[bool, str]:
        """验证 ZIP 文件是否为有效的项目压缩包
        
        Args:
            zip_path: ZIP 文件路径
            
        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        if not os.path.exists(zip_path):
            return False, "文件不存在"
        
        if not zipfile.is_zipfile(zip_path):
            return False, "不是有效的 ZIP 文件"
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                namelist = zipf.namelist()
                
                if not namelist:
                    return False, "ZIP 文件为空"
                
                found_project_json = False
                found_tree_json = False
                
                for name in namelist:
                    normalized = os.path.normpath(name)
                    if normalized.startswith('..') or os.path.isabs(normalized):
                        return False, "ZIP 包含路径遍历条目，可能是恶意文件"
                    
                    basename = os.path.basename(name)
                    if basename == "project.json":
                        found_project_json = True
                    elif basename == "tree.json":
                        found_tree_json = True
                
                if not found_project_json:
                    return False, "缺少 project.json 文件"
                
                if not found_tree_json:
                    return False, "缺少 tree.json 文件"
                
                return True, ""
                
        except zipfile.BadZipFile:
            return False, "ZIP 文件已损坏"
        except Exception as e:
            return False, f"读取 ZIP 文件失败: {str(e)}"
    
    def get_project_name(self, zip_path: str) -> Optional[str]:
        """从 ZIP 文件中获取项目名称

        优先级（统一回退策略）：
            1. ZIP 内 project.json 的 project_info.name
            2. ZIP 文件名去扩展名

        注意：不再使用"第一个条目的顶级目录名"作为优先来源，
        因为导出时该目录名 = 项目文件夹名，可能与 project_info.name 不一致。
        导入后实际文件夹名以此返回值为准，并强制写入 project_info.name。

        Args:
            zip_path: ZIP 文件路径

        Returns:
            项目名称，如果无法获取则返回 None
        """
        try:
            import json
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                # 1. 优先读 ZIP 内 project.json 的 project_info.name
                for name in zipf.namelist():
                    basename = os.path.basename(name)
                    if basename == "project.json":
                        try:
                            with zipf.open(name) as f:
                                project_config = json.loads(f.read().decode("utf-8-sig"))
                                project_info = project_config.get("project_info", {})
                                name_val = project_info.get("name", "").strip()
                                if name_val:
                                    return name_val
                        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                            pass
                        break

                # 2. 回退到 ZIP 文件名去扩展名
                return os.path.splitext(os.path.basename(zip_path))[0] or None

        except Exception:
            return None
    
    def get_project_root_in_zip(self, zip_path: str) -> Optional[str]:
        """获取 ZIP 内项目的根目录路径
        
        Args:
            zip_path: ZIP 文件路径
            
        Returns:
            ZIP 内项目根目录的路径前缀
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                namelist = zipf.namelist()
                
                if not namelist:
                    return None
                
                for name in namelist:
                    if name.endswith("project.json"):
                        parts = name.rsplit("/", 1)
                        if len(parts) > 1:
                            return parts[0]
                        return ""
                
                return None
                
        except Exception:
            return None
    
    def import_from_zip(
        self, 
        zip_path: str, 
        target_dir: str,
        overwrite: bool = False,
        new_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """从 ZIP 文件导入项目
        
        Args:
            zip_path: ZIP 文件路径
            target_dir: 目标目录
            overwrite: 是否覆盖已存在的项目
            new_name: 新项目名称（用于重命名）
            
        Returns:
            Tuple[bool, str, Optional[str]]: (是否成功, 错误信息, 导入后的项目路径)
        """
        is_valid, error_msg = self.validate_package(zip_path)
        if not is_valid:
            return False, error_msg, None
        
        project_name = new_name or self.get_project_name(zip_path)
        if not project_name:
            project_name = os.path.splitext(os.path.basename(zip_path))[0]
        
        project_root = os.path.join(target_dir, project_name)
        
        if os.path.exists(project_root) and not overwrite:
            return False, "PROJECT_EXISTS", project_root
        
        try:
            os.makedirs(target_dir, exist_ok=True)
            
            if os.path.exists(project_root):
                shutil.rmtree(project_root)
            
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zip_root = self.get_project_root_in_zip(zip_path)

                for member in zipf.namelist():
                    if zip_root:
                        if not member.startswith(zip_root + "/") and member != zip_root + "/":
                            continue
                        relative_path = member[len(zip_root) + 1:]
                    else:
                        relative_path = member

                    if not relative_path or relative_path.endswith("/"):
                        continue

                    target_path = os.path.normpath(os.path.join(project_root, relative_path))

                    normalized_root = os.path.normpath(project_root)
                    if not (target_path.startswith(normalized_root + os.sep) or
                            target_path == normalized_root):
                        continue

                    os.makedirs(os.path.dirname(target_path), exist_ok=True)

                    with zipf.open(member) as source, open(target_path, 'wb') as target:
                        target.write(source.read())

            # 强制同步 project_info.name = 实际新文件夹名（处理冲突后缀的情况）
            # 确保导入后 project_info.name 与文件夹名一致，避免后续校验弹窗
            from bt_utils.project_manager import ProjectManager
            ProjectManager.update_project_info_name(project_root, project_name)

            return True, "", project_root
            
        except Exception as e:
            return False, f"解压失败: {str(e)}", None
    
    def generate_new_name(self, base_name: str, target_dir: str) -> str:
        """生成不冲突的新项目名称
        
        Args:
            base_name: 基础名称
            target_dir: 目标目录
            
        Returns:
            新的项目名称
        """
        if not os.path.exists(os.path.join(target_dir, base_name)):
            return base_name
        
        counter = 1
        while True:
            new_name = f"{base_name}_{counter}"
            if not os.path.exists(os.path.join(target_dir, new_name)):
                return new_name
            counter += 1
            
            if counter > 1000:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                return f"{base_name}_{timestamp}"
