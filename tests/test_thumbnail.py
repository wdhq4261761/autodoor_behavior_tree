import os

from PIL import Image

from bt_gui.bt_editor.thumbnail import load_thumbnail, resolve_resource_path


def test_load_thumbnail_scales_down(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (400, 200), "red").save(src)
    img, size = load_thumbnail(str(src), max_size=(232, 140))
    assert img is not None
    assert size[0] <= 232 and size[1] <= 140


def test_load_thumbnail_missing_returns_none(tmp_path):
    assert load_thumbnail(str(tmp_path / "none.png")) == (None, None)


def test_resolve_relative_resource(tmp_path):
    assert resolve_resource_path("./images/a.png", str(tmp_path)) == os.path.normpath(
        os.path.join(str(tmp_path), "images", "a.png"))


def test_load_thumbnail_does_not_upscale(tmp_path):
    src = tmp_path / "small.png"
    Image.new("RGB", (100, 50), "blue").save(src)
    img, size = load_thumbnail(str(src), max_size=(232, 140))
    assert img is not None
    assert size == (100, 50)


def test_load_thumbnail_corrupt_returns_none(tmp_path):
    src = tmp_path / "broken.png"
    src.write_bytes(b"not an image")
    assert load_thumbnail(str(src)) == (None, None)


def test_load_thumbnail_rgba(tmp_path):
    src = tmp_path / "alpha.png"
    Image.new("RGBA", (300, 300), (255, 0, 0, 128)).save(src)
    img, size = load_thumbnail(str(src), max_size=(232, 140))
    assert img is not None
    assert img.mode == "RGBA"
    assert size == (140, 140)


def test_resolve_absolute_and_empty(tmp_path):
    abs_path = str(tmp_path / "a.png")
    assert resolve_resource_path(abs_path, None) == abs_path
    assert resolve_resource_path("", str(tmp_path)) == ""

    # project_root=None 时相对路径转为绝对路径
    rel_path = os.path.join("some_dir", "b.png")
    assert resolve_resource_path(rel_path, None) == os.path.abspath(rel_path)
