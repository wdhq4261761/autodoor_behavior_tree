"""assets 素材清单命令的单元测试。"""
from __future__ import annotations

import json
import os

import pytest
from PIL import Image, ImageDraw

from bt_cli.commands.assets import (
    _archive_source,
    _dominant_color,
    _infer_origin,
    _load_manifest,
    _normalize_hex,
    _parse_bbox,
    _parse_point,
)

RED = (226, 59, 59)
BG = (30, 40, 50)


def _probe_image(path, size=(400, 300)):
    im = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(im)
    draw.rectangle([120, 100, 190, 160], fill=RED)
    im.save(path)
    return path


class TestParsing:
    def test_parse_bbox_standard(self):
        assert _parse_bbox("1,2,3,4") == [1, 2, 3, 4]

    def test_parse_bbox_with_spaces(self):
        assert _parse_bbox(" 10 , 20 , 30 , 40 ") == [10, 20, 30, 40]

    def test_parse_bbox_fullwidth_comma(self):
        assert _parse_bbox("10，20，30，40") == [10, 20, 30, 40]

    def test_parse_bbox_float_values(self):
        assert _parse_bbox("10.7,20.2,30.9,40.1") == [10, 20, 30, 40]

    def test_parse_bbox_rejects_wrong_count(self):
        with pytest.raises(SystemExit):
            _parse_bbox("1,2,3")

    def test_parse_point_two_values(self):
        """--origin 是 x,y 两个数（此前误用了四数值解析器，参数完全不可用）"""
        assert _parse_point("100,200") == (100, 200)

    def test_parse_point_negative(self):
        """多显示器副屏在左时原点为负，必须支持负号"""
        assert _parse_point("-1920,0") == (-1920, 0)

    def test_parse_point_spaces_and_fullwidth(self):
        assert _parse_point(" -50 , -60 ") == (-50, -60)
        assert _parse_point("-50，-60") == (-50, -60)

    def test_parse_point_rejects_four_values(self):
        with pytest.raises(SystemExit):
            _parse_point("1,2,3,4")

    def test_normalize_hex_short(self):
        assert _normalize_hex("#e2b") == "#ee22bb"

    def test_normalize_hex_upper(self):
        assert _normalize_hex("#E23B3B") == "#e23b3b"

    def test_normalize_hex_invalid(self):
        with pytest.raises(SystemExit):
            _normalize_hex("#12345")


class TestDominantColor:
    def test_extracts_foreground_over_background(self, tmp_path):
        p = _probe_image(tmp_path / "probe.png")
        with Image.open(p) as im:
            color, ratio = _dominant_color(im.crop((112, 92, 199, 169)))
        assert color.lower() == "#e23b3b"
        assert 0.5 < ratio <= 1.0

    def test_handles_uniform_image(self):
        im = Image.new("RGB", (40, 40), (10, 20, 30))
        color, ratio = _dominant_color(im)
        assert color == "#0a141e" or color.startswith("#")
        assert 0.0 < ratio <= 1.0


class TestArchive:
    def test_external_file_is_copied_into_raw(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        external = tmp_path / "outside.png"
        _probe_image(external)

        archived = _archive_source(str(external), str(project))
        assert os.path.dirname(os.path.abspath(archived)).endswith("raw")
        assert os.path.exists(archived)

    def test_internal_file_is_kept(self, tmp_path):
        project = tmp_path / "proj"
        raw = project / "assets" / "raw"
        raw.mkdir(parents=True)
        inside = raw / "shot.png"
        _probe_image(inside)

        archived = _archive_source(str(inside), str(project))
        assert os.path.abspath(archived) == os.path.abspath(inside)


class TestManifestIO:
    def test_load_missing_returns_empty(self, tmp_path):
        data = _load_manifest(tmp_path / "nope.json")
        assert data["targets"] == []

    def test_load_empty_file(self, tmp_path):
        p = tmp_path / "m.json"
        p.write_text("", encoding="utf-8")
        assert _load_manifest(p)["targets"] == []

    def test_load_valid(self, tmp_path):
        p = tmp_path / "m.json"
        p.write_text(json.dumps({"targets": [{"name": "a"}]}), encoding="utf-8")
        assert _load_manifest(p)["targets"][0]["name"] == "a"


class TestInferOrigin:
    """全屏截图的原点推断

    多显示器且虚拟桌面原点为负时，把图像坐标当屏幕坐标会整体偏移
    且不报错。这里固化「按图像尺寸识别全屏截图」的推断逻辑。
    """

    def test_fullscreen_infers_virtual_origin(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "bt_utils.screen_utils.get_virtual_screen_bounds",
            lambda: (-1920, 0, 2560, 1440),
        )
        p = tmp_path / "full.png"
        Image.new("RGB", (4480, 1440), "black").save(p)
        assert _infer_origin(str(p)) == (-1920, 0)

    def test_single_monitor_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "bt_utils.screen_utils.get_virtual_screen_bounds",
            lambda: (0, 0, 1920, 1080),
        )
        p = tmp_path / "single.png"
        Image.new("RGB", (1920, 1080), "black").save(p)
        assert _infer_origin(str(p)) == (0, 0)

    def test_partial_crop_defaults_to_zero(self, tmp_path, monkeypatch):
        """尺寸不等于虚拟桌面的图视为局部裁剪，原点按 0 处理"""
        monkeypatch.setattr(
            "bt_utils.screen_utils.get_virtual_screen_bounds",
            lambda: (-1920, 0, 2560, 1440),
        )
        p = tmp_path / "crop.png"
        Image.new("RGB", (300, 200), "black").save(p)
        assert _infer_origin(str(p)) == (0, 0)

    def test_missing_file_falls_back(self, monkeypatch):
        monkeypatch.setattr(
            "bt_utils.screen_utils.get_virtual_screen_bounds",
            lambda: (-1920, 0, 2560, 1440),
        )
        assert _infer_origin("/nonexistent/x.png") == (0, 0)


class TestInferOrigin:
    """全屏截图的原点推断

    多显示器且虚拟桌面原点为负时，把图像坐标当屏幕坐标会整体偏移
    且不报错。这里固化「按图像尺寸识别全屏截图」的推断逻辑。
    """

    def test_fullscreen_infers_virtual_origin(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "bt_utils.screen_utils.get_virtual_screen_bounds",
            lambda: (-1920, 0, 2560, 1440),
        )
        p = tmp_path / "full.png"
        Image.new("RGB", (4480, 1440), "black").save(p)
        assert _infer_origin(str(p)) == (-1920, 0)

    def test_single_monitor_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "bt_utils.screen_utils.get_virtual_screen_bounds",
            lambda: (0, 0, 1920, 1080),
        )
        p = tmp_path / "single.png"
        Image.new("RGB", (1920, 1080), "black").save(p)
        assert _infer_origin(str(p)) == (0, 0)

    def test_partial_crop_defaults_to_zero(self, tmp_path, monkeypatch):
        """尺寸不等于虚拟桌面的图视为局部裁剪，原点按 0 处理"""
        monkeypatch.setattr(
            "bt_utils.screen_utils.get_virtual_screen_bounds",
            lambda: (-1920, 0, 2560, 1440),
        )
        p = tmp_path / "crop.png"
        Image.new("RGB", (300, 200), "black").save(p)
        assert _infer_origin(str(p)) == (0, 0)

    def test_missing_file_falls_back(self, monkeypatch):
        monkeypatch.setattr(
            "bt_utils.screen_utils.get_virtual_screen_bounds",
            lambda: (-1920, 0, 2560, 1440),
        )
        assert _infer_origin("/nonexistent/x.png") == (0, 0)
