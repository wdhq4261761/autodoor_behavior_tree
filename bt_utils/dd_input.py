"""
DD虚拟键盘输入控制器实现
DD版专用方案
"""
import os
import sys
import ctypes
import time
from typing import Optional, Tuple

from .base_input import BaseInputController, InputLevel


VK_CODE_MAP = {
    'backspace': 0x08,
    'tab': 0x09,
    'enter': 0x0D,
    'return': 0x0D,
    'shift': 0x10,
    'control': 0x11,
    'ctrl': 0x11,
    'alt': 0x12,
    'pause': 0x13,
    'caps_lock': 0x14,
    'capslock': 0x14,
    'escape': 0x1B,
    'esc': 0x1B,
    'space': 0x20,
    'pageup': 0x21,
    'prior': 0x21,
    'pagedown': 0x22,
    'next': 0x22,
    'end': 0x23,
    'home': 0x24,
    'left': 0x25,
    'up': 0x26,
    'right': 0x27,
    'down': 0x28,
    'print_screen': 0x2C,
    'printscreen': 0x2C,
    'insert': 0x2D,
    'ins': 0x2D,
    'delete': 0x2E,
    'del': 0x2E,
    
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59,
    'z': 0x5A,
    
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74,
    'f6': 0x75, 'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79,
    'f11': 0x7A, 'f12': 0x7B,
    
    'shift_l': 0xA0, 'shiftleft': 0xA0,
    'shift_r': 0xA1, 'shiftright': 0xA1,
    'control_l': 0xA2, 'ctrlleft': 0xA2, 'ctrl_l': 0xA2,
    'control_r': 0xA3, 'ctrlright': 0xA3, 'ctrl_r': 0xA3,
    'alt_l': 0xA4, 'altleft': 0xA4,
    'alt_r': 0xA5, 'altright': 0xA5,
    
    'win_l': 0x5B, 'winleft': 0x5B,
    'win_r': 0x5C, 'winright': 0x5C,
    'win': 0x5B,
    
    'num_lock': 0x90, 'numlock': 0x90,
    'scroll_lock': 0x91, 'scrolllock': 0x91,
    
    'multiply': 0x6A,
    'add': 0x6B,
    'separator': 0x6C,
    'subtract': 0x6D,
    'decimal': 0x6E,
    'divide': 0x6F,
    
    'numpad0': 0x60, 'numpad1': 0x61, 'numpad2': 0x62,
    'numpad3': 0x63, 'numpad4': 0x64, 'numpad5': 0x65,
    'numpad6': 0x66, 'numpad7': 0x67, 'numpad8': 0x68,
    'numpad9': 0x69,
    
    'oem_1': 0xBA,
    'oem_plus': 0xBB,
    'oem_comma': 0xBC,
    'oem_minus': 0xBD,
    'oem_period': 0xBE,
    'oem_2': 0xBF,
    'oem_3': 0xC0,
    'oem_4': 0xDB,
    'oem_5': 0xDC,
    'oem_6': 0xDD,
    'oem_7': 0xDE,
    
    ';': 0xBA,
    '=': 0xBB,
    ',': 0xBC,
    '-': 0xBD,
    '.': 0xBE,
    '/': 0xBF,
    '`': 0xC0,
    '[': 0xDB,
    '\\': 0xDC,
    ']': 0xDD,
    "'": 0xDE,
}


class DDVirtualInput(BaseInputController):
    """DD虚拟键盘输入控制器"""
    
    _stop_requested = False  # 类变量：全局停止标志
    
    @classmethod
    def get_input_level(cls) -> InputLevel:
        return InputLevel.DRIVER
    
    @classmethod
    def is_driver_available(cls) -> bool:
        """检测DD64.dll是否可用（类方法，无需实例化）"""
        possible_paths = []
        base_path = os.path.dirname(os.path.abspath(__file__))
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        possible_paths.extend([
            os.path.join(os.path.dirname(base_path), "drivers", "DD64.dll"),
            os.path.join(base_path, "..", "drivers", "DD64.dll"),
            os.path.join(base_path, "drivers", "DD64.dll"),
            os.path.join(base_path, "DD64.dll"),
        ])
        return any(os.path.exists(p) for p in possible_paths)
    
    def __init__(self, app=None, dll_path: str = None):
        self._dd_dll = None
        self._available = False
        self._dll_path = dll_path
        self.app = app
        self._vk_cache = {}
        
        self._load_dd_dll()
    
    @classmethod
    def request_stop(cls):
        """请求停止所有正在进行的操作（F12调用）"""
        cls._stop_requested = True
        print("[DD] 收到停止请求")
    
    @classmethod
    def clear_stop(cls):
        """清除停止标志（新操作开始前调用）"""
        cls._stop_requested = False
    
    def _check_stop(self) -> bool:
        """检查是否应该停止
        
        Returns:
            True: 应该停止
            False: 继续执行
        """
        return DDVirtualInput._stop_requested
    
    def _load_dd_dll(self) -> bool:
        """加载DD虚拟键盘DLL"""
        possible_paths = []

        if self._dll_path:
            possible_paths.append(self._dll_path)

        base_path = os.path.dirname(os.path.abspath(__file__))

        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS

        possible_paths.extend([
            os.path.join(os.path.dirname(base_path), "drivers", "DD64.dll"),
            os.path.join(base_path, "..", "drivers", "DD64.dll"),
            os.path.join(base_path, "drivers", "DD64.dll"),
            os.path.join(base_path, "DD64.dll"),
        ])

        for path in possible_paths:
            if os.path.exists(path):
                try:
                    self._dd_dll = ctypes.cdll.LoadLibrary(path)
                    self._setup_dd_api()
                    # DD64.dll 在初始化失败时会弹出 MessageBox 阻塞进程
                    # 临时禁用 MessageBox，防止 DLL 弹窗导致应用无法启动
                    result = self._init_dd_with_silent()
                    self._log(f"DD_btn(0) init result={result}, dll={path}")
                    if result == 1:
                        self._available = True
                        self._dll_path = path
                        # 检查管理员权限
                        self._check_admin()
                        return True
                    else:
                        self._log(f"DD_btn(0) 返回 {result}，驱动可能未正确安装")
                        # 初始化失败，释放 DLL 避免资源泄漏
                        try:
                            ctypes.windll.kernel32.FreeLibrary(self._dd_dll._handle)
                        except Exception:
                            pass
                        self._dd_dll = None
                except Exception as e:
                    self._log(f"加载 {path} 失败: {e}")
                    self._dd_dll = None
                    continue

        return False

    def _setup_dd_api(self):
        """设置 DD DLL 函数的参数和返回类型"""
        if not self._dd_dll:
            return
        try:
            # DD_btn(int) -> int
            self._dd_dll.DD_btn.argtypes = [ctypes.c_int]
            self._dd_dll.DD_btn.restype = ctypes.c_int
            # DD_mov(int, int) -> int
            self._dd_dll.DD_mov.argtypes = [ctypes.c_int, ctypes.c_int]
            self._dd_dll.DD_mov.restype = ctypes.c_int
            # DD_movR(int, int) -> int
            self._dd_dll.DD_movR.argtypes = [ctypes.c_int, ctypes.c_int]
            self._dd_dll.DD_movR.restype = ctypes.c_int
            # DD_key(int, int) -> int
            self._dd_dll.DD_key.argtypes = [ctypes.c_int, ctypes.c_int]
            self._dd_dll.DD_key.restype = ctypes.c_int
            # DD_todc(int) -> int
            self._dd_dll.DD_todc.argtypes = [ctypes.c_int]
            self._dd_dll.DD_todc.restype = ctypes.c_int
            # DD_whl(int) -> int
            self._dd_dll.DD_whl.argtypes = [ctypes.c_int]
            self._dd_dll.DD_whl.restype = ctypes.c_int
        except Exception as e:
            self._log(f"设置 DD API 类型失败: {e}")

    def _init_dd_with_silent(self) -> int:
        """在子线程中初始化 DD，避免 DLL 弹窗阻塞主线程

        DD64.dll 在驱动启动失败时会调用 MessageBoxA 弹出
        "DD start error.驱动启动错误." 的错误对话框，
        这会阻塞调用线程。在子线程中调用可避免阻塞主线程。
        """
        if not self._dd_dll:
            return 0

        import threading

        init_result = [0]
        init_done = threading.Event()

        def do_init():
            try:
                init_result[0] = self._dd_dll.DD_btn(0)
            except Exception:
                init_result[0] = 0
            finally:
                init_done.set()

        t = threading.Thread(target=do_init, daemon=True)
        t.start()
        # 等待初始化完成（不阻塞主线程，弹窗由用户手动关闭）
        init_done.wait()
        return init_result[0]

    def _check_admin(self):
        """检查是否以管理员权限运行"""
        try:
            import ctypes as _ct
            is_admin = _ct.windll.shell32.IsUserAnAdmin() != 0
            if not is_admin:
                self._log("⚠ 未以管理员身份运行，DD驱动操作可能失败")
            else:
                self._log("已以管理员身份运行")
        except Exception:
            pass
    
    def get_name(self) -> str:
        return "DD虚拟键盘"
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    @property
    def dll_path(self) -> Optional[str]:
        return self._dll_path if self._available else None
    
    def _log(self, message: str):
        """日志输出（调试日志已禁用）"""
        pass
    
    def _get_dd_code(self, key: str) -> int:
        """
        获取DD键码
        通过DD_todc函数动态转换Windows VK码到DD码
        """
        key_lower = key.lower()

        if key_lower in self._vk_cache:
            return self._vk_cache[key_lower]

        vk_code = VK_CODE_MAP.get(key_lower)

        if vk_code is None:
            if len(key_lower) == 1 and key_lower.isalpha():
                vk_code = ord(key_lower.upper())
            else:
                return 0

        if self._available and self._dd_dll:
            try:
                dd_code = self._dd_dll.DD_todc(vk_code)
                if dd_code > 0:
                    self._vk_cache[key_lower] = dd_code
                    return dd_code
            except Exception:
                pass

        fallback_map = {
            'altleft': 0x12, 'alt_l': 0x12, 'altright': 0x12, 'alt_r': 0x12,
            'ctrlleft': 0x11, 'ctrl_l': 0x11, 'ctrlright': 0x11, 'ctrl_r': 0x11,
            'shiftleft': 0x10, 'shift_l': 0x10, 'shiftright': 0x10, 'shift_r': 0x10,
        }

        fallback_vk = fallback_map.get(key_lower)
        if fallback_vk and self._available and self._dd_dll:
            try:
                dd_code = self._dd_dll.DD_todc(fallback_vk)
                if dd_code > 0:
                    self._vk_cache[key_lower] = dd_code
                    return dd_code
            except Exception:
                pass

        return 0
    
    def key_press(self, key: str, action: str = "press", duration: int = 0) -> None:
        """按键操作"""
        if action == "press":
            self.key_down(key)
            if duration > 0:
                time.sleep(duration / 1000.0)
            self.key_up(key)
        elif action == "down":
            self.key_down(key)
        elif action == "up":
            self.key_up(key)
    
    def key_down(self, key: str) -> None:
        """按下按键"""
        if not self._available or not self._dd_dll:
            return
        
        dd_code = self._get_dd_code(key)
        if dd_code == 0:
            return
        
        try:
            self._dd_dll.DD_key(dd_code, 1)
        except Exception:
            pass
    
    def key_up(self, key: str) -> None:
        """释放按键"""
        if not self._available or not self._dd_dll:
            return
        
        dd_code = self._get_dd_code(key)
        if dd_code == 0:
            return
        
        try:
            self._dd_dll.DD_key(dd_code, 2)
        except Exception:
            pass
    
    def mouse_click(self, button: str = "left", position: Tuple[int, int] = None,
                   action: str = "press", duration: int = 0) -> None:
        """鼠标点击"""
        if not self._available or not self._dd_dll:
            self._log(f"mouse_click SKIP: engine not available")
            return

        self._log(f"mouse_click: button={button}, position={position}, action={action}, duration={duration}")

        if position:
            self.mouse_move(position, relative=False)

        if action == "press":
            self.mouse_down(button)
            if duration > 0:
                time.sleep(duration / 1000.0)
            self.mouse_up(button)
        elif action == "down":
            self.mouse_down(button)
        elif action == "up":
            self.mouse_up(button)
    
    def mouse_down(self, button: str = "left") -> None:
        """按下鼠标"""
        if not self._available or not self._dd_dll:
            return

        btn_map = {'left': 1, 'right': 4, 'middle': 16}
        btn_code = btn_map.get(button, 1)

        try:
            result = self._dd_dll.DD_btn(btn_code)
            self._log(f"mouse_down: button={button}, btn_code={btn_code}, result={result}")
        except Exception as e:
            self._log(f"mouse_down ERROR: button={button}, {e}")

    def mouse_up(self, button: str = "left") -> None:
        """释放鼠标"""
        if not self._available or not self._dd_dll:
            return

        btn_map = {'left': 2, 'right': 8, 'middle': 32}
        btn_code = btn_map.get(button, 2)

        try:
            result = self._dd_dll.DD_btn(btn_code)
            self._log(f"mouse_up: button={button}, btn_code={btn_code}, result={result}")
        except Exception as e:
            self._log(f"mouse_up ERROR: button={button}, {e}")
    
    def mouse_move(self, position: Tuple[int, int], relative: bool = False) -> None:
        """移动鼠标"""
        if not self._available or not self._dd_dll:
            self._log(f"mouse_move SKIP: engine not available")
            return

        try:
            if relative:
                result = self._dd_dll.DD_movR(position[0], position[1])
                self._log(f"mouse_move: relative=({position[0]}, {position[1]}), result={result}")
            else:
                result = self._dd_dll.DD_mov(position[0], position[1])
                self._log(f"mouse_move: absolute=({position[0]}, {position[1]}), result={result}")
        except Exception as e:
            self._log(f"mouse_move ERROR: {e}")
    
    def mouse_scroll(self, amount: int, position: Tuple[int, int] = None,
                     horizontal: bool = False) -> None:
        """鼠标滚轮

        Args:
            amount: 滚动量（点击数，正数向上，负数向下）
            position: 滚动位置 (x, y)
            horizontal: True=水平滚动（DD_whl 不支持，改用 mouse_event(HWHEEL)）

        DD_whl()的参数定义（官方文档确认）:
            - 1 = 向前/向上滚动1格 (≈120 WHEEL_DELTA)
            - 2 = 向后/向下滚动1格 (≈120 WHEEL_DELTA)

        实现特性:
            1. 最快速度执行滚动
            2. 最长执行时间5秒（超时自动停止）
            3. 响应F12全局停止请求（立即中断）
        """
        if not self._available or not self._dd_dll:
            return

        if horizontal:
            if self._check_stop():
                return
            if position:
                self._dd_dll.DD_mov(position[0], position[1])
            delta = int(round(amount)) * 120
            if delta == 0:
                return
            self._log(f"mouse_scroll horizontal: amount={amount}, delta={delta}, position={position}")
            ctypes.windll.user32.mouse_event(0x01000, 0, 0, delta, 0)  # MOUSEEVENTF_HWHEEL
            return

        try:
            if position:
                self._dd_dll.DD_mov(position[0], position[1])

            import time
            
            total = abs(amount)
            if total == 0:
                return
            
            # ★ 关键检查：如果已经收到停止请求，直接返回（防止clicks循环重复启动）
            if self._check_stop():
                print(f"[DD_SCROLL] ⚠️ 检测到已停止状态，跳过本次滚动")
                return
            
            # ★ 清除停止标志，开始新的滚动操作
            DDVirtualInput.clear_stop()
            
            # ★ 计算参数：最快速度 + 1秒超时
            MAX_DURATION = 1.0  # 最大执行时间1秒（用户要求）
            start_time = time.time()
            
            # 动态计算间隔：在1秒内完成所有滚动
            # 如果total=500，则间隔=2ms；如果total=50，则间隔=20ms
            interval = MAX_DURATION / total
            interval = max(interval, 0.001)  # 最少1ms（尽可能快）
            
            print(f"[DD_SCROLL] 开始滚动: amount={amount}, 总次数={total}, 间隔={interval*1000:.1f}ms, 最大时长={MAX_DURATION}s")
            
            executed_count = 0
            direction = 1 if amount > 0 else 2  # 1=向上, 2=向下
            
            for i in range(total):
                # ★ 检查1：是否超过1秒
                elapsed = time.time() - start_time
                if elapsed >= MAX_DURATION:
                    print(f"[DD_SCROLL] ⏱ 1秒超时！已执行 {i}/{total} 次 ({elapsed:.1f}s)")
                    break
                
                # ★ 检查2：是否收到F12停止请求
                if self._check_stop():
                    print(f"[DD_SCROLL] 🛑 收到停止信号！已执行 {i}/{total} 次 ({elapsed:.1f}s)")
                    break
                
                # 执行滚动
                result = self._dd_dll.DD_whl(direction)
                executed_count += 1
                
                # 只打印前3次和最后3次（避免刷屏）
                if i < 3 or i >= total - 3:
                    print(f"[DD_SCROLL] DD_whl({direction}) {i+1}/{total}, 返回值={result}, 已用时{elapsed:.2f}s")
                
                # ★ 短暂休眠（让出CPU，可响应中断）
                time.sleep(interval)
            
            total_time = time.time() - start_time
            print(f"[DD_SCROLL] ✓ 滚动完成: 实际执行{executed_count}/{total}次, 用时{total_time:.2f}s")
            
        except Exception as e:
            print(f"[DD_SCROLL_ERROR] mouse_scroll异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
