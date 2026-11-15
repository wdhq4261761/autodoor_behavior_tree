import threading
import time
from typing import Optional, Callable, Dict, Any

from .nodes import Node, NodeStatus
from .context import ExecutionContext
from bt_utils.stats import get_stats_collector


class BehaviorTreeEngine:
    """行为树执行引擎

    负责行为树的加载、执行、暂停、停止等生命周期管理。
    执行在独立线程中进行，支持状态回调通知。

    Args:
        root_node: 行为树根节点
    """

    def __init__(self, root_node: Node = None):
        self.root_node = root_node
        self.context: Optional[ExecutionContext] = None
        self.last_status: Optional[NodeStatus] = None
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._tick_interval = 0.033  # 默认 33ms，与配置层 behavior_tree.tick_interval 保持一致
        self._on_status_change: Optional[Callable] = None
        self._on_node_status: Optional[Callable] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stats = get_stats_collector()
        # 异步执行器（基于 SharedThreadPool）
        from bt_utils.async_executor import AsyncExecutor
        self._async_executor = AsyncExecutor()
        # 引擎 tick 线程 ID（供 MessageBus.request() 防死锁检测使用）
        self._engine_thread_id = None

    def load_tree(self, data: Dict[str, Any]) -> None:
        """从字典数据加载行为树

        Args:
            data: 行为树字典数据
        """
        from .serializer import Serializer
        result = Serializer.deserialize(data)
        if isinstance(result, tuple):
            self.root_node = result[0]
        else:
            self.root_node = result

    def load_from_file(self, filepath: str) -> None:
        """从文件加载行为树

        Args:
            filepath: 文件路径
        """
        from .serializer import Serializer
        result = Serializer.load_from_file(filepath)
        if isinstance(result, tuple):
            self.root_node = result[0]
        else:
            self.root_node = result

    def save_to_file(self, filepath: str, format: str = "json") -> None:
        """保存行为树到文件

        Args:
            filepath: 文件路径
            format: 文件格式 (json/yaml/txt)
        """
        from .serializer import Serializer
        Serializer.save_to_file(self.root_node, filepath, format)

    def start(self, context: ExecutionContext = None) -> None:
        """启动执行

        Args:
            context: 执行上下文，为None时自动创建
        """
        with self._lock:
            if self._running:
                return

            # 每次启动清空运行日志，仅保留当次运行现场
            from bt_utils.log_manager import LogManager
            LogManager.clear_run_log()

            self.context = context or ExecutionContext()
            self.context.set_stats_collector(self._stats)
            self._running = True
            self.last_status = None
            self._paused = False
            self._stats.start_session()

            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

            # 发布事件到消息总线
            if context and hasattr(context, 'publish_event'):
                context.publish_event(
                    f"bt.{context.get_tree_id()}.event.tree.started",
                    {"tree_id": context.get_tree_id()}
                )

            if self._on_status_change:
                self._on_status_change("running")

    def stop(self) -> None:
        with self._lock:
            tree_id = self.context.get_tree_id() if self.context else "default"
            self._running = False
            self._paused = False
            self._stop_event.set()
            self._pause_event.set()

            if self.context:
                self.context._is_running = False

            if self.root_node and self.context:
                self.root_node.abort(self.context)
            elif self.root_node:
                self.root_node.reset()

            # 取消所有异步任务
            if hasattr(self, '_async_executor'):
                self._async_executor.cancel_all()

            self._stop_all_script_nodes()

            self._stats.end_session()
            self._output_stats_report()

            # 发布事件到消息总线
            if self.context and hasattr(self.context, 'publish_event'):
                self.context.publish_event(
                    f"bt.{tree_id}.event.tree.stopped",
                    {"tree_id": tree_id}
                )

            if self._on_status_change:
                self._on_status_change("stopped")

    def _stop_all_script_nodes(self) -> None:
        if not self.root_node:
            return
        from bt_nodes.actions.script import ScriptNode
        for node in self._iter_all_nodes(self.root_node):
            if isinstance(node, ScriptNode):
                node.stop_executor()

    def _iter_all_nodes(self, node):
        yield node
        if hasattr(node, 'children'):
            for child in node.children:
                yield from self._iter_all_nodes(child)

    def pause(self) -> None:
        tree_id = self.context.get_tree_id() if self.context else "default"
        self._paused = True
        self._pause_event.clear()
        # 发布事件到消息总线
        if self.context and hasattr(self.context, 'publish_event'):
            self.context.publish_event(
                f"bt.{tree_id}.event.tree.paused",
                {"tree_id": tree_id}
            )
        if self._on_status_change:
            self._on_status_change("paused")

    def resume(self) -> None:
        tree_id = self.context.get_tree_id() if self.context else "default"
        self._paused = False
        self._pause_event.set()
        # 发布事件到消息总线
        if self.context and hasattr(self.context, 'publish_event'):
            self.context.publish_event(
                f"bt.{tree_id}.event.tree.resumed",
                {"tree_id": tree_id}
            )
        if self._on_status_change:
            self._on_status_change("running")

    def get_last_status(self) -> Optional[NodeStatus]:
        """获取最近一次运行结束时根节点的最终状态。

        根节点在完成后会被 reset()，因此不能直接读取 root_node.status。
        用户主动停止或尚未运行时返回 None。
        """
        return self.last_status

    def get_status(self) -> Dict[str, Any]:
        """获取执行状态

        Returns:
            状态字典
        """
        return {
            "running": self._running,
            "paused": self._paused,
            "elapsed_time": self.context.elapsed_time if self.context else 0,
            "tick_count": self.context.tick_count if self.context else 0,
        }

    def _output_stats_report(self):
        """输出统计报告（仅终端显示，不显示在前端日志）"""
        from bt_utils.log_manager import LogManager
        
        if not self._stats.is_enabled():
            return
        
        report = self._stats.get_report()
        if not report:
            return
        
        session = report.get("session", {})
        summary = report.get("summary", {})
        
        LogManager.debug_print("📊 执行统计报告")
        LogManager.debug_print(f"  执行时长: {session.get('duration_ms', 0):.0f}ms")
        LogManager.debug_print(f"  Tick次数: {session.get('tick_count', 0)}")
        LogManager.debug_print(f"  节点执行总数: {session.get('total_node_executions', 0)}")
        LogManager.debug_print(f"  成功率: {summary.get('success_rate', 0):.1f}%")
        
        top_by_time = report.get("top_by_time", [])
        if top_by_time:
            LogManager.debug_print("  耗时最多的节点:")
            for i, node in enumerate(top_by_time[:5], 1):
                LogManager.debug_print(
                    f"    {i}. {node.get('node_name', '')} ({node.get('node_type', '')}): "
                    f"{node.get('total_time_ms', 0):.2f}ms, {node.get('total_executions', 0)}次"
                )
        
        top_by_count = report.get("top_by_count", [])
        if top_by_count:
            LogManager.debug_print("  执行最多的节点:")
            for i, node in enumerate(top_by_count[:5], 1):
                LogManager.debug_print(
                    f"    {i}. {node.get('node_name', '')} ({node.get('node_type', '')}): "
                    f"{node.get('total_executions', 0)}次, 成功率{node.get('success_rate', 0):.1f}%"
                )

    def get_stats_report(self) -> Dict[str, Any]:
        """获取统计报告

        Returns:
            统计报告字典
        """
        return self._stats.get_report()

    def export_stats(self, filepath: str) -> bool:
        """导出统计报告到文件

        Args:
            filepath: 文件路径

        Returns:
            是否成功
        """
        return self._stats.export_to_file(filepath)

    def _run_loop(self) -> None:
        # 记录引擎线程 ID（必须在 _run_loop 中记录，而非 start()）
        self._engine_thread_id = threading.get_ident()
        # 注册到 MessageBus 以激活 request() 死锁防护
        bus = self.context.get_message_bus() if self.context else None
        if bus is not None:
            bus.set_engine_thread_id(self._engine_thread_id)
        start_time = time.time()
        self._stop_event.clear()

        while self._running and not self._stop_event.is_set():
            if not self._pause_event.wait(0.1):
                continue

            if self._stop_event.is_set() or not self._running:
                break

            self.context.elapsed_time = time.time() - start_time
            self.context.tick_count += 1
            self._stats.record_tick()

            if self.root_node:
                from bt_utils.log_manager import LogManager
                try:
                    status = self.root_node.tick(self.context)
                    self.last_status = status

                    if self._on_node_status:
                        self._on_node_status(self.root_node.node_id, status.value)

                    if status != NodeStatus.RUNNING:
                        self._running = False
                        
                        self._stats.end_session()
                        self._output_stats_report()
                        
                        # 正常完成时使用 reset() 而非 abort()
                        # abort() 会将节点状态覆盖为 ABORTED 并通知 UI，导致正常完成的节点显示为"已中止"
                        # reset() 仅重置节点状态为初始值，准备下次执行，不影响最终状态显示
                        if self.root_node:
                            self.root_node.reset()
                        
                        # 通知 GUI 引擎已完成（正常完成路径）
                        if self._on_status_change:
                            self._on_status_change("completed", status)
                except Exception as e:
                    import traceback
                    status = NodeStatus.FAILURE
                    self.last_status = status
                    error_traceback = traceback.format_exc()
                    error_msg = f"[ERROR] Engine._run_loop: 异常发生\n{error_traceback}"
                    LogManager.debug_print(error_msg)
                    LogManager.instance().log_failure(
                        node_type="引擎",
                        node_name="行为树引擎",
                        reason=str(e)
                    )
                    self._running = False
                    self._stats.end_session()
                    self._output_stats_report()
                    if self.root_node:
                        self.root_node.reset()
                    
                    if self._on_status_change:
                        self._on_status_change("completed", status)

            if self._stop_event.wait(self._tick_interval):
                break
