from abc import ABC, abstractmethod
from enum import Enum
from typing import Tuple, Optional


class InputLevel(Enum):
    """输入模拟层级"""
    APPLICATION = "application"
    DRIVER = "driver"
    BACKGROUND = "background"


class BaseKeyboardController(ABC):
    """键盘输入控制器基类"""

    @classmethod
    @abstractmethod
    def get_input_level(cls) -> InputLevel:
        pass

    @classmethod
    @abstractmethod
    def is_driver_available(cls) -> bool:
        pass

    @abstractmethod
    def key_press(self, key: str, action: str = "press", duration: int = 0) -> None:
        pass

    @abstractmethod
    def key_down(self, key: str) -> None:
        pass

    @abstractmethod
    def key_up(self, key: str) -> None:
        pass

    @classmethod
    def is_simulating(cls) -> bool:
        return False

    @classmethod
    def release_all_keys(cls) -> None:
        """释放所有按下的按键"""
        pass

    def get_name(self) -> str:
        return self.__class__.__name__

    def set_target_window(self, hwnd: int) -> None:
        pass

    def get_target_window(self) -> Optional[int]:
        return None


class BaseMouseController(ABC):
    """鼠标输入控制器基类"""

    @abstractmethod
    def mouse_click(self, button: str = "left", position: Tuple[int, int] = None,
                   action: str = "press", duration: int = 0) -> None:
        pass

    @abstractmethod
    def mouse_down(self, button: str = "left") -> None:
        pass

    @abstractmethod
    def mouse_up(self, button: str = "left") -> None:
        pass

    @abstractmethod
    def mouse_move(self, position: Tuple[int, int], relative: bool = False) -> None:
        pass

    @abstractmethod
    def mouse_scroll(self, amount: int, position: Tuple[int, int] = None,
                     horizontal: bool = False) -> None:
        pass

    def move_to(self, x: int, y: int) -> None:
        self.mouse_move((x, y), relative=False)

    def get_position(self) -> Tuple[int, int]:
        try:
            import pyautogui
            return pyautogui.position()
        except Exception:
            return (0, 0)

    @classmethod
    def release_all_mouse(cls) -> None:
        """释放所有按下的鼠标按钮"""
        pass

    def get_name(self) -> str:
        return self.__class__.__name__

    def set_target_window(self, hwnd: int) -> None:
        pass

    def get_target_window(self) -> Optional[int]:
        return None


class BaseInputController(BaseKeyboardController, BaseMouseController):
    """组合基类：同时实现键盘和鼠标（向后兼容）"""

    @classmethod
    def release_all(cls) -> None:
        """释放所有按下的按键和鼠标按钮"""
        cls.release_all_keys()
        cls.release_all_mouse()
