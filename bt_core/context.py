from typing import Callable, Optional, Tuple, List, TYPE_CHECKING
import os
import re
import time

from .blackboard import Blackboard
from bt_utils.log_manager import LogManager

if TYPE_CHECKING:
    pass


class ExecutionContext:
    """执行上下文

    封装行为树执行过程中的运行时依赖，包括黑板系统、
    截图管理器、输入控制器和OCR管理器等。

    Attributes:
        blackboard: 黑板系统实例
        elapsed_time: 已执行时间（秒）
        tick_count: tick执行次数
        project_root: 项目根目录
    """

    MAX_SUBTREE_DEPTH = 10

    def __init__(self, project_root: str = None):
        self.blackboard = Blackboard()
        self.elapsed_time: float = 0.0
        self.tick_count: int = 0
        self.project_root = project_root or os.getcwd()
        self._is_running = True
        self._is_paused = False
        self._on_node_status: Optional[Callable] = None
        self._screenshot_manager = None
        self._ocr_manager = None
        self._alarm_player = None
        self._path_resolver = None
        self._stats_collector = None
        self._bound_window: Optional[int] = None
        # 截图通道：printwindow（默认，PC 原生）| screengrab（安卓窗口按屏幕抓取）
        self._capture_mode: str = "printwindow"
        # 绑定窗口内容区顶部需要扣除的标题栏高度（apkstart 应用窗口为 38px）
        self._content_offset_top: int = 0
        self._previous_foreground_window: Optional[int] = None
        self._subtree_stack: List[str] = []
        self._parent_context: Optional['ExecutionContext'] = None
        # 帧级截图缓存：同一tick内相同region只截图一次
        self._screenshot_cache: dict = {}
        self._screenshot_cache_tick: int = -1
        # Tab管理器引用（用于启动/停止节点访问其他行为树）
        self._tab_manager = None
        self._current_tab_id: Optional[str] = None
        self._headless: bool = False
        self._async_executor = None
        # 消息总线和服务层（阶段 3 新增）
        self._message_bus = None
        self._service_registry = None
        self._adapter_manager = None
        self._auth_principal = None

    def set_stats_collector(self, collector):
        """设置统计收集器
        
        Args:
            collector: 统计收集器实例
        """
        self._stats_collector = collector

    def set_tab_manager(self, tab_manager, tab_id: str = None):
        """设置Tab管理器和当前Tab ID

        Args:
            tab_manager: GuiTabManager 实例
            tab_id: 当前 Tab ID
        """
        self._tab_manager = tab_manager
        self._current_tab_id = tab_id

    def get_tab_manager(self):
        """获取Tab管理器"""
        return self._tab_manager

    def get_current_tab_id(self) -> Optional[str]:
        """获取当前Tab ID"""
        return self._current_tab_id

    def set_headless(self, headless: bool) -> None:
        """设置 Headless 模式

        Args:
            headless: True=无 GUI 模式（notify_node_status 为空操作）
        """
        self._headless = headless

    def is_headless(self) -> bool:
        """是否为 Headless 模式"""
        return self._headless

    def set_async_executor(self, executor) -> None:
        """设置异步执行器"""
        self._async_executor = executor

    def get_async_executor(self):
        """获取异步执行器"""
        return getattr(self, '_async_executor', None)

    def set_message_bus(self, bus) -> None:
        """设置消息总线

        同时将 bus 注入 blackboard，使 blackboard.set() 能向总线发布
        bt.{tree_id}.data.blackboard.changed 事件。传 None 清除引用并降级。
        """
        self._message_bus = bus
        if self.blackboard is not None:
            self.blackboard.set_message_bus(bus, self.get_tree_id())

    def get_message_bus(self):
        """获取消息总线"""
        return self._message_bus

    def set_service_registry(self, registry) -> None:
        """设置服务注册中心"""
        self._service_registry = registry

    def get_service(self, name: str):
        """获取服务"""
        if self._service_registry:
            return self._service_registry.get(name)
        return None

    def set_adapter_manager(self, manager) -> None:
        """设置适配器管理器"""
        self._adapter_manager = manager

    def get_adapter_manager(self):
        """获取适配器管理器"""
        return self._adapter_manager

    def publish_event(self, topic: str, data) -> None:
        """发布事件到消息总线"""
        if self._message_bus:
            self._message_bus.publish(topic, data)

    def set_auth_principal(self, principal) -> None:
        """设置当前认证主体"""
        self._auth_principal = principal

    def get_auth_principal(self):
        """获取当前认证主体"""
        return self._auth_principal

    def is_authenticated(self) -> bool:
        """是否已认证"""
        return self._auth_principal is not None

    def get_tree_id(self) -> str:
        """返回当前行为树 ID（用于消息总线主题隔离）"""
        return self._current_tab_id or "default"

    def push_subtree(self, subtree_path: str) -> None:
        """进入子树时压栈

        Args:
            subtree_path: 子树文件路径
        """
        self._subtree_stack.append(subtree_path)
    
    def pop_subtree(self) -> Optional[str]:
        """退出子树时出栈

        Returns:
            弹出的子树路径，如果栈为空返回 None
        """
        return self._subtree_stack.pop() if self._subtree_stack else None
    
    def get_subtree_depth(self) -> int:
        """获取当前子树嵌套深度"""
        return len(self._subtree_stack)
    
    def is_in_subtree(self, path: str) -> bool:
        """检查路径是否已在引用链中

        Args:
            path: 待检查的子树路径

        Returns:
            是否已在引用链中
        """
        normalized_path = os.path.normpath(os.path.abspath(path))
        for p in self._subtree_stack:
            if os.path.normpath(os.path.abspath(p)) == normalized_path:
                return True
        return False
    
    def can_enter_subtree(self) -> bool:
        """检查是否可以进入新的子树（深度限制）"""
        return len(self._subtree_stack) < self.MAX_SUBTREE_DEPTH
    
    def record_node_stats(self, node_id: str, node_type: str, node_name: str,
                          status: str, duration_ms: float):
        """记录节点执行统计
        
        Args:
            node_id: 节点ID
            node_type: 节点类型
            node_name: 节点名称
            status: 执行状态
            duration_ms: 执行时长（毫秒）
        """
        if self._stats_collector:
            self._stats_collector.record_node(node_id, node_type, node_name, status, duration_ms)
    
    def check_running(self) -> bool:
        if self._is_paused:
            self._wait_if_paused()
        if self._parent_context and not self._parent_context._is_running:
            self._is_running = False
            return False
        return self._is_running
    
    def _wait_if_paused(self, check_interval: float = 0.1) -> None:
        while self._is_paused and self._is_running:
            time.sleep(check_interval)

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._is_running

    @property
    def is_paused(self) -> bool:
        """是否暂停"""
        return self._is_paused

    def notify_node_status(self, node_id: str, status: str) -> None:
        """通知节点状态变化

        Args:
            node_id: 节点ID
            status: 状态字符串
        """
        if self._headless:
            return
        if self._on_node_status:
            try:
                from bt_utils.ui_dispatcher import UIUpdateDispatcher
                dispatcher = UIUpdateDispatcher()
                dispatcher.dispatch_node_status(node_id, status, self._on_node_status)
            except ImportError:
                self._on_node_status(node_id, status)

    def get_screenshot(self, region: tuple = None):
        """获取屏幕截图（带帧级缓存）

        同一tick内相同region的截图只执行一次，避免多节点重复截图。

        Args:
            region: 截图区域 (left, top, right, bottom)，窗口相对坐标

        Returns:
            PIL.Image 截图对象
        """
        # 确保region为tuple（list不可作为dict键）
        if isinstance(region, list):
            region = tuple(region)

        # 新tick开始时清空缓存
        if self.tick_count != self._screenshot_cache_tick:
            self._screenshot_cache.clear()
            self._screenshot_cache_tick = self.tick_count

        # 生成缓存键：region为None时用特殊标记
        cache_key = region if region else "__full_screen__"

        # 命中缓存直接返回
        if cache_key in self._screenshot_cache:
            return self._screenshot_cache[cache_key]

        # 执行截图
        if self._bound_window:
            if self._capture_mode == "screengrab":
                from bt_utils.window_screen_capture import capture_window_content
                screenshot = capture_window_content(
                    self._bound_window, region, self._content_offset_top
                )
            else:
                from bt_utils.window_capture import WindowCapture
                if region:
                    screenshot = WindowCapture.capture_window_region(self._bound_window, region)
                else:
                    screenshot = WindowCapture.capture_window(self._bound_window)
        else:
            if self._screenshot_manager is None:
                from bt_utils.screenshot import ScreenshotManager
                self._screenshot_manager = ScreenshotManager()

            if region:
                screenshot = self._screenshot_manager.get_region_screenshot(region)
            else:
                screenshot = self._screenshot_manager.get_full_screenshot()

        # 写入缓存
        self._screenshot_cache[cache_key] = screenshot
        return screenshot

    def _get_input_manager(self):
        """获取 InputControllerManager 单例"""
        from bt_utils.input_manager import InputControllerManager
        return InputControllerManager()

    def execute_key_press(self, key: str, action: str = "press", duration: int = 0) -> None:
        """执行按键操作"""
        manager = self._get_input_manager()
        kwargs = {}
        if manager.get_keyboard_method() == "bg" and self._bound_window:
            kwargs["hwnd"] = self._bound_window
        engine = manager.get_keyboard_engine(**kwargs)
        if engine:
            engine.key_press(key, action, duration)

        self._screenshot_cache.clear()

    def execute_mouse_click(self, button: str = "left", position: tuple = None,
                           action: str = "press", duration: int = 0,
                           x_float: int = 0, y_float: int = 0) -> None:
        """执行鼠标点击（全局自动坐标转换）"""
        manager = self._get_input_manager()
        mouse_method = manager.get_mouse_method()

        if position:
            if mouse_method == "bg" and self._bound_window:
                pass
            elif self._bound_window:
                position = self.convert_to_screen_coords(position)

            if x_float > 0 or y_float > 0:
                from bt_utils.helpers import get_random_value
                px = get_random_value(position[0], x_float, min_value=0)
                py = get_random_value(position[1], y_float, min_value=0)
                position = (px, py)

        kwargs = {}
        if mouse_method == "bg" and self._bound_window:
            kwargs["hwnd"] = self._bound_window

        engine = manager.get_mouse_engine(**kwargs)

        if engine:
            engine.mouse_click(button, position, action, duration)
        else:
            LogManager.debug_print(f"[WARN] [CTX] mouse_click: 引擎为空，未执行点击")

        self._screenshot_cache.clear()

    def execute_mouse_move(self, position: tuple, relative: bool = False,
                           x_float: int = 0, y_float: int = 0) -> None:
        """执行鼠标移动（全局自动坐标转换）"""
        manager = self._get_input_manager()
        mouse_method = manager.get_mouse_method()

        if position:
            if mouse_method == "bg" and self._bound_window and not relative:
                pass
            elif self._bound_window and not relative:
                position = self.convert_to_screen_coords(position)

            if x_float > 0 or y_float > 0:
                from bt_utils.helpers import get_random_value
                px = get_random_value(position[0], x_float, min_value=0)
                py = get_random_value(position[1], y_float, min_value=0)
                position = (px, py)

        kwargs = {}
        if mouse_method == "bg" and self._bound_window:
            kwargs["hwnd"] = self._bound_window

        engine = manager.get_mouse_engine(**kwargs)
        if engine:
            engine.mouse_move(position, relative)

        self._screenshot_cache.clear()

    def get_mouse_position(self) -> Optional[Tuple[int, int]]:
        """获取当前鼠标位置"""
        manager = self._get_input_manager()
        engine = manager.get_mouse_engine()
        if engine:
            return engine.get_position()
        return None

    def execute_mouse_scroll(self, amount: int, position: tuple = None,
                             horizontal: bool = False) -> bool:
        """执行鼠标滚轮滚动

        Returns:
            True: 已成功调用引擎；False: 引擎不可用或执行异常
        """
        try:
            manager = self._get_input_manager()
            kwargs = {}
            if manager.get_mouse_method() == "bg" and self._bound_window:
                kwargs["hwnd"] = self._bound_window
            engine = manager.get_mouse_engine(**kwargs)
            if not engine:
                return False
            engine.mouse_scroll(amount, position, horizontal)
            return True
        except Exception as e:
            LogManager.debug_print(f"[WARN] mouse_scroll failed: {e}")
            return False

    def perform_ocr(self, image, keywords: str = None, language: str = "eng",
                    region: Tuple[int, int, int, int] = None,
                    preprocess_mode: str = "normal") -> tuple:
        """执行OCR识别

        Args:
            image: PIL.Image 图像
            keywords: 关键词（逗号分隔）
            language: OCR语言
            region: 截图区域 (left, top, right, bottom)，用于坐标转换
            preprocess_mode: 预处理模式 (normal/game/adaptive/auto)

        Returns:
            (是否找到, 位置, 所有识别文本) 元组
        """
        if self._ocr_manager is None:
            from bt_utils.ocr_manager import OCRManager
            self._ocr_manager = OCRManager()

        return self._ocr_manager.recognize(
            image, keywords, language, region=region,
            preprocess_mode=preprocess_mode
        )
    
    def resolve_path(self, relative_path: str) -> str:
        """解析相对路径为绝对路径
        
        Args:
            relative_path: 相对路径（以 ./ 开头）
        
        Returns:
            绝对路径
        """
        if self._path_resolver is None:
            from bt_utils.path_resolver import PathResolver
            self._path_resolver = PathResolver(self.project_root)
        
        if relative_path.startswith("./"):
            return self._path_resolver.to_absolute(relative_path)
        return relative_path

    def bind_window(self, hwnd: int) -> None:
        self._bound_window = hwnd

    def get_bound_window(self) -> Optional[int]:
        return self._bound_window

    def set_capture_mode(self, mode: str) -> None:
        """设置截图通道

        Args:
            mode: printwindow（PC 原生）| screengrab（按窗口内容区抓屏幕）
        """
        if mode not in ("printwindow", "screengrab"):
            raise ValueError(f"不支持的截图模式: {mode}")
        self._capture_mode = mode

    def get_capture_mode(self) -> str:
        return self._capture_mode

    def set_content_offset_top(self, offset: int) -> None:
        """设置绑定窗口内容区顶部需要扣除的标题栏高度"""
        self._content_offset_top = max(0, int(offset or 0))

    def get_content_offset_top(self) -> int:
        return self._content_offset_top

    def convert_to_screen_coords(self, region: tuple) -> tuple:
        if self._bound_window is None:
            return region

        # 有内容区偏移时，以「内容区左上角」为原点换算
        if self._content_offset_top > 0:
            from bt_utils.window_geometry import (
                content_point_to_screen,
                content_region_to_screen,
                get_content_rect,
            )
            content_rect = get_content_rect(self._bound_window, self._content_offset_top)
            if content_rect:
                if len(region) == 2:
                    return content_point_to_screen(region, content_rect)
                return content_region_to_screen(region, content_rect)

        from bt_utils.coordinate import CoordinateConverter
        if len(region) == 2:
            result = CoordinateConverter.client_to_absolute(region[0], region[1], self._bound_window)
            return result if result else region
        return CoordinateConverter.window_region_to_screen(region, self._bound_window)

    def smart_switch_to_bound_window(self) -> bool:
        if self._bound_window is None:
            return False
        from bt_utils.window_manager import WindowManager
        self._previous_foreground_window = WindowManager.get_foreground_window()
        return WindowManager.set_foreground_window(self._bound_window)

    def smart_restore_foreground_window(self) -> bool:
        if self._previous_foreground_window is None:
            return False
        from bt_utils.window_manager import WindowManager
        result = WindowManager.set_foreground_window(self._previous_foreground_window)
        self._previous_foreground_window = None
        return result

    def resolve_variable_refs(self, text: str) -> str:
        """解析 ${variable_name} 变量引用

        将文本中的 ${variable_name} 替换为黑板中对应变量的值。

        Args:
            text: 包含变量引用的文本

        Returns:
            解析后的文本
        """
        if not text or "${" not in text:
            return text

        pattern = r'\$\{(\w+)\}'

        def replacer(match):
            key = match.group(1)
            value = self.blackboard.get(key)
            return str(value) if value is not None else ""

        return re.sub(pattern, replacer, text)
