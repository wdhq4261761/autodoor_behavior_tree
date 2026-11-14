"""daemon 命令 — 守护进程模式"""
import os
import sys
import json
import time
import signal
import threading
from datetime import datetime

from bt_utils.json_io import load_json


DAEMON_PID_FILE = os.path.join(os.path.expanduser("~"), ".autodoor_bt", "daemon.pid")
DAEMON_STATUS_FILE = os.path.join(os.path.expanduser("~"), ".autodoor_bt", "daemon_status.json")


def cmd_daemon(args):
    """守护进程管理"""
    if args.start:
        _start_daemon()
    elif args.stop:
        _stop_daemon()
    elif args.restart:
        _stop_daemon()
        time.sleep(1)
        _start_daemon()
    elif args.status:
        _show_status()
    elif args.foreground:
        _run_foreground()
    else:
        print("用法: autodoor-bt daemon --start|--stop|--restart|--status|--foreground")
        sys.exit(1)


def _start_daemon():
    """启动守护进程"""
    # 检查是否已在运行
    if os.path.isfile(DAEMON_PID_FILE):
        try:
            with open(DAEMON_PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print(f"守护进程已在运行 (PID: {old_pid})")
            return
        except (ProcessLookupError, ValueError):
            pass  # 进程不存在，继续启动

    # 启动守护进程
    import subprocess
    subprocess.Popen(
        [sys.executable, "cli.py", "daemon", "--foreground"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    print("守护进程已启动")


def _stop_daemon():
    """停止守护进程"""
    if not os.path.isfile(DAEMON_PID_FILE):
        print("守护进程未运行")
        return

    try:
        with open(DAEMON_PID_FILE, "r") as f:
            pid = int(f.read().strip())

        import platform
        if platform.system() == "Windows":
            import subprocess
            subprocess.call(["taskkill", "/PID", str(pid), "/F"])
        else:
            os.kill(pid, signal.SIGTERM)

        os.remove(DAEMON_PID_FILE)
        if os.path.isfile(DAEMON_STATUS_FILE):
            os.remove(DAEMON_STATUS_FILE)
        print(f"守护进程已停止 (PID: {pid})")
    except ProcessLookupError:
        print("守护进程进程不存在，清理 PID 文件")
        os.remove(DAEMON_PID_FILE)
    except Exception as e:
        print(f"停止失败: {e}")


def _show_status():
    """显示守护进程状态"""
    if not os.path.isfile(DAEMON_STATUS_FILE):
        print("守护进程未运行")
        return

    try:
        status = load_json(DAEMON_STATUS_FILE)
        print(f"守护进程状态:")
        print(f"  PID: {status.get('pid', 'N/A')}")
        print(f"  启动时间: {status.get('start_time', 'N/A')}")
        print(f"  运行任务: {status.get('task_count', 0)}")
    except Exception as e:
        print(f"读取状态失败: {e}")


def _run_foreground():
    """前台运行守护进程"""
    from bt_cli.scheduler import Scheduler

    os.makedirs(os.path.dirname(DAEMON_PID_FILE), exist_ok=True)

    # 写入 PID
    with open(DAEMON_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # 写入状态
    status = {
        "pid": os.getpid(),
        "start_time": datetime.now().isoformat(),
        "task_count": 0,
    }
    with open(DAEMON_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    print(f"守护进程启动 (PID: {os.getpid()})")

    # 启动调度器
    scheduler = Scheduler()
    scheduler.start()

    try:
        while True:
            time.sleep(60)
            # 更新状态
            tasks = scheduler.list_tasks()
            status["task_count"] = len(tasks)
            with open(DAEMON_STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status, f, ensure_ascii=False, indent=2)
    except KeyboardInterrupt:
        print("\n停止守护进程...")
        scheduler.stop()
    finally:
        # 清理
        if os.path.isfile(DAEMON_PID_FILE):
            os.remove(DAEMON_PID_FILE)
        if os.path.isfile(DAEMON_STATUS_FILE):
            os.remove(DAEMON_STATUS_FILE)
