"""鼠标滚轮：各输入引擎的单位换算、水平滚动，以及节点与上下文的协作"""
import contextlib
import ctypes
from unittest import mock

from bt_core.config import NodeConfig
from bt_core.context import ExecutionContext
from bt_core.nodes import NodeStatus
from bt_nodes.actions.scroll import MouseScrollNode
from bt_utils.bg_input import (
    BackgroundInputController,
    WM_MOUSEHWHEEL,
)
from bt_utils.ib_input import (
    IbInputSimulatorInput,
    MOUSEEVENTF_HWHEEL,
    MOUSEEVENTF_WHEEL,
)
from bt_utils.input_controller_factory import PyAutoGUIInput


# ── PyAutoGUI ──

def _make_pyautogui():
    return object.__new__(PyAutoGUIInput)


def test_pyautogui_vertical_scroll_scales_to_wheel_delta():
    engine = _make_pyautogui()
    with mock.patch("pyautogui.scroll") as scroll:
        engine.mouse_scroll(3)
    scroll.assert_called_once_with(360)


def test_pyautogui_horizontal_scroll_uses_hwheel():
    engine = _make_pyautogui()
    with mock.patch("pyautogui.scroll") as scroll, \
            mock.patch.object(ctypes.windll.user32, "mouse_event") as mouse_event:
        engine.mouse_scroll(2, horizontal=True)
    scroll.assert_not_called()
    assert mouse_event.call_args[0][0] == 0x01000
    assert mouse_event.call_args[0][3] == 240


def test_pyautogui_zero_amount_sends_nothing():
    engine = _make_pyautogui()
    with mock.patch("pyautogui.scroll") as scroll, \
            mock.patch.object(ctypes.windll.user32, "mouse_event") as mouse_event:
        engine.mouse_scroll(0)
    scroll.assert_not_called()
    mouse_event.assert_not_called()


def test_pyautogui_uses_round_for_non_integer_amount():
    # distance 在 UI/配置中是整数；这里锁定 int(round()) 的现有行为（2.5 -> 2 格）
    engine = _make_pyautogui()
    with mock.patch("pyautogui.scroll") as scroll:
        engine.mouse_scroll(2.5)
    scroll.assert_called_once_with(240)


# ── IbInputSimulator ──

def _make_ib():
    engine = object.__new__(IbInputSimulatorInput)
    engine._available = True
    sent = []
    engine._hook_context = lambda: contextlib.nullcontext()
    engine._send_inputs = lambda inputs: sent.extend(inputs) or len(inputs)
    return engine, sent


def test_ib_horizontal_scroll_uses_hwheel_flags():
    engine, sent = _make_ib()
    engine.mouse_scroll(2, horizontal=True)
    assert len(sent) == 1
    assert sent[0].union.mi.mouseData == 240
    assert sent[0].union.mi.dwFlags == MOUSEEVENTF_HWHEEL


def test_ib_vertical_scroll_uses_wheel_flags():
    engine, sent = _make_ib()
    engine.mouse_scroll(2)
    assert len(sent) == 1
    assert sent[0].union.mi.mouseData == 240
    assert sent[0].union.mi.dwFlags == MOUSEEVENTF_WHEEL


def test_ib_negative_horizontal_scroll_keeps_sign():
    engine, sent = _make_ib()
    engine.mouse_scroll(-2, horizontal=True)
    assert len(sent) == 1
    assert sent[0].union.mi.mouseData & 0xFFFFFFFF == 0xFFFFFF10
    assert sent[0].union.mi.dwFlags == MOUSEEVENTF_HWHEEL


# ── 后台消息 ──

def _make_bg(hwnd=0x1234):
    engine = object.__new__(BackgroundInputController)
    engine._hwnd = hwnd
    engine._available = True
    return engine


def test_bg_horizontal_scroll_posts_hwheel_message(monkeypatch):
    engine = _make_bg()
    calls = []

    def fake_post(hwnd, msg, wparam, lparam):
        calls.append((hwnd, msg, wparam, lparam))
        return 1

    def fake_client_to_screen(hwnd, ptr):
        return 1

    monkeypatch.setattr("bt_utils.bg_input.user32.PostMessageW", fake_post)
    monkeypatch.setattr("bt_utils.bg_input.user32.ClientToScreen", fake_client_to_screen)

    engine.mouse_scroll(2, horizontal=True)

    assert len(calls) == 1
    _, msg, wparam, _ = calls[0]
    assert msg == WM_MOUSEHWHEEL
    assert (wparam >> 16) & 0xFFFF == 240


def test_bg_negative_horizontal_scroll_sign_extends_wparam(monkeypatch):
    engine = _make_bg()
    calls = []

    def fake_post(hwnd, msg, wparam, lparam):
        calls.append((hwnd, msg, wparam, lparam))
        return 1

    def fake_client_to_screen(hwnd, ptr):
        return 1

    monkeypatch.setattr("bt_utils.bg_input.user32.PostMessageW", fake_post)
    monkeypatch.setattr("bt_utils.bg_input.user32.ClientToScreen", fake_client_to_screen)

    engine.mouse_scroll(-1, horizontal=True)

    assert len(calls) == 1
    _, msg, wparam, _ = calls[0]
    assert msg == WM_MOUSEHWHEEL
    assert wparam == 0xFF880000  # delta=-120，高 16 位 0xFF88


# ── ExecutionContext ──

class _FakeEngine:
    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    def mouse_scroll(self, amount, position=None, horizontal=False):
        if self._fail:
            raise RuntimeError("boom")
        self.calls.append((amount, position, horizontal))


class _FakeManager:
    def __init__(self, engine):
        self._engine = engine

    def get_mouse_method(self):
        return "pyautogui"

    def get_mouse_engine(self, **kwargs):
        return self._engine


def _make_ctx(engine):
    ctx = ExecutionContext()
    ctx._get_input_manager = lambda: _FakeManager(engine)
    return ctx


def test_execute_mouse_scroll_returns_true_and_forwards_horizontal():
    engine = _FakeEngine()
    ctx = _make_ctx(engine)
    assert ctx.execute_mouse_scroll(2, horizontal=True) is True
    assert engine.calls == [(2, None, True)]


def test_execute_mouse_scroll_returns_false_without_engine():
    ctx = _make_ctx(None)
    assert ctx.execute_mouse_scroll(2) is False


def test_execute_mouse_scroll_returns_false_on_engine_error():
    ctx = _make_ctx(_FakeEngine(fail=True))
    assert ctx.execute_mouse_scroll(2) is False


def test_execute_mouse_scroll_returns_false_when_manager_raises():
    ctx = ExecutionContext()

    def boom():
        raise RuntimeError("manager unavailable")

    ctx._get_input_manager = boom
    assert ctx.execute_mouse_scroll(1) is False


# ── MouseScrollNode ──

class FakeContext:
    def __init__(self, result=True):
        self.calls = []
        self.is_running = True
        self._result = result

    def execute_mouse_scroll(self, amount, position=None, horizontal=False):
        self.calls.append((amount, horizontal))
        return self._result


def make_node(distance=5, clicks=1, direction="向上"):
    config = NodeConfig(name="滚轮")
    config.set("distance", distance)
    config.set("clicks", clicks)
    config.set("direction", direction)
    return MouseScrollNode(None, config)


def test_node_right_is_positive_horizontal():
    ctx = FakeContext()
    node = make_node(distance=2, clicks=1, direction="向右")
    assert node._execute_action(ctx) == NodeStatus.SUCCESS
    assert ctx.calls == [(2, True)]


def test_node_down_is_negative_vertical():
    ctx = FakeContext()
    node = make_node(distance=2, clicks=1, direction="向下")
    assert node._execute_action(ctx) == NodeStatus.SUCCESS
    assert ctx.calls == [(-2, False)]


def test_node_engine_failure_returns_failure():
    ctx = FakeContext(result=False)
    node = make_node(distance=2, clicks=1, direction="向上")
    assert node._execute_action(ctx) == NodeStatus.FAILURE


def test_node_unknown_direction_returns_failure():
    ctx = FakeContext()
    node = make_node(distance=2, clicks=1, direction="斜着")
    assert node._execute_action(ctx) == NodeStatus.FAILURE
    assert ctx.calls == []


def test_node_zero_distance_returns_failure():
    ctx = FakeContext()
    node = make_node(distance=0, clicks=1, direction="向上")
    assert node._execute_action(ctx) == NodeStatus.FAILURE
    assert ctx.calls == []
