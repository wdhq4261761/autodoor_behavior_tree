from types import SimpleNamespace

from bt_gui.bt_editor.window_state import apply_window_state, collect_window_state


def _node(node_id, config, children=None):
    return SimpleNamespace(node_id=node_id, config=config, children=children or [])


def test_collect_nested_window_state():
    root = _node("start", {"window_size": "800x600", "window_maximized": False}, [
        _node("img", {"template_path": "./images/a.png"}),
    ])
    assert collect_window_state(root) == {"start": {"window_size": "800x600", "window_maximized": False}}


def test_collect_skips_nodes_without_state():
    root = _node("seq", {"foo": "bar"})
    assert collect_window_state(root) == {}


def test_apply_updates_canvas_config():
    root = _node("start", {"window_size": "800x600", "window_maximized": False})
    canvas_nodes = {"start": SimpleNamespace(config={})}
    assert apply_window_state(root, canvas_nodes) == ["start"]
    assert canvas_nodes["start"].config == {"window_size": "800x600", "window_maximized": False}


def test_apply_is_noop_when_unchanged():
    root = _node("start", {"window_size": "800x600"})
    canvas_nodes = {"start": SimpleNamespace(config={"window_size": "800x600"})}
    assert apply_window_state(root, canvas_nodes) == []


def test_apply_ignores_missing_target_and_non_dict_config():
    root = _node("start", {"window_size": "800x600"})
    assert apply_window_state(root, {}) == []
    assert apply_window_state(root, {"start": SimpleNamespace(config=None)}) == []


def test_collect_handles_cycles_without_recursion_error():
    a = _node("a", {"window_size": "800x600"})
    b = _node("b", {})
    a.children = [b]
    b.children = [a]
    assert collect_window_state(a) == {"a": {"window_size": "800x600"}}
