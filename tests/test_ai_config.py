# tests/test_ai_config.py
"""AI 配置项测试

环境说明:
    bt_utils/__init__.py 会 eager-import OCRManager / ScriptRecorder 等模块,
    它们依赖 rapidocr / pynput 等重型三方库。本测试仅关注 SettingsManager
    的 AI 配置,因此在导入前用 MagicMock 占位这些缺失的可选依赖。
"""
import os
import shutil
import sys
import tempfile
from unittest.mock import MagicMock

# ------------------------------------------------------------------
# 在导入 SettingsManager 之前,为环境中缺失的可选重型依赖注入 Mock,
# 使 bt_utils/__init__.py 的 eager import 链不致中断。
# ------------------------------------------------------------------
_MISSING_OPTIONAL_DEPS = [
    "rapidocr",
    "pynput",
    "pynput.mouse",
    "pynput.keyboard",
    "cv2",
    "pyautogui",
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "win32clipboard",
    "win32event",
]
for _name in _MISSING_OPTIONAL_DEPS:
    if _name in sys.modules:
        continue
    try:
        # 只有"确实无法导入"的模块才注入 Mock。
        # 原实现只判断 sys.modules，会在纯净环境或不同执行顺序下，
        # 把已安装的 cv2 / rapidocr 等真实模块替换成 MagicMock 并永久驻留，
        # 导致后续测试拿到 MagicMock 而大面积失败（表现为解包得到 0 个值）。
        __import__(_name)
    except ImportError:
        sys.modules[_name] = MagicMock()


def _reset_settings_singleton():
    """彻底重置 SettingsManager 单例。

    SettingsManager 使用 @singleton 装饰器,其 ``_instance`` 存储在
    ``__new__`` 的闭包中,``reset_instance()`` 仅重置类属性,无法触及
    闭包变量。这里手动遍历闭包 cell 来完成真正的重置。
    """
    from config.settings_manager import SettingsManager

    # 先调用类方法重置类属性
    SettingsManager.reset_instance()

    # 再重置 __new__ 闭包中的 _instance 变量
    new_func = SettingsManager.__new__
    if hasattr(new_func, "__closure__") and new_func.__closure__:
        for cell in new_func.__closure__:
            try:
                val = cell.cell_contents
            except ValueError:
                # 空 cell,跳过
                continue
            if val is not None and isinstance(val, SettingsManager):
                # 取消可能挂起的延迟保存定时器,避免污染后续测试
                timer = getattr(val, "_save_timer", None)
                if timer is not None:
                    try:
                        timer.cancel()
                    except Exception:
                        pass
                cell.cell_contents = None


def _test_config_dir():
    """获取跨平台兼容的测试配置目录"""
    return os.path.join(tempfile.gettempdir(), "test_ai_config")


def test_ai_config_defaults():
    """验证 AI 配置默认值存在且结构正确"""
    from config.settings_manager import SettingsManager
    _reset_settings_singleton()

    config_dir = _test_config_dir()
    # 清理旧配置文件,确保使用 DEFAULT_SETTINGS
    shutil.rmtree(config_dir, ignore_errors=True)

    sm = SettingsManager(config_dir=config_dir)

    assert sm.get("ai.enabled") == False
    assert sm.get("ai.llm.base_url") == "https://api.openai.com/v1"
    assert sm.get("ai.llm.model") == "gpt-4o"
    assert sm.get("ai.llm.timeout_ms") == 300000
    assert sm.get("ai.llm.max_tokens") == 4096
    assert sm.get("ai.vlm.base_url") == "https://api.openai.com/v1"
    assert sm.get("ai.vlm.model") == "gpt-4o"
    assert sm.get("ai.vlm.timeout_ms") == 300000
    assert sm.get("ai.vlm.image_detail") == "high"
    assert sm.get("ai.iteration.max_rounds") == 3
    assert sm.get("ai.iteration.test_timeout_ms") == 30000


def test_ai_config_set_and_get():
    """验证 AI 配置可读写"""
    from config.settings_manager import SettingsManager
    _reset_settings_singleton()

    config_dir = _test_config_dir()
    shutil.rmtree(config_dir, ignore_errors=True)

    sm = SettingsManager(config_dir=config_dir)
    sm.set("ai.llm.base_url", "http://localhost:11434/v1")
    sm.set("ai.llm.model", "qwen2.5")

    assert sm.get("ai.llm.base_url") == "http://localhost:11434/v1"
    assert sm.get("ai.llm.model") == "qwen2.5"


def test_ai_timeout_migration_from_30000():
    """旧版本残留的 ai.llm/ai.vlm.timeout_ms=30000 应自动升级为 300000"""
    import json
    from config.settings_manager import SettingsManager

    _reset_settings_singleton()

    config_dir = _test_config_dir()
    shutil.rmtree(config_dir, ignore_errors=True)
    os.makedirs(config_dir, exist_ok=True)

    # 写入一份含旧超时值 30000 的配置文件
    legacy = {
        "version": "1.0.0",
        "ai": {
            "llm": {"timeout_ms": 30000},
            "vlm": {"timeout_ms": 30000},
        },
    }
    with open(os.path.join(config_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(legacy, f, ensure_ascii=False)

    sm = SettingsManager(config_dir=config_dir)
    assert sm.get("ai.llm.timeout_ms") == 300000
    assert sm.get("ai.vlm.timeout_ms") == 300000
