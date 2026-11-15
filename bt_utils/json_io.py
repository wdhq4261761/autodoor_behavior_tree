"""统一 JSON 读写：读取兼容 UTF-8 BOM（utf-8-sig），写入固定 UTF-8。"""
import json
import os
from typing import Any, Optional


class JsonFormatError(ValueError):
    """JSON 文件格式错误（便于调用方精确捕获）。"""


def load_json(path, default: Optional[Any] = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise
    except json.JSONDecodeError as e:
        raise JsonFormatError(f"JSON 格式错误: {path}: {e}") from e


def save_json(path, data: Any, indent: int = 2) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
