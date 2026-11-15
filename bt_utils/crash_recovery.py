import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from bt_utils.json_io import load_json


class CrashRecoveryHandler:
    """崩溃恢复处理器
    
    功能：
    - 捕获未处理异常
    - 保存崩溃现场数据
    - 启动时检测崩溃恢复文件
    """
    
    CRASH_FILE_PREFIX = "crash_"
    CRASH_FILE_SUFFIX = ".json"
    
    def __init__(
        self,
        get_data_func: Callable[[], Dict[str, Any]] = None,
        recovery_dir: str = "data/recovery",
        log_func: Optional[Callable[[str], None]] = None
    ):
        self._get_data_func = get_data_func
        self._recovery_dir = Path(recovery_dir)
        self._log_func = log_func
        self._original_excepthook = None
        self._is_installed = False
        
    def install(self) -> None:
        if self._is_installed:
            return
        
        self._recovery_dir.mkdir(parents=True, exist_ok=True)
        self._original_excepthook = sys.excepthook
        sys.excepthook = self._handle_exception
        self._is_installed = True
        
    def uninstall(self) -> None:
        if not self._is_installed:
            return
        
        if self._original_excepthook:
            sys.excepthook = self._original_excepthook
            self._original_excepthook = None
        
        self._is_installed = False
        
    def _handle_exception(
        self,
        exc_type: type,
        exc_value: BaseException,
        exc_tb: Any
    ) -> None:
        try:
            self._save_crash_recovery(exc_type, exc_value, exc_tb)
            self._log_crash(exc_type, exc_value, exc_tb)
        except Exception:
            pass
        
        if self._original_excepthook:
            self._original_excepthook(exc_type, exc_value, exc_tb)
        else:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            
    def _save_crash_recovery(
        self,
        exc_type: type,
        exc_value: BaseException,
        exc_tb: Any
    ) -> Optional[Path]:
        try:
            data = self._get_data_func()
            
            if not data:
                return None
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.CRASH_FILE_PREFIX}{timestamp}{self.CRASH_FILE_SUFFIX}"
            filepath = self._recovery_dir / filename
            
            if "metadata" not in data:
                data["metadata"] = {}
            
            data["metadata"]["save_type"] = "crash"
            data["metadata"]["crash_time"] = datetime.now().isoformat()
            data["metadata"]["crash_type"] = exc_type.__name__ if exc_type else "Unknown"
            data["metadata"]["crash_message"] = str(exc_value) if exc_value else ""
            
            if exc_tb:
                tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
                data["metadata"]["crash_traceback"] = "".join(tb_lines)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return filepath
            
        except Exception:
            return None
            
    def _log_crash(
        self,
        exc_type: type,
        exc_value: BaseException,
        exc_tb: Any
    ) -> None:
        if not self._log_func:
            return
        
        try:
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            tb_str = "".join(tb_lines)
            
            self._log_func(f"[崩溃恢复] 检测到异常: {exc_type.__name__}: {exc_value}")
            self._log_func(f"[崩溃恢复] 堆栈跟踪:\n{tb_str}")
        except Exception:
            pass
            
    def find_crash_files(self) -> List[Dict[str, Any]]:
        if not self._recovery_dir.exists():
            return []
        
        crash_files = []
        
        for filepath in self._recovery_dir.glob(f"{self.CRASH_FILE_PREFIX}*{self.CRASH_FILE_SUFFIX}"):
            try:
                stat = filepath.stat()
                crash_files.append({
                    "path": str(filepath),
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                    "name": filepath.name
                })
            except Exception:
                continue
        
        return sorted(crash_files, key=lambda x: x["mtime"], reverse=True)
        
    def load_crash_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        try:
            return load_json(filepath)
        except Exception:
            return None
            
    def delete_crash_file(self, filepath: str) -> bool:
        try:
            Path(filepath).unlink()
            return True
        except Exception:
            return False
            
    def cleanup_old_crash_files(self, keep_days: int = 7) -> int:
        if not self._recovery_dir.exists():
            return 0
        
        deleted_count = 0
        cutoff_time = datetime.now().timestamp() - (keep_days * 24 * 60 * 60)
        
        for filepath in self._recovery_dir.glob(f"{self.CRASH_FILE_PREFIX}*{self.CRASH_FILE_SUFFIX}"):
            try:
                if filepath.stat().st_mtime < cutoff_time:
                    filepath.unlink()
                    deleted_count += 1
            except Exception:
                continue
        
        return deleted_count
        
    def has_crash_recovery(self) -> bool:
        crash_files = self.find_crash_files()
        return len(crash_files) > 0
        
    def get_latest_crash_info(self) -> Optional[Dict[str, Any]]:
        crash_files = self.find_crash_files()
        
        if not crash_files:
            return None
        
        latest = crash_files[0]
        data = self.load_crash_file(latest["path"])
        
        if data:
            return {
                **latest,
                "crash_time": data.get("metadata", {}).get("crash_time", ""),
                "crash_type": data.get("metadata", {}).get("crash_type", ""),
                "crash_message": data.get("metadata", {}).get("crash_message", "")
            }
        
        return latest
