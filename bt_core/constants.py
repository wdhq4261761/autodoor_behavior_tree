"""项目命名与路径的统一常量定义。

本模块是项目命名与资源目录的单一权威源（SSOT），所有相关常量必须在此定义，
其它模块禁止硬编码这些字符串，必须引用本模块的常量。

设计原则：
- 文件夹名为项目名的唯一权威源
- 客户端永不修改文件夹名
- project_info.name 作为元数据，与文件夹名保持一致
"""

import os
import json

from bt_utils.json_io import load_json


class ProjectConstants:
    """项目命名与路径的单一权威源常量类。

    所有常量均为类属性，禁止在运行时修改。
    """

    # ===== 资源目录常量（消除 3 处硬编码：project_manager / resource_service / resource_importer）=====
    RESOURCE_DIRS = {
        'image':      'images/templates',
        'script':     'scripts/script',
        'code':       'scripts/code',
        'audio':      'audio/alarms',
        'data':       'data/config',
        'subtree':    'subtrees',
        'other':      'data/other',
        'screenshot': 'images/screenshots',
        'cache':      'cache',
        'docs':       'docs',
    }

    # ===== 项目初始目录结构（create_project 时按此创建子目录）=====
    PROJECT_INIT_DIRS = [
        'images/templates',
        'images/screenshots',
        'scripts/script',
        'scripts/code',
        'audio/alarms',
        'data/config',
        'cache',
        'docs',
    ]

    # ===== 文件名常量 =====
    PROJECT_META_FILE = 'project.json'
    MAIN_TREE_FILE = 'tree.json'          # 默认主树文件名

    # ===== 格式版本常量（消除三值不一致：behavior_tree_editor / behavior_tree_standalone / behavior_tree_with_subtrees）=====
    PROJECT_FORMAT_TYPE = 'behavior_tree_project'
    PROJECT_FORMAT_VERSION = '1.0'

    TREE_FORMAT_TYPE = 'behavior_tree'    # 统一为一个值
    TREE_FORMAT_VERSION = '2.1'           # 统一为最高版本

    # ===== 资源路径字段名（节点 config 中存储相对路径的 key，序列化时强制正斜杠）=====
    # 顺序与 RESOURCE_DIRS 中的资源类型一一对应（subtype 仅用于映射，不在此列表）
    RESOURCE_PATH_KEYS = (
        'template_path',   # image
        'script_path',     # script
        'code_path',       # code
        'sound_path',      # audio
        'file_path',       # data
        'subtree_path',    # subtree
    )

    # ===== 路径分隔符（跨平台，JSON 中存储统一用正斜杠）=====
    PATH_SEPARATOR = '/'


def get_app_version() -> str:
    """获取应用版本号。

    从 bt_utils/build_info.json 读取，避免导入 main.py 触发的副作用（DPI 初始化等）。
    失败时回退到默认版本。

    Returns:
        版本号字符串，如 "1.2.2a"
    """
    # 优先从 build_info.json 读取
    build_info_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'bt_utils', 'build_info.json'
    )
    if os.path.exists(build_info_path):
        try:
            build_info = load_json(build_info_path)
            version = build_info.get('version', '').strip()
            if version:
                return version
        except (ValueError, OSError):
            pass
    return '1.0.0'
