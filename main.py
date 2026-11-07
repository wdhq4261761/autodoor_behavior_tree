import sys
import os
import traceback
import threading

def write_log(msg):
    """写入启动日志（与运行日志共用同一套逻辑，统一保存到项目 logs/ 目录）"""
    try:
        from bt_utils.log_manager import LogManager
        LogManager.write_startup_log(msg)
    except Exception:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "startup_error.log"), 'a', encoding='utf-8') as f:
                timestamp = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"[{timestamp}] {msg}\n")
        except Exception:
            pass

write_log("=== Application startup begin ===")
write_log(f"Python version: {sys.version}")
write_log(f"Working directory: {os.getcwd()}")
write_log(f"sys.executable: {sys.executable}")
write_log(f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'Not set')}")

def setup_error_logging():
    def exception_hook(exctype, value, tb):
        error_msg = ''.join(traceback.format_exception(exctype, value, tb))
        write_log(f"EXCEPTION: {error_msg}")
        try:
            from bt_utils.log_manager import LogManager
            print(f"STARTUP ERROR - Log file: {LogManager.get_log_file_path()}")
        except Exception:
            pass
        print(error_msg)
        sys.__excepthook__(exctype, value, tb)
    
    sys.excepthook = exception_hook

    def thread_exception_hook(args):
        # 线程级未捕获异常：覆盖引擎/子树等所有工作线程。
        # 否则打包后 stderr 被丢弃，线程崩溃将完全无日志输出。
        try:
            tb_lines = "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback))
            thread_name = getattr(args.thread, "name", "?")
            write_log(f"THREAD EXCEPTION ({thread_name}): {tb_lines}")
            from bt_utils.log_manager import LogManager
            LogManager.debug_print(
                f"[THREAD-CRASH] thread='{thread_name}': {tb_lines}"
            )
        except Exception:
            pass
        # 保留 Python 默认线程异常处理（含未设 hook 时的默认输出）
        threading._excepthook(args)

    threading.excepthook = thread_exception_hook

    # faulthandler：进程级 segfault / 卡死时可 dump 全线程调用栈到 logs/
    # all_threads=True 确保能抓出引擎线程 / 子树线程卡死现场
    try:
        import faulthandler
        from bt_utils.log_manager import LogManager
        log_dir = LogManager._get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        fd = os.open(
            os.path.join(log_dir, "faulthandler.log"),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND
        )
        faulthandler.enable(fd, all_threads=True)
    except Exception:
        pass

    try:
        from bt_utils.log_manager import LogManager
        return LogManager.get_log_file_path()
    except Exception:
        return ""

LOG_FILE_RESULT = setup_error_logging()
try:
    from bt_utils.log_manager import LogManager
    print(f"Error logging initialized. Log file: {LogManager.get_log_file_path()}")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

write_log("Importing dpi_awareness...")
try:
    from bt_utils.dpi_awareness import initialize_dpi_awareness
    initialize_dpi_awareness()
    write_log("dpi_awareness initialized successfully")
except Exception as e:
    write_log(f"DPI awareness initialization failed: {e}")
    traceback.print_exc()

write_log("Importing json and logging...")
import json
import logging
write_log("json and logging imported successfully")

def get_resource_path(relative_path):
    """获取资源文件的绝对路径，支持PyInstaller打包后的路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

def load_version():
    """从build_info.json加载版本信息"""
    build_info_file = get_resource_path('bt_utils/build_info.json')
    
    if os.path.exists(build_info_file):
        try:
            with open(build_info_file, 'r', encoding='utf-8') as f:
                build_info = json.load(f)
                return build_info.get('version', '1.0.0')
        except Exception:
            pass
    
    return "1.2.2a"

def load_github_info():
    """从build_info.json加载GitHub仓库信息"""
    build_info_file = get_resource_path('bt_utils/build_info.json')
    
    if os.path.exists(build_info_file):
        try:
            with open(build_info_file, 'r', encoding='utf-8') as f:
                build_info = json.load(f)
                github = build_info.get('github', {})
                return github.get('owner', 'wdhq4261761'), github.get('repo', 'autodoor_behavior_tree')
        except Exception:
            pass
    
    return 'wdhq4261761', 'autodoor_behavior_tree'

VERSION = load_version()
write_log(f"Version loaded: {VERSION}")

write_log("Importing version_checker...")
from bt_utils.version_checker import BetaExpirationChecker
write_log("version_checker imported successfully")

beta_checker = BetaExpirationChecker()
if beta_checker.check_expiration():
    write_log("Beta expiration detected, showing dialog")
    beta_checker.show_expiration_dialog()
    sys.exit(0)

write_log("Importing customtkinter...")
import customtkinter as ctk
write_log("customtkinter imported successfully")

write_log("Importing BehaviorTreeApp...")
from bt_gui.app import BehaviorTreeApp
write_log("BehaviorTreeApp imported successfully")

write_log("Importing registry...")
from bt_core.registry import register_all_nodes
write_log("registry imported successfully")


def ensure_workspace_exists():
    """确保workspace文件夹存在"""
    from config.settings_manager import SettingsManager
    
    settings_manager = SettingsManager()
    saved_path = settings_manager.get("default_project_path", "")
    
    if saved_path and os.path.exists(saved_path):
        return
    
    workspace_dir = SettingsManager.get_default_workspace_path()
    
    try:
        os.makedirs(workspace_dir, exist_ok=True)
    except Exception:
        pass


def check_vcredist():
    """检查 Visual C++ Redistributable 运行时库"""
    try:
        import onnxruntime
        return True
    except ImportError as e:
        if "DLL load failed" in str(e) or "onnxruntime_pybind11_state" in str(e):
            return False
        raise
    except Exception:
        return False


def initialize_ocr():
    """初始化OCR引擎"""
    try:
        if not check_vcredist():
            import tkinter as tk
            from tkinter import messagebox
            
            root = tk.Tk()
            root.withdraw()
            
            messagebox.showwarning(
                "缺少运行时库",
                "程序检测到缺少 Visual C++ Redistributable 运行时库。\n\n"
                "OCR 相关功能将无法使用。\n\n"
                "请下载并安装：\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                "安装后重启程序即可使用 OCR 功能。\n\n"
                "其他功能不受影响，可正常使用。"
            )
            
            root.destroy()
            
            from bt_utils.ocr_manager import OCRManager
            OCRManager.set_unavailable("缺少 Visual C++ Redistributable 运行时库")
            
            return False
        
        from bt_utils.ocr_manager import OCRManager
        OCRManager.initialize()
        return True
        
    except Exception as e:
        from bt_utils.ocr_manager import OCRManager
        OCRManager.set_unavailable(str(e))
        
        return False


def initialize_input():
    """初始化输入控制器"""
    try:
        from bt_utils.input_controller_factory import InputController
        InputController()
        return True
    except Exception:
        return False


def check_admin_for_driver(method: str, display_name: str, is_available_fn):
    """检查驱动模式是否需要管理员权限，如需要则提权重启

    Args:
        method: 输入方式 key（如 "dd", "ib"）
        display_name: 显示名称（如 "DD虚拟键盘", "IbInputSimulator"）
        is_available_fn: 检测 DLL 是否存在的函数
    """
    from config.settings_manager import SettingsManager
    from bt_utils.app_restarter import is_admin, restart_as_admin

    settings = SettingsManager.get_instance()
    kb_method = settings.get("input.keyboard_method", "pyautogui")
    ms_method = settings.get("input.mouse_method", "pyautogui")

    # 键盘或鼠标任一使用该驱动都需要管理员权限
    if kb_method != method and ms_method != method:
        return True

    if not is_available_fn():
        write_log(f"{display_name} DLL not found, falling back to PyAutoGUI")
        if kb_method == method:
            settings.set("input.keyboard_method", "pyautogui")
        if ms_method == method:
            settings.set("input.mouse_method", "pyautogui")
        return True

    if is_admin():
        write_log(f"{display_name}: already running as admin")
        return True

    write_log(f"{display_name}: not admin, requesting elevation")

    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()

    result = messagebox.askyesno(
        "需要管理员权限",
        f"{display_name}需要管理员权限才能正常工作。\n\n"
        "是否以管理员身份重新启动应用？\n\n"
        "点击「否」将使用 PyAutoGUI 模式启动。",
        icon='warning'
    )
    root.destroy()

    if result:
        success = restart_as_admin()
        if success:
            write_log("Admin restart initiated, exiting current process")
            sys.exit(0)
        else:
            write_log("Admin restart failed (UAC denied or error)")
            root2 = tk.Tk()
            root2.withdraw()
            messagebox.showwarning(
                "权限获取失败",
                "无法获取管理员权限，将使用 PyAutoGUI 模式启动。"
            )
            root2.destroy()

    write_log("Falling back to PyAutoGUI mode")
    if kb_method == method:
        settings.set("input.keyboard_method", "pyautogui")
    if ms_method == method:
        settings.set("input.mouse_method", "pyautogui")
    return True


def parse_args():
    """解析命令行参数"""
    import argparse
    parser = argparse.ArgumentParser(description="AutoDoor 行为树编辑器")
    parser.add_argument("--headless", type=str, default=None,
                        help="无 GUI 模式运行指定行为树文件")
    parser.add_argument("--project", type=str, default=None,
                        help="项目根目录（headless 模式）")
    return parser.parse_args()


def run_headless(tree_file, project_root=None):
    """Headless 模式入口"""
    from bt_core.headless import HeadlessRunner
    from bt_core.registry import register_all_nodes
    register_all_nodes()
    runner = HeadlessRunner()
    return runner.run(tree_file, project_root)


def main():
    # CLI 模式检测
    # 命令名从 cli.COMMAND_NAMES 取，避免与 cli.py 的子命令定义漂移。
    # 打包成 exe 后这是 CLI 的唯一入口，漏一个命令就会退回 GUI 启动。
    if len(sys.argv) > 1:
        _cli_commands = None
        try:
            from cli import COMMAND_NAMES as _cli_commands
        except Exception as _e:
            write_log(f"CLI command table unavailable: {_e}")
        if _cli_commands is None:
            # 兜底：与 cli.py 的 COMMAND_NAMES 保持一致
            _cli_commands = ("run", "status", "stop", "schedule", "daemon",
                             "remote", "plugin", "config", "ai", "assets")
        if sys.argv[1] in _cli_commands:
            from cli import main as cli_main
            cli_main()
            return

    args = parse_args()

    if args.headless:
        run_headless(args.headless, args.project)
        return

    ensure_workspace_exists()

    from bt_utils.app_restarter import is_dd_available, is_ib_available
    check_admin_for_driver("dd", "DD虚拟键盘", is_dd_available)
    check_admin_for_driver("ib", "IbInputSimulator", is_ib_available)
    
    initialize_ocr()
    initialize_input()
    
    from bt_utils.log_manager import LogManager
    LogManager.enable_file_log(True)
    
    register_all_nodes()
    
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    app = BehaviorTreeApp()
    
    from bt_utils.version_checker import VersionChecker
    github_owner, github_repo = load_github_info()
    version_checker = VersionChecker(
        app=app,
        owner=github_owner,
        repo=github_repo,
        current_version=VERSION
    )
    
    app._version_checker = version_checker
    
    version_checker.check_force_update()
    
    version_checker.start_auto_check(app)
    
    app.mainloop()


if __name__ == "__main__":
    main()
