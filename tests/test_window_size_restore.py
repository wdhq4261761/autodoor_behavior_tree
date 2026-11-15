"""窗口尺寸记录/还原测试

验证开始节点绑定窗口时：
- 首次运行记录当前窗口尺寸；
- 已记录尺寸且差异超过容差时自动还原；
- 尺寸接近时不重复设置；
- restore_window_size=False 时不还原也不改写记录；
- 最小化/最大化窗口不记录错误尺寸。
"""
import builtins
import sys
from unittest.mock import MagicMock, patch

from bt_core.nodes import StartNode
from bt_utils.window_manager import WindowManager


class _FakeWin32Gui:
    def __init__(self, placement):
        self.placement = placement

    def GetWindowPlacement(self, hwnd):
        return self.placement


class _FakeWin32Con:
    SW_SHOWNORMAL = 1
    SW_SHOWMINIMIZED = 2
    SW_SHOWMAXIMIZED = 3


def test_parse_and_format_window_size():
    assert WindowManager.parse_window_size("1280x720") == (1280, 720)
    assert WindowManager.parse_window_size("1280×720") == (1280, 720)
    assert WindowManager.parse_window_size("") is None
    assert WindowManager.format_window_size((1280, 720)) == "1280x720"


def test_parse_window_size_invalid_returns_none():
    assert WindowManager.parse_window_size("abc") is None
    assert WindowManager.parse_window_size("1280x") is None
    assert WindowManager.parse_window_size("0x720") is None


def test_size_helpers_return_safe_defaults_without_win32gui():
    real_import = builtins.__import__

    def _import_without_win32gui(name, *args, **kwargs):
        if name == "win32gui":
            raise ImportError("win32gui unavailable")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import_without_win32gui):
        assert WindowManager.get_window_size(1) is None
        assert WindowManager.set_window_size(1, (800, 600)) is False
        assert WindowManager.is_maximized(1) is False
        assert WindowManager.is_minimized(1) is False


def test_is_maximized_uses_window_placement():
    fake_gui = _FakeWin32Gui((0, _FakeWin32Con.SW_SHOWMAXIMIZED, 0, 0, 0, 0, 0, 0, 0, 0))
    fake_con = _FakeWin32Con()
    with patch.dict(sys.modules, {"win32gui": fake_gui, "win32con": fake_con}):
        assert WindowManager.is_maximized(100) is True

    fake_gui.placement = (0, _FakeWin32Con.SW_SHOWNORMAL, 0, 0, 0, 0, 0, 0, 0, 0)
    with patch.dict(sys.modules, {"win32gui": fake_gui, "win32con": fake_con}):
        assert WindowManager.is_maximized(100) is False


def test_is_minimized_uses_iconic():
    class _FakeWin32GuiIconic:
        def __init__(self, iconic):
            self.iconic = iconic

        def IsIconic(self, hwnd):
            return self.iconic

    fake_gui = _FakeWin32GuiIconic(True)
    with patch.dict(sys.modules, {"win32gui": fake_gui}):
        assert WindowManager.is_minimized(100) is True

    fake_gui.iconic = False
    with patch.dict(sys.modules, {"win32gui": fake_gui}):
        assert WindowManager.is_minimized(100) is False


def test_start_node_records_size_when_missing():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size", return_value=(800, 600)), \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False):
        node._bind_window_to_context(MagicMock())
    assert node.config.get("window_size") == "800x600"
    assert node.config.get("window_maximized") is False


def test_start_node_restores_size_when_recorded():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    node.config.set("window_size", "1024x768")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size", return_value=(900, 700)), \
         patch("bt_utils.window_manager.WindowManager.set_window_size", return_value=True) as setter, \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False):
        node._bind_window_to_context(MagicMock())
    setter.assert_called_once_with(100, (1024, 768))


def test_restore_triggered_when_one_dimension_exceeds_tolerance():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    node.config.set("window_size", "1024x768")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size", return_value=(1027, 768)), \
         patch("bt_utils.window_manager.WindowManager.set_window_size", return_value=True) as setter, \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False):
        node._bind_window_to_context(MagicMock())
    setter.assert_called_once_with(100, (1024, 768))


def test_restore_skipped_when_size_close_enough():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    node.config.set("window_size", "1024x768")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size", return_value=(1025, 767)), \
         patch("bt_utils.window_manager.WindowManager.set_window_size") as setter, \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False):
        node._bind_window_to_context(MagicMock())
    setter.assert_not_called()


def test_restore_skipped_at_exact_tolerance():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    node.config.set("window_size", "1024x768")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size", return_value=(1026, 770)), \
         patch("bt_utils.window_manager.WindowManager.set_window_size") as setter, \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False):
        node._bind_window_to_context(MagicMock())
    setter.assert_not_called()


def test_restore_window_size_disabled_skips_set():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    node.config.set("window_size", "1024x768")
    node.config.set("restore_window_size", False)
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size", return_value=(900, 700)), \
         patch("bt_utils.window_manager.WindowManager.set_window_size") as setter, \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False):
        node._bind_window_to_context(MagicMock())
    setter.assert_not_called()
    assert node.config.get("window_size") == "1024x768"


def test_invalid_window_size_string_records_current():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    node.config.set("window_size", "abc")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size", return_value=(800, 600)), \
         patch("bt_utils.window_manager.WindowManager.set_window_size") as setter, \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False):
        node._bind_window_to_context(MagicMock())
    setter.assert_not_called()
    assert node.config.get("window_size") == "800x600"
    assert node.config.get("window_maximized") is False


def test_maximized_window_records_flag_without_size():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size") as getter, \
         patch("bt_utils.window_manager.WindowManager.set_window_size") as setter, \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=True), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False):
        node._bind_window_to_context(MagicMock())
    setter.assert_not_called()
    getter.assert_not_called()
    assert node.config.get("window_size", "") == ""
    assert node.config.get("window_maximized") is True


def test_minimized_window_skips_size_logic():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    node.config.set("window_size", "1024x768")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size") as getter, \
         patch("bt_utils.window_manager.WindowManager.set_window_size") as setter, \
         patch("bt_utils.window_manager.WindowManager.is_maximized") as maximized, \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=True):
        node._bind_window_to_context(MagicMock())
    setter.assert_not_called()
    getter.assert_not_called()
    maximized.assert_not_called()
    assert node.config.get("window_size") == "1024x768"


def test_restore_failure_logs_failure():
    node = StartNode(config=None)
    node.config.set("bind_window", True)
    node.config.set("window_title", "Notepad")
    node.config.set("window_size", "1024x768")
    with patch("bt_utils.window_manager.WindowManager.find_window_smart_with_hwnd", return_value=(100, "title")), \
         patch("bt_utils.window_manager.WindowManager.get_window_size", return_value=(900, 700)), \
         patch("bt_utils.window_manager.WindowManager.set_window_size", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_maximized", return_value=False), \
         patch("bt_utils.window_manager.WindowManager.is_minimized", return_value=False), \
         patch("bt_core.nodes.LogManager.instance") as log_instance:
        node._bind_window_to_context(MagicMock())
    log_instance.return_value.log_failure.assert_called_once_with(
        node_type="开始节点",
        node_name=node.name,
        reason="窗口尺寸还原失败: 1024x768"
    )
