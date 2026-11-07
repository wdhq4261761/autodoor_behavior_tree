"""E2E：制作期素材流水线 -> 运行期节点检测

用一个固定位置、已知 bbox 的结构化控件做 ground truth（避免依赖真实窗口的不确定性），
走完整链路：
  Tk 渲染结构化目标 -> 截屏 -> assets add（裁剪 + 主色 + 坐标 + manifest）
  -> assets verify -> ImageConditionNode 检测 -> 断言中心点与真值一致

运行：venv/Scripts/python.exe tests/e2e_assets_pipeline.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".ai" / "_e2e"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

# ---- 1. 用 Tk 在固定位置画一个结构化目标（边缘清晰，适合模板匹配）----
import tkinter as tk
from PIL import ImageGrab, Image

WIN_X, WIN_Y, WIN_W, WIN_H = 300, 240, 520, 360
CANVAS_OFF = (8, 32)
TGT = (120, 90, 220, 170)  # Canvas 内坐标 -> 100x80

root = tk.Tk()
root.title("AutoDoor E2E Target")
root.geometry(f"{WIN_W}x{WIN_H}+{WIN_X}+{WIN_Y}")
root.configure(bg="#2b2f36")
root.attributes("-topmost", True)

c = tk.Canvas(root, width=WIN_W - 16, height=WIN_H - 40, bg="#2b2f36",
              highlightthickness=0)
c.place(x=CANVAS_OFF[0], y=CANVAS_OFF[1])

# 同色系干扰块（验证不会误命中）
c.create_rectangle(20, 20, 100, 80, fill="#3d4550", outline="#6b7684", width=2)
c.create_rectangle(20, 200, 90, 280, fill="#3d4550", outline="#6b7684", width=2)

# 目标：红底 + 白色斜十字 + 黄点 + 黑描边（边缘能量高、形状唯一）
tx1, ty1, tx2, ty2 = TGT
c.create_rectangle(tx1, ty1, tx2, ty2, fill="#d93b3b", outline="#111111", width=3)
c.create_line(tx1 + 6, ty1 + 6, tx2 - 6, ty2 - 6, fill="#ffffff", width=6)
c.create_line(tx2 - 6, ty1 + 6, tx1 + 6, ty2 - 6, fill="#ffffff", width=6)
c.create_oval(tx1 + 38, ty1 + 28, tx1 + 62, ty1 + 52, fill="#f5d76e", outline="#111111", width=2)

root.update_idletasks()
root.update()
time.sleep(0.8)

shot = ImageGrab.grab(all_screens=True)
screen_path = OUT / "screen.png"
shot.save(screen_path)
print(f"[1] 截屏 {shot.size} -> {screen_path}")

abs_bbox = [
    WIN_X + CANVAS_OFF[0] + tx1,
    WIN_Y + CANVAS_OFF[1] + ty1,
    WIN_X + CANVAS_OFF[0] + tx2,
    WIN_Y + CANVAS_OFF[1] + ty2,
]
expected_cx = (abs_bbox[0] + abs_bbox[2]) / 2
expected_cy = (abs_bbox[1] + abs_bbox[3]) / 2

# 全屏截图以虚拟桌面左上角为原点，需换算成图像内坐标
from bt_utils.screen_utils import get_virtual_screen_bounds
min_x, min_y, _, _ = get_virtual_screen_bounds()
img_bbox = [abs_bbox[0] - min_x, abs_bbox[1] - min_y,
            abs_bbox[2] - min_x, abs_bbox[3] - min_y]
print(f"[2] ground truth 屏幕bbox={abs_bbox} 图像bbox={img_bbox} "
      f"虚拟桌面原点=({min_x},{min_y})")
print(f"    期望屏幕中心=({expected_cx:.0f},{expected_cy:.0f})")

env = dict(os.environ, PYTHONIOENCODING="utf-8")


def run(args):
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())
    return r.returncode, out


py = str(ROOT / "venv" / "Scripts" / "python.exe")

# ---- 2. 制作期：assets add ----
print("\n[3] assets add")
code, out = run([py, "cli.py", "assets", "add",
                 "--name", "e2e_target",
                 "--source", str(screen_path.relative_to(ROOT)),
                 "--bbox", ",".join(str(v) for v in img_bbox),
                 "--semantic", "深红底白色斜十字的按钮图标",
                 "--project", ".ai/_e2e"])

root.destroy()

if code != 0:
    print("!! assets add 失败")
    sys.exit(1)

manifest_path = OUT / "assets" / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
print(f"[4] manifest keys={list(manifest.keys())}")

entry = next((t for t in manifest.get("targets", []) if t.get("name") == "e2e_target"), {})
print(f"    template={entry.get('template')}  dominant={entry.get('dominant_color')}"
      f"  ratio={entry.get('color_ratio')}  屏幕中心={entry.get('center_screen')}")

# ---- 3. 制作期：assets verify ----
print("\n[5] assets verify")
code_v, out_v = run([py, "cli.py", "assets", "verify", "--project", ".ai/_e2e"])

# ---- 4. 运行期：ImageConditionNode 检测（只消费本地文件，不联网）----
print("\n[6] ImageConditionNode 检测")
from bt_nodes.conditions.image import ImageConditionNode
from bt_core.config import NodeConfig
from bt_core.blackboard import Blackboard

tpl_rel = entry.get("template")
# 故意不配 region：走整屏检测路径，验证虚拟桌面坐标补偿
cfg = NodeConfig.from_dict({
    "template_path": str(OUT / tpl_rel) if tpl_rel else "",
    "threshold": 75,
    "save_position": True,
})
node = ImageConditionNode(node_id="e2e", config=cfg)

bb = Blackboard()
screen_img = Image.open(screen_path).convert("RGB")


class FakeContext:
    """最小执行上下文：只提供截图与黑板"""
    def __init__(self, img, board):
        self._img = img
        self.blackboard = board

    def get_screenshot(self, region=None):
        if region:
            return self._img.crop(tuple(region))
        return self._img

    def get_bound_window(self):
        return None


ctx = FakeContext(screen_img, bb)

t0 = time.time()
found = node._check_condition(ctx)
dt = (time.time() - t0) * 1000

pos = (bb.get("last_detection_x"), bb.get("last_detection_y"))
dx = abs(pos[0] - expected_cx) if pos[0] is not None else None
dy = abs(pos[1] - expected_cy) if pos[1] is not None else None

print(f"[7] found={found} pos={pos} 耗时={dt:.0f}ms")
print(f"[8] 真值 center=({expected_cx:.0f},{expected_cy:.0f}) 误差 dx={dx} dy={dy}px")

ok = bool(found) and dx is not None and dx <= 2 and dy <= 2
print("\n=== E2E 结果:", "PASS" if ok else "FAIL", "===")

report = {
    "ground_truth_bbox": abs_bbox,
    "ground_truth_center": [expected_cx, expected_cy],
    "found": bool(found),
    "detected_pos": list(pos),
    "error_px": [dx, dy],
    "elapsed_ms": round(dt, 1),
    "assets_add_rc": code,
    "assets_verify_rc": code_v,
    "template": tpl_rel,
    "template_size": entry.get("template_size"),
    "dominant_color": entry.get("dominant_color"),
    "color_ratio": entry.get("color_ratio"),
    "center_screen": entry.get("center_screen"),
    "pass": ok,
}
(OUT / "e2e_result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
sys.exit(0 if ok else 1)
