import hashlib
import os
import socket
import time
from typing import Any, Dict, Optional

import requests

from bt_utils.log_manager import LogManager


def _load_dotenv() -> None:
    """加载项目根目录的 .env 文件到环境变量（不覆盖已存在的环境变量）。

    仅解析简单的 KEY=VALUE 行，忽略空行与 # 注释，避免引入额外依赖。
    """
    try:
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            ".env")
        if not os.path.isfile(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_dotenv()


class PlatformAPIClient:
    # 登录服务器地址：优先从环境变量 AUTODOOR_BT_SERVER_URL 读取。
    # 开源仓库不包含真实服务器地址，未配置时使用占位符（需自行配置）。
    DEFAULT_BASE_URL = os.environ.get(
        "AUTODOOR_BT_SERVER_URL", "https://your-server.example.com")
    # API 命名空间：优先从环境变量 AUTODOOR_BT_API_NAMESPACE 读取。
    API_NAMESPACE = os.environ.get(
        "AUTODOOR_BT_API_NAMESPACE", "/wp-json/bt/v1/executor")
    CONNECT_TIMEOUT = 10
    READ_TIMEOUT = 30

    def __init__(self, base_url: str = None):
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AutoDoorEditor",
        })
        self._token: Optional[str] = None
        self._token_expire_time: float = 0
        self._last_error: str = ""

    def _build_url(self, endpoint: str) -> str:
        return f"{self._base_url}{self.API_NAMESPACE}{endpoint}"

    def _get_auth_headers(self) -> Dict[str, str]:
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def login(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        try:
            device_id = hashlib.md5(f"{username}_{socket.gethostname()}".encode()).hexdigest()[:16]
            device_name = f"Editor-{socket.gethostname()}"

            url = self._build_url("/request-token")
            payload = {
                "username": username,
                "password": password,
                "device_id": device_id,
                "device_name": device_name,
            }

            print(f"[Auth] 请求登录: {url}, user={username}")
            response = self._session.post(
                url,
                json=payload,
                timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT)
            )

            if response.status_code != 200:
                try:
                    err_data = response.json()
                    msg = err_data.get("message", "")
                    if not msg:
                        code = err_data.get("code", "")
                        msg = code if code else f"登录失败({response.status_code})"
                except Exception:
                    msg = f"登录失败({response.status_code})"
                self._last_error = msg
                print(f"[Auth] 登录失败: {msg} (status={response.status_code})")
                return None

            result = response.json()
            if result.get("success", False):
                data = result.get("data", {})
                token = data.get("token", data.get("session_token", ""))
                self._token = token
                self._token_expire_time = time.time() + 3600
                self._last_error = ""
                print(f"[Auth] 登录成功: {username}, token={token[:16]}...")
                return {
                    "token": token,
                    "user_id": str(data.get("user_id", "")),
                    "display_name": data.get("display_name", username),
                    "roles": data.get("roles", []),
                    "expires_in": 3600,
                }

            self._last_error = result.get("message", "登录失败")
            print(f"[Auth] 登录失败: {self._last_error}")
            return None

        except requests.RequestException as e:
            self._last_error = f"网络请求失败: {e}"
            print(f"[Auth] 登录请求异常: {e}")
            return None

    def get_last_error(self) -> str:
        return self._last_error

    def refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        try:
            response = self._session.post(
                self._build_url("/refresh-token"),
                json={"refresh_token": refresh_token},
                timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT)
            )
            response.raise_for_status()
            result = response.json()
            if result.get("success", False):
                data = result.get("data", {})
                token = data.get("token", data.get("session_token", ""))
                self._token = token
                self._token_expire_time = time.time() + 3600
                return {"token": token, "expires_in": 3600}
            return None
        except requests.RequestException as e:
            LogManager.instance().log_failure(
                node_type="PlatformAPIClient",
                node_name="refresh_token",
                reason=f"刷新令牌失败: {e}"
            )
            return None

    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            original_token = self._token
            self._token = token
            response = self._session.post(
                self._build_url("/validate-token"),
                headers=self._get_auth_headers(),
                timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT)
            )
            response.raise_for_status()
            result = response.json()
            if result.get("success", False):
                self._token_expire_time = time.time() + 3600
                return {"valid": True, "expires_in": 3600}
            return None
        except requests.RequestException as e:
            LogManager.instance().log_failure(
                node_type="PlatformAPIClient",
                node_name="validate_token",
                reason=f"验证令牌失败: {e}"
            )
            return None
        finally:
            self._token = original_token

    def get_user_info(self) -> Optional[Dict[str, Any]]:
        try:
            if not self._token:
                return None
            response = self._session.get(
                self._build_url("/user-info"),
                headers=self._get_auth_headers(),
                timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT)
            )
            response.raise_for_status()
            result = response.json()
            if result.get("success", False):
                return result.get("data", {})
            return None
        except requests.RequestException as e:
            LogManager.instance().log_failure(
                node_type="PlatformAPIClient",
                node_name="get_user_info",
                reason=f"获取用户信息失败: {e}"
            )
            return None

    def set_token(self, token: str, expire_time: float = 0) -> None:
        self._token = token
        self._token_expire_time = expire_time

    def get_token(self) -> Optional[str]:
        return self._token

    def is_token_expired(self) -> bool:
        if not self._token:
            return True
        return time.time() >= self._token_expire_time

    def logout(self) -> None:
        try:
            if self._token:
                self._session.post(
                    self._build_url("/revoke-token"),
                    headers=self._get_auth_headers(),
                    timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT)
                )
        except requests.RequestException:
            pass
        finally:
            self._token = None
            self._token_expire_time = 0
