"""定时调度器 — 支持 cron 表达式和间隔执行"""
import os
import json
import time
import threading
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from bt_utils.json_io import load_json


class ScheduleTask:
    """定时任务"""

    def __init__(self, task_id: str, name: str, tree_file: str,
                 cron: str = None, interval: str = None, once: str = None,
                 headless: bool = True, enabled: bool = True):
        self.task_id = task_id
        self.name = name
        self.tree_file = tree_file
        self.cron = cron          # "分 时 日 月 周"
        self.interval = interval   # "30s", "5m", "1h"
        self.once = once           # "2024-12-25 09:00:00"
        self.headless = headless
        self.enabled = enabled
        self.last_run = None
        self.next_run = None
        self.run_count = 0
        self.last_run_status = None  # "success" / "failed(code)" / "timeout" / "error(msg)"

    def to_dict(self):
        return {
            "task_id": self.task_id, "name": self.name,
            "tree_file": self.tree_file, "cron": self.cron,
            "interval": self.interval, "once": self.once,
            "headless": self.headless, "enabled": self.enabled,
            "last_run": self.last_run, "next_run": self.next_run,
            "run_count": self.run_count,
            "last_run_status": self.last_run_status,
        }

    @classmethod
    def from_dict(cls, data):
        task = cls(
            task_id=data["task_id"], name=data["name"],
            tree_file=data["tree_file"], cron=data.get("cron"),
            interval=data.get("interval"), once=data.get("once"),
            headless=data.get("headless", True),
            enabled=data.get("enabled", True),
        )
        task.last_run = data.get("last_run")
        task.next_run = data.get("next_run")
        task.run_count = data.get("run_count", 0)
        task.last_run_status = data.get("last_run_status")
        return task


class CronMatcher:
    """简单 cron 表达式匹配器"""

    @staticmethod
    def match(cron_expr: str, dt: datetime) -> bool:
        """检查给定时间是否匹配 cron 表达式"""
        parts = cron_expr.split()
        if len(parts) != 5:
            return False

        def match_field(expr: str, value: int, min_val: int, max_val: int) -> bool:
            if expr == "*":
                return True
            # 处理逗号分隔
            for part in expr.split(","):
                # 处理范围 "1-5"
                if "-" in part:
                    lo, hi = part.split("-")
                    if int(lo) <= value <= int(hi):
                        return True
                # 处理步进 "*/2"
                elif part.startswith("*/"):
                    step = int(part[2:])
                    if value % step == 0:
                        return True
                # 精确匹配
                else:
                    if int(part) == value:
                        return True
            return False

        return (match_field(parts[0], dt.minute, 0, 59) and
                match_field(parts[1], dt.hour, 0, 23) and
                match_field(parts[2], dt.day, 1, 31) and
                match_field(parts[3], dt.month, 1, 12) and
                match_field(parts[4], (dt.weekday() + 1) % 7, 0, 6))


def parse_interval(interval: str) -> Optional[float]:
    """解析间隔字符串为秒数"""
    if not interval:
        return None
    m = re.match(r'^(\d+)([smh])$', interval.lower())
    if not m:
        return None
    num = int(m.group(1))
    unit = m.group(2)
    if unit == 's':
        return float(num)
    elif unit == 'm':
        return float(num * 60)
    elif unit == 'h':
        return float(num * 3600)
    return None


class Scheduler:
    """定时调度器"""

    DATA_DIR = os.path.join(os.path.expanduser("~"), ".autodoor_bt")
    SCHEDULES_FILE = os.path.join(DATA_DIR, "schedules.json")

    def __init__(self):
        self._tasks: Dict[str, ScheduleTask] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._load()

    def _load(self):
        """从文件加载定时任务"""
        if os.path.isfile(self.SCHEDULES_FILE):
            try:
                data = load_json(self.SCHEDULES_FILE)
                for task_data in data.get("tasks", []):
                    task = ScheduleTask.from_dict(task_data)
                    self._tasks[task.task_id] = task
            except Exception:
                pass

    def _save(self):
        """保存定时任务到文件"""
        os.makedirs(self.DATA_DIR, exist_ok=True)
        data = {"tasks": [t.to_dict() for t in self._tasks.values()]}
        with open(self.SCHEDULES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_task(self, name: str, tree_file: str, cron=None, interval=None,
                 once=None, headless=True) -> str:
        """添加定时任务"""
        import uuid
        if not os.path.isfile(tree_file):
            print(f"[Scheduler] 行为树文件不存在: {tree_file}")
            return ""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = ScheduleTask(
            task_id=task_id, name=name or tree_file, tree_file=tree_file,
            cron=cron, interval=interval, once=once, headless=headless
        )
        self._tasks[task_id] = task
        self._save()
        return task_id

    def remove_task(self, task_id: str) -> bool:
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._save()
            return True
        return False

    def list_tasks(self) -> List[ScheduleTask]:
        return list(self._tasks.values())

    def enable_task(self, task_id: str) -> bool:
        if task_id in self._tasks:
            self._tasks[task_id].enabled = True
            self._save()
            return True
        return False

    def disable_task(self, task_id: str) -> bool:
        if task_id in self._tasks:
            self._tasks[task_id].enabled = False
            self._save()
            return True
        return False

    def run_task_now(self, task_id: str) -> bool:
        """立即执行一次"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        self._execute_task(task)
        return True

    def _execute_task(self, task: ScheduleTask):
        """执行任务"""
        import subprocess
        print(f"[Scheduler] 执行任务: {task.name} ({task.tree_file})")
        task.last_run = datetime.now().isoformat()
        task.run_count += 1

        try:
            cmd = ["python", "cli.py", "run", task.tree_file]
            if task.headless:
                cmd.append("--headless")
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=300,
            )
            task.last_run_status = "success" if result.returncode == 0 else f"failed({result.returncode})"
        except subprocess.TimeoutExpired:
            task.last_run_status = "timeout"
        except Exception as e:
            task.last_run_status = f"error({e})"

        self._save()

    def start(self):
        """启动调度器线程"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("[Scheduler] 调度器已启动")

    def stop(self):
        """停止调度器"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[Scheduler] 调度器已停止")

    def _run_loop(self):
        """调度器主循环"""
        while not self._stop_event.is_set():
            now = datetime.now()
            for task in list(self._tasks.values()):
                if not task.enabled:
                    continue
                if self._should_run(task, now):
                    self._execute_task(task)
            # 每 30 秒检查一次
            self._stop_event.wait(30)

    def _should_run(self, task: ScheduleTask, now: datetime) -> bool:
        """检查任务是否应该运行"""
        # cron 模式
        if task.cron:
            if CronMatcher.match(task.cron, now):
                # 避免同一分钟重复执行
                if task.last_run:
                    last = datetime.fromisoformat(task.last_run)
                    if (now - last).total_seconds() < 60:
                        return False
                return True
        # interval 模式
        if task.interval:
            seconds = parse_interval(task.interval)
            if seconds and task.last_run:
                last = datetime.fromisoformat(task.last_run)
                if (now - last).total_seconds() >= seconds:
                    return True
            elif seconds and not task.last_run:
                return True
        # once 模式
        if task.once:
            try:
                target = datetime.fromisoformat(task.once)
                if now >= target and not task.last_run:
                    return True
            except ValueError:
                pass
        return False
