"""status 命令 — 查询运行状态"""
import os

from bt_utils.json_io import load_json


def cmd_status(args):
    """查询运行状态"""
    # 检查是否有运行中的守护进程
    data_dir = os.path.join(os.path.expanduser("~"), ".autodoor_bt")
    status_file = os.path.join(data_dir, "daemon_status.json")

    if os.path.isfile(status_file):
        status = load_json(status_file)
        print(f"守护进程状态:")
        print(f"  PID: {status.get('pid', 'N/A')}")
        print(f"  启动时间: {status.get('start_time', 'N/A')}")
        trees = status.get("trees", {})
        if trees:
            print(f"  运行中的行为树: {len(trees)}")
            for tree_id, info in trees.items():
                print(f"    - {tree_id}: {info.get('status', 'unknown')}")
        else:
            print(f"  无运行中的行为树")
    else:
        print("未检测到运行中的守护进程")
        print("使用 'autodoor-bt run <tree_file> --headless' 运行行为树")
