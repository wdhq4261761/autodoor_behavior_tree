"""模板缩略图：纯函数，便于单测，不依赖 Tk。"""
import os

from PIL import Image

DEFAULT_MAX_SIZE = (232, 140)


def resolve_resource_path(path: str, project_root: str = None) -> str:
    if not path:
        return ""
    if path.startswith("./") and project_root:
        return os.path.normpath(os.path.join(project_root, path[2:]))
    if os.path.isabs(path):
        return path
    if project_root:
        return os.path.normpath(os.path.join(project_root, path))
    return os.path.abspath(path)


def load_thumbnail(path: str, max_size=DEFAULT_MAX_SIZE):
    if not path or not os.path.isfile(path):
        return None, None
    try:
        with Image.open(path) as img:
            img.load()
            img = img.convert("RGBA")
            width, height = img.size
            max_w, max_h = max_size
            ratio = min(max_w / width, max_h / height, 1.0)
            size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
            return img.resize(size, Image.LANCZOS), size
    except Exception:
        return None, None
