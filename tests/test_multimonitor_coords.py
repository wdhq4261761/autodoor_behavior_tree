"""多显示器虚拟桌面坐标补偿回归测试

背景：`ImageGrab.grab(all_screens=True)` 返回的图像以**虚拟桌面左上角**为原点，
而虚拟桌面原点在多显示器场景下可能为负（副屏挂在主屏左侧/上方）。
若把图像内坐标直接当屏幕坐标用，点击位置会整体偏移 |min_x| 像素且**不会报错**。

这类缺陷只在实际多显示器环境下暴露，单屏 CI 永远测不出来，
因此这里用 monkeypatch 注入虚拟桌面边界来固化行为。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bt_core.config import NodeConfig
from bt_nodes.conditions.image import ImageConditionNode
from bt_core.blackboard import Blackboard


class Ctx:
    """最小上下文：只提供黑板与窗口绑定状态"""

    def __init__(self, bound_hwnd=None):
        self.blackboard = Blackboard()
        self._hwnd = bound_hwnd

    def get_bound_window(self):
        return self._hwnd


def _node(**cfg):
    base = {"template_path": "dummy.png"}
    base.update(cfg)
    return ImageConditionNode("t", NodeConfig.from_dict(base))


# ---------------------------------------------------------------------------
# _adjust_position：图像坐标 -> 屏幕坐标
# ---------------------------------------------------------------------------
class TestAdjustPosition:
    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(-1920, 0, 2560, 1440))
    def test_fullscreen_compensates_negative_origin(self, _):
        """整屏检测：图像 x=2348 应为屏幕 x=428"""
        n = _node()
        assert n._adjust_position((2348, 362), Ctx()) == (428, 362)

    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(-1920, 0, 2560, 1440))
    def test_fullscreen_compensates_negative_y(self, _):
        """虚拟桌面原点在 y 为负时同样补偿"""
        n = _node()
        assert n._adjust_position((100, 200), Ctx()) == (100 - 1920, 200)

    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(0, 0, 1920, 1080))
    def test_single_monitor_unchanged(self, _):
        """单屏不引入任何偏移"""
        n = _node()
        assert n._adjust_position((300, 200), Ctx()) == (300, 200)

    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(-1920, 0, 2560, 1440))
    def test_region_only_adds_region_offset(self, _):
        """配了 region：只加 region 偏移，不再叠加虚拟桌面偏移（避免双算）"""
        n = _node(region=[400, 300, 900, 800])
        assert n._adjust_position((50, 60), Ctx()) == (450, 360)

    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(-1920, 0, 2560, 1440))
    def test_bound_window_returns_relative(self, _):
        """绑定窗口时坐标为窗口内相对值，交给 execute_mouse_* 换算"""
        n = _node()
        assert n._adjust_position((120, 80), Ctx(bound_hwnd=12345)) == (120, 80)

    def test_none_position(self):
        assert _node()._adjust_position(None, Ctx()) is None

    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(-1920, 0, 2560, 1440))
    def test_no_context_uses_config_region(self, _):
        """无 context 时不崩溃，按配置 region 处理"""
        n = _node(region=[100, 100, 300, 300])
        assert n._adjust_position((10, 20), None) == (110, 120)


# ---------------------------------------------------------------------------
# _get_fallback_region：边界应钳制到虚拟桌面而非 0
# ---------------------------------------------------------------------------
class TestFallbackRegion:
    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(-1920, 0, 2560, 1440))
    def test_clamps_to_virtual_bounds_not_zero(self, _):
        """副屏上的点（x 为负）不应被钳到 0，否则区域整体丢失"""
        n = _node()
        ctx = Ctx()
        ctx.blackboard.set("last_detection_position", (-1800, 500))
        x1, y1, x2, y2 = n._get_fallback_region(ctx)
        assert x1 == -1920          # 钳到虚拟桌面左边界，而不是 0
        assert x1 < -1800
        assert (x1, y1, x2, y2) == (-1920, 350, -1650, 650)

    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(-1920, 0, 2560, 1440))
    def test_clamps_right_edge(self, _):
        n = _node()
        ctx = Ctx()
        ctx.blackboard.set("last_detection_position", (2500, 1400))
        x1, y1, x2, y2 = n._get_fallback_region(ctx)
        assert x2 == 2560 and y2 == 1440

    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(0, 0, 1920, 1080))
    def test_single_monitor_symmetric(self, _):
        n = _node()
        ctx = Ctx()
        ctx.blackboard.set("last_detection_position", (500, 400))
        r = 150
        assert n._get_fallback_region(ctx) == (500 - r, 400 - r, 500 + r, 400 + r)

    def test_no_last_position_returns_none(self):
        assert _node()._get_fallback_region(Ctx()) is None


# ---------------------------------------------------------------------------
# 端到端一致性：assets 记录的屏幕坐标 与 运行期检测坐标 应一致
# ---------------------------------------------------------------------------
class TestCoordinateRoundTrip:
    @patch("bt_utils.screen_utils.get_virtual_screen_bounds",
           return_value=(-1920, 0, 2560, 1440))
    def test_assets_and_node_agree(self, _):
        """制作期记录 center_screen，运行期从同一张全屏图检测，
        两处坐标应严格一致（这正是 E2E 暴露的错位点）。"""
        from bt_cli.commands.assets import _infer_origin
        from PIL import Image
        import tempfile

        # 全屏图 4480x1440 = 虚拟桌面尺寸 -> 原点应推断为 (-1920, 0)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            Image.new("RGB", (4480, 1440), "black").save(f.name)
            assert _infer_origin(f.name) == (-1920, 0)

        # 单屏尺寸 -> 原点 (0,0)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f2:
            Image.new("RGB", (1920, 1080), "black").save(f2.name)
            assert _infer_origin(f2.name) == (0, 0)

        # 制作期：bbox 在图像内的 (2348,362) + origin(-1920,0) -> 屏幕 (428,362)
        origin = (-1920, 0)
        img_bbox = [2348, 362, 2448, 442]
        bbox_screen = [origin[0] + img_bbox[0], origin[1] + img_bbox[1],
                       origin[0] + img_bbox[2], origin[1] + img_bbox[3]]
        assert bbox_screen == [428, 362, 528, 442]

        # 运行期：节点从全屏图检到 (2348,362) 应换算成同一屏幕坐标
        n = _node()
        assert n._adjust_position((img_bbox[0], img_bbox[1]), Ctx()) == (428, 362)
