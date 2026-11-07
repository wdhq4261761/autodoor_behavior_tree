"""uia_bridge 插件的单元测试（假控件树，不依赖真实窗口）。"""
from __future__ import annotations

import pytest

from bt_core.config import NodeConfig
from bt_core.context import ExecutionContext
from bt_core.nodes import NodeStatus
from plugins.uia_bridge import nodes as un


class FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top = left, top
        self.right, self.bottom = right, bottom


class FakeInfo:
    def __init__(self, name, control_type):
        self.name = name
        self.control_type = control_type


class FakeElem:
    def __init__(self, name, control_type, rect,
                 enabled=True, visible=True):
        self.element_info = FakeInfo(name, control_type)
        self._rect = rect
        self._enabled = enabled
        self._visible = visible

    def rectangle(self):
        return FakeRect(*self._rect)

    def is_enabled(self):
        return self._enabled

    def is_visible(self):
        return self._visible

    def window_text(self):
        return self.element_info.name


class FakeWindow:
    def __init__(self, elems):
        self._elems = elems

    def descendants(self):
        return list(self._elems)


ELEMS = [
    FakeElem("属性", "Button", (194, 37, 216, 61)),
    FakeElem("新建文件夹", "Button", (216, 37, 238, 61)),
    FakeElem("地址栏", "Edit", (100, 10, 900, 30)),
    FakeElem("某个按钮", "Button", (300, 40, 340, 60), enabled=False),
]


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(un, "_resolve_hwnd", lambda cfg: 12345)
    monkeypatch.setattr(un, "_connect", lambda hwnd: FakeWindow(ELEMS))
    # 客户区原点固定在 (156, 34)，便于断言相对坐标
    from bt_utils.coordinate import CoordinateConverter
    monkeypatch.setattr(
        CoordinateConverter, "absolute_to_client",
        staticmethod(lambda x, y, hwnd: (x - 156, y - 34)),
    )
    return monkeypatch


class TestMatch:
    def test_exact_hit(self):
        assert un._match(ELEMS[0], "属性", "Button", "exact") is True

    def test_exact_miss(self):
        assert un._match(ELEMS[0], "属", "Button", "exact") is False

    def test_contains(self):
        assert un._match(ELEMS[1], "文件", "Button", "contains") is True

    def test_regex(self):
        assert un._match(ELEMS[1], r"新建.*夹", "Button", "regex") is True

    def test_control_type_filter(self):
        assert un._match(ELEMS[2], "", "Button", "exact") is False

    def test_empty_name_matches_any(self):
        assert un._match(ELEMS[2], "", "Edit", "exact") is True


class TestFindControls:
    def test_filters_by_type(self):
        found = un._find_controls(FakeWindow(ELEMS), "", "Button", "exact", 100)
        assert len(found) == 3

    def test_respects_max_nodes(self):
        found = un._find_controls(FakeWindow(ELEMS), "", "Button", "exact", 1)
        assert len(found) <= 1


class TestUIASampleNode:
    def test_success_writes_both_coordinates(self, patched):
        cfg = NodeConfig.from_dict({
            "hwnd": 12345, "control_name": "属性", "control_type": "Button",
            "output_mode": "client", "position_key": "btn",
            "write_scalar": True,
        })
        node = un.UIASampleNode(node_id="s", config=cfg)
        ctx = ExecutionContext(project_root=".")

        assert node._execute_action(ctx) == NodeStatus.SUCCESS
        assert ctx.blackboard.get("uia_rect") == [194, 37, 216, 61]
        assert ctx.blackboard.get("uia_screen_x") == 205
        assert ctx.blackboard.get("uia_screen_y") == 49
        assert ctx.blackboard.get("uia_client_x") == 49
        assert ctx.blackboard.get("uia_client_y") == 15
        assert ctx.blackboard.get("btn") == (49, 15)
        assert ctx.blackboard.get("last_detection_x") == 49

    def test_screen_mode_outputs_absolute(self, patched):
        cfg = NodeConfig.from_dict({
            "hwnd": 12345, "control_name": "属性", "control_type": "Button",
            "output_mode": "screen", "position_key": "btn",
        })
        node = un.UIASampleNode(node_id="s", config=cfg)
        ctx = ExecutionContext(project_root=".")
        node._execute_action(ctx)
        assert ctx.blackboard.get("btn") == (205, 49)

    def test_not_found_returns_failure(self, patched):
        cfg = NodeConfig.from_dict({
            "hwnd": 12345, "control_name": "不存在的控件", "control_type": "Button",
        })
        node = un.UIASampleNode(node_id="s", config=cfg)
        assert node._execute_action(ExecutionContext(project_root=".")) == NodeStatus.FAILURE

    def test_nth_out_of_range_returns_failure(self, patched):
        cfg = NodeConfig.from_dict({
            "hwnd": 12345, "control_type": "Button", "nth": 99,
        })
        node = un.UIASampleNode(node_id="s", config=cfg)
        assert node._execute_action(ExecutionContext(project_root=".")) == NodeStatus.FAILURE

    def test_missing_window_config_returns_failure(self):
        """未配置 hwnd/标题时，应显式失败而不是抛异常穿透。"""
        cfg = NodeConfig.from_dict({"control_type": "Button"})
        node = un.UIASampleNode(node_id="s", config=cfg)
        assert node._execute_action(ExecutionContext(project_root=".")) == NodeStatus.FAILURE


class TestUIAStateNode:
    def _node(self, expect, name="属性", ctype="Button", nth=0):
        return un.UIAStateNode(node_id="q", config=NodeConfig.from_dict({
            "hwnd": 12345, "control_name": name,
            "control_type": ctype, "expect": expect, "nth": nth,
        }))

    def test_exists(self, patched):
        assert self._node("exists")._check_condition(
            ExecutionContext(project_root=".")) is True

    def test_enabled(self, patched):
        assert self._node("enabled")._check_condition(
            ExecutionContext(project_root=".")) is True

    def test_disabled_false_for_enabled_control(self, patched):
        assert self._node("disabled")._check_condition(
            ExecutionContext(project_root=".")) is False

    def test_disabled_true_for_disabled_control(self, patched):
        node = self._node("disabled", name="某个按钮")
        assert node._check_condition(ExecutionContext(project_root=".")) is True

    def test_missing_control_returns_false(self, patched):
        node = self._node("exists", name="不存在")
        assert node._check_condition(ExecutionContext(project_root=".")) is False

    def test_unknown_expect_returns_false(self, patched):
        assert self._node("whatever")._check_condition(
            ExecutionContext(project_root=".")) is False
