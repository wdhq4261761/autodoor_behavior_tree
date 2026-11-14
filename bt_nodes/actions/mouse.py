from bt_core.nodes import ActionNode, NodeStatus
from bt_core.config import NodeConfig
from typing import Dict, Any, Tuple, Optional
import time
from bt_utils.log_manager import LogManager
from bt_utils.helpers import get_random_duration, get_random_interval


def _get_default_position_key() -> str:
    try:
        from config.settings_manager import get_default_position_key
        return get_default_position_key()
    except ImportError:
        return "last_detection_position"


def _ensure_tuple_position(value):
    if value is None:
        return None
    if isinstance(value, str):
        parts = value.replace(" ", "").split(",")
        if len(parts) >= 2:
            try:
                return (int(parts[0]), int(parts[1]))
            except (ValueError, TypeError):
                pass
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (int(value[0]), int(value[1]))
    return value


class MouseClickNode(ActionNode):
    NODE_TYPE = "MouseClickNode"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.button = self.config.get("button", "left")
        self.position: Optional[Tuple[int, int]] = _ensure_tuple_position(self.config.get("position", None))
        self.action = self.config.get("action", "press")
        self.duration = self.config.get_int("duration", 100)
        self.use_blackboard = self.config.get_bool("use_blackboard", False)
        self.position_key = self.config.get("position_key", _get_default_position_key())
        self.click_count = self.config.get_int("click_count", 1)
        self.click_interval = self.config.get_int("click_interval", 100)
        self.duration_random = self.config.get_int("duration_random", 0)
        self.click_interval_random = self.config.get_int("click_interval_random", 0)
        self.x_float = self.config.get_int("x_float", 0)
        self.y_float = self.config.get_int("y_float", 0)
        self._current_click = 0
        self._last_click_time: Optional[float] = None
        self._actual_interval: Optional[int] = None
        self._actual_duration: Optional[int] = None
        self._abort_flag = False
        self._click_started = False
        self._button_pressed = False
        self._context = None

    def _execute_action(self, context) -> NodeStatus:
        try:
            self._context = context
            click_position = self._get_position(context)

            if not self._click_started:
                self._click_started = True
                self._current_click = 0
                self._last_click_time = None

            if self._abort_flag or not context.check_running():
                self._release_button()
                LogManager.instance().log_aborted(
                    node_type="鼠标点击节点",
                    node_name=self.name
                )
                return NodeStatus.ABORTED

            click_count = self.config.get_int("click_count", 1)
            if click_count == -1:
                return self._non_blocking_infinite_click(context, click_position)
            else:
                return self._non_blocking_finite_click(context, click_position)
            
        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"MouseClickNode '{self.name}'")
            LogManager.instance().log_failure(
                node_type="鼠标点击节点",
                node_name=self.name,
                reason="执行异常，详情见终端日志"
            )
            return NodeStatus.FAILURE

    def _get_position(self, context) -> Optional[Tuple[int, int]]:
        use_blackboard = self.config.get_bool("use_blackboard", False)
        position_key = self.config.get("position_key", "") or _get_default_position_key()
        config_position = self.config.get("position", None)

        if use_blackboard:
            bb_position = context.blackboard.get(position_key)
            if bb_position:
                result = _ensure_tuple_position(bb_position)
                return result

        result = _ensure_tuple_position(config_position)
        return result

    def _non_blocking_finite_click(self, context, position: Optional[Tuple[int, int]]) -> NodeStatus:
        current_time = time.time() * 1000

        click_interval = self.config.get_int("click_interval", 100)
        click_interval_random = self.config.get_int("click_interval_random", 0)

        if self._actual_interval is None:
            self._actual_interval = get_random_interval(click_interval, click_interval_random)

        if self._last_click_time is not None and self._actual_interval > 0:
            elapsed = current_time - self._last_click_time
            if elapsed < self._actual_interval:
                return NodeStatus.RUNNING

        click_count = self.config.get_int("click_count", 1)
        if self._current_click < click_count:
            if self._abort_flag or not context.check_running():
                LogManager.debug_print(f"[WARN] [MOUSE] _non_blocking_finite_click: 中止或未运行，释放按钮")
                self._release_button()
                return NodeStatus.ABORTED

            button = self.config.get("button", "left")
            action = self.config.get("action", "press")
            duration = self.config.get_int("duration", 100)
            duration_random = self.config.get_int("duration_random", 0)

            if self._actual_duration is None:
                self._actual_duration = get_random_duration(duration, duration_random)

            context.execute_mouse_click(button, position, action, self._actual_duration,
                                        x_float=self.x_float, y_float=self.y_float)

            if action == "down":
                self._button_pressed = True

            self._current_click += 1
            self._last_click_time = time.time() * 1000
            self._actual_interval = None
            self._actual_duration = None

            if self._current_click < click_count:
                return NodeStatus.RUNNING
        
        self._reset_click_state()
        LogManager.instance().log_success(
            node_type="鼠标点击节点",
            node_name=self.name
        )
        return NodeStatus.SUCCESS

    def _non_blocking_infinite_click(self, context, position: Optional[Tuple[int, int]]) -> NodeStatus:
        current_time = time.time() * 1000

        click_interval = self.config.get_int("click_interval", 100)
        click_interval_random = self.config.get_int("click_interval_random", 0)

        if self._actual_interval is None:
            self._actual_interval = get_random_interval(click_interval, click_interval_random)

        if self._last_click_time is not None and self._actual_interval > 0:
            elapsed = current_time - self._last_click_time
            if elapsed < self._actual_interval:
                return NodeStatus.RUNNING

        if self._abort_flag or not context.check_running():
            self._release_button()
            LogManager.instance().log_aborted(
                node_type="鼠标点击节点",
                node_name=self.name
            )
            return NodeStatus.ABORTED

        button = self.config.get("button", "left")
        action = self.config.get("action", "press")
        duration = self.config.get_int("duration", 100)
        duration_random = self.config.get_int("duration_random", 0)

        if self._actual_duration is None:
            self._actual_duration = get_random_duration(duration, duration_random)
        context.execute_mouse_click(button, position, action, self._actual_duration,
                                    x_float=self.x_float, y_float=self.y_float)

        if action == "down":
            self._button_pressed = True
        
        self._current_click += 1
        self._last_click_time = time.time() * 1000
        self._actual_interval = None
        self._actual_duration = None
        
        return NodeStatus.RUNNING

    def _release_button(self) -> None:
        if self._button_pressed and self._context:
            try:
                button = self.config.get("button", "left")
                self._context.execute_mouse_click(button, None, "up", 0)
            except Exception:
                pass
        self._reset_click_state()

    def _reset_click_state(self) -> None:
        self._current_click = 0
        self._last_click_time = None
        self._actual_interval = None
        self._actual_duration = None
        self._abort_flag = False
        self._click_started = False
        self._button_pressed = False

    def abort(self, context) -> None:
        self._abort_flag = True
        self._release_button()
        super().abort(context)

    def reset(self, reset_counters: bool = True) -> None:
        self._release_button()
        self._context = None
        super().reset(reset_counters=reset_counters)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MouseClickNode":
        config = NodeConfig.from_dict(data.get("config", {}))
        node = cls(node_id=data.get("id"), config=config)
        node.button = config.get("button", "left")
        node.position = _ensure_tuple_position(config.get("position", None))
        node.action = config.get("action", "press")
        node.duration = config.get_int("duration", 100)
        node.use_blackboard = config.get_bool("use_blackboard", False)
        node.position_key = config.get("position_key", "last_detection_position")
        node.click_count = config.get_int("click_count", 1)
        node.click_interval = config.get_int("click_interval", 100)
        node.duration_random = config.get_int("duration_random", 0)
        node.click_interval_random = config.get_int("click_interval_random", 0)
        node.x_float = config.get_int("x_float", 0)
        node.y_float = config.get_int("y_float", 0)
        return node


class MouseMoveNode(ActionNode):
    NODE_TYPE = "MouseMoveNode"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.position: Tuple[int, int] = _ensure_tuple_position(self.config.get("position", (0, 0))) or (0, 0)
        self.use_blackboard = self.config.get_bool("use_blackboard", False)
        self.position_key = self.config.get("position_key", _get_default_position_key())
        self.move_type = self.config.get("move_type", "移动")
        self.drag_button = self.config.get("drag_button", "left")
        self.end_position: Optional[Tuple[int, int]] = _ensure_tuple_position(self.config.get("end_position", None))
        self.relative = self.config.get_bool("relative", False)
        offset = self.config.get("offset", None)
        if offset is not None:
            if isinstance(offset, (list, tuple)) and len(offset) >= 2:
                self.offset = (int(offset[0]), int(offset[1]))
            else:
                self.offset = (0, 0)
        else:
            self.offset = (0, 0)
        self.use_blackboard_end = self.config.get_bool("use_blackboard_end", False)
        self.position_key_end = self.config.get("position_key_end", "")
        self.move_duration = self.config.get_int("move_duration", 0)
        self.move_duration_random = self.config.get_int("move_duration_random", 0)
        self.drag_duration = self.config.get_int("drag_duration", 0)
        self.drag_duration_random = self.config.get_int("drag_duration_random", 0)
        self.x_float = self.config.get_int("x_float", 0)
        self.y_float = self.config.get_int("y_float", 0)

    def _execute_action(self, context) -> NodeStatus:
        try:
            start_pos = self._get_start_position(context)

            if not start_pos:
                LogManager.instance().log_failure(
                    node_type="鼠标移动节点",
                    node_name=self.name,
                    reason="未指定起点位置"
                )
                return NodeStatus.FAILURE

            end_pos = self._get_end_position(context, start_pos)

            move_type = self.config.get("move_type", "移动")
            if move_type == "拖拽":
                return self._execute_drag(context, start_pos, end_pos)
            else:
                return self._execute_move(context, start_pos, end_pos)
                
        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"MouseMoveNode '{self.name}'")
            LogManager.instance().log_failure(
                node_type="鼠标移动节点",
                node_name=self.name,
                reason="执行异常，详情见终端日志"
            )
            try:
                context.execute_mouse_click(self.config.get("drag_button", "left"), None, "up", 0)
            except Exception:
                pass
            return NodeStatus.FAILURE

    def _get_start_position(self, context) -> Optional[Tuple[int, int]]:
        if self.config.get_bool("use_blackboard", False):
            position_key = self.config.get("position_key", "") or _get_default_position_key()
            bb_position = context.blackboard.get(position_key)
            if bb_position:
                return _ensure_tuple_position(bb_position)
        return _ensure_tuple_position(self.config.get("position", (0, 0)))

    def _get_end_position(self, context, start_pos: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        if self.config.get_bool("relative", False):
            offset = self.config.get("offset", None)
            if offset is not None and isinstance(offset, (list, tuple)) and len(offset) >= 2:
                return (start_pos[0] + int(offset[0]), start_pos[1] + int(offset[1]))
            return start_pos

        if self.config.get_bool("use_blackboard_end", False):
            position_key_end = self.config.get("position_key_end", "")
            bb_position = context.blackboard.get(position_key_end)
            if bb_position:
                return _ensure_tuple_position(bb_position)

        return _ensure_tuple_position(self.config.get("end_position", None))

    def _smoothstep(self, t: float) -> float:
        return t * t * (3 - 2 * t)

    def _execute_move(self, context, start_pos: Tuple[int, int], end_pos: Optional[Tuple[int, int]]) -> NodeStatus:
        if not end_pos:
            context.execute_mouse_move(start_pos, relative=False,
                                       x_float=self.x_float, y_float=self.y_float)
            LogManager.instance().log_success(
                node_type="鼠标移动节点",
                node_name=self.name
            )
            return NodeStatus.SUCCESS

        move_duration = self.config.get_int("move_duration", 0)
        move_duration_random = self.config.get_int("move_duration_random", 0)
        actual_duration = get_random_duration(move_duration, move_duration_random)
        
        context.execute_mouse_move(start_pos, relative=False,
                                   x_float=self.x_float, y_float=self.y_float)
        time.sleep(0.01)
        
        if actual_duration > 0:
            total_duration_sec = actual_duration / 1000.0
            steps = max(10, actual_duration // 50)
            dx = end_pos[0] - start_pos[0]
            dy = end_pos[1] - start_pos[1]
            
            start_time = time.time()
            
            for i in range(steps):
                if not context.check_running():
                    return NodeStatus.ABORTED
                
                elapsed = time.time() - start_time
                progress = min(elapsed / total_duration_sec, 1.0)
                
                t = self._smoothstep(progress)
                current_x = int(start_pos[0] + dx * t)
                current_y = int(start_pos[1] + dy * t)
                context.execute_mouse_move((current_x, current_y), relative=False,
                                           x_float=self.x_float, y_float=self.y_float)
                
                if progress >= 1.0:
                    break
                
                time.sleep(total_duration_sec / steps)

            # 插值按整数取整 + 随机抖动会累计误差，最终落点必须精确对齐
            context.execute_mouse_move(end_pos, relative=False, x_float=0, y_float=0)
        else:
            context.execute_mouse_move(end_pos, relative=False,
                                       x_float=self.x_float, y_float=self.y_float)
        
        LogManager.instance().log_success(
            node_type="鼠标移动节点",
            node_name=self.name
        )
        return NodeStatus.SUCCESS

    def _execute_drag(self, context, start_pos: Tuple[int, int], end_pos: Optional[Tuple[int, int]]) -> NodeStatus:
        if not end_pos:
            LogManager.instance().log_failure(
                node_type="鼠标移动节点",
                node_name=self.name,
                reason="未指定拖拽终点"
            )
            return NodeStatus.FAILURE

        move_duration = self.config.get_int("move_duration", 0)
        move_duration_random = self.config.get_int("move_duration_random", 0)
        drag_duration = self.config.get_int("drag_duration", 0)
        drag_duration_random = self.config.get_int("drag_duration_random", 0)
        drag_button = self.config.get("drag_button", "left")

        actual_duration = get_random_duration(
            move_duration if move_duration > 0 else drag_duration,
            move_duration_random if move_duration_random > 0 else drag_duration_random
        )

        context.execute_mouse_move(start_pos, relative=False,
                                   x_float=self.x_float, y_float=self.y_float)
        time.sleep(0.02)

        context.execute_mouse_click(drag_button, start_pos, "down", 0)
        time.sleep(0.02)
        
        if actual_duration > 0:
            total_duration_sec = actual_duration / 1000.0
            steps = max(10, actual_duration // 50)
            dx = end_pos[0] - start_pos[0]
            dy = end_pos[1] - start_pos[1]
            
            start_time = time.time()
            
            for i in range(steps):
                if not context.check_running():
                    context.execute_mouse_click(drag_button, end_pos, "up", 0)
                    return NodeStatus.ABORTED
                
                elapsed = time.time() - start_time
                progress = min(elapsed / total_duration_sec, 1.0)
                
                t = self._smoothstep(progress)
                current_x = int(start_pos[0] + dx * t)
                current_y = int(start_pos[1] + dy * t)
                context.execute_mouse_move((current_x, current_y), relative=False,
                                           x_float=self.x_float, y_float=self.y_float)
                
                if progress >= 1.0:
                    break
                
                time.sleep(total_duration_sec / steps)

            # 插值按整数取整 + 随机抖动会累计误差，最终落点必须精确对齐
            context.execute_mouse_move(end_pos, relative=False, x_float=0, y_float=0)
        else:
            context.execute_mouse_move(end_pos, relative=False,
                                       x_float=self.x_float, y_float=self.y_float)
        
        time.sleep(0.02)
        context.execute_mouse_click(drag_button, end_pos, "up", 0)

        LogManager.instance().log_success(
            node_type="鼠标移动节点",
            node_name=self.name
        )
        return NodeStatus.SUCCESS

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MouseMoveNode":
        config = NodeConfig.from_dict(data.get("config", {}))
        node = cls(node_id=data.get("id"), config=config)
        node.position = _ensure_tuple_position(config.get("position", (0, 0))) or (0, 0)
        node.use_blackboard = config.get_bool("use_blackboard", False)
        node.position_key = config.get("position_key", "last_detection_position")
        node.move_type = config.get("move_type", "移动")
        node.drag_button = config.get("drag_button", "left")
        node.end_position = _ensure_tuple_position(config.get("end_position", None))
        node.relative = config.get_bool("relative", False)
        offset = config.get("offset", None)
        if offset is not None:
            if isinstance(offset, (list, tuple)) and len(offset) >= 2:
                node.offset = (int(offset[0]), int(offset[1]))
            else:
                node.offset = (0, 0)
        else:
            node.offset = (0, 0)
        node.use_blackboard_end = config.get_bool("use_blackboard_end", False)
        node.position_key_end = config.get("position_key_end", "")
        node.move_duration = config.get_int("move_duration", 0)
        node.move_duration_random = config.get_int("move_duration_random", 0)
        node.drag_duration = config.get_int("drag_duration", 0)
        node.drag_duration_random = config.get_int("drag_duration_random", 0)
        node.x_float = config.get_int("x_float", 0)
        node.y_float = config.get_int("y_float", 0)
        return node
