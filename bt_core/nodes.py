from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, TYPE_CHECKING
import uuid
import os
import time

from .status import NodeStatus
from .config import NodeConfig
from bt_utils.helpers import get_random_interval
from bt_utils.log_manager import LogManager

if TYPE_CHECKING:
    from .context import ExecutionContext


class Node(ABC):
    """节点抽象基类

    所有行为树节点的基类，定义了节点的通用接口和行为。

    Args:
        node_id: 节点唯一标识
        config: 节点配置
    """
    NODE_TYPE = "Node"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        self.node_id = node_id or str(uuid.uuid4())[:8]
        self.config = config or NodeConfig()
        self.name = self.config.name
        self.description = self.config.description
        self.enabled = self.config.enabled
        self.skip = self.config.skip
        self.status = NodeStatus.SUCCESS
        self.children: List["Node"] = []
        self.parent: Optional["Node"] = None
        self._tick_count = 0
        self._is_protected = False  # 节点保护标记,防止被删除
        self._retry_count = 0
        self._repeat_count = 0
        self._start_time: Optional[float] = None
        self._child_index = 0
        self._children_running = False
        # 异步节点支持（阶段 0.2 新增）
        self._is_async: bool = False
        self._async_started: bool = False

    @abstractmethod
    def tick(self, context: "ExecutionContext") -> NodeStatus:
        """执行节点逻辑

        Args:
            context: 执行上下文

        Returns:
            节点执行状态
        """
        pass

    def _execute_with_decorators(self, context: "ExecutionContext", 
                                   execute_func: callable) -> NodeStatus:
        if not self.config.enabled:
            return NodeStatus.SUCCESS

        # 跳过模式：跳过节点自身逻辑，透传执行其子节点（无子节点则视为成功）
        if self.config.skip:
            if self.children:
                status = self._execute_children(context)
                if status != NodeStatus.RUNNING:
                    self.status = status
                return status
            self.status = NodeStatus.SUCCESS
            return NodeStatus.SUCCESS

        if self.status != NodeStatus.RUNNING:
            context.notify_node_status(self.node_id, "running")

        if self._start_time is None:
            self._start_time = context.elapsed_time

        timeout_ms = self.config.timeout_ms
        if timeout_ms > 0:
            elapsed_ms = (context.elapsed_time - self._start_time) * 1000
            if elapsed_ms >= timeout_ms:
                self.status = NodeStatus.FAILURE
                context.notify_node_status(self.node_id, "failure")
                context.record_node_stats(self.node_id, self.NODE_TYPE, self.name, "failure", timeout_ms)
                
                LogManager.instance().log_timeout(
                    node_type=self.NODE_TYPE,
                    node_name=self.name,
                    timeout_ms=timeout_ms
                )
                
                return NodeStatus.FAILURE

        start_time = time.perf_counter()
        status = execute_func(context)
        duration_ms = (time.perf_counter() - start_time) * 1000
        self.status = status

        retry_count = self.config.retry_count
        if status == NodeStatus.FAILURE and retry_count != 0:
            if retry_count == -1 or self._retry_count < retry_count:
                self._retry_count += 1

                repeat_interval_ms = self.config.repeat_interval_ms
                repeat_interval_ms_random = self.config.get_int("repeat_interval_ms_random", 0)
                if repeat_interval_ms > 0 or repeat_interval_ms_random > 0:    
                    actual_interval = get_random_interval(repeat_interval_ms, repeat_interval_ms_random)
                    if actual_interval > 0:
                        elapsed = 0
                        while elapsed < actual_interval / 1000 and context.check_running():
                            sleep_time = min(0.01, actual_interval / 1000 - elapsed)
                            time.sleep(sleep_time)
                            elapsed += sleep_time

                if not context.check_running():
                    return NodeStatus.ABORTED

                self._reset_for_retry()

                return NodeStatus.RUNNING

        repeat_count = self.config.repeat_count
        if status == NodeStatus.SUCCESS and repeat_count != 0:
            if repeat_count == -1 or self._repeat_count < repeat_count:
                self._repeat_count += 1
                
                repeat_interval_ms = self.config.repeat_interval_ms
                repeat_interval_ms_random = self.config.get_int("repeat_interval_ms_random", 0)
                if repeat_interval_ms > 0 or repeat_interval_ms_random > 0:    
                    actual_interval = get_random_interval(repeat_interval_ms, repeat_interval_ms_random)
                    if actual_interval > 0:
                        elapsed = 0
                        while elapsed < actual_interval / 1000 and context.check_running():
                            sleep_time = min(0.01, actual_interval / 1000 - elapsed)
                            time.sleep(sleep_time)
                            elapsed += sleep_time

                if not context.check_running():
                    return NodeStatus.ABORTED

                self._reset_for_repeat()
                return NodeStatus.RUNNING

        status_str = "success" if status == NodeStatus.SUCCESS else "failure" if status == NodeStatus.FAILURE else "running"
        context.record_node_stats(self.node_id, self.NODE_TYPE, self.name, status_str, duration_ms)

        if status == NodeStatus.SUCCESS:
            context.notify_node_status(self.node_id, "success")
        elif status == NodeStatus.FAILURE:
            context.notify_node_status(self.node_id, "failure")

        return status

    def _reset_for_retry(self) -> None:
        self.status = NodeStatus.RUNNING
        self._tick_count = 0
        self._start_time = None
        self._child_index = 0
        self._children_running = False
        if hasattr(self, 'current_index'):
            self.current_index = 0
        if hasattr(self, '_last_child_finish_time'):
            self._last_child_finish_time = None
        for child in self.children:
            child.reset()

    def _reset_for_repeat(self) -> None:
        """重复执行时重置状态（保留重复计数器）"""
        saved_repeat_count = self._repeat_count
        self.reset(reset_counters=False)
        self._repeat_count = saved_repeat_count
        self.status = NodeStatus.RUNNING

    def reset(self, reset_counters: bool = True) -> None:
        """重置节点状态

        Args:
            reset_counters: 是否重置计数器（重复执行时不应重置）
        """
        self.status = NodeStatus.SUCCESS
        self._tick_count = 0
        if reset_counters:
            self._retry_count = 0
            self._repeat_count = 0
        self._start_time = None
        self._child_index = 0
        self._children_running = False
        for child in self.children:
            child.reset()

    def _execute_children(self, context: "ExecutionContext") -> NodeStatus:
        """执行子节点（通用实现）

        Args:
            context: 执行上下文

        Returns:
            执行状态
        """
        while self._child_index < len(self.children):
            child = self.children[self._child_index]
            status = child.tick(context)
            
            if status == NodeStatus.RUNNING:
                self._children_running = True
                return NodeStatus.RUNNING
            
            if status != NodeStatus.SUCCESS:
                self._child_index = 0
                self._children_running = False
                return status
            
            self._child_index += 1
        
        self._child_index = 0
        self._children_running = False
        return NodeStatus.SUCCESS

    def is_protected(self) -> bool:
        """
        检查节点是否受保护(不可删除)
        
        Returns:
            bool: True表示受保护,False表示可删除
        """
        return self._is_protected

    def abort(self, context: "ExecutionContext") -> None:
        """中止节点执行

        当节点被外部中止时调用（如并行节点完成时中止其他RUNNING子节点）。

        Args:
            context: 执行上下文
        """
        self.reset()
        self.status = NodeStatus.ABORTED
        context.notify_node_status(self.node_id, "aborted")
        for child in self.children:
            child.abort(context)

    def add_child(self, child: "Node") -> None:
        """添加子节点

        Args:
            child: 子节点
        """
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: "Node") -> None:
        """移除子节点

        Args:
            child: 子节点
        """
        if child in self.children:
            self.children.remove(child)
            child.parent = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典

        Returns:
            字典表示
        """
        return {
            "id": self.node_id,
            "type": self.NODE_TYPE,
            "name": self.name,
            "enabled": self.enabled,
            "skip": self.skip,
            "config": self.config.to_dict(),
            "children": [child.node_id for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Node":
        """从字典反序列化

        Args:
            data: 字典数据

        Returns:
            节点实例
        """
        config = NodeConfig.from_dict(data.get("config", {}))
        
        if "name" in data:
            config.name = data["name"]
        if "description" in data:
            config.description = data["description"]
        if "enabled" in data:
            config.enabled = data["enabled"]
        
        node = cls(node_id=data.get("id"), config=config)
        return node


class CompositeNode(Node):
    """组合节点基类

    包含多个子节点的节点，按特定策略执行子节点。
    """
    NODE_TYPE = "CompositeNode"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.current_index = 0

    def reset(self, reset_counters: bool = True) -> None:
        """重置节点状态"""
        super().reset(reset_counters)
        self.current_index = 0

    def abort(self, context: "ExecutionContext") -> None:
        """中止节点执行，递归中止所有子节点

        Args:
            context: 执行上下文
        """
        for child in self.children:
            child.abort(context)
        super().abort(context)


class SequenceNode(CompositeNode):
    NODE_TYPE = "SequenceNode"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.continue_on_failure = self.config.get_bool("continue_on_failure", False)
        self.child_interval = self.config.get_int("childinterval", 0)
        self.child_interval_random = self.config.get_int("childinterval_random", 0)
        self._last_child_finish_time: Optional[float] = None
        self._completed = False

    def tick(self, context: "ExecutionContext") -> NodeStatus:
        return self._execute_with_decorators(context, self._tick_internal)

    def _tick_internal(self, context: "ExecutionContext") -> NodeStatus:
        if self._completed:
            return NodeStatus.SUCCESS

        if not self.children:
            self._completed = True
            return NodeStatus.SUCCESS

        has_failure = False

        while self.current_index < len(self.children):
            child = self.children[self.current_index]

            if not child.config.enabled:
                self.current_index += 1
                continue

            if self.child_interval > 0 and self._last_child_finish_time is not None:
                current_time = context.elapsed_time * 1000
                actual_interval = get_random_interval(self.child_interval, self.child_interval_random)
                if current_time - self._last_child_finish_time < actual_interval:
                    return NodeStatus.RUNNING

            status = child.tick(context)

            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING

            if status == NodeStatus.FAILURE:
                if self.continue_on_failure:
                    has_failure = True
                    self.current_index += 1
                    self._last_child_finish_time = context.elapsed_time * 1000
                    continue
                else:
                    self.current_index = 0
                    LogManager.instance().log_failure(
                        node_type="顺序节点",
                        node_name=self.name,
                        reason=f"子节点 '{child.name}' 执行失败"
                    )
                    return NodeStatus.FAILURE

            self.current_index += 1
            self._last_child_finish_time = context.elapsed_time * 1000

        self.current_index = 0
        
        if has_failure:
            LogManager.instance().log_failure(
                node_type="顺序节点",
                node_name=self.name,
                reason="部分子节点执行失败（继续执行模式）"
            )
        else:
            LogManager.instance().log_success(
                node_type="顺序节点",
                node_name=self.name
            )
        
        self._completed = True
        return NodeStatus.FAILURE if has_failure else NodeStatus.SUCCESS

    def reset(self, reset_counters: bool = True) -> None:
        super().reset(reset_counters)
        self._last_child_finish_time = None
        self._completed = False

    def _reset_for_retry(self) -> None:
        super()._reset_for_retry()
        self._last_child_finish_time = None
        self._completed = False


class SelectorNode(CompositeNode):
    NODE_TYPE = "SelectorNode"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.child_interval = self.config.get_int("childinterval", 0)
        self.child_interval_random = self.config.get_int("childinterval_random", 0)
        self._last_child_time = 0

    def tick(self, context: "ExecutionContext") -> NodeStatus:
        return self._execute_with_decorators(context, self._tick_internal)

    def _tick_internal(self, context: "ExecutionContext") -> NodeStatus:
        
        if not self.children:
            LogManager.instance().log_failure(
                node_type="选择节点",
                node_name=self.name,
                reason="没有子节点"
            )
            return NodeStatus.FAILURE

        while self.current_index < len(self.children):
            child = self.children[self.current_index]

            if not child.config.enabled:
                self.current_index += 1
                continue

            if self.child_interval > 0:
                current_time = context.elapsed_time * 1000
                actual_interval = get_random_interval(self.child_interval, self.child_interval_random)
                if current_time - self._last_child_time < actual_interval:
                    return NodeStatus.RUNNING
                self._last_child_time = current_time

            status = child.tick(context)

            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING

            if status == NodeStatus.SUCCESS:
                self.current_index = 0
                LogManager.instance().log_success(
                    node_type="选择节点",
                    node_name=self.name
                )
                return NodeStatus.SUCCESS

            self.current_index += 1

        self.current_index = 0
        LogManager.instance().log_failure(
            node_type="选择节点",
            node_name=self.name,
            reason="所有子节点都执行失败"
        )
        return NodeStatus.FAILURE

    def reset(self, reset_counters: bool = True) -> None:
        super().reset(reset_counters)
        self._last_child_time = 0

    def _reset_for_retry(self) -> None:
        super()._reset_for_retry()
        self._last_child_time = 0


class ParallelNode(CompositeNode):
    """并行节点

    同时执行所有子节点，根据策略决定成功条件。

    Args:
        success_policy: 成功策略，require_all（全部成功）或 require_one（任一成功）
    """
    NODE_TYPE = "ParallelNode"

    SUCCESS_POLICY_ALL = "require_all"
    SUCCESS_POLICY_ONE = "require_one"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.cached_statuses: Dict[int, NodeStatus] = {}
        self.success_policy = self.config.get("success_policy", self.SUCCESS_POLICY_ALL)

    def tick(self, context: "ExecutionContext") -> NodeStatus:
        return self._execute_with_decorators(context, self._tick_internal)

    def _tick_internal(self, context: "ExecutionContext") -> NodeStatus:
        
        if not self.children:
            LogManager.instance().log_success(
                node_type="并行节点",
                node_name=self.name
            )
            return NodeStatus.SUCCESS

        success_count = 0
        failure_count = 0
        running_children = []
        enabled_count = 0

        for i, child in enumerate(self.children):
            if not child.config.enabled:
                continue

            enabled_count += 1

            if i in self.cached_statuses:
                status = self.cached_statuses[i]
                if status == NodeStatus.SUCCESS:
                    success_count += 1
                    continue
                elif status == NodeStatus.FAILURE:
                    failure_count += 1
                    continue

            status = child.tick(context)

            if status == NodeStatus.SUCCESS:
                self.cached_statuses[i] = NodeStatus.SUCCESS
                success_count += 1
            elif status == NodeStatus.FAILURE:
                self.cached_statuses[i] = NodeStatus.FAILURE
                failure_count += 1
            elif status == NodeStatus.RUNNING:
                running_children.append(child)

        if self.success_policy == self.SUCCESS_POLICY_ONE and success_count > 0:
            self._abort_running(context, running_children)
            LogManager.instance().log_success(
                node_type="并行节点",
                node_name=self.name
            )
            return NodeStatus.SUCCESS

        if running_children:
            return NodeStatus.RUNNING

        if self.success_policy == self.SUCCESS_POLICY_ALL:
            if success_count == enabled_count:
                LogManager.instance().log_success(
                    node_type="并行节点",
                    node_name=self.name
                )
                return NodeStatus.SUCCESS
            else:
                LogManager.instance().log_failure(
                    node_type="并行节点",
                    node_name=self.name,
                    reason=f"成功 {success_count}/{enabled_count} 个子节点"
                )
                return NodeStatus.FAILURE
        else:
            if success_count > 0:
                LogManager.instance().log_success(
                    node_type="并行节点",
                    node_name=self.name
                )
                return NodeStatus.SUCCESS
            else:
                LogManager.instance().log_failure(
                    node_type="并行节点",
                    node_name=self.name,
                    reason="所有子节点都执行失败"
                )
                return NodeStatus.FAILURE

    def _abort_running(self, context: "ExecutionContext", children: List[Node]) -> None:
        """中止正在运行的子节点

        Args:
            context: 执行上下文
            children: 正在运行的子节点列表
        """
        for child in children:
            child.abort(context)

    def reset(self, reset_counters: bool = True) -> None:
        """重置节点状态"""
        super().reset(reset_counters)
        self.cached_statuses.clear()
    
    def _reset_for_retry(self) -> None:
        """重试时重置状态（保留重试计数器）"""
        super()._reset_for_retry()
        self.cached_statuses.clear()
    
    def _reset_for_repeat(self) -> None:
        """重复执行时重置状态（保留重复计数器）"""
        super()._reset_for_repeat()
        self.cached_statuses.clear()


class RandomNode(CompositeNode):
    """随机节点

    随机执行子节点，根据策略决定成功条件。

    Args:
        success_policy: 成功策略，require_all（全部成功）或 require_one（任一成功）
        continue_on_failure: 失败后是否继续执行
        fully_random: 是否完全随机（True时已执行的子节点仍可被选中）
    """
    NODE_TYPE = "RandomNode"

    SUCCESS_POLICY_ALL = "require_all"
    SUCCESS_POLICY_ONE = "require_one"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.success_policy = self.config.get("success_policy", self.SUCCESS_POLICY_ALL)
        self.continue_on_failure = self.config.get_bool("continue_on_failure", False)
        self.fully_random = self.config.get_bool("fully_random", False)
        self._executed_indices: set = set()
        self._success_indices: set = set()
        self._failure_indices: set = set()
        self._current_running_index: Optional[int] = None
        self._enabled_indices: List[int] = []

    def tick(self, context: "ExecutionContext") -> NodeStatus:
        return self._execute_with_decorators(context, self._tick_internal)

    def _tick_internal(self, context: "ExecutionContext") -> NodeStatus:
        import random
        
        if not self.children:
            LogManager.instance().log_success(
                node_type="随机节点",
                node_name=self.name
            )
            return NodeStatus.SUCCESS

        if not self._enabled_indices:
            self._enabled_indices = [
                i for i, child in enumerate(self.children) 
                if child.config.enabled
            ]
        
        if not self._enabled_indices:
            LogManager.instance().log_success(
                node_type="随机节点",
                node_name=self.name
            )
            return NodeStatus.SUCCESS

        if self._current_running_index is not None:
            child = self.children[self._current_running_index]
            status = child.tick(context)
            
            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING
            
            if status == NodeStatus.SUCCESS:
                self._success_indices.add(self._current_running_index)
                if self.success_policy == self.SUCCESS_POLICY_ONE:
                    LogManager.instance().log_success(
                        node_type="随机节点",
                        node_name=self.name
                    )
                    return NodeStatus.SUCCESS
            elif status == NodeStatus.FAILURE:
                self._failure_indices.add(self._current_running_index)
                if not self.continue_on_failure and self.success_policy == self.SUCCESS_POLICY_ALL:
                    LogManager.instance().log_failure(
                        node_type="随机节点",
                        node_name=self.name,
                        reason=f"子节点 '{child.name}' 执行失败"
                    )
                    return NodeStatus.FAILURE
            
            self._current_running_index = None

        available_indices = self._get_available_indices()
        
        if not available_indices:
            return self._determine_final_status()
        
        if self.fully_random and self._executed_indices == set(self._enabled_indices):
            return self._determine_final_status()

        next_index = random.choice(available_indices)
        
        self._executed_indices.add(next_index)
        
        self._current_running_index = next_index
        child = self.children[next_index]
        status = child.tick(context)
        
        if status == NodeStatus.RUNNING:
            return NodeStatus.RUNNING
        
        if status == NodeStatus.SUCCESS:
            self._success_indices.add(next_index)
            if self.success_policy == self.SUCCESS_POLICY_ONE:
                LogManager.instance().log_success(
                    node_type="随机节点",
                    node_name=self.name
                )
                return NodeStatus.SUCCESS
        elif status == NodeStatus.FAILURE:
            self._failure_indices.add(next_index)
            if not self.continue_on_failure and self.success_policy == self.SUCCESS_POLICY_ALL:
                LogManager.instance().log_failure(
                    node_type="随机节点",
                    node_name=self.name,
                    reason=f"子节点 '{child.name}' 执行失败"
                )
                return NodeStatus.FAILURE
        
        self._current_running_index = None
        
        available_indices = self._get_available_indices()
        if not available_indices:
            return self._determine_final_status()
        
        return NodeStatus.RUNNING

    def _get_available_indices(self) -> List[int]:
        """获取可执行的子节点索引列表
        
        Returns:
            可执行的子节点索引列表
        """
        if self.fully_random:
            return self._enabled_indices
        else:
            return [i for i in self._enabled_indices if i not in self._executed_indices]

    def _determine_final_status(self) -> NodeStatus:
        """确定最终状态
        
        Returns:
            最终节点状态
        """
        
        enabled_count = len(self._enabled_indices)
        success_count = len(self._success_indices)
        
        if self.success_policy == self.SUCCESS_POLICY_ALL:
            if success_count == enabled_count:
                LogManager.instance().log_success(
                    node_type="随机节点",
                    node_name=self.name
                )
                return NodeStatus.SUCCESS
            else:
                LogManager.instance().log_failure(
                    node_type="随机节点",
                    node_name=self.name,
                    reason=f"成功 {success_count}/{enabled_count} 个子节点"
                )
                return NodeStatus.FAILURE
        else:
            if success_count > 0:
                LogManager.instance().log_success(
                    node_type="随机节点",
                    node_name=self.name
                )
                return NodeStatus.SUCCESS
            else:
                LogManager.instance().log_failure(
                    node_type="随机节点",
                    node_name=self.name,
                    reason="所有子节点都执行失败"
                )
                return NodeStatus.FAILURE

    def reset(self, reset_counters: bool = True) -> None:
        """重置节点状态"""
        super().reset(reset_counters)
        self._executed_indices.clear()
        self._success_indices.clear()
        self._failure_indices.clear()
        self._current_running_index = None
        self._enabled_indices = []
    
    def _reset_for_retry(self) -> None:
        """重试时重置状态（保留重试计数器）"""
        super()._reset_for_retry()
        self._executed_indices.clear()
        self._success_indices.clear()
        self._failure_indices.clear()
        self._current_running_index = None
        self._enabled_indices = []
    
    def _reset_for_repeat(self) -> None:
        """重复执行时重置状态（保留重复计数器）"""
        super()._reset_for_repeat()
        self._executed_indices.clear()
        self._success_indices.clear()
        self._failure_indices.clear()
        self._current_running_index = None
        self._enabled_indices = []


class ConditionNode(Node):
    NODE_TYPE = "ConditionNode"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.invert = self.config.get_bool("invert", False)
        
        self._last_check_time = -self.config.get_int("check_interval_ms", 300) - 1
        # 智能跳过：连续相同结果时延长检测间隔
        self._consecutive_same_count = 0
        self._last_condition_result = None
        self._STABLE_THRESHOLD = 15        # 连续15次相同 → 间隔×2

    def _parse_region(self, region_config) -> tuple:
        """解析区域配置
        
        Args:
            region_config: 区域配置，支持 None、list、tuple、str 格式
            
        Returns:
            tuple: (x1, y1, x2, y2) 区域坐标
        """
        if region_config is None:
            return None
        elif isinstance(region_config, (list, tuple)):
            if len(region_config) == 4:
                return tuple(int(x) for x in region_config)
            return tuple(region_config)
        elif isinstance(region_config, str):
            try:
                import re
                if region_config.startswith('['):
                    match = re.findall(r'\d+', region_config)
                    if len(match) >= 4:
                        return tuple(int(x) for x in match[:4])
                parts = [int(x.strip()) for x in region_config.split(",")]
                if len(parts) == 4:
                    return tuple(parts)
            except (ValueError, AttributeError):
                pass
        return None

    def _parse_color(self, color_config) -> tuple:
        """解析颜色配置
        
        Args:
            color_config: 颜色配置，支持 None、list、tuple、str 格式
            
        Returns:
            tuple: (r, g, b) 颜色值
        """
        if color_config is None:
            return (255, 0, 0)
        elif isinstance(color_config, (list, tuple)):
            return tuple(int(c) for c in color_config[:3])
        elif isinstance(color_config, str):
            import re
            match = re.search(r'RGB\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', color_config, re.IGNORECASE)
            if match:
                return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            # 十六进制颜色: #RRGGBB / RRGGBB / #RGB（最常见格式，此前未支持）
            hex6 = re.match(r'^#?([0-9a-fA-F]{6})$', color_config.strip())
            if hex6:
                h = hex6.group(1)
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            hex3 = re.match(r'^#?([0-9a-fA-F]{3})$', color_config.strip())
            if hex3:
                h = hex3.group(1)
                return tuple(int(c * 2, 16) for c in h)
            try:
                parts = [int(x.strip()) for x in color_config.split(",")]
                if len(parts) >= 3:
                    return tuple(parts[:3])
            except (ValueError, AttributeError):
                pass
        return (255, 0, 0)

    def _adjust_position(self, position: tuple, context=None) -> tuple:
        """把检测到的「图像内坐标」换算为「屏幕绝对坐标」

        三种情形：

        1. 配置了 region：截图是该 region 的裁剪，图像原点即 region 左上角，
           加上 region 偏移即可。
        2. 未配置 region 且绑定了窗口：截图是窗口图像，坐标是窗口内相对坐标，
           @p 原样返回，由 ExecutionContext 的 execute_mouse_* 负责换算。
        3. 未配置 region 且未绑定窗口：截图是**整个虚拟桌面**，其图像原点对应
           虚拟桌面左上角 (min_x, min_y)。多显示器时 min_x/min_y 可能为负
           （副屏挂在主屏左侧/上方），此时若不补偿，点击位置会整体偏移
           |min_x| 像素且不会报错——这类缺陷极难排查。

        Args:
            position: 图像内坐标
            context: 执行上下文

        Returns:
            屏幕绝对坐标（或窗口内相对坐标）
        """
        if position is None:
            return None
        region = self._get_effective_region(context) if context else self._parse_region(self.config.get("region", None))
        if region:
            return (position[0] + region[0], position[1] + region[1])

        # 绑定窗口时为窗口内相对坐标，交给 execute_mouse_* 换算
        if context is not None and getattr(context, "get_bound_window", None):
            if context.get_bound_window():
                return position

        try:
            from bt_utils.screen_utils import get_virtual_screen_bounds
            min_x, min_y, _, _ = get_virtual_screen_bounds()
            if min_x or min_y:
                return (position[0] + min_x, position[1] + min_y)
        except Exception:
            pass
        return position

    def _apply_offset(self, position: tuple) -> tuple:
        """应用坐标偏移

        Args:
            position: 原始位置 (x, y)

        Returns:
            tuple: 偏移后的位置
        """
        if position is None:
            return None

        offset = self._get_offset()
        return (position[0] + offset[0], position[1] + offset[1])

    def _get_offset(self) -> tuple:
        """从配置读取坐标偏移"""
        offset = self.config.get("offset", None)
        if offset is not None:
            if isinstance(offset, (list, tuple)) and len(offset) >= 2:
                return (int(offset[0]), int(offset[1]))
            else:
                return (0, 0)
        else:
            offset_x = self.config.get_int("offset_x", 0)
            offset_y = self.config.get_int("offset_y", 0)
            return (offset_x, offset_y)

    def _save_position(self, context, position: tuple):
        """保存位置到黑板（应用偏移）

        坐标转换由 ExecutionContext 的 execute_mouse_* 方法自动处理。

        Args:
            context: 执行上下文
            position: 原始位置（窗口相对坐标或屏幕绝对坐标）
        """
        save_position = self.config.get_bool("save_position", True)
        if position and save_position:
            final_position = self._apply_offset(position)
            try:
                from config.settings_manager import get_default_position_key
                default_position_key = get_default_position_key()
            except ImportError:
                default_position_key = "last_detection_position"
            position_key = self.config.get("position_key", "") or default_position_key
            context.blackboard.set(position_key, final_position)
            context.blackboard.set("last_detection_x", final_position[0])
            context.blackboard.set("last_detection_y", final_position[1])

    def tick(self, context: "ExecutionContext") -> NodeStatus:
        return self._execute_with_decorators(context, self._tick_internal)

    def _tick_internal(self, context: "ExecutionContext") -> NodeStatus:

        if self._children_running and self.children:
            return self._execute_children(context)

        check_interval_ms = self.config.get_int("check_interval_ms", 300)
        effective_interval_ms = check_interval_ms
        if self._consecutive_same_count >= self._STABLE_THRESHOLD:
            effective_interval_ms = check_interval_ms * 2

        current_time = context.elapsed_time * 1000
        time_since_last = current_time - self._last_check_time
        if time_since_last < effective_interval_ms:
            return self.status

        self._last_check_time = current_time
        result = self._check_condition(context)

        # 更新连续相同结果计数
        if self._last_condition_result is not None and result == self._last_condition_result:
            self._consecutive_same_count += 1
        else:
            self._consecutive_same_count = 0
        self._last_condition_result = result

        invert = self.config.get_bool("invert", False)
        if invert:
            result = not result

        status = NodeStatus.SUCCESS if result else NodeStatus.FAILURE
        self.status = status

        if status == NodeStatus.SUCCESS and self.children:
            context.notify_node_status(self.node_id, "success")
            self._children_running = True
            return self._execute_children(context)

        return status

    @abstractmethod
    def _check_condition(self, context: "ExecutionContext") -> bool:
        """检测条件是否满足

        Args:
            context: 执行上下文

        Returns:
            条件是否满足
        """
        pass

    def _validate_region(self, region) -> bool:
        """验证区域配置是否有效

        Args:
            region: 区域配置

        Returns:
            区域是否有效
        """
        if region is None:
            return True
        if isinstance(region, (list, tuple)) and len(region) == 4:
            return all(isinstance(x, int) for x in region)
        return False

    # 差异截图：无region时的默认检测区域半径
    _DEFAULT_REGION_RADIUS = 150

    def _get_region_image(self, context):
        try:
            region_mode = self.config.get("region_mode", "fixed")
            if region_mode == "dynamic":
                region = self._resolve_dynamic_region(context)
            else:
                region = self._parse_region(self.config.get("region", None))

            # 差异截图优化：无region时尝试使用上次检测位置附近的区域
            if region is None:
                region = self._get_fallback_region(context)

            return context.get_screenshot(region)
        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"{self.NODE_TYPE} '{self.name}' 截图失败")
            return None

    def _get_effective_region(self, context):
        region_mode = self.config.get("region_mode", "fixed")
        if region_mode == "dynamic":
            return self._resolve_dynamic_region(context)
        else:
            region = self._parse_region(self.config.get("region", None))
            if region is None:
                region = self._get_fallback_region(context)
            return region

    def _get_fallback_region(self, context):
        """当未配置region时，尝试使用上次检测位置附近的区域作为回退

        避免全屏截图的开销。如果黑板中有上次检测位置，则以其为中心
        截取 _DEFAULT_REGION_RADIUS 范围内的区域。

        Args:
            context: 执行上下文

        Returns:
            region元组 (x1,y1,x2,y2) 或 None（无可用的回退位置时）
        """
        pos = context.blackboard.get("last_detection_position")
        if pos is None or not isinstance(pos, (tuple, list)) or len(pos) < 2:
            return None

        cx, cy = int(pos[0]), int(pos[1])
        r = self._DEFAULT_REGION_RADIUS

        # 边界用虚拟桌面范围而非 0：多显示器时虚拟桌面原点可为负，
        # 直接用 max(0, ...) 会把副屏上的区域错误裁到主屏
        try:
            from bt_utils.screen_utils import get_virtual_screen_bounds
            min_x, min_y, max_x, max_y = get_virtual_screen_bounds()
        except Exception:
            min_x = min_y = 0
            max_x = max_y = 10 ** 6

        return (max(min_x, cx - r), max(min_y, cy - r),
                min(max_x, cx + r), min(max_y, cy + r))

    def _resolve_dynamic_region(self, context):
        use_last_pos = self.config.get_bool("region_use_last_pos", True)
        if use_last_pos:
            anchor_key = "last_detection_position"
        else:
            anchor_key = self.config.get("region_anchor", "") or "last_detection_position"

        pos = context.blackboard.get(anchor_key)
        if pos is None or not isinstance(pos, (tuple, list)) or len(pos) < 2:
            from bt_utils.log_manager import LogManager
            LogManager.instance().log_failure(
                node_type=self.NODE_TYPE,
                node_name=self.name,
                reason=f"动态区域锚点 '{anchor_key}' 不存在或格式无效，使用全屏截图"
            )
            return None

        cx, cy = int(pos[0]), int(pos[1])

        offset = self.config.get("region_offset", [-50, -50, 50, 50])
        if isinstance(offset, str):
            try:
                offset = [int(x.strip()) for x in offset.split(",")]
            except (ValueError, AttributeError):
                offset = [-50, -50, 50, 50]

        if not isinstance(offset, (list, tuple)) or len(offset) < 4:
            offset = [-50, -50, 50, 50]

        return (cx + int(offset[0]), cy + int(offset[1]),
                cx + int(offset[2]), cy + int(offset[3]))

    def _log_condition_result(self, success: bool, reason: str = None,
                               extra_info: str = None):
        """记录条件检测结果日志

        Args:
            success: 是否成功
            reason: 失败原因（成功时为None）
            extra_info: 额外信息
        """
        if success:
            LogManager.instance().log_success(
                node_type=self.NODE_TYPE,
                node_name=self.name
            )
        else:
            log_reason = reason or "条件不满足"
            if extra_info:
                log_reason += f"，{extra_info}"
            LogManager.instance().log_failure(
                node_type=self.NODE_TYPE,
                node_name=self.name,
                reason=log_reason
            )

    def reset(self, reset_counters: bool = True) -> None:
        super().reset(reset_counters)
        check_interval_ms = self.config.get_int("check_interval_ms", 300)
        self._last_check_time = -check_interval_ms - 1
        self._consecutive_same_count = 0
        self._last_condition_result = None


class ActionNode(Node):
    """动作节点基类

    执行特定动作，动作成功后可选执行子节点。
    """
    NODE_TYPE = "ActionNode"
    
    SKIP_WINDOW_SWITCH = False

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self._window_switched = False
        self._was_already_foreground = False
        self._original_foreground_window = None

    def tick(self, context: "ExecutionContext") -> NodeStatus:
        if self._is_async:
            return self._tick_async(context)
        return self._execute_with_decorators(context, self._tick_internal)

    def _tick_internal(self, context: "ExecutionContext") -> NodeStatus:
        bound_window = context.get_bound_window()

        # 后台模式：跳过窗口切换，直接执行动作
        if bound_window and not self.SKIP_WINDOW_SWITCH:
            # 检查是否为后台输入模式
            is_bg_mode = False
            try:
                manager = context._get_input_manager()
                is_bg_mode = (manager.get_keyboard_method() == "bg" or manager.get_mouse_method() == "bg")
            except Exception:
                pass

            if is_bg_mode:
                # 后台模式不需要切换窗口
                if not self._children_running:
                    status = self._execute_action(context)
                    self.status = status

                    if status == NodeStatus.SUCCESS and self.children:
                        context.notify_node_status(self.node_id, "success")
                        self._children_running = True
                        return self._execute_children(context)

                    return status
                else:
                    return self._execute_children(context)

            if self._children_running:
                return self._execute_children(context)
            
            from bt_utils.window_manager import WindowManager
            
            if not self._window_switched:
                self._was_already_foreground = WindowManager.is_foreground_window(bound_window)
                foreground_hwnd = WindowManager.get_foreground_window()
                
                if self._was_already_foreground:
                    self._window_switched = True
                else:
                    if self._original_foreground_window is None:
                        self._original_foreground_window = foreground_hwnd
                    
                    max_retries = 3
                    switch_success = False
                    
                    for attempt in range(max_retries):
                        retry_delay = 0.1 * (2 ** attempt)
                        context.smart_switch_to_bound_window()
                        after_switch_foreground = WindowManager.is_foreground_window(bound_window)
                        
                        if after_switch_foreground:
                            switch_success = True
                            break
                        else:
                            time.sleep(retry_delay)
                    
                    if switch_success:
                        self._window_switched = True
                    else:
                        LogManager.instance().log_failure(
                            node_type="动作节点",
                            node_name=self.name,
                            reason="窗口切换失败，目标窗口无法切换到前台"
                        )
                        self._reset_window_state()
                        return NodeStatus.FAILURE
            else:
                is_foreground_now = WindowManager.is_foreground_window(bound_window)
                if not is_foreground_now:
                    self._window_switched = False
                    self._was_already_foreground = False
                    return NodeStatus.RUNNING
            
            status = self._execute_action(context)
            
            if status != NodeStatus.RUNNING:
                if not self._was_already_foreground and self._original_foreground_window is not None:
                    from bt_utils.window_manager import WindowManager
                    if WindowManager.is_window_valid(self._original_foreground_window):
                        WindowManager.set_foreground_window(self._original_foreground_window)
                        context._previous_foreground_window = None
                self._window_switched = False
                self._was_already_foreground = False
                self._original_foreground_window = None
            
            self.status = status

            if status == NodeStatus.SUCCESS and self.children:
                context.notify_node_status(self.node_id, "success")
                self._children_running = True
                return self._execute_children(context)

            return status

        if not self._children_running:
            status = self._execute_action(context)
            self.status = status

            if status == NodeStatus.SUCCESS and self.children:
                context.notify_node_status(self.node_id, "success")
                self._children_running = True
                return self._execute_children(context)

            return status
        else:
            return self._execute_children(context)

    def _reset_window_state(self) -> None:
        self._window_switched = False
        self._was_already_foreground = False
        self._original_foreground_window = None

    def reset(self, reset_counters: bool = True) -> None:
        super().reset(reset_counters)
        self._window_switched = False
        self._was_already_foreground = False
        self._original_foreground_window = None
        self._async_started = False

    def _tick_async(self, context: "ExecutionContext") -> NodeStatus:
        async_executor = context.get_async_executor()
        if not async_executor:
            return self._execute_with_decorators(context, self._tick_internal)

        if self.status != NodeStatus.RUNNING and not self._async_started:
            context.notify_node_status(self.node_id, "running")
            self.status = NodeStatus.RUNNING

        if not self._async_started:
            timeout_ms = self.config.get_int("timeout_ms", 30000)

            def _async_func():
                try:
                    return self._execute_action(context)
                except Exception as e:
                    LogManager.instance().log_failure(
                        node_type=self.NODE_TYPE,
                        node_name=self.name,
                        reason=f"异步执行异常: {e}"
                    )
                    return NodeStatus.FAILURE

            async_executor.submit(self.node_id, _async_func, timeout_ms)
            self._async_started = True
            return NodeStatus.RUNNING

        if async_executor.is_done(self.node_id):
            result = async_executor.get_result(self.node_id)
            self.status = result
            self._async_started = False

            if result == NodeStatus.SUCCESS:
                context.notify_node_status(self.node_id, "success")
                LogManager.instance().log_success(
                    node_type=self.NODE_TYPE,
                    node_name=self.name
                )
                if self.children:
                    return self._execute_children(context)
            elif result == NodeStatus.FAILURE:
                context.notify_node_status(self.node_id, "failure")
                LogManager.instance().log_failure(
                    node_type=self.NODE_TYPE,
                    node_name=self.name,
                    reason="异步执行失败"
                )

            return result

        return NodeStatus.RUNNING

    @abstractmethod
    def _execute_action(self, context: "ExecutionContext") -> NodeStatus:
        """执行动作

        Args:
            context: 执行上下文

        Returns:
            执行状态
        """
        pass


class StartNode(CompositeNode):
    """
    开始节点 - 行为树的根节点
    
    特性:
    - 继承CompositeNode的组合节点特性
    - 顺序执行子节点，失败后继续执行下一个
    - 支持装饰器参数(重复次数、重复间隔、超时等)
    - 不可删除、不可复制、不可剪切
    """
    NODE_TYPE = "StartNode"
    
    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self._is_protected = True
        self.bind_window = self.config.get_bool("bind_window", False)
        self.window_title = self.config.get("window_title", "")
        self.window_pid = self.config.get_int("window_pid", 0)
        self._window_bound = False
        self._completed = False
    
    def tick(self, context: "ExecutionContext") -> NodeStatus:
        """顺序执行所有子节点,失败后继续执行
        
        与SequenceNode的区别:
        - SequenceNode: 任一子节点失败立即返回FAILURE
        - StartNode: 子节点失败后继续执行后续子节点
        
        Args:
            context: 执行上下文
            
        Returns:
            NodeStatus: 执行状态
        """
        return self._execute_with_decorators(context, self._tick_internal)
    
    def _tick_internal(self, context: "ExecutionContext") -> NodeStatus:
        if self._completed:
            return NodeStatus.SUCCESS

        bind_window = self.config.get_bool("bind_window", False)
        window_title = self.config.get("window_title", "")
        if bind_window and window_title and not self._window_bound:
            self._bind_window_to_context(context)
            self._window_bound = True

        if not self.children:
            self._completed = True
            LogManager.instance().log_success(
                node_type="开始节点",
                node_name=self.name
            )
            return NodeStatus.SUCCESS

        while self.current_index < len(self.children):
            child = self.children[self.current_index]
            
            if not child.config.enabled:
                self.current_index += 1
                continue

            status = child.tick(context)
            
            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING
            
            if status == NodeStatus.FAILURE:
                LogManager.instance().log_failure(
                    node_type="开始节点",
                    node_name=self.name,
                    reason=f"子节点 '{child.name}' 执行失败，继续执行后续节点"
                )
            
            self.current_index += 1
        
        self.current_index = 0
        self._completed = True
        
        LogManager.instance().log_success(
            node_type="开始节点",
            node_name=self.name
        )
        
        return NodeStatus.SUCCESS
    
    def reset(self, reset_counters: bool = True) -> None:
        """重置节点状态"""
        super().reset(reset_counters)
        self._window_bound = False
        self._completed = False
        for child in self.children:
            child.reset()

    def _bind_window_to_context(self, context: "ExecutionContext") -> None:
        from bt_utils.window_manager import WindowManager

        window_hwnd = self.config.get_int("window_hwnd", 0)
        window_pid = self.config.get_int("window_pid", 0)
        window_title = self.config.get("window_title", "")

        hwnd, find_method = WindowManager.find_window_smart_with_hwnd(
            hwnd=window_hwnd if window_hwnd > 0 else 0,
            pid=window_pid if window_pid > 0 else None,
            title_keyword=window_title
        )

        if hwnd:
            context.bind_window(hwnd)
            if window_hwnd != hwnd:
                self.config.set("window_hwnd", hwnd)
        else:
            LogManager.instance().log_failure(
                node_type="开始节点",
                node_name=self.name,
                reason=f"未找到窗口: hwnd={window_hwnd}, pid={window_pid}, title='{window_title}'"
            )
    
    def _reset_for_retry(self) -> None:
        """重试时重置状态（保留重试计数器）"""
        super()._reset_for_retry()
        self._completed = False
    
    def _reset_for_repeat(self) -> None:
        """重复执行时重置状态（保留重复计数器）"""
        super()._reset_for_repeat()
        self._completed = False
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            Dict[str, Any]: 节点数据字典
        """
        data = super().to_dict()
        data["_is_protected"] = self._is_protected
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StartNode":
        """
        从字典反序列化
        
        Args:
            data: 节点数据字典
            
        Returns:
            StartNode: 节点实例
        """
        node = super().from_dict(data)
        node._is_protected = data.get("_is_protected", True)
        return node


class SubtreeNode(CompositeNode):
    """子树引用节点

    引用外部行为树文件作为子树执行。

    配置参数:
        subtree_path: 子树文件路径（相对于项目根目录）
        blackboard_mode: "inherit" | "isolated" | "namespaced"
        namespace: 命名空间前缀（namespaced模式使用）
        auto_reload: 每次执行前重新加载子树（默认False，缓存加载）
    """
    NODE_TYPE = "SubtreeNode"

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)
        self.subtree_path = self.config.get("subtree_path", "")
        self.blackboard_mode = self.config.get("blackboard_mode", "inherit")
        self.namespace = self.config.get("namespace", "")
        self.auto_reload = self.config.get_bool("auto_reload", False)

        self._subtree_root: Optional[Node] = None
        self._subtree_context: Optional["ExecutionContext"] = None
        self._loaded_path: Optional[str] = None
        self._subtree_project_dir: Optional[str] = None
        self._file_modified_time: Optional[float] = None

    def tick(self, context: "ExecutionContext") -> NodeStatus:
        return self._execute_with_decorators(context, self._tick_internal)

    def _tick_internal(self, context: "ExecutionContext") -> NodeStatus:

        if not self._ensure_loaded(context):
            return NodeStatus.FAILURE

        if self._subtree_root is None:
            LogManager.instance().log_failure(
                node_type="子树节点",
                node_name=self.name,
                reason="子树加载失败"
            )
            return NodeStatus.FAILURE

        # 同步父上下文的时间信息到子树上下文
        # 子树上下文在 _create_subtree_context 中创建时 elapsed_time=0.0，
        # 而 Engine 只更新根上下文的 elapsed_time，
        # 如果不同步，子树内依赖 elapsed_time 的逻辑（如 childinterval、timeout）会失效
        if self._subtree_context is not None:
            self._subtree_context.elapsed_time = context.elapsed_time
            self._subtree_context.tick_count = context.tick_count

        context.push_subtree(self._loaded_path)

        try:
            status = self._subtree_root.tick(self._subtree_context)

            if status != NodeStatus.RUNNING:
                self._on_subtree_complete(status)

            return status
        finally:
            context.pop_subtree()

    def _ensure_loaded(self, context: "ExecutionContext") -> bool:
        """确保子树已加载，返回是否成功"""
        from .cycle_detector import CycleDetector

        subtree_project_dir = self._resolve_path(context)
        if not subtree_project_dir:
            LogManager.instance().log_failure(
                node_type="子树节点",
                node_name=self.name,
                reason="子树路径为空"
            )
            return False

        if not os.path.isdir(subtree_project_dir):
            LogManager.instance().log_failure(
                node_type="子树节点",
                node_name=self.name,
                reason=f"子树项目文件夹不存在: {subtree_project_dir}"
            )
            return False

        is_encrypted, aut_file = self._check_encrypted_subtree(subtree_project_dir)

        if is_encrypted:
            tree_data = self._load_encrypted_subtree(subtree_project_dir, aut_file, context)
            if not tree_data:
                return False
        else:
            tree_file = self._find_tree_file(subtree_project_dir)
            if not tree_file:
                LogManager.instance().log_failure(
                    node_type="子树节点",
                    node_name=self.name,
                    reason=f"子树项目文件夹中未找到行为树文件: {subtree_project_dir}"
                )
                return False

        if not is_encrypted and self._subtree_root and not self.config.get_bool("auto_reload", False):
            if self._loaded_path == tree_file:
                if not self._has_file_changed(tree_file):
                    if self._subtree_context is None:
                        self._subtree_context = self._create_subtree_context(context)
                    return True

        detector = CycleDetector()
        if not detector.check_with_context(context, subtree_project_dir):
            LogManager.instance().log_failure(
                node_type="子树节点",
                node_name=self.name,
                reason=f"检测到循环引用: {subtree_project_dir}"
            )
            return False

        if not context.can_enter_subtree():
            LogManager.instance().log_failure(
                node_type="子树节点",
                node_name=self.name,
                reason=f"子树嵌套深度超过限制 ({ExecutionContext.MAX_SUBTREE_DEPTH})"
            )
            return False

        try:
            from .serializer import Serializer

            if is_encrypted and tree_data:
                self._subtree_root, _, _ = Serializer.deserialize(tree_data)
                self._loaded_path = f"encrypted:{subtree_project_dir}"
            else:
                self._subtree_root, _, _ = Serializer.load_from_file(tree_file)
                self._loaded_path = tree_file
                self._file_modified_time = os.path.getmtime(tree_file)

            self._subtree_project_dir = subtree_project_dir
            self._subtree_context = self._create_subtree_context(context)

            if is_encrypted:
                self._inject_aut_parameters(self._subtree_context)

            return True

        except Exception as e:
            LogManager.instance().log_failure(
                node_type="子树节点",
                node_name=self.name,
                reason=f"加载子树失败: {e}"
            )
            return False

    def _create_subtree_context(self, parent_context: "ExecutionContext") -> "ExecutionContext":
        """根据 blackboard_mode 创建子树上下文

        子树的 project_root 设置为子树项目文件夹，
        确保子树中的条件节点、脚本节点等能正确引用项目内资源。
        """
        from .context import ExecutionContext
        from .blackboard import NamespacedBlackboard

        subtree_project_dir = getattr(self, '_subtree_project_dir', None) or parent_context.project_root

        blackboard_mode = self.config.get("blackboard_mode", "inherit")

        if blackboard_mode == "inherit":
            sub_context = ExecutionContext(subtree_project_dir)
            sub_context.blackboard = parent_context.blackboard
            sub_context._subtree_stack = parent_context._subtree_stack.copy()
            sub_context._parent_context = parent_context
            return sub_context

        elif blackboard_mode == "isolated":
            sub_context = ExecutionContext(subtree_project_dir)
            sub_context._subtree_stack = parent_context._subtree_stack.copy()
            sub_context._parent_context = parent_context
            return sub_context

        elif blackboard_mode == "namespaced":
            sub_context = ExecutionContext(subtree_project_dir)
            namespace = self.config.get("namespace", "") or self.name or self.node_id
            sub_context.blackboard = NamespacedBlackboard(
                parent_context.blackboard,
                namespace
            )
            sub_context._parent_context = parent_context
            sub_context._subtree_stack = parent_context._subtree_stack.copy()
            return sub_context

        return parent_context

    def _resolve_path(self, context: "ExecutionContext") -> Optional[str]:
        """解析子树项目文件夹路径（相对路径→绝对路径）

        subtree_path 现在指向项目文件夹而非 JSON 文件。
        """
        subtree_path = self.config.get("subtree_path", "")
        if not subtree_path:
            return None

        if os.path.isabs(subtree_path):
            return subtree_path

        return os.path.join(context.project_root, subtree_path)

    def _find_tree_file(self, project_dir: str) -> Optional[str]:
        """在子树项目文件夹中查找行为树文件

        查找顺序：
        1. project.json 中指定的 main_tree
        2. tree.json（默认行为树文件）
        3. 文件夹中唯一的 .json 文件（排除 project.json）
        """
        project_json = os.path.join(project_dir, "project.json")
        if os.path.exists(project_json):
            try:
                with open(project_json, 'r', encoding='utf-8') as f:
                    import json
                    proj_data = json.load(f)
                main_tree = proj_data.get("main_tree", "tree.json")
                tree_path = os.path.join(project_dir, main_tree)
                if os.path.exists(tree_path):
                    return tree_path
            except Exception:
                pass

        tree_json = os.path.join(project_dir, "tree.json")
        if os.path.exists(tree_json):
            return tree_json

        json_files = [f for f in os.listdir(project_dir)
                      if f.endswith('.json') and f != 'project.json']
        if len(json_files) == 1:
            return os.path.join(project_dir, json_files[0])

        return None

    def _has_file_changed(self, path: str) -> bool:
        """检查文件是否已修改"""
        if self._file_modified_time is None:
            return True
        try:
            current_mtime = os.path.getmtime(path)
            return current_mtime > self._file_modified_time
        except Exception:
            return True

    def _on_subtree_complete(self, status: NodeStatus):
        """子树完成时的处理"""
        pass

    def _check_encrypted_subtree(self, project_dir: str) -> tuple:
        try:
            project_json = os.path.join(project_dir, "project.json")
            if not os.path.exists(project_json):
                return False, None

            with open(project_json, 'r', encoding='utf-8') as f:
                import json as _json
                proj_data = _json.load(f)

            if proj_data.get("encrypted") and proj_data.get("aut_file"):
                aut_path = os.path.join(project_dir, proj_data["aut_file"])
                if os.path.exists(aut_path):
                    return True, aut_path
        except Exception:
            pass

        return False, None

    def _load_encrypted_subtree(self, project_dir: str, aut_file: str,
                                 context: "ExecutionContext") -> Optional[dict]:
        try:
            from bt_core.file_decoder import BtexeFileDecoder
            decryption_key = self._get_decryption_key(aut_file, context)
            if not decryption_key:
                LogManager.instance().log_failure(
                    node_type="子树节点",
                    node_name=self.name,
                    reason="无法获取解密密钥"
                )
                return None

            decoder = BtexeFileDecoder()
            parsed_data = decoder.decode(aut_file, decryption_key)

            if not parsed_data:
                return None

            tree_data = parsed_data.get("tree_data", {})

            resources = parsed_data.get("resources", {})
            if resources:
                import json as _json
                subtree_name = os.path.basename(project_dir)
                resource_dir = os.path.join(
                    os.path.dirname(project_dir), "subtrees", subtree_name
                )
                os.makedirs(resource_dir, exist_ok=True)
                for res_name, res_data in resources.items():
                    try:
                        import base64
                        res_path = os.path.join(resource_dir, res_name)
                        os.makedirs(os.path.dirname(res_path), exist_ok=True)
                        with open(res_path, 'wb') as rf:
                            rf.write(base64.b64decode(res_data))
                    except Exception:
                        pass

            return tree_data

        except ImportError:
            return None
        except Exception as e:
            LogManager.instance().log_failure(
                node_type="子树节点",
                node_name=self.name,
                reason=f"加载加密子树失败: {e}"
            )
            return None

    def _get_decryption_key(self, aut_file: str, context: "ExecutionContext") -> Optional[bytes]:
        try:
            from bt_core.file_decoder import BtexeFileDecoder
            decoder = BtexeFileDecoder()
            metadata = decoder.read_metadata(aut_file)
            file_hash = metadata.get("file_hash", "")
            if not file_hash:
                return None

            api_client = getattr(context, '_api_client', None)
            if not api_client:
                return None

            token = api_client.get_session_token()
            response = api_client.get_decryption_key(file_hash, token)
            if not response.get("success"):
                return None

            import base64
            key_base64 = response.get("data", {}).get("key", "")
            if not key_base64:
                return None

            return base64.b64decode(key_base64)
        except ImportError:
            return None
        except Exception:
            return None

    def _inject_aut_parameters(self, sub_context: "ExecutionContext"):
        prefix = "_aut_param_"
        if hasattr(self.config, 'extra'):
            items = self.config.extra.items()
        elif isinstance(self.config, dict):
            items = self.config.items()
        else:
            return

        node_params = {}
        for key, value in items:
            if key.startswith(prefix):
                param_path = key[len(prefix):]
                if "__" in param_path:
                    node_id, param_name = param_path.split("__", 1)
                    if node_id not in node_params:
                        node_params[node_id] = {}
                    node_params[node_id][param_name] = value

        for node_id, params in node_params.items():
            target_node = self._find_node_by_id(self._subtree_root, node_id)
            if target_node:
                for param_name, value in params.items():
                    sub_context.blackboard.set(param_name, value)
                    self._apply_param_to_node(target_node, param_name, value)

    def _find_node_by_id(self, root: "Node", node_id: str):
        if root is None:
            return None
        if root.node_id == node_id:
            return root
        for child in root.children:
            result = self._find_node_by_id(child, node_id)
            if result:
                return result
        return None

    def _apply_param_to_node(self, node: "Node", param_name: str, value: Any):
        if isinstance(value, str) and value.startswith('['):
            try:
                import json as _json
                value = _json.loads(value)
            except (_json.JSONDecodeError, ValueError):
                pass

        if isinstance(value, str):
            try:
                if value.lstrip('-').isdigit():
                    value = int(value)
                elif value.replace('.', '', 1).lstrip('-').isdigit():
                    value = float(value)
            except (ValueError, AttributeError):
                pass

        if hasattr(node.config, 'set'):
            node.config.set(param_name, value)
        elif hasattr(node.config, param_name):
            setattr(node.config, param_name, value)

        if hasattr(node, param_name):
            setattr(node, param_name, value)

    def reset(self, reset_counters: bool = True) -> None:
        """重置节点状态"""
        super().reset(reset_counters)
        if self._subtree_root:
            self._subtree_root.reset(reset_counters)

    def abort(self, context: "ExecutionContext") -> None:
        """中止节点执行"""
        if self._subtree_root and self._subtree_context:
            self._subtree_root.abort(self._subtree_context)
        self._subtree_context = None
        self._children_running = False
        super().abort(context)

    def _reset_for_retry(self) -> None:
        """重试时重置状态"""
        super()._reset_for_retry()
        if self._subtree_root:
            self._subtree_root.reset(False)

    def _reset_for_repeat(self) -> None:
        """重复执行时重置状态"""
        super()._reset_for_repeat()
        if self._subtree_root:
            self._subtree_root.reset(False)


