"""按窗口内容区抓屏

apkstart 的应用窗口由 Electron 壳与嵌入的模拟器子窗口组成，
`PrintWindow` 在这种跨进程子窗口上通常只能拿到黑帧；
因此这里直接抓「内容区在屏幕上的那块像素」。

抓图前提：窗口可见且未被遮挡（屏幕抓图的物理限制）。
"""
import ctypes
from ctypes import wintypes
from typing import Callable, Optional, Tuple

from PIL import Image, ImageGrab

from bt_utils.window_geometry import clamp_region_to_size, get_content_rect

user32 = ctypes.windll.user32


def capture_window_content(hwnd: int,
                           region: Optional[Tuple[int, int, int, int]] = None,
                           offset_top: int = 0,
                           grabber: Optional[Callable] = None) -> Image.Image:
    """抓取窗口内容区（安卓画面）的屏幕像素。

    Args:
        hwnd: 窗口句柄
        region: 内容区相对坐标 (left, top, right, bottom)，None 表示整块内容区
        offset_top: 内容区顶部需要扣掉的标题栏高度
        grabber: 可注入的截图函数，便于测试

    Returns:
        PIL.Image

    Raises:
        RuntimeError: 取不到窗口内容区几何
        ValueError: 区域完全越界或退化
    """
    content_rect = get_content_rect(hwnd, offset_top)
    if content_rect is None:
        raise RuntimeError(f"无法获取窗口 {hwnd} 的内容区矩形")

    if grabber is None:
        image = ImageGrab.grab(bbox=content_rect, all_screens=True)
    else:
        image = grabber(bbox=content_rect, all_screens=True)

    if region:
        clipped = clamp_region_to_size(region, image.size)
        if clipped is None:
            raise ValueError(f"截图区域无效或完全越界: {region}")
        image = image.crop(clipped)

    return image


def is_window_occluded(hwnd: int,
                       rect: Optional[Tuple[int, int, int, int]],
                       sampler: Optional[Callable[[int, int], int]] = None) -> bool:
    """用 3x3 采样判断内容区是否被其它窗口遮挡。

    Args:
        hwnd: 目标窗口句柄
        rect: 内容区屏幕矩形
        sampler: 可注入的取窗口函数 (x, y) -> hwnd，便于测试

    Returns:
        True 表示至少一个采样点不属于目标窗口
    """
    if not rect:
        return False

    left, top, right, bottom = rect
    if right <= left or bottom <= top:
        return False

    sample = sampler or _window_from_point
    xs = (left, (left + right) // 2, right - 1)
    ys = (top, (top + bottom) // 2, bottom - 1)

    for y in ys:
        for x in xs:
            if sample(x, y) != hwnd:
                return True
    return False


def _window_from_point(x: int, y: int) -> int:
    return int(user32.WindowFromPoint(wintypes.POINT(int(x), int(y))) or 0)
