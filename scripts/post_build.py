"""发布包后处理 — 本地构建与 CI 共用

职责：
1. 在产物目录下创建 plugins/（即使没有任何插件，也保证目录存在）
2. 只复制白名单插件：example / uia_bridge / vlm_vision
   （math_expressions、yolo_vision 属于本地试验插件，不随包发布）
3. 生成 launcher-notes.txt
4. 用 autodoor-cli.exe 做插件自检

用法：
    python scripts/post_build.py <输出目录>
"""
import io
import json
import os
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# CI 的 Windows runner 默认 stdout 编码是 cp1252，直接 print 中文会抛
# UnicodeEncodeError 并中断打包后处理。统一改为 UTF-8，日志也可读。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# (源目录, 产物内目录名)
PLUGIN_WHITELIST = [
    (os.path.join("bt_plugins", "builtin", "example"), "example"),
    (os.path.join("plugins", "uia_bridge"), "uia_bridge"),
    (os.path.join("plugins", "vlm_vision"), "vlm_vision"),
]

_IGNORE_NAMES = {"__pycache__", "tests", ".pytest_cache"}
_IGNORE_SUFFIXES = (".pyc", ".pyo")

PLUGINS_README = """AutoDoor 插件目录
=================

把插件文件夹放在本目录下即可，程序启动时会自动扫描每个含 plugin.json 的子目录。
插件管理页（顶部「插件管理」标签）可以加载、启动、停止插件。

- 每个插件目录必须包含 plugin.json，字段 name/display_name/version/author/description 为必填。
- 插件节点在树文件中写作 {插件名}.{节点类型}，例如 vlm_vision.VLMLocateNode。
- 可用环境变量 AUTODOOR_PLUGINS_DIR 指定其他插件目录。

随包示例：example、uia_bridge、vlm_vision
"""


def _copy_plugin(src: str, dst: str) -> bool:
    """复制单个插件目录，跳过缓存与测试文件"""
    if not os.path.isdir(src):
        print("[WARN] 插件源目录不存在，跳过: %s" % src)
        return False

    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in _IGNORE_NAMES]
        rel = os.path.relpath(root, src)
        target_dir = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            if name.endswith(_IGNORE_SUFFIXES):
                continue
            shutil.copy2(os.path.join(root, name), os.path.join(target_dir, name))
    return True


def _read_version() -> str:
    try:
        with open(os.path.join(PROJECT_ROOT, "build_config.json"), "r", encoding="utf-8") as f:
            return str(json.load(f).get("version", "0.0.0"))
    except (OSError, ValueError):
        return "0.0.0"


def _write_launcher_notes(out_dir: str, version: str) -> None:
    try:
        import generate_launcher_notes
        generate_launcher_notes.main(["generate_launcher_notes.py", version, out_dir])
    except Exception as e:
        print("[WARN] 生成启动说明失败: %s" % e)


def _self_check(out_dir: str) -> bool:
    """用 CLI 版 exe 验证插件能被扫描到（GUI exe 无 stdout，不能用）"""
    cli_exe = os.path.join(out_dir, "autodoor-cli.exe")
    if not os.path.isfile(cli_exe):
        print("[WARN] 未找到 autodoor-cli.exe，跳过插件自检")
        return True

    try:
        result = subprocess.run(
            [cli_exe, "plugin", "nodes"],
            cwd=out_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except Exception as e:
        print("[WARN] 插件自检执行失败: %s" % e)
        return False

    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        print("[WARN] autodoor-cli.exe plugin nodes 返回 %s" % result.returncode)
        print(output[:2000])
        return False

    missing = [name for _, name in PLUGIN_WHITELIST if name not in output]
    if missing:
        print("[WARN] 插件自检缺少: %s" % ", ".join(missing))
        return False

    print("      插件自检通过: %s" % ", ".join(name for _, name in PLUGIN_WHITELIST))
    return True


def main(argv) -> int:
    if len(argv) < 2:
        print("usage: python scripts/post_build.py <output_dir>")
        return 2

    out_dir = os.path.abspath(argv[1])
    if not os.path.isdir(out_dir):
        print("Error: 输出目录不存在: %s" % out_dir)
        return 1

    version = _read_version()
    plugins_dir = os.path.join(out_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)

    print("Post-processing: %s" % out_dir)
    print("[1/3] 复制插件到 %s ..." % plugins_dir)
    copied = []
    for src_rel, name in PLUGIN_WHITELIST:
        if _copy_plugin(os.path.join(PROJECT_ROOT, src_rel), os.path.join(plugins_dir, name)):
            copied.append(name)
    print("      已复制: %s" % (", ".join(copied) if copied else "无"))

    readme_path = os.path.join(plugins_dir, "README.txt")
    if not os.path.isfile(readme_path):
        with io.open(readme_path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(PLUGINS_README)

    print("[2/3] 生成启动说明 ...")
    _write_launcher_notes(out_dir, version)

    print("[3/3] 插件自检 ...")
    if not _self_check(out_dir):
        print("WARNING: 插件自检失败，请检查产物")
        return 1

    print("Post-processing done: %s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
