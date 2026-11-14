"""
输入控制器工厂
根据配置或编译参数选择具体实现
支持DD虚拟键盘和PyAutoGUI两种方式
"""
import os
import threading
import time
from typing import Optional, Tuple

from .base_input import BaseInputController, InputLevel


def _get_input_method_from_settings() -> str:
    try:
        from config.settings_manager import SettingsManager
        method = SettingsManager.get_instance().get("input.keyboard_method", "pyautogui")
    except Exception:
        method = "pyautogui"

    if method == "dd":
        from .app_restarter import is_dd_available
        if not is_dd_available():
            method = "pyautogui"

    return method

_dd_input_instance = None


def _get_dd_input(app=None):
    """延迟加载DD输入实例"""
    global _dd_input_instance
    if _dd_input_instance is None:
        try:
            from .dd_input import DDVirtualInput
            _dd_input_instance = DDVirtualInput(app=app)
        except Exception:
            pass
    return _dd_input_instance


class PyAutoGUIInput(BaseInputController):
    """PyAutoGUI输入控制器"""
    
    @classmethod
    def get_input_level(cls) -> InputLevel:
        return InputLevel.APPLICATION
    
    @classmethod
    def is_driver_available(cls) -> bool:
        return True
    
    def __init__(self, app=None):
        self._available = True
        self.app = app
        self._simulate_lock = threading.Lock()
        self._simulating = False
        
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0  # 禁用全局 PAUSE，延迟由节点/脚本显式控制（DelayNode/click_interval/Delay 命令）
    
    def get_name(self) -> str:
        return "PyAutoGUI"
    
    def _log(self, message: str):
        """日志输出"""
        pass
    
    def _set_simulating(self, value: bool):
        with self._simulate_lock:
            self._simulating = value
    
    def key_press(self, key: str, action: str = "press", duration: int = 0) -> None:
        """按键操作"""
        import pyautogui
        self._set_simulating(True)
        try:
            if action == "press":
                if duration > 0:
                    pyautogui.keyDown(key)
                    time.sleep(duration / 1000.0)
                    pyautogui.keyUp(key)
                else:
                    pyautogui.press(key)
            elif action == "down":
                pyautogui.keyDown(key)
            elif action == "up":
                pyautogui.keyUp(key)
        finally:
            self._set_simulating(False)
    
    def key_down(self, key: str) -> None:
        """按下按键"""
        import pyautogui
        self._set_simulating(True)
        try:
            pyautogui.keyDown(key)
        finally:
            self._set_simulating(False)
    
    def key_up(self, key: str) -> None:
        """释放按键"""
        import pyautogui
        self._set_simulating(True)
        try:
            pyautogui.keyUp(key)
        finally:
            self._set_simulating(False)
    
    def mouse_click(self, button: str = "left", position: Tuple[int, int] = None,
                   action: str = "press", duration: int = 0) -> None:
        """鼠标点击"""
        import pyautogui
        from bt_utils.log_manager import LogManager

        self._set_simulating(True)
        try:
            if position:
                pyautogui.moveTo(position[0], position[1])

            if action == "press":
                if duration > 0:
                    pyautogui.mouseDown(button=button)
                    time.sleep(duration / 1000.0)
                    pyautogui.mouseUp(button=button)
                else:
                    pyautogui.click(button=button)
            elif action == "down":
                pyautogui.mouseDown(button=button)
            elif action == "up":
                pyautogui.mouseUp(button=button)

        except Exception as e:
            LogManager.debug_print(f"[PYAUTO] mouse_click: 异常 - {type(e).__name__}: {e}")
            import traceback
            LogManager.debug_print(f"[PYAUTO] mouse_click: 异常堆栈:\n{traceback.format_exc()}")
            raise
        finally:
            self._set_simulating(False)
    
    def mouse_down(self, button: str = "left") -> None:
        """按下鼠标"""
        import pyautogui
        self._set_simulating(True)
        try:
            pyautogui.mouseDown(button=button)
        finally:
            self._set_simulating(False)
    
    def mouse_up(self, button: str = "left") -> None:
        """释放鼠标"""
        import pyautogui
        self._set_simulating(True)
        try:
            pyautogui.mouseUp(button=button)
        finally:
            self._set_simulating(False)
    
    def mouse_move(self, position: Tuple[int, int], relative: bool = False) -> None:
        """移动鼠标"""
        import pyautogui
        if relative:
            pyautogui.move(position[0], position[1])
        else:
            pyautogui.moveTo(position[0], position[1])
    
    def mouse_scroll(self, amount: int, position: Tuple[int, int] = None,
                     horizontal: bool = False) -> None:
        """鼠标滚轮（amount 单位为格，1 格 = 120 WHEEL_DELTA）"""
        import pyautogui
        import ctypes

        delta = int(round(amount)) * 120
        if delta == 0:
            return
        if position:
            pyautogui.moveTo(position[0], position[1])
        if horizontal:
            ctypes.windll.user32.mouse_event(0x01000, 0, 0, delta, 0)  # MOUSEEVENTF_HWHEEL
        else:
            pyautogui.scroll(delta)


class DDInputWrapper(BaseInputController):
    """DD输入控制器包装器"""
    
    @classmethod
    def get_input_level(cls) -> InputLevel:
        return InputLevel.DRIVER
    
    @classmethod
    def is_driver_available(cls) -> bool:
        from .dd_input import DDVirtualInput
        return DDVirtualInput.is_driver_available()
    
    def __init__(self, dd_instance, app=None):
        self._dd = dd_instance
        self.app = app
    
    def get_name(self) -> str:
        return "DD虚拟键盘"
    
    def _log(self, message: str):
        pass
    
    def key_press(self, key: str, action: str = "press", duration: int = 0) -> None:
        """按键操作"""
        if action == "press":
            self._dd.key_press(key, action, duration)
        elif action == "down":
            self._dd.key_down(key)
        elif action == "up":
            self._dd.key_up(key)
    
    def key_down(self, key: str) -> None:
        """按下按键"""
        self._dd.key_down(key)
    
    def key_up(self, key: str) -> None:
        """释放按键"""
        self._dd.key_up(key)
    
    def mouse_click(self, button: str = "left", position: Tuple[int, int] = None,
                   action: str = "press", duration: int = 0) -> None:
        """鼠标点击"""
        self._dd.mouse_click(button, position, action, duration)
    
    def mouse_down(self, button: str = "left") -> None:
        """按下鼠标"""
        self._dd.mouse_down(button)
    
    def mouse_up(self, button: str = "left") -> None:
        """释放鼠标"""
        self._dd.mouse_up(button)
    
    def mouse_move(self, position: Tuple[int, int], relative: bool = False) -> None:
        """移动鼠标"""
        self._dd.mouse_move(position, relative)
    
    def mouse_scroll(self, amount: int, position: Tuple[int, int] = None,
                     horizontal: bool = False) -> None:
        """鼠标滚轮"""
        self._dd.mouse_scroll(amount, position, horizontal)


class InputController:
    """
    输入控制器类（工厂模式）
    
    根据环境变量 AUTODOOR_USE_DD 自动选择DD虚拟键盘或PyAutoGUI
    """
    
    @classmethod
    def get_input_level(cls) -> InputLevel:
        """获取输入层级（委托给实际实现）"""
        instance = cls._get_default_instance()
        if instance:
            return instance.get_input_level()
        return InputLevel.APPLICATION
    
    @classmethod
    def is_driver_available(cls) -> bool:
        """检测驱动是否可用（委托给实际实现）"""
        return True
    
    _default_instance = None
    
    @classmethod
    def _get_default_instance(cls):
        if cls._default_instance is None:
            try:
                cls._default_instance = InputController()
            except Exception:
                pass
        return cls._default_instance
    
    _simulate_lock = threading.Lock()
    _simulating = False
    
    @classmethod
    def is_simulating(cls) -> bool:
        """检查当前是否正在执行模拟操作"""
        with cls._simulate_lock:
            return cls._simulating
    
    @classmethod
    def _set_simulating(cls, value: bool):
        """设置模拟状态"""
        with cls._simulate_lock:
            cls._simulating = value
    
    @classmethod
    def release_all(cls):
        """释放所有按下的按键和鼠标按钮"""
        cls._set_simulating(True)
        try:
            from pynput import keyboard, mouse
            
            keyboard_controller = keyboard.Controller()
            mouse_controller = mouse.Controller()
            
            for key in [keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
                       keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
                       keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
                       keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
                       keyboard.Key.caps_lock, keyboard.Key.num_lock,
                       keyboard.Key.scroll_lock]:
                try:
                    keyboard_controller.release(key)
                except:
                    pass
            
            for char in 'abcdefghijklmnopqrstuvwxyz0123456789':
                try:
                    keyboard_controller.release(char)
                except:
                    pass
            
            for key_name in ['f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
                            'space', 'enter', 'tab', 'escape', 'backspace', 'delete', 'insert',
                            'home', 'end', 'page_up', 'page_down', 'up', 'down', 'left', 'right']:
                try:
                    keyboard_controller.release(getattr(keyboard.Key, key_name, None))
                except:
                    pass
            
            mouse_controller.release(mouse.Button.left)
            mouse_controller.release(mouse.Button.middle)
            
        except Exception:
            pass
        finally:
            cls._set_simulating(False)
    
    def __init__(self, app=None, method: str = None):
        self.app = app
        self._method = method
        self._impl = None
        
        self._init_implementation()
    
    def _init_implementation(self):
        method = self._method
        
        if method is None:
            method = _get_input_method_from_settings()
        
        if method == 'dd':
            dd_instance = _get_dd_input(self.app)
            if dd_instance and dd_instance.is_available:
                self._impl = DDInputWrapper(dd_instance, self.app)
                self._method = 'dd'
                return
            else:
                self._impl = PyAutoGUIInput(self.app)
                self._method = 'pyautogui'
                return
        
        self._impl = PyAutoGUIInput(self.app)
        self._method = 'pyautogui'
    
    @property
    def method(self) -> str:
        return self._method
    
    @property
    def is_available(self) -> bool:
        return self._impl is not None
    
    def _log(self, message: str):
        pass
    
    def key_press(self, key: str, action: str = "press", duration: int = 0) -> None:
        if self._impl:
            self._impl.key_press(key, action, duration)
    
    def key_down(self, key: str) -> None:
        if self._impl:
            self._impl.key_down(key)
    
    def key_up(self, key: str) -> None:
        if self._impl:
            self._impl.key_up(key)
    
    def mouse_click(self, button: str = "left", position: tuple = None,
                   action: str = "press", duration: int = 0) -> None:
        if self._impl:
            self._impl.mouse_click(button, position, action, duration)
    
    def mouse_down(self, button: str = "left") -> None:
        if self._impl:
            self._impl.mouse_down(button)
    
    def mouse_up(self, button: str = "left") -> None:
        if self._impl:
            self._impl.mouse_up(button)
    
    def mouse_move(self, position: tuple, relative: bool = False) -> None:
        if self._impl:
            self._impl.mouse_move(position, relative)
    
    def mouse_scroll(self, amount: int, position: tuple = None,
                     horizontal: bool = False) -> None:
        if self._impl:
            self._impl.mouse_scroll(amount, position, horizontal)
    
    def move_to(self, x: int, y: int) -> None:
        self.mouse_move((x, y), relative=False)
    
    def get_position(self) -> tuple:
        try:
            import pyautogui
            return pyautogui.position()
        except:
            return (0, 0)


def create_input_controller(app=None, method: str = None) -> InputController:
    return InputController(app=app, method=method)
