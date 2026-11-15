"""
IbInputSimulator 输入控制器实现

通过 IbInputSimulator.dll 实现多驱动输入模拟，
支持罗技/雷蛇/MouClassInputInjection 等多种硬件厂商驱动。

核心机制：
  IbSendInputHook hook 的是 SendInput API。
  Python 中必须使用 SendInput（而非 keybd_event/mouse_event）才能被 hook 拦截。

  操作模式（参考 AHK 绑定）：
    Hook ON → SendInput → Hook OFF（每次操作都切换，避免拦截其他输入）

  注意：不同驱动模式对鼠标的支持情况不同：
    - Logitech LGS: 支持鼠标
    - Logitech G HUB ≥ 2022.3.2300: 不支持鼠标（Issue #8）
    - Razer Synapse: 支持鼠标
    - MouClassInputInjection: 支持鼠标
    - SendInput: 支持鼠标
    用户需自行选择和尝试，如果某个驱动模式下鼠标不工作，可切换鼠标引擎。

DLL API 参考（来自官方 AHK2 绑定 IbInputSimulator.ahk v0.4.1）：
  IbSendInit(int send_type, int mode, void* args) → int
    send_type: 0=AnyDriver, 1=SendInput, 2=Logitech, 3=Razer,
               5=MouClassInputInjection, 6=LogitechGHubNew
    mode: 0=不Hook, 1=Hook SendInput
    args: MCII模式传UInt64进程ID, 其他传NULL
    返回: 0=成功, 1=InvalidArgument, 2=LibraryNotFound, 3=LibraryLoadFailed,
          4=LibraryError, 5=DeviceCreateFailed, 6=DeviceNotFound, 7=DeviceOpenFailed
  IbSendInputHook(int mode) → void
    mode: 1=Hook, 0=Unhook
  IbSendDestroy() → void
  IbSendSyncKeyStates() → void
"""
import os
import sys
import ctypes
import ctypes.wintypes
import time
from typing import Optional, Tuple
from contextlib import contextmanager

from .base_input import BaseInputController, InputLevel
from .dd_input import VK_CODE_MAP
from .log_manager import LogManager

# IbSendInit 的 send_type 整数值（来自官方 AHK 绑定）
IB_SEND_TYPE_INT = {
    "any_driver": 0,
    "send_input": 1,
    "logitech": 2,
    "razer": 3,
    "mou_class": 5,
    "logitech_ghub_new": 6,
}

# IbSendInit 返回的错误码
IB_INIT_ERRORS = {
    0: "成功",
    1: "InvalidArgument",
    2: "LibraryNotFound",
    3: "LibraryLoadFailed",
    4: "LibraryError",
    5: "DeviceCreateFailed",
    6: "DeviceNotFound",
    7: "DeviceOpenFailed",
}

# ── SendInput 相关常量与结构体 ──

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# 键盘事件标志
KEYEVENTF_KEYUP = 0x0002

# 鼠标事件标志
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
MOUSEEVENTF_ABSOLUTE = 0x8000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", _INPUT_UNION),
    ]


def is_logitech_ghub_installed() -> bool:
    """检测 Logitech G HUB 是否已安装"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Logitech\G HUB", 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        winreg.CloseKey(key)
        return True
    except (OSError, ImportError):
        pass

    ghub_paths = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "LGHUB"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "LGHUB"),
    ]
    for p in ghub_paths:
        if os.path.isdir(p):
            return True

    return False


def is_logitech_lgs_installed() -> bool:
    """检测 Logitech Gaming Software 是否已安装"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Logitech\Gaming Software", 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        winreg.CloseKey(key)
        return True
    except (OSError, ImportError):
        pass

    lgs_paths = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Logitech Gaming Software"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Logitech Gaming Software"),
    ]
    for p in lgs_paths:
        if os.path.isdir(p):
            return True

    return False


def is_razer_synapse_installed() -> bool:
    """检测 Razer Synapse 是否已安装"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Razer\Synapse3", 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        winreg.CloseKey(key)
        return True
    except (OSError, ImportError):
        pass

    razer_paths = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Razer"),
    ]
    for p in razer_paths:
        if os.path.isdir(p):
            return True

    return False


def detect_ib_driver_status() -> dict:
    """检测本机可用的 IbInputSimulator 驱动"""
    return {
        "logitech": {
            "name": "Logitech LGS",
            "installed": is_logitech_lgs_installed(),
        },
        "logitech_ghub_new": {
            "name": "Logitech G HUB (新版)",
            "installed": is_logitech_ghub_installed(),
        },
        "razer": {
            "name": "Razer Synapse",
            "installed": is_razer_synapse_installed(),
        },
    }


class IbInputSimulatorInput(BaseInputController):
    """IbInputSimulator 多驱动输入控制器

    键盘和鼠标均通过 Hook + SendInput 走驱动层。
    不同驱动模式对鼠标的支持情况不同，用户需自行尝试。
    """

    def __init__(self, app=None, dll_path: str = None, send_mode: str = None, target_pid: int = 0):
        self._ib_dll = None
        self._available = False
        self._dll_path = dll_path
        self._send_mode = send_mode or self._load_send_mode()
        self._target_pid = target_pid or self._load_target_pid()
        self.app = app

        self._load_ib_dll()

    @classmethod
    def get_input_level(cls) -> InputLevel:
        return InputLevel.DRIVER

    @classmethod
    def is_driver_available(cls) -> bool:
        """检测 IbInputSimulator.dll 是否可用"""
        possible_paths = cls._get_dll_paths()
        return any(os.path.exists(p) for p in possible_paths)

    @classmethod
    def _get_dll_paths(cls):
        possible_paths = []
        base_path = os.path.dirname(os.path.abspath(__file__))
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        possible_paths.extend([
            os.path.join(os.path.dirname(base_path), "drivers", "IbInputSimulator.dll"),
            os.path.join(base_path, "..", "drivers", "IbInputSimulator.dll"),
            os.path.join(base_path, "drivers", "IbInputSimulator.dll"),
            os.path.join(base_path, "IbInputSimulator.dll"),
        ])
        return possible_paths

    def _load_send_mode(self) -> str:
        try:
            from config.settings_manager import SettingsManager
            return SettingsManager.get_instance().get("input.ib_send_mode", "any_driver")
        except Exception:
            return "any_driver"

    def _load_target_pid(self) -> int:
        try:
            from config.settings_manager import SettingsManager
            return SettingsManager.get_instance().get("input.ib_target_pid", 0)
        except Exception:
            return 0

    def _load_ib_dll(self) -> bool:
        """加载 IbInputSimulator DLL 并初始化驱动"""
        possible_paths = []

        if self._dll_path:
            possible_paths.append(self._dll_path)

        possible_paths.extend(self._get_dll_paths())

        for path in possible_paths:
            if os.path.exists(path):
                try:
                    self._ib_dll = ctypes.cdll.LoadLibrary(path)

                    send_type = IB_SEND_TYPE_INT.get(self._send_mode, 0)

                    self._ib_dll.IbSendInit.restype = ctypes.c_int

                    if self._send_mode == "mou_class" and self._target_pid > 0:
                        self._ib_dll.IbSendInit.argtypes = [
                            ctypes.c_int, ctypes.c_int, ctypes.c_uint64
                        ]
                        result = self._ib_dll.IbSendInit(send_type, 0, self._target_pid)
                    else:
                        self._ib_dll.IbSendInit.argtypes = [
                            ctypes.c_int, ctypes.c_int, ctypes.c_void_p
                        ]
                        result = self._ib_dll.IbSendInit(send_type, 0, None)

                    if result == 0:
                        try:
                            self._ib_dll.IbSendSyncKeyStates.restype = None
                            self._ib_dll.IbSendSyncKeyStates.argtypes = []
                            self._ib_dll.IbSendSyncKeyStates()
                        except Exception:
                            pass

                        self._available = True
                        self._dll_path = path
                        return True
                    else:
                        error_msg = IB_INIT_ERRORS.get(result, f"未知错误({result})")
                        self._log(f"IbSendInit 失败: {error_msg} (send_type={send_type})")
                except Exception:
                    continue

        return False

    @property
    def is_available(self) -> bool:
        return self._available

    def get_name(self) -> str:
        return f"IbInputSimulator({self._send_mode})"

    def _log(self, message: str):
        pass

    def _get_vk_code(self, key: str) -> int:
        """获取 Windows VK 码"""
        key_lower = key.lower()
        vk_code = VK_CODE_MAP.get(key_lower)
        if vk_code is None:
            if len(key_lower) == 1 and key_lower.isalpha():
                vk_code = ord(key_lower.upper())
        return vk_code or 0

    # ── Hook 管理 ──

    @contextmanager
    def _hook_context(self):
        """Hook 上下文管理器：Hook ON → 操作 → Hook OFF"""
        try:
            self._ib_dll.IbSendInputHook(1)
            yield
        finally:
            try:
                self._ib_dll.IbSendInputHook(0)
            except Exception:
                pass

    # ── SendInput 发送 ──

    def _send_inputs(self, inputs) -> int:
        """通过 SendInput 发送输入数组，返回成功插入的事件数"""
        n = len(inputs)
        for i, inp in enumerate(inputs):
            if inp.type == INPUT_MOUSE:
                mi = inp.union.mi
                self._log(f"  [{i}] MOUSE: dx={mi.dx}, dy={mi.dy}, data={mi.mouseData}, "
                          f"flags=0x{mi.dwFlags:X} "
                          f"({'ABSOLUTE' if mi.dwFlags & MOUSEEVENTF_ABSOLUTE else 'REL'} "
                          f"{'MOVE' if mi.dwFlags & MOUSEEVENTF_MOVE else ''} "
                          f"{'LDOWN' if mi.dwFlags & MOUSEEVENTF_LEFTDOWN else ''} "
                          f"{'LUP' if mi.dwFlags & MOUSEEVENTF_LEFTUP else ''} "
                          f"{'RDOWN' if mi.dwFlags & MOUSEEVENTF_RIGHTDOWN else ''} "
                          f"{'RUP' if mi.dwFlags & MOUSEEVENTF_RIGHTUP else ''} "
                          f"{'MDOWN' if mi.dwFlags & MOUSEEVENTF_MIDDLEDOWN else ''} "
                          f"{'MUP' if mi.dwFlags & MOUSEEVENTF_MIDDLEUP else ''} "
                          f"{'WHEEL' if mi.dwFlags & MOUSEEVENTF_WHEEL else ''})")
            elif inp.type == INPUT_KEYBOARD:
                ki = inp.union.ki
                self._log(f"  [{i}] KEY: vk=0x{ki.wVk:02X}, flags=0x{ki.dwFlags:X}")
        arr = (INPUT * n)(*inputs)
        user32 = ctypes.windll.user32
        user32.SendInput.restype = ctypes.c_uint
        result = user32.SendInput(n, ctypes.byref(arr[0]), ctypes.sizeof(INPUT))
        self._log(f"  SendInput({n} events, cbSize={ctypes.sizeof(INPUT)}) → result={result}")
        return result

    def _make_keyboard_input(self, vk_code: int, flags: int = 0) -> INPUT:
        """构造键盘 INPUT 结构体"""
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk_code
        inp.union.ki.wScan = 0
        inp.union.ki.dwFlags = flags
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = 0
        return inp

    def _make_mouse_input(self, dx: int = 0, dy: int = 0, mouse_data: int = 0,
                          flags: int = 0) -> INPUT:
        """构造鼠标 INPUT 结构体"""
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = dx
        inp.union.mi.dy = dy
        inp.union.mi.mouseData = mouse_data
        inp.union.mi.dwFlags = flags
        inp.union.mi.time = 0
        inp.union.mi.dwExtraInfo = 0
        return inp

    # ── 坐标归一化 ──

    def _normalize_position(self, position: Tuple[int, int]) -> Tuple[int, int]:
        """将屏幕坐标归一化到 0~65535（MOUSEEVENTF_ABSOLUTE 使用）"""
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN
        if screen_w > 0 and screen_h > 0:
            norm_x = int(position[0] * 65535 / screen_w)
            norm_y = int(position[1] * 65535 / screen_h)
        else:
            norm_x, norm_y = position[0], position[1]
        return norm_x, norm_y

    # ── 键盘操作 ──

    def key_press(self, key: str, action: str = "press", duration: int = 0) -> None:
        """按键操作（Hook + SendInput，驱动层）"""
        if not self._available:
            return

        vk_code = self._get_vk_code(key)
        if vk_code == 0:
            return

        with self._hook_context():
            if action == "press":
                self._send_inputs([self._make_keyboard_input(vk_code, 0)])
                if duration > 0:
                    time.sleep(duration / 1000.0)
                self._send_inputs([self._make_keyboard_input(vk_code, KEYEVENTF_KEYUP)])
            elif action == "down":
                self._send_inputs([self._make_keyboard_input(vk_code, 0)])
            elif action == "up":
                self._send_inputs([self._make_keyboard_input(vk_code, KEYEVENTF_KEYUP)])

    def key_down(self, key: str) -> None:
        if not self._available:
            return
        vk_code = self._get_vk_code(key)
        if vk_code:
            with self._hook_context():
                self._send_inputs([self._make_keyboard_input(vk_code, 0)])

    def key_up(self, key: str) -> None:
        if not self._available:
            return
        vk_code = self._get_vk_code(key)
        if vk_code:
            with self._hook_context():
                self._send_inputs([self._make_keyboard_input(vk_code, KEYEVENTF_KEYUP)])

    # ── 鼠标操作（Hook + SendInput，驱动层） ──

    def _move_to(self, position: Tuple[int, int]) -> None:
        """驱动层鼠标移动：SetCursorPos + SendInput MOVE|ABSOLUTE"""
        ctypes.windll.user32.SetCursorPos(position[0], position[1])
        norm_x, norm_y = self._normalize_position(position)
        self._log(f"  SetCursorPos to ({position[0]}, {position[1]}), norm=({norm_x}, {norm_y})")
        self._send_inputs([self._make_mouse_input(
            dx=norm_x, dy=norm_y, flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)])

    _MOUSE_BUTTON_FLAGS = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }

    def mouse_click(self, button: str = "left", position: Tuple[int, int] = None,
                   action: str = "press", duration: int = 0) -> None:
        """鼠标点击（Hook + SendInput，驱动层）

        所有鼠标事件都包含 MOUSEEVENTF_ABSOLUTE + 归一化坐标，
        与 PyAutoGUI 的 mouse_event 实现一致，确保驱动知道点击位置。
        """
        if not self._available:
            return

        self._log(f"mouse_click: button={button}, position={position}, action={action}, duration={duration}")
        down_flag, up_flag = self._MOUSE_BUTTON_FLAGS.get(button, self._MOUSE_BUTTON_FLAGS["left"])

        with self._hook_context():
            # 获取归一化坐标（移动事件需要）
            if position:
                self._move_to(position)
                norm_x, norm_y = self._normalize_position(position)
            else:
                # 无指定位置时，获取当前光标位置
                point = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
                norm_x, norm_y = self._normalize_position((point.x, point.y))
            self._log(f"  click norm=({norm_x}, {norm_y})")

            # 点击事件：尝试两种方式
            # 方式1: ABSOLUTE + 坐标（驱动可能不支持）
            # 方式2: 不带ABSOLUTE, dx=0,dy=0（在当前位置点击）
            if action == "press":
                self._send_inputs([self._make_mouse_input(flags=down_flag)])
                if duration > 0:
                    time.sleep(duration / 1000.0)
                self._send_inputs([self._make_mouse_input(flags=up_flag)])
            elif action == "down":
                self._send_inputs([self._make_mouse_input(flags=down_flag)])
            elif action == "up":
                self._send_inputs([self._make_mouse_input(flags=up_flag)])

    def mouse_down(self, button: str = "left") -> None:
        """按下鼠标（Hook + SendInput，驱动层）"""
        if not self._available:
            return
        down_flag, _ = self._MOUSE_BUTTON_FLAGS.get(button, self._MOUSE_BUTTON_FLAGS["left"])
        self._log(f"mouse_down: button={button}")
        with self._hook_context():
            self._send_inputs([self._make_mouse_input(flags=down_flag)])

    def mouse_up(self, button: str = "left") -> None:
        """释放鼠标（Hook + SendInput，驱动层）"""
        if not self._available:
            return
        _, up_flag = self._MOUSE_BUTTON_FLAGS.get(button, self._MOUSE_BUTTON_FLAGS["left"])
        self._log(f"mouse_up: button={button}")
        with self._hook_context():
            self._send_inputs([self._make_mouse_input(flags=up_flag)])

    def mouse_move(self, position: Tuple[int, int], relative: bool = False) -> None:
        """移动鼠标（Hook + SendInput，驱动层）"""
        if not self._available:
            return

        self._log(f"mouse_move: target=({position[0]}, {position[1]}), relative={relative}")
        with self._hook_context():
            if relative:
                self._send_inputs([self._make_mouse_input(
                    dx=position[0], dy=position[1], flags=MOUSEEVENTF_MOVE)])
            else:
                self._move_to(position)

    def mouse_scroll(self, amount: int, position: Tuple[int, int] = None,
                     horizontal: bool = False) -> None:
        """鼠标滚轮（Hook + SendInput，驱动层）"""
        if not self._available:
            return

        self._log(f"mouse_scroll: amount={amount}, position={position}, horizontal={horizontal}")
        delta = int(round(amount)) * 120  # WHEEL_DELTA = 120
        if delta == 0:
            return
        flags = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
        with self._hook_context():
            if position:
                self._move_to(position)
            self._send_inputs([self._make_mouse_input(
                mouse_data=delta, flags=flags)])

    def cleanup(self) -> None:
        """销毁驱动"""
        if self._available and self._ib_dll:
            try:
                self._ib_dll.IbSendDestroy.restype = None
                self._ib_dll.IbSendDestroy.argtypes = []
                self._ib_dll.IbSendDestroy()
            except Exception:
                pass
            self._available = False
