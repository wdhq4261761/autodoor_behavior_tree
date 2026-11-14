"""MouseMoveNode 插值落点精确性测试。"""
from unittest.mock import MagicMock

import pytest

from bt_core.config import NodeConfig
from bt_core.nodes import NodeStatus
from bt_nodes.actions.mouse import MouseMoveNode


@pytest.fixture
def no_sleep(monkeypatch):
    """跳过真实 sleep，模拟循环在到达 progress==1.0 前就用尽 steps。"""
    monkeypatch.setattr("bt_nodes.actions.mouse.time.sleep", lambda *_: None)


def _make_node(config_dict):
    return MouseMoveNode(
        node_id="move",
        config=NodeConfig.from_dict({"name": "move", **config_dict}),
    )


def _make_context():
    ctx = MagicMock()
    ctx.check_running.return_value = True
    ctx.get_bound_window.return_value = None
    return ctx


def _move_calls(ctx):
    return [c for c in ctx.execute_mouse_move.call_args_list]


def _last_move(ctx):
    return _move_calls(ctx)[-1]


def test_move_lands_exactly_on_end_position(no_sleep):
    node = _make_node({
        "position": (10, 10),
        "end_position": (120, 88),
        "move_type": "移动",
        "move_duration": 60,
    })
    ctx = _make_context()

    status = node.tick(ctx)

    assert status == NodeStatus.SUCCESS
    last = _last_move(ctx)
    assert last.args[0] == (120, 88)
    assert last.kwargs.get("x_float") == 0
    assert last.kwargs.get("y_float") == 0


def test_drag_lands_exactly_before_button_up(no_sleep):
    node = _make_node({
        "position": (10, 10),
        "end_position": (200, 150),
        "move_type": "拖拽",
        "move_duration": 60,
    })
    ctx = _make_context()

    status = node.tick(ctx)

    assert status == NodeStatus.SUCCESS
    calls = ctx.mock_calls
    last_move_index = max(
        i for i, c in enumerate(calls)
        if c[0] == "execute_mouse_move"
    )
    up_indices = [
        i for i, c in enumerate(calls)
        if c[0] == "execute_mouse_click" and c[1][2] == "up"
    ]
    assert up_indices
    up_index = up_indices[-1]

    assert last_move_index < up_index
    move_call = calls[last_move_index]
    assert move_call[1][0] == (200, 150)
    assert move_call[2].get("x_float") == 0
    assert move_call[2].get("y_float") == 0


def test_move_zero_duration_still_ends_on_target(no_sleep):
    node = _make_node({
        "position": (10, 10),
        "end_position": (120, 88),
        "move_type": "移动",
        "move_duration": 0,
    })
    ctx = _make_context()

    status = node.tick(ctx)

    assert status == NodeStatus.SUCCESS
    assert _last_move(ctx).args[0] == (120, 88)


def test_move_with_jitter_ends_without_jitter(no_sleep):
    node = _make_node({
        "position": (10, 10),
        "end_position": (120, 88),
        "move_type": "移动",
        "move_duration": 60,
        "x_float": 3,
        "y_float": 3,
    })
    ctx = _make_context()

    status = node.tick(ctx)

    assert status == NodeStatus.SUCCESS
    last = _last_move(ctx)
    assert last.args[0] == (120, 88)
    assert last.kwargs.get("x_float") == 0
    assert last.kwargs.get("y_float") == 0
