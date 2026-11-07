"""assets 命令 — 制作期视觉素材的落盘与校验

设计目标（对应 v3 方案的「制作时接入、运行时依赖本地留存图片」）：

1. 制作期由 VLM / UIA 产出 ``bbox`` 与语义描述；
2. 本命令把 bbox 裁剪成模板 PNG、提取主色、换算客户区相对坐标，
   统一写入 ``assets/manifest.json``；
3. 运行期 ``ImageConditionNode`` / ``ColorConditionNode`` 只消费这些
   静态文件，全程不联网、不调用任何模型。

子命令：
    add     新增/更新一条素材记录
    verify  校验 manifest 与模板文件的一致性
    list    列出已登记的素材
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Tuple

MANIFEST_VERSION = 1
DEFAULT_MANIFEST = os.path.join("assets", "manifest.json")
TEMPLATE_DIR = os.path.join("assets", "templates")
RAW_DIR = os.path.join("assets", "raw")


def cmd_assets(args):
    action = getattr(args, "assets_action", None)
    if action is None:
        print("用法: autodoor-bt assets <add|verify|list>")
        sys.exit(1)

    if action == "add":
        _add(args)
    elif action == "verify":
        sys.exit(_verify(args))
    elif action == "list":
        _list(args)


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------
def _add(args) -> None:
    from PIL import Image

    project = os.path.abspath(args.project or os.getcwd())
    manifest_path = _manifest_path(project, args.manifest)

    # 1) 取得源图
    source_path, origin = _resolve_source(args, project)

    # 2) 裁剪模板
    bbox = _parse_bbox(args.bbox)
    im = Image.open(source_path).convert("RGB")

    if getattr(args, "refine_color", None):
        from bt_utils.image_processor import ImageProcessor
        rgb = _hex_to_rgb(args.refine_color)
        refined = ImageProcessor.refine_bbox(
            im, bbox, rgb,
            expand=float(getattr(args, "refine_expand", 3.0)),
            tolerance=int(getattr(args, "refine_tolerance", 50)),
        )
        if refined:
            print(f"[INFO] 精定位: 粗框 {bbox} -> {list(refined)}")
            bbox = list(refined)
        else:
            print("[WARN] 精定位未命中，沿用原始粗框")

    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        print(f"[ERROR] bbox 非法: {bbox}（需满足 x2>x1 且 y2>y1）")
        sys.exit(1)
    if x2 > im.width or y2 > im.height:
        print(f"[ERROR] bbox {bbox} 超出源图尺寸 {im.size}")
        sys.exit(1)

    tpl = im.crop((x1, y1, x2, y2))
    name = args.name
    if not name:
        print("[ERROR] 必须指定 --name")
        sys.exit(1)

    tpl_rel = os.path.join(TEMPLATE_DIR, f"{name}.png").replace("\\", "/")
    tpl_abs = os.path.join(project, tpl_rel)
    os.makedirs(os.path.dirname(tpl_abs), exist_ok=True)
    tpl.save(tpl_abs)

    # 3) 主色提取
    if args.color:
        dominant, ratio = _normalize_hex(args.color), None
    else:
        dominant, ratio = _dominant_color(tpl)

    # 4) 坐标换算
    bbox_screen = [origin[0] + x1, origin[1] + y1, origin[0] + x2, origin[1] + y2]
    center_screen = ((bbox_screen[0] + bbox_screen[2]) // 2,
                     (bbox_screen[1] + bbox_screen[3]) // 2)

    coord_client = None
    anchor = args.anchor or "center"
    if args.hwnd:
        coord_client = _to_client(center_screen, int(args.hwnd))
    elif args.offset:
        coord_client = _to_client(center_screen, _parse_point(args.offset))

    # 5) 写 manifest
    data = _load_manifest(manifest_path)
    entry = {
        "name": name,
        "semantic": args.semantic or "",
        "template": tpl_rel,
        "kind": "template",
        "template_size": [tpl.width, tpl.height],
        "bbox_image": bbox,
        "bbox_screen": bbox_screen,
        "center_screen": center_screen,
        "coord_client": coord_client,
        "anchor": anchor,
        "dominant_color": dominant,
        "color_ratio": None if ratio is None else round(ratio, 4),
        "source_image": os.path.relpath(source_path, project).replace("\\", "/"),
        "source_origin": list(origin),
        "hwnd": args.hwnd,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

    targets = [t for t in data.get("targets", []) if t.get("name") != name]
    targets.append(entry)
    data["targets"] = targets
    data["version"] = MANIFEST_VERSION
    data.setdefault("created_at", entry["updated_at"])
    data["updated_at"] = entry["updated_at"]

    os.makedirs(os.path.dirname(manifest_path) or ".", exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] 素材已登记: {name}")
    print(f"     模板: {tpl_rel}  ({tpl.width}x{tpl.height})")
    print(f"     主色: {dominant}" + (f" (占比 {ratio:.1%})" if ratio else ""))
    print(f"     屏幕坐标: {bbox_screen}  中心 {center_screen}")
    if coord_client:
        print(f"     客户区相对坐标: {coord_client}")
    print(f"     manifest: {os.path.relpath(manifest_path, project)}")


def _resolve_source(args, project):
    """返回 (源图绝对路径, 源图左上角对应的屏幕坐标)。"""
    if args.capture:
        from PIL import ImageGrab
        region = _parse_bbox(args.capture)
        os.makedirs(os.path.join(project, RAW_DIR), exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(project, RAW_DIR, f"screen_{stamp}.png")
        img = ImageGrab.grab(bbox=tuple(region), all_screens=True)
        img.save(path)
        print(f"[INFO] 已截屏: {os.path.relpath(path, project)} {img.size} @ {region[:2]}")
        return path, (region[0], region[1])

    if not args.source:
        print("[ERROR] 需要 --source <图片> 或 --capture <x1,y1,x2,y2>")
        sys.exit(1)

    path = args.source
    if not os.path.isabs(path):
        # 先按当前工作目录解析，找不到再按项目根解析（两种调用习惯都支持）
        if os.path.exists(path):
            path = os.path.abspath(path)
        else:
            path = os.path.join(project, path)
    if not os.path.exists(path):
        print(f"[ERROR] 源图不存在: {path}")
        sys.exit(1)

    path = _archive_source(path, project)

    origin = _parse_point(args.origin) if args.origin else _infer_origin(path)
    return path, origin


def _infer_origin(path):
    """推断源图左上角对应的屏幕坐标。

    全屏截图（ImageGrab.grab(all_screens=True)）的图像原点对应的是**虚拟桌面**
    左上角，而多显示器场景下虚拟桌面原点可能为负（副屏挂在主屏左侧/上方）。
    此时若把图像坐标当屏幕坐标用，会产生整屏宽的偏移，且不会报错——
    这是最难排查的一类缺陷。这里用图像尺寸与虚拟桌面尺寸比对来自动纠正。
    """
    try:
        from PIL import Image
        from bt_utils.screen_utils import get_virtual_screen_bounds

        min_x, min_y, max_x, max_y = get_virtual_screen_bounds()
        with Image.open(path) as im:
            w, h = im.size
        if (w, h) == (max_x - min_x, max_y - min_y):
            if (min_x, min_y) != (0, 0):
                print(f"[INFO] 源图为全屏截图，自动推断原点为虚拟桌面左上角 ({min_x},{min_y})")
            return (min_x, min_y)
    except Exception:
        pass
    return (0, 0)


def _archive_source(path, project):
    """把项目外的源图复制进 assets/raw/，保证素材目录自包含。

    运行期需要「本地留存图片」可回溯，源图散落在外部路径会导致
    manifest 无法复现；统一归档后，整个 assets/ 可整体迁移。
    """
    import shutil

    src = os.path.abspath(path)
    root = os.path.abspath(project)
    try:
        if os.path.commonpath([src, root]) == root:
            return src
    except ValueError:
        pass  # 跨盘符无法比较，直接归档

    raw_dir = os.path.join(root, RAW_DIR)
    os.makedirs(raw_dir, exist_ok=True)
    dst = os.path.join(raw_dir, os.path.basename(src))
    if os.path.abspath(dst) != src:
        shutil.copy2(src, dst)
    return dst


def _to_client(screen_point, hwnd_or_offset):
    from bt_utils.coordinate import CoordinateConverter

    if isinstance(hwnd_or_offset, (tuple, list)):
        ox, oy = hwnd_or_offset[0], hwnd_or_offset[1]
        return [screen_point[0] - ox, screen_point[1] - oy]

    result = CoordinateConverter.absolute_to_client(
        screen_point[0], screen_point[1], hwnd_or_offset
    )
    return list(result) if result else None


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
def _verify(args) -> int:
    from PIL import Image

    project = os.path.abspath(args.project or os.getcwd())
    manifest_path = _manifest_path(project, args.manifest)

    if not os.path.exists(manifest_path):
        print(f"[FAIL] manifest 不存在: {manifest_path}")
        return 1

    try:
        data = _load_manifest(manifest_path)
    except json.JSONDecodeError as e:
        print(f"[FAIL] manifest JSON 解析失败: {e}")
        return 1

    targets = data.get("targets", [])
    if not targets:
        print("[FAIL] manifest 中没有任何 targets")
        return 1

    errors, warnings = [], []
    errors_by_name = {}
    seen = set()

    def _err(name, msg):
        errors.append(msg)
        errors_by_name.setdefault(name, []).append(msg)

    def _warn(msg):
        warnings.append(msg)

    for t in targets:
        name = t.get("name", "<unnamed>")
        if name in seen:
            _err(name, f"{name}: 名称重复")
        seen.add(name)

        kind = t.get("kind", "template")

        # anchor 类型（UIA 采样产物）没有模板图像，只校验坐标
        if kind == "anchor":
            if not t.get("coord_client") and not t.get("center_screen"):
                _err(name, f"{name}: anchor 缺少 coord_client / center_screen")
            if not t.get("control_type") and not t.get("semantic"):
                _warn(f"{name}: anchor 未记录控件类型与语义，无法追溯来源")
            continue

        tpl_rel = t.get("template")
        if not tpl_rel:
            _err(name, f"{name}: 缺少 template 字段")
            continue
        tpl_abs = os.path.join(project, tpl_rel)
        if not os.path.exists(tpl_abs):
            _err(name, f"{name}: 模板文件不存在 {tpl_rel}")
            continue

        try:
            with Image.open(tpl_abs) as im:
                w, h = im.size
        except Exception as e:
            _err(name, f"{name}: 模板无法打开 {e}")
            continue

        declared = t.get("template_size")
        if declared and list(declared) != [w, h]:
            _err(name, f"{name}: 模板尺寸不符 声明{declared} 实际{[w, h]}")

        bbox = t.get("bbox_screen")
        if bbox:
            if len(bbox) != 4 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                _err(name, f"{name}: bbox_screen 非法 {bbox}")
            else:
                bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                if (bw, bh) != (w, h):
                    _warn(f"{name}: bbox 尺寸 {(bw, bh)} 与模板 {(w, h)} 不一致")
        else:
            _err(name, f"{name}: 缺少 bbox_screen")

        color = t.get("dominant_color")
        if color and not _is_hex(color):
            _err(name, f"{name}: dominant_color 非法 {color}")
        elif not color:
            _warn(f"{name}: 未记录主色，无法用 ColorConditionNode")

        if not t.get("semantic"):
            _warn(f"{name}: 缺少语义描述，制作过程不可追溯")

    print(f"manifest: {os.path.relpath(manifest_path, project)}")
    print(f"条目数: {len(targets)}")
    for t in targets:
        name = t.get("name")
        mark = "ERR " if errors_by_name.get(name) else "OK  "
        print(f"  [{mark}] {name}  ->  {t.get('template')}  "
              f"{t.get('dominant_color') or '-'}  {t.get('coord_client') or '-'}")

    for w in warnings:
        print(f"  [WARN] {w}")
    for e in errors:
        print(f"  [ERR ] {e}")

    if errors:
        print(f"\n校验失败：{len(errors)} 个错误，{len(warnings)} 个警告")
        return 1
    print(f"\n校验通过（{len(warnings)} 个警告）")
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
def _list(args) -> None:
    project = os.path.abspath(args.project or os.getcwd())
    manifest_path = _manifest_path(project, args.manifest)
    if not os.path.exists(manifest_path):
        print(f"manifest 不存在: {manifest_path}")
        return

    data = _load_manifest(manifest_path)
    targets = data.get("targets", [])
    if not targets:
        print("无素材记录")
        return

    print(f"{'名称':<22}{'主色':<10}{'模板尺寸':<12}{'客户区坐标'}")
    print("-" * 70)
    for t in targets:
        size = t.get("template_size") or ["?", "?"]
        coord = t.get("coord_client") or "-"
        print(f"{t.get('name', '-'):<22}{t.get('dominant_color') or '-':<10}"
              f"{f'{size[0]}x{size[1]}':<12}{coord}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _manifest_path(project, override):
    if override:
        return override if os.path.isabs(override) else os.path.join(project, override)
    return os.path.join(project, DEFAULT_MANIFEST)


def _load_manifest(path) -> dict:
    if not os.path.exists(path):
        return {"version": MANIFEST_VERSION, "targets": []}
    with open(path, encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return {"version": MANIFEST_VERSION, "targets": []}
    data = json.loads(content)
    data.setdefault("targets", [])
    return data


def _parse_point(text):
    """解析 x,y 两个数值（用于 --origin）。支持负数与中英文逗号。"""
    if isinstance(text, (list, tuple)):
        parts = [str(v) for v in text]
    else:
        parts = [p.strip() for p in str(text).replace("，", ",").split(",") if p.strip()]
    if len(parts) != 2:
        print(f"[ERROR] 坐标需为 2 个数 x,y，实际: {text}")
        sys.exit(1)
    return int(float(parts[0])), int(float(parts[1]))


def _parse_bbox(text):
    if isinstance(text, (list, tuple)):
        return [int(v) for v in text]
    parts = [p.strip() for p in str(text).replace("，", ",").split(",") if p.strip()]
    if len(parts) != 4:
        print(f"[ERROR] 坐标需为 4 个数 x1,y1,x2,y2，实际: {text}")
        sys.exit(1)
    return [int(float(p)) for p in parts]


def _normalize_hex(text: str) -> str:
    s = text.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        print(f"[ERROR] 颜色格式非法: {text}")
        sys.exit(1)
    return "#" + s.lower()


def _is_hex(text: str) -> bool:
    s = str(text).lstrip("#")
    return len(s) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in s)


def _hex_to_rgb(text: str) -> Tuple[int, int, int]:
    s = _normalize_hex(text).lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _dominant_color(im):
    """提取主色：先剔除背景色，再对前景做量化取最高频。

    模板通常包含目标及其周围背景，直接取最高频会得到背景色，
    因此先用四角像素估计背景，再排除接近背景的像素。
    """
    import numpy as np

    arr = np.array(im.convert("RGB"))
    if arr.size == 0:
        return "#000000", 0.0

    corners = np.array([
        arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1],
    ], dtype=np.int16)
    bg = np.median(corners, axis=0)

    flat = arr.reshape(-1, 3).astype(np.int16)
    dist = np.abs(flat - bg).sum(axis=1)
    foreground = flat[dist > 60]
    base = foreground if foreground.size else flat

    # 32 级量化后取最高频桶，再用桶内真实均值还原颜色
    quant = (base // 32 * 32).astype(np.uint8)
    colors, counts = np.unique(quant, axis=0, return_counts=True)
    idx = int(counts.argmax())
    mask = np.all(quant == colors[idx], axis=1)
    real = base[mask].mean(axis=0).astype(int)

    hex_color = "#{:02x}{:02x}{:02x}".format(*real)
    ratio = float(counts[idx]) / float(len(flat))
    return hex_color, ratio
