import json

import pytest

from bt_utils.json_io import JsonFormatError, load_json, save_json


def test_load_json_with_bom(tmp_path):
    p = tmp_path / "bom.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"name": "行为树"}, ensure_ascii=False).encode("utf-8"))
    assert load_json(p) == {"name": "行为树"}


def test_load_json_without_bom(tmp_path):
    p = tmp_path / "plain.json"
    p.write_text('{"ok": true}', encoding="utf-8")
    assert load_json(p) == {"ok": True}


def test_load_json_missing_returns_default(tmp_path):
    assert load_json(tmp_path / "none.json", default={"x": 1}) == {"x": 1}


def test_load_json_missing_without_default_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_json(tmp_path / "none.json")


def test_load_json_invalid_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        load_json(p)


def test_load_json_invalid_raises_json_format_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(JsonFormatError):
        load_json(p)
    assert issubclass(JsonFormatError, ValueError)


def test_load_json_empty_raises_value_error(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        load_json(p)


def test_save_json_roundtrip(tmp_path):
    p = tmp_path / "out.json"
    save_json(p, {"k": "中文"})
    assert load_json(p)["k"] == "中文"


def test_save_json_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "out.json"
    save_json(p, {"k": "中文"})
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8"))["k"] == "中文"


def test_save_json_writes_without_bom(tmp_path):
    p = tmp_path / "out.json"
    save_json(p, {"k": "中文"})
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")


def test_package_import_reads_bom_project_json(tmp_path):
    import zipfile

    from bt_utils.package_importer import PackageImporter

    zip_path = tmp_path / "pkg.zip"
    payload = b"\xef\xbb\xbf" + json.dumps(
        {"project_info": {"name": "带BOM项目"}}, ensure_ascii=False
    ).encode("utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("src/project.json", payload)
    assert PackageImporter().get_project_name(str(zip_path)) == "带BOM项目"
