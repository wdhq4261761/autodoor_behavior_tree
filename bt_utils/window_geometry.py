"""窗口内容区几何

apkstart 的应用窗口是「Electron 无边框壳 + 顶部自绘标题栏 + 下方嵌入的模拟器画面」。
本模块把「内容区」（真正的安卓画面）在屏幕上的矩形作为唯一来源，
截图与坐标换算都从这里取，避免两处各算一遍导致系统性偏移。

所有纯几何函数都显式接收矩形，便于在无窗口环境下测试。
"""
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple

user32 = ctypes.windll.user32

Rect = Tuple[int, int, int, int]

DEFAULT_CONTENT_OFFSET_TOP = 38


def offset_rect(rect: Optional[Rect],
                offset_top: int = DEFAULT_CONTENT_OFFSET_TOP) -> Optional[Rect]:
    """把客户区矩形裁掉顶部标题栏，得到内容区矩形。

    Args:
        rect: 客户区屏幕矩形 (left, top, right, bottom)
        offset_top: 顶部需要裁掉的高度（px）

    Returns:
        内容区屏幕矩形；rect 为空时返回 None
    """
    if rect is None:
        return None
    offset = max(0, int(offset_top or 0))
    left, top, right, bottom = rect
    return (left, top + offset, right, bottom)


def content_point_to_screen(point: Optional[Tuple[int, int]],
                            rect: Optional[Rect]) -> Optional[Tuple[int, int]]:
    """内容区坐标 → 屏幕坐标"""
    if point is None or rect is None:
        return None
    return (point[0] + rect[0], point[1] + rect[1])


def content_region_to_screen(region: Optional[Tuple[int, int, int, int]],
                             rect: Optional[Rect]) -> Optional[Tuple[int, int, int, int]]:
    """内容区矩形 → 屏幕矩形"""
    if region is None or rect is None:
        return None
    left, top = rect[0], rect[1]
    return (region[0] + left, region[1] + top, region[2] + left, region[3] + top)


def clamp_region_to_size(region: Optional[Tuple[int, int, int, int]],
                         size: Tuple[int, int]) -> Optional[Tuple[int, int, int, int]]:
    """把区域钳制到 (width, height) 内；完全越界或退化时返回 None"""
    if not region or not size:
        return None
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        return None

    left = max(0, int(region[0]))
    top = max(0, int(region[1]))
    right = min(width, int(region[2]))
    bottom = min(height, int(region[3]))
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def get_client_rect_screen(hwnd: int) -> Optional[Rect]:
    """获取客户区在屏幕上的矩形（物理像素）"""
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None

    origin = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None

    return (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)


def get_content_rect(hwnd: int,
                     offset_top: int = DEFAULT_CONTENT_OFFSET_TOP) -> Optional[Rect]:
    """获取内容区在屏幕上的矩形（已扣除顶部标题栏）"""
    return offset_rect(get_client_rect_screen(hwnd), offset_top)
