import json
import os
import time
from typing import Optional, Dict, Any

from bt_utils.json_io import load_json
from bt_utils.log_manager import LogManager


class CredentialStore:
    _KEYRING_SERVICE = "AutoDoorBT"

    def __init__(self):
        pass

    def _get_file_path(self) -> str:
        app_data = os.path.expanduser("~/.autodoor_bt")
        os.makedirs(app_data, exist_ok=True)
        return os.path.join(app_data, "credentials.json")

    def save_credentials(self, username: str, password: str, token: str = "",
                         refresh_token: str = "", expire_time: float = 0) -> bool:
        try:
            file_path = self._get_file_path()
            credentials = self._load_from_file()
            credentials[username] = {
                "password": password,
                "token": token,
                "refresh_token": refresh_token,
                "expire_time": expire_time,
                "saved_at": time.time()
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=2)
            return True
        except Exception as e:
            LogManager.instance().log_failure(
                node_type="CredentialStore",
                node_name="save_credentials",
                reason=f"保存凭据失败: {e}"
            )
            return False

    def get_credentials(self, username: str) -> Optional[Dict[str, Any]]:
        try:
            credentials = self._load_from_file()
            return credentials.get(username)
        except Exception as e:
            LogManager.instance().log_failure(
                node_type="CredentialStore",
                node_name="get_credentials",
                reason=f"获取凭据失败: {e}"
            )
            return None

    def _load_from_file(self) -> Dict[str, Any]:
        file_path = self._get_file_path()
        if os.path.exists(file_path):
            try:
                return load_json(file_path)
            except (ValueError, IOError):
                return {}
        return {}

    def get_all_usernames(self) -> list:
        """获取所有已存储凭据的用户名列表"""
        try:
            credentials = self._load_from_file()
            return list(credentials.keys())
        except Exception:
            return []

    def get_first_credential(self) -> Optional[tuple]:
        """获取最近保存的凭据 (username, credential_dict)"""
        try:
            credentials = self._load_from_file()
            if credentials:
                sorted_items = sorted(
                    credentials.items(),
                    key=lambda x: x[1].get("saved_at", 0),
                    reverse=True
                )
                if sorted_items:
                    username, data = sorted_items[0]
                    return username, data
            return None
        except Exception:
            return None

    def delete_credentials(self, username: str) -> bool:
        try:
            credentials = self._load_from_file()
            if username in credentials:
                del credentials[username]
                file_path = self._get_file_path()
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(credentials, f, indent=2)
            return True
        except Exception as e:
            LogManager.instance().log_failure(
                node_type="CredentialStore",
                node_name="delete_credentials",
                reason=f"删除凭据失败: {e}"
            )
            return False

    def save_token(self, username: str, token: str, refresh_token: str = "",
                   expire_time: float = 0) -> bool:
        creds = self.get_credentials(username)
        if creds:
            creds["token"] = token
            creds["refresh_token"] = refresh_token
            creds["expire_time"] = expire_time
            return self.save_credentials(
                username, creds.get("password", ""),
                token, refresh_token, expire_time
            )
        return False

    def get_token(self, username: str) -> Optional[str]:
        creds = self.get_credentials(username)
        if creds and creds.get("token"):
            expire_time = creds.get("expire_time", 0)
            if expire_time == 0 or time.time() < expire_time:
                return creds["token"]
        return None

    def is_token_expired(self, username: str) -> bool:
        creds = self.get_credentials(username)
        if not creds or not creds.get("token"):
            return True
        expire_time = creds.get("expire_time", 0)
        return expire_time > 0 and time.time() >= expire_time
