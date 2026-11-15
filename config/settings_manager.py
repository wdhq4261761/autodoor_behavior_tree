import json
import os
import copy
import datetime
from typing import Any, Dict, Optional, List, Callable
from bt_utils.log_manager import LogManager
from bt_utils.json_io import load_json
from dataclasses import dataclass, field, asdict
from bt_utils.singleton import singleton


VERSION = "1.0.0"


@dataclass(frozen=True)
class BlackboardConfig:
    """黑板配置（不可变）"""
    default_position_key: str = "last_detection_position"
    default_value_key: str = "last_number_value"
    default_ocr_text_key: str = "last_ocr_text"
    default_color_key: str = "last_color_value"
    default_image_match_key: str = "last_image_match"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_position_key": self.default_position_key,
            "default_value_key": self.default_value_key,
            "default_ocr_text_key": self.default_ocr_text_key,
            "default_color_key": self.default_color_key,
            "default_image_match_key": self.default_image_match_key,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BlackboardConfig":
        return cls(
            default_position_key=data.get("default_position_key", "last_detection_position"),
            default_value_key=data.get("default_value_key", "last_number_value"),
            default_ocr_text_key=data.get("default_ocr_text_key", "last_ocr_text"),
            default_color_key=data.get("default_color_key", "last_color_value"),
            default_image_match_key=data.get("default_image_match_key", "last_image_match"),
        )


@dataclass
class SessionConfig:
    """会话配置"""
    last_file_path: str = ""
    recent_files: List[str] = field(default_factory=list)
    window_geometry: str = "1280x800"
    last_export_path: str = ""
    open_tabs: List[Dict[str, str]] = field(default_factory=list)
    active_tab_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_file_path": self.last_file_path,
            "recent_files": self.recent_files[:10],
            "window_geometry": self.window_geometry,
            "last_export_path": self.last_export_path,
            "open_tabs": self.open_tabs,
            "active_tab_id": self.active_tab_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionConfig":
        return cls(
            last_file_path=data.get("last_file_path", ""),
            recent_files=data.get("recent_files", [])[:10],
            window_geometry=data.get("window_geometry", "1280x800"),
            last_export_path=data.get("last_export_path", ""),
            open_tabs=data.get("open_tabs", []),
            active_tab_id=data.get("active_tab_id", ""),
        )


@singleton
class SettingsManager:
    """统一配置管理器
    
    管理应用程序所有设置，支持：
    - 持久化存储到系统目录
    - 版本管理和配置迁移
    - 延迟保存机制
    - 配置变更监听
    - 配置缓存机制
    
    使用单例模式，线程安全。
    """
    
    VERSION = "1.0.0"
    CONFIG_FILE_NAME = "config.json"
    
    DEFAULT_SETTINGS = {
        "version": VERSION,
        "tesseract_path": "",
        "alarm_sound_path": "",
        "alarm_volume": 70,
        "default_project_path": "",
        "shortcuts": {
            "start": "F10",
            "stop": "F12",
            "record": "F11",
            "tab_shortcuts": [
                {"hotkey": "F1"},
                {"hotkey": "F2"},
                {"hotkey": "F3"}
            ]
        },
        "behavior_tree": {
            "tick_interval": 33,
            "auto_save_interval": 30,
            "default_format": "json",
            "default_check_interval_ms": 300,
            "default_timeout_ms": 0,
            "default_retry_count": 0,
            "default_repeat_count": 0,
            "default_child_interval": 0,
            "max_undo_history": 50
        },
        "ui": {
            "theme": "dark",
            "language": "zh_CN",
            "font_size": 10
        },
        "session": {
            "last_file_path": "",
            "recent_files": [],
            "window_geometry": "1280x800",
            "last_export_path": "",
            "open_tabs": [],
            "active_tab_id": ""
        },
        "blackboard": {
            "default_position_key": "last_detection_position",
            "default_value_key": "last_number_value",
            "default_ocr_text_key": "last_ocr_text",
            "default_color_key": "last_color_value",
            "default_image_match_key": "last_image_match"
        },
        "input": {
            "keyboard_method": "pyautogui",
            "mouse_method": "pyautogui",
            "ib_send_mode": "any_driver",
            "ib_target_pid": 0,
        },
        "update": {
            "ignored_version": "",
            "last_check_time": "",
            "check_interval": 86400,
            "force_update_cache": {}
        },
        "message_bus": {
            "enabled": False,
            "shared_thread_pool_size": 8,
            "dead_letter_queue_size": 1000,
        },
        "rest_server": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 8080,
            "auth_enabled": False,
        },
        "websocket_server": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 8765,
            "heartbeat_interval": 30,
        },
        "sse_server": {
            "enabled": True,
            "max_clients": 10,
        },
        "adapters": {
            "http": {"enabled": False, "timeout_ms": 5000, "retry_count": 3},
            "websocket": {"enabled": False, "reconnect_interval_ms": 5000},
        },
        "auth": {
            "enabled": False,
            "method": "noop",
            "api_key": {"keys": []},
            "token_expiry_seconds": 3600,
            "platform": {
                "base_url": "",
                "api_namespace": "/wp-json/bt/v1/executor",
                "connect_timeout": 10,
                "read_timeout": 30,
            }
        },
        # 插件系统配置
        "plugins": {},
        # 定时调度配置
        "schedules": {},
        # AI 编排配置
        "ai": {
            "enabled": False,
            "llm": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "",
                "model": "gpt-4o",
                "timeout_ms": 300000,
                "max_tokens": 4096,
            },
            "vlm": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "",
                "model": "gpt-4o",
                "timeout_ms": 300000,
                "max_tokens": 4096,
                "image_detail": "high",
            },
            "iteration": {
                "max_rounds": 3,
                "test_timeout_ms": 30000,
            },
        },
    }
    
    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = self._get_default_config_dir()
        
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, self.CONFIG_FILE_NAME)
        self.settings: Dict[str, Any] = {}
        
        self._save_timer = None
        self._save_callback = None
        self._listeners: Dict[str, List[Callable]] = {}
        
        self._blackboard_config_cache: Optional[BlackboardConfig] = None
        self._session_config_cache: Optional[SessionConfig] = None
        
        self._load_settings()
    
    @classmethod
    def get_instance(cls) -> "SettingsManager":
        return cls()
    
    @classmethod
    def reset_instance(cls):
        from bt_utils.singleton import reset_singleton
        reset_singleton(cls)
    
    def _get_default_config_dir(self) -> str:
        """获取默认配置目录
        
        Windows: %APPDATA%/autodoor_behavior_tree
        Linux/Mac: ~/.config/autodoor_behavior_tree
        """
        if os.name == 'nt':
            base_dir = os.environ.get('APPDATA', os.path.expanduser('~'))
        else:
            base_dir = os.environ.get('XDG_CONFIG_HOME',
                                       os.path.join(os.path.expanduser('~'), '.config'))
        
        return os.path.join(base_dir, "autodoor_behavior_tree")
    
    @staticmethod
    def get_default_workspace_path() -> str:
        """获取默认workspace路径
        
        默认保存在系统持久化目录下，确保更换客户端不会丢失数据。
        Windows: %APPDATA%/autodoor_behavior_tree/workspace
        Linux/Mac: ~/.config/autodoor_behavior_tree/workspace
        """
        if os.name == 'nt':
            base_dir = os.environ.get('APPDATA', os.path.expanduser('~'))
        else:
            base_dir = os.environ.get('XDG_CONFIG_HOME',
                                       os.path.join(os.path.expanduser('~'), '.config'))
        
        return os.path.join(base_dir, "autodoor_behavior_tree", "workspace")
    
    def _load_settings(self) -> None:
        """加载设置"""
        if os.path.exists(self.config_file):
            try:
                self.settings = load_json(self.config_file)
                self._merge_defaults()
                self._migrate_config()
            except Exception as e:
                LogManager.debug_print(f"[WARN] 加载配置文件失败: {e}")
                self.settings = copy.deepcopy(self.DEFAULT_SETTINGS)
        else:
            self.settings = copy.deepcopy(self.DEFAULT_SETTINGS)
    
    def _merge_defaults(self) -> None:
        """合并默认设置"""
        def merge_dict(base: dict, default: dict) -> dict:
            for key, value in default.items():
                if key not in base:
                    base[key] = value
                elif isinstance(value, dict) and isinstance(base.get(key), dict):
                    merge_dict(base[key], value)
            return base
        
        merge_dict(self.settings, self.DEFAULT_SETTINGS)
    
    def _migrate_config(self) -> None:
        """配置迁移处理"""
        config_version = self.settings.get("version", "0.0.0")

        # 迁移 input.method → input.keyboard_method + input.mouse_method
        input_settings = self.settings.get("input", {})
        if "method" in input_settings:
            old_method = input_settings.pop("method")
            if "keyboard_method" not in input_settings:
                input_settings["keyboard_method"] = old_method
            if "mouse_method" not in input_settings:
                input_settings["mouse_method"] = old_method

        # 迁移 AI LLM/VLM 超时：旧版本默认 30000ms 过短，升级为 300000ms（5 分钟）
        for ai_key in ("llm", "vlm"):
            section = self.settings.get("ai", {}).get(ai_key)
            if isinstance(section, dict) and section.get("timeout_ms") == 30000:
                section["timeout_ms"] = 300000

        if config_version != self.VERSION:
            self.settings["version"] = self.VERSION
            self.settings["last_save_time"] = datetime.datetime.now().isoformat()
            self.save_settings()
    
    def save_settings(self) -> bool:
        """保存设置到文件"""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            
            self.settings["last_save_time"] = datetime.datetime.now().isoformat()
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            LogManager.debug_print(f"[WARN] 保存配置文件失败: {e}")
            return False
    
    def defer_save(self, delay_ms: int = 1000) -> None:
        """延迟保存配置，避免频繁保存"""
        if self._save_timer is not None:
            try:
                self._save_timer.cancel()
            except Exception:
                pass
        
        import threading
        self._save_timer = threading.Timer(delay_ms / 1000, self._do_deferred_save)
        self._save_timer.daemon = True
        self._save_timer.start()
    
    def _do_deferred_save(self) -> None:
        """执行延迟保存"""
        self.save_settings()
        self._save_timer = None
    
    def set_save_callback(self, callback: Callable) -> None:
        """设置保存回调函数"""
        self._save_callback = callback
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取设置值
        
        Args:
            key: 设置键（支持点号分隔的嵌套键）
            default: 默认值
        """
        keys = key.split('.')
        value = self.settings
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any, auto_save: bool = True) -> None:
        """设置值
        
        Args:
            key: 设置键（支持点号分隔的嵌套键）
            value: 设置值
            auto_save: 是否自动触发延迟保存
        """
        keys = key.split('.')
        data = self.settings
        
        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]
        
        data[keys[-1]] = value
        
        if key.startswith("blackboard"):
            self._blackboard_config_cache = None
        elif key.startswith("session"):
            self._session_config_cache = None
        
        self._notify_listeners(key, value)
        
        if auto_save:
            self.defer_save()
    
    def add_listener(self, key: str, callback: Callable) -> None:
        """添加配置变更监听器
        
        Args:
            key: 监听的配置键
            callback: 回调函数
        """
        if key not in self._listeners:
            self._listeners[key] = []
        self._listeners[key].append(callback)
    
    def remove_listener(self, key: str, callback: Callable) -> None:
        """移除配置变更监听器"""
        if key in self._listeners:
            try:
                self._listeners[key].remove(callback)
            except ValueError:
                pass
    
    def _notify_listeners(self, key: str, value: Any) -> None:
        """通知监听器"""
        if key in self._listeners:
            for callback in self._listeners[key]:
                try:
                    callback(key, value)
                except Exception as e:
                    LogManager.debug_print(f"[WARN] 配置监听器回调失败: {e}")
    
    def reset(self, key: str = None) -> None:
        """重置设置
        
        Args:
            key: 设置键，为None时重置所有设置
        """
        if key is None:
            self.settings = copy.deepcopy(self.DEFAULT_SETTINGS)
            self._blackboard_config_cache = None
            self._session_config_cache = None
        else:
            keys = key.split('.')
            default_value = self.DEFAULT_SETTINGS
            
            for k in keys:
                if isinstance(default_value, dict) and k in default_value:
                    default_value = default_value[k]
                else:
                    return
            
            self.set(key, default_value)
        
        self.save_settings()
    
    def get_blackboard_config(self) -> BlackboardConfig:
        """获取黑板配置（带缓存）"""
        if self._blackboard_config_cache is not None:
            return self._blackboard_config_cache
        
        data = self.get("blackboard", {})
        self._blackboard_config_cache = BlackboardConfig.from_dict(data)
        return self._blackboard_config_cache
    
    def set_blackboard_config(self, config: BlackboardConfig) -> None:
        """设置黑板配置"""
        self._blackboard_config_cache = config
        self.set("blackboard", asdict(config))
    
    def get_session_config(self) -> SessionConfig:
        """获取会话配置（带缓存）"""
        if self._session_config_cache is not None:
            return self._session_config_cache
        
        data = self.get("session", {})
        self._session_config_cache = SessionConfig.from_dict(data)
        return self._session_config_cache
    
    def set_session_config(self, config: SessionConfig) -> None:
        """设置会话配置"""
        self._session_config_cache = config
        self.set("session", asdict(config))
    
    def invalidate_config_cache(self) -> None:
        """使配置缓存失效"""
        self._blackboard_config_cache = None
        self._session_config_cache = None
    
    def get_last_file_path(self) -> str:
        """获取上次打开的文件路径"""
        return self.get("session.last_file_path", "")
    
    def set_last_file_path(self, file_path: str) -> None:
        """设置上次打开的文件路径"""
        self.set("session.last_file_path", file_path)
        if file_path:
            self._add_recent_file(file_path)
    
    def get_recent_files(self) -> List[str]:
        """获取最近文件列表"""
        return self.get("session.recent_files", [])
    
    def _add_recent_file(self, file_path: str) -> None:
        """添加到最近文件列表"""
        recent = self.get("session.recent_files", [])
        if file_path in recent:
            recent.remove(file_path)
        recent.insert(0, file_path)
        self.set("session.recent_files", recent[:10])
    
    def clear_recent_files(self) -> None:
        """清空最近文件列表"""
        self.set("session.recent_files", [])
    
    def get_last_export_path(self) -> str:
        """获取上次导出路径"""
        return self.get("session.last_export_path", "")
    
    def set_last_export_path(self, export_path: str) -> None:
        """设置上次导出路径"""
        self.set("session.last_export_path", export_path)
    
    def get_open_tabs(self) -> List[Dict[str, str]]:
        """获取打开的 Tab 列表"""
        return self.get("session.open_tabs", [])
    
    def set_open_tabs(self, tabs: List[Dict[str, str]]) -> None:
        """保存打开的 Tab 列表"""
        self.set("session.open_tabs", tabs)
    
    def get_active_tab_id(self) -> str:
        """获取活动 Tab ID"""
        return self.get("session.active_tab_id", "")
    
    def set_active_tab_id(self, tab_id: str) -> None:
        """保存活动 Tab ID"""
        self.set("session.active_tab_id", tab_id)
    
    def get_all_settings(self) -> Dict[str, Any]:
        """获取所有设置"""
        return copy.deepcopy(self.settings)

    def get_default_config(self) -> dict:
        """返回默认配置的副本"""
        return copy.deepcopy(self.DEFAULT_SETTINGS)
    
    def load_all_settings(self, settings: Dict[str, Any]) -> None:
        """加载所有设置"""
        self.settings = settings
        self._merge_defaults()
        self.invalidate_config_cache()
        self.save_settings()


def get_settings_manager() -> SettingsManager:
    """获取设置管理器单例"""
    return SettingsManager.get_instance()


def get_default_position_key() -> str:
    return get_settings_manager().get("blackboard.default_position_key", "last_detection_position")


def get_default_value_key() -> str:
    return get_settings_manager().get("blackboard.default_value_key", "last_number_value")


def get_blackboard_config() -> BlackboardConfig:
    return get_settings_manager().get_blackboard_config()


def get_session_config() -> SessionConfig:
    return get_settings_manager().get_session_config()
