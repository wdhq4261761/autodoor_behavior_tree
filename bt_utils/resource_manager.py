import os
import sys
from bt_utils.singleton import singleton


def get_app_root() -> str:
    """获取应用根目录
    
    兼容开发环境和打包后的环境
    
    Returns:
        应用根目录路径
    """
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径
    
    兼容开发环境和打包后的环境
    
    Args:
        relative_path: 相对于项目根目录的路径
        
    Returns:
        资源文件的绝对路径
    """
    app_root = get_app_root()
    return os.path.join(app_root, relative_path)


def get_app_home() -> str:
    """获取应用主目录（可写区域）

    与 get_app_root() 的区别：
    - get_app_root() 在打包后指向 _internal，是随包分发的只读安装内容；
    - 本函数在打包后指向 exe 所在目录，适合放用户可编辑的内容（插件、配置、素材）。

    若不区分这两者，打包版把插件写进 _internal，用户既看不到也改不了，
    且升级覆盖安装时会被清空。

    Returns:
        应用主目录
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_builtin_plugins_dir() -> str:
    """内置插件目录（随包分发，只读）"""
    return os.path.join(get_app_root(), "bt_plugins", "builtin")


def get_user_plugin_dir() -> str:
    """用户插件目录（可写）

    解析顺序：
    1. 环境变量 AUTODOOR_PLUGINS_DIR（便于多实例 / CI 隔离）
    2. 应用主目录下的 plugins/

    打包版务必落在 exe 同级，而不是依赖 os.getcwd()——
    用户从任意目录双击或通过快捷方式启动时，cwd 并非 exe 所在目录，
    用 cwd 会导致插件「莫名消失」。
    """
    env_dir = os.environ.get("AUTODOOR_PLUGINS_DIR")
    if env_dir:
        return os.path.abspath(env_dir)
    return os.path.join(get_app_home(), "plugins")


@singleton
class ResourceManager:
    DEFAULT_ALARM_SOUND = "assets/sounds/alarm.mp3"
    DEFAULT_START_SOUND = "assets/sounds/alarm.mp3"
    DEFAULT_STOP_SOUND = "assets/sounds/temp_reversed.mp3"
    DEFAULT_ICON = "assets/icons/autodoor.ico"
    
    def __init__(self):
        self._app_root = get_app_root()
    
    @property
    def app_root(self) -> str:
        return self._app_root
    
    def get_alarm_sound_path(self) -> str:
        """获取默认报警音效路径"""
        return get_resource_path(self.DEFAULT_ALARM_SOUND)
    
    def get_start_sound_path(self) -> str:
        """获取开始运行音效路径"""
        return get_resource_path(self.DEFAULT_START_SOUND)
    
    def get_stop_sound_path(self) -> str:
        """获取停止运行音效路径"""
        return get_resource_path(self.DEFAULT_STOP_SOUND)
    
    def get_icon_path(self) -> str:
        """获取应用图标路径"""
        return get_resource_path(self.DEFAULT_ICON)
    
    def resource_exists(self, relative_path: str) -> bool:
        """检查资源文件是否存在
        
        Args:
            relative_path: 相对路径
            
        Returns:
            文件是否存在
        """
        full_path = get_resource_path(relative_path)
        return os.path.exists(full_path)
    
    def alarm_sound_exists(self) -> bool:
        """检查报警音效是否存在"""
        return os.path.exists(self.get_alarm_sound_path())
    
    def icon_exists(self) -> bool:
        """检查图标是否存在"""
        return os.path.exists(self.get_icon_path())
    
    def get_all_resources(self) -> dict:
        """获取所有资源路径
        
        Returns:
            资源路径字典
        """
        return {
            "alarm_sound": self.get_alarm_sound_path(),
            "start_sound": self.get_start_sound_path(),
            "stop_sound": self.get_stop_sound_path(),
            "icon": self.get_icon_path(),
            "alarm_sound_exists": self.alarm_sound_exists(),
            "icon_exists": self.icon_exists(),
        }


def get_resource_manager() -> ResourceManager:
    """获取资源管理器单例"""
    return ResourceManager()
