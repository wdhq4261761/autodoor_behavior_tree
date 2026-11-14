from typing import Tuple, Optional
from PIL import Image


class InputProxy:
    """输入代理类

    封装输入控制功能，委托给 InputControllerManager 统一管理。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

    def _get_keyboard_engine(self, **kwargs):
        """获取键盘引擎"""
        from bt_utils.input_manager import InputControllerManager
        return InputControllerManager().get_keyboard_engine(**kwargs)

    def _get_mouse_engine(self, **kwargs):
        """获取鼠标引擎"""
        from bt_utils.input_manager import InputControllerManager
        return InputControllerManager().get_mouse_engine(**kwargs)

    @classmethod
    def use_dd_input(cls, use_dd: bool = True) -> None:
        """设置是否使用DD虚拟输入"""
        from bt_utils.input_manager import InputControllerManager
        method = "dd" if use_dd else "pyautogui"
        manager = InputControllerManager()
        manager.set_keyboard_method(method)
        manager.set_mouse_method(method)

    def key_press(self, key: str, action: str = "press", duration: int = 0) -> None:
        """按键操作"""
        engine = self._get_keyboard_engine()
        if engine:
            engine.key_press(key, action, duration)

    def mouse_click(self, button: str = "left", position: Tuple[int, int] = None,
                   action: str = "press", duration: int = 0) -> None:
        """鼠标点击"""
        engine = self._get_mouse_engine()
        if engine:
            engine.mouse_click(button, position, action, duration)

    def mouse_move(self, position: Tuple[int, int], relative: bool = False) -> None:
        """移动鼠标"""
        engine = self._get_mouse_engine()
        if engine:
            engine.mouse_move(position, relative)

    def mouse_scroll(self, amount: int, position: Tuple[int, int] = None,
                     horizontal: bool = False) -> None:
        """鼠标滚轮"""
        engine = self._get_mouse_engine()
        if engine:
            engine.mouse_scroll(amount, position, horizontal)


class ScreenshotProxy:
    """截图代理类

    封装截图功能，提供统一的截图接口。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

    def get_full_screenshot(self) -> Image.Image:
        """获取全屏截图

        Returns:
            PIL.Image 图像
        """
        from bt_utils.screen_service import ScreenService
        return ScreenService.capture_screen()

    def get_region_screenshot(self, region: Tuple[int, int, int, int]) -> Image.Image:
        """获取区域截图

        Args:
            region: 区域 (left, top, right, bottom)

        Returns:
            PIL.Image 图像
        """
        from bt_utils.screen_service import ScreenService
        return ScreenService.capture_screen(region=region)

    def capture_window(self, hwnd) -> Optional[Image.Image]:
        """捕获窗口图像

        Args:
            hwnd: 窗口句柄

        Returns:
            PIL.Image 图像
        """
        from bt_utils.screen_service import ScreenService
        return ScreenService.capture_window(hwnd)

    def capture_window_by_title(self, title: str) -> Optional[Image.Image]:
        """根据标题捕获窗口

        Args:
            title: 窗口标题

        Returns:
            PIL.Image 图像
        """
        try:
            from bt_utils.screen_service import ScreenService
            from bt_utils.window_capture import WindowCapture
            hwnd = WindowCapture.find_window(title=title)
            if not hwnd:
                return None
            return ScreenService.capture_window(hwnd)
        except Exception:
            return None


class AlarmProxy:
    """报警代理类

    封装报警功能，提供统一的报警接口。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        from bt_utils.alarm import AlarmPlayer
        self._alarm = AlarmPlayer()

    def play(self, sound_path: str = "", volume: int = 70, wait_complete: bool = True) -> None:
        """播放报警音效

        Args:
            sound_path: 音效文件路径
            volume: 音量 (0-100)
            wait_complete: 是否等待播放完成
        """
        self._alarm.play(sound_path, volume, wait_complete)

    def stop(self) -> None:
        """停止播放"""
        try:
            self._alarm.stop()
        except Exception:
            pass
