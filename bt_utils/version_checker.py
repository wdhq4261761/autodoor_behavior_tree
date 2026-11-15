import requests
import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from datetime import datetime
from typing import Optional, Dict, Any
from bt_utils.json_io import load_json
from bt_utils.log_manager import LogManager


def get_resource_path(relative_path):
    """获取资源文件的绝对路径，支持PyInstaller打包后的路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)


def load_build_info():
    """加载构建信息"""
    build_info_file = get_resource_path('bt_utils/build_info.json')
    
    if os.path.exists(build_info_file):
        try:
            return load_json(build_info_file)
        except Exception:
            pass
    
    return {
        "version": "1.0.0",
        "expire_date": "2099-12-31",
        "force_update": False,
        "build_type": "release",
        "update_links": {
            "tool_intro": "https://my.feishu.cn/wiki/Z2AAwPevRiavmwkFf3jcL0Emnye?from=from_copylink",
            "download": "https://my.feishu.cn/wiki/Z2AAwPevRiavmwkFf3jcL0Emnye?from=from_copylink",
            "changelog": "https://my.feishu.cn/wiki/Z2AAwPevRiavmwkFf3jcL0Emnye?from=from_copylink",
            "video_tutorial": "https://www.bilibili.com/video/BV1LodDBkEzS"
        }
    }


_build_info = load_build_info()

_default_update_links = {
    "tool_intro": "https://my.feishu.cn/wiki/Z2AAwPevRiavmwkFf3jcL0Emnye?from=from_copylink",
    "download": "https://my.feishu.cn/wiki/Z2AAwPevRiavmwkFf3jcL0Emnye?from=from_copylink",
    "changelog": "https://my.feishu.cn/wiki/Z2AAwPevRiavmwkFf3jcL0Emnye?from=from_copylink",
    "video_tutorial": "https://www.bilibili.com/video/BV1LodDBkEzS"
}

UPDATE_LINKS = {**_default_update_links, **_build_info.get('update_links', {})}


def open_tool_intro():
    """打开工具介绍页面"""
    try:
        webbrowser.open(UPDATE_LINKS["tool_intro"])
    except Exception as e:
        LogManager.debug_print(f"打开工具介绍页面失败: {str(e)}")


def open_download_page():
    """打开下载页面"""
    try:
        webbrowser.open(UPDATE_LINKS["download"])
    except Exception as e:
        LogManager.debug_print(f"打开下载页面失败: {str(e)}")


def open_video_tutorial():
    """打开视频教程页面"""
    try:
        webbrowser.open(UPDATE_LINKS["video_tutorial"])
    except Exception as e:
        LogManager.debug_print(f"打开视频教程页面失败: {str(e)}")


class BetaExpirationChecker:
    """Beta 版本过期检查器"""
    
    def __init__(self, app=None):
        self.app = app
        
        self.EXPIRE_DATE = _build_info.get('expire_date', '2099-12-31')
    
    def check_expiration(self) -> bool:
        """检查是否过期
        
        Returns:
            True: 已过期
            False: 未过期
        """
        try:
            expire_date = datetime.strptime(self.EXPIRE_DATE, "%Y-%m-%d")
            current_date = datetime.now()
            
            return current_date > expire_date
        except Exception as e:
            LogManager.debug_print(f"过期检查失败: {str(e)}")
            return False
    
    def show_expiration_dialog(self):
        """显示过期弹窗并退出"""
        import sys
        
        root = tk.Tk()
        root.withdraw()
        
        dialog = tk.Toplevel(root)
        dialog.title("测试版本已过期")
        dialog.geometry("400x200")
        dialog.transient(root)
        dialog.grab_set()
        
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 400) // 2
        y = (dialog.winfo_screenheight() - 200) // 2
        dialog.geometry(f"400x200+{x}+{y}")
        
        frame = ttk.Frame(dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="⚠️ 测试版本已过期",
                  font=('Arial', 14, 'bold')).pack(pady=(0, 15))
        
        ttk.Label(frame, text=f"此测试版本已于 {self.EXPIRE_DATE} 过期").pack()
        ttk.Label(frame, text="感谢您的测试！请下载最新版本继续使用。",
                  wraplength=350).pack(pady=(10, 15))
        
        def on_confirm():
            dialog.destroy()
            root.destroy()
            sys.exit(0)
        
        ttk.Button(frame, text="确定", command=on_confirm).pack(pady=10)
        
        root.mainloop()


class VersionChecker:
    """版本检查器"""
    
    GITHUB_API_URL = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
    
    def __init__(self, app, owner: str, repo: str, current_version: str = None):
        self.app = app
        self.owner = owner
        self.repo = repo
        if current_version:
            self.current_version = current_version
        elif hasattr(app, 'version'):
            self.current_version = app.version
        else:
            self.current_version = _build_info.get('version', '1.0.0')
        self.ignored_version = self._load_ignored_version()
        self._force_update_cache = self._load_force_update_cache()
    
    def _get_root_window(self):
        """获取根窗口
        
        BehaviorTreeApp继承自CTk，本身就是根窗口
        兼容旧代码中检查self.app.root的情况
        """
        if self.app is None:
            return None
        if hasattr(self.app, 'root') and self.app.root:
            return self.app.root
        return self.app
    
    def _get_config_file_path(self) -> str:
        """获取配置文件路径"""
        try:
            from config.settings_manager import SettingsManager
            settings = SettingsManager.get_instance()
            return settings.config_file
        except Exception:
            config_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 
                                     "autodoor_behavior_tree")
            os.makedirs(config_dir, exist_ok=True)
            return os.path.join(config_dir, "config.json")
    
    def _load_ignored_version(self) -> Optional[str]:
        """从配置中加载已忽略的版本"""
        try:
            config_file = self._get_config_file_path()
            if os.path.exists(config_file):
                config = load_json(config_file)
                return config.get('update', {}).get('ignored_version')
        except Exception as e:
            LogManager.debug_print(f"加载已忽略版本失败: {str(e)}")
        return None
    
    def _load_force_update_cache(self) -> Dict[str, Any]:
        """加载强制更新缓存"""
        try:
            config_file = self._get_config_file_path()
            if os.path.exists(config_file):
                config = load_json(config_file)
                return config.get('update', {}).get('force_update_cache', {})
        except Exception as e:
            LogManager.debug_print(f"加载强制更新缓存失败: {str(e)}")
        return {}
    
    def _save_force_update_cache(self, version: str):
        """保存强制更新缓存到配置文件"""
        try:
            config_file = self._get_config_file_path()
            
            if os.path.exists(config_file):
                try:
                    config = load_json(config_file)
                except ValueError:
                    config = {}
            else:
                config = {}
            
            if 'update' not in config:
                config['update'] = {}
            
            config['update']['force_update_cache'] = {
                'version': version,
                'timestamp': datetime.now().isoformat(),
                'force_update': True
            }
            
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            pass
    
    def _is_force_update_cached(self) -> bool:
        """检查是否已有强制更新缓存"""
        if not self._force_update_cache:
            return False
        
        cached_version = self._force_update_cache.get('version')
        force_update = self._force_update_cache.get('force_update', False)
        
        return force_update and cached_version is not None
    
    def check_force_update(self) -> bool:
        """检查是否需要强制更新（异步，不阻塞）
        
        Returns:
            True: 需要强制更新
            False: 无需强制更新
        """
        if self._is_force_update_cached():
            cached_version = self._force_update_cache.get('version', 'Unknown')
            self._show_force_update_dialog(cached_version, UPDATE_LINKS["download"])
            return True
        
        def check_async():
            try:
                url = self.GITHUB_API_URL.format(owner=self.owner, repo=self.repo)
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                
                data = response.json()
                latest_version = data.get('tag_name', '')
                release_body = data.get('body', '')
                
                if self._parse_force_update_flag(release_body):
                    if self._is_newer_version(latest_version):
                        self._save_force_update_cache(latest_version)
                        
                        download_url = self._get_download_url(data)
                        
                        root = self._get_root_window()
                        if root:
                            root.after(0, lambda: self._show_force_update_dialog(
                                latest_version, download_url))
                        else:
                            self._show_force_update_dialog(latest_version, download_url)
                        return
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    pass
                else:
                    pass
            except requests.exceptions.Timeout:
                pass
            except requests.exceptions.RequestException as e:
                pass
            except Exception as e:
                pass
        
        thread = threading.Thread(target=check_async, daemon=True)
        thread.start()
        
        return False
    
    def _parse_force_update_flag(self, release_body: str) -> bool:
        """解析 Release body 中的强制更新标记"""
        return '[FORCE_UPDATE]' in release_body.upper()
    
    def _get_download_url(self, data: Dict[str, Any]) -> str:
        """获取下载链接

        Release 资产名可能是 autodoor-behaviortree-x.y.z.zip（CI 打包）
        或含 windows 的独立文件，两者都接受。
        """
        for asset in data.get('assets', []):
            asset_name = asset.get('name', '').lower()
            if 'windows' in asset_name or asset_name.endswith(('.zip', '.7z', '.exe')):
                return asset.get('browser_download_url', UPDATE_LINKS["download"])
        
        return UPDATE_LINKS["download"]
    
    def _show_force_update_dialog(self, latest_version: str, download_url: str):
        """显示强制更新弹窗（模态，无法关闭）"""
        import sys
        
        root = self._get_root_window()
        if not root:
            LogManager.debug_print("无法显示强制更新弹窗：root 窗口未初始化")
            return
        
        dialog = tk.Toplevel(root)
        dialog.title("需要强制更新")
        dialog.geometry("450x320")
        dialog.transient(root)
        dialog.grab_set()
        
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 450) // 2
        y = (dialog.winfo_screenheight() - 320) // 2
        dialog.geometry(f"450x320+{x}+{y}")
        
        frame = ttk.Frame(dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="⚠️ 需要强制更新",
                  font=('Arial', 14, 'bold')).pack(pady=(0, 15))
        
        ttk.Label(frame, text=f"当前版本: {self.current_version}").pack()
        ttk.Label(frame, text=f"最新版本: {latest_version}").pack(pady=(0, 15))
        
        ttk.Label(frame, text="此版本已不再维护，请更新到最新版本以继续使用。",
                  wraplength=400).pack(pady=(0, 10))
        
        ttk.Label(frame, text="点击下方按钮前往更新页面。",
                  wraplength=400).pack(pady=(0, 15))
        
        def open_download():
            try:
                webbrowser.open(download_url)
            except Exception as e:
                LogManager.debug_print(f"打开下载页面失败: {str(e)}")
            finally:
                dialog.destroy()
                root = self._get_root_window()
                if root:
                    root.quit()
                sys.exit(0)
        
        ttk.Button(frame, text="去更新", command=open_download).pack(pady=10)
        
        dialog.mainloop()
    
    def check_for_updates(self, manual: bool = False):
        """检查版本更新（异步，不阻塞）"""
        def check_async():
            try:
                url = self.GITHUB_API_URL.format(owner=self.owner, repo=self.repo)
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                
                data = response.json()
                latest_version = data.get('tag_name', '')
                
                if self._is_newer_version(latest_version):
                    if not manual and self.ignored_version:
                        ignored_comparison = self._compare_versions(self.ignored_version, latest_version)
                        if ignored_comparison <= 0:
                            return
                    
                    download_url = self._get_download_url(data)
                    
                    root = self._get_root_window()
                    if root:
                        root.after(0, lambda: self._show_update_notification(
                            data, latest_version, download_url))
                else:
                    if manual:
                        root = self._get_root_window()
                        if root:
                            root.after(0, self.show_no_update_notification)
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    if manual:
                        root = self._get_root_window()
                        if root:
                            root.after(0, lambda: messagebox.showinfo(
                                "检查更新", "暂无版本信息。\n\n可能原因：\n1. 仓库尚未发布Release\n2. 仓库地址配置错误\n\n请稍后再试或联系开发者。"))
                else:
                    if manual:
                        root = self._get_root_window()
                        if root:
                            root.after(0, lambda: messagebox.showinfo(
                                "检查更新", f"网络请求失败: {str(e)}"))
            except requests.exceptions.Timeout:
                if manual:
                    root = self._get_root_window()
                    if root:
                        root.after(0, lambda: messagebox.showinfo(
                            "检查更新", "网络连接超时，请稍后再试。"))
            except requests.exceptions.RequestException as e:
                if manual:
                    root = self._get_root_window()
                    if root:
                        root.after(0, lambda: messagebox.showinfo(
                            "检查更新", "网络连接失败，请检查网络设置。"))
            except Exception:
                pass
        
        thread = threading.Thread(target=check_async, daemon=True)
        thread.start()
    
    def _is_newer_version(self, latest: str) -> bool:
        """检查是否为新版本"""
        return self._compare_versions(self.current_version, latest) == 1
    
    def _compare_versions(self, current: str, latest: str) -> int:
        """比较两个版本号
        
        支持格式：
        - 纯数字：1.1.8
        - 带后缀：1.1.1a, 1.2.0beta
        
        Returns:
            1: 当前版本旧，需要更新
            0: 当前版本是最新
            -1: 当前版本新（开发版本）
        """
        try:
            def normalize_version(v):
                v = v.lstrip('vV')
                v = v.replace('Release', '').replace('release', '').strip()
                v = v.split('-')[0].split('+')[0]
                parts = v.split('.')
                normalized = []
                suffix = ''
                
                for i, part in enumerate(parts):
                    if part.isdigit():
                        normalized.append(int(part))
                    else:
                        match = ''.join(filter(str.isdigit, part))
                        if match:
                            normalized.append(int(match))
                        else:
                            normalized.append(0)
                        
                        if i == len(parts) - 1:
                            suffix = ''.join(filter(str.isalpha, part))
                
                return normalized, suffix
            
            current_parts, current_suffix = normalize_version(current)
            latest_parts, latest_suffix = normalize_version(latest)
            
            for i in range(max(len(current_parts), len(latest_parts))):
                current_val = current_parts[i] if i < len(current_parts) else 0
                latest_val = latest_parts[i] if i < len(latest_parts) else 0
                
                if current_val < latest_val:
                    return 1
                elif current_val > latest_val:
                    return -1
            
            if current_suffix and latest_suffix:
                if current_suffix < latest_suffix:
                    return 1
                elif current_suffix > latest_suffix:
                    return -1
            elif current_suffix and not latest_suffix:
                return 1
            elif not current_suffix and latest_suffix:
                return -1
            
            return 0
        except Exception:
            return 0
    
    def _show_update_notification(self, data: Dict[str, Any], latest_version: str, download_url: str):
        """显示更新通知"""
        root = self._get_root_window()
        if not root:
            return
        
        release_date = data.get('published_at', '')
        changelog = data.get('body', '')
        
        if release_date:
            try:
                release_date_obj = datetime.fromisoformat(release_date.replace('Z', '+00:00'))
                release_date_str = release_date_obj.strftime('%Y-%m-%d')
            except Exception:
                release_date_str = release_date
        else:
            release_date_str = '未知'
        
        changelog_summary = changelog[:500] + '...' if len(changelog) > 500 else changelog
        
        notification_window = tk.Toplevel(root)
        notification_window.title("发现新版本")
        window_width = 450
        window_height = 400
        notification_window.geometry(f"{window_width}x{window_height}")
        notification_window.minsize(window_width, window_height)
        notification_window.transient(root)
        notification_window.grab_set()
        
        root.update_idletasks()
        root.update()
        
        root_x = root.winfo_rootx()
        root_y = root.winfo_rooty()
        root_width = root.winfo_width()
        root_height = root.winfo_height()
        
        if root_width < 100 or root_height < 100:
            root_width = 1280
            root_height = 800
            root_x = (notification_window.winfo_screenwidth() - root_width) // 2
            root_y = (notification_window.winfo_screenheight() - root_height) // 2
        
        pos_x = root_x + (root_width // 2) - (window_width // 2)
        pos_y = root_y + (root_height // 2) - (window_height // 2)
        
        notification_window.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")
        
        frame = ttk.Frame(notification_window, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=f"发现新版本: v{latest_version}", 
                  font=('Arial', 12, 'bold')).pack(pady=(0, 10))
        ttk.Label(frame, text=f"发布日期: {release_date_str}").pack(pady=(0, 10))
        ttk.Label(frame, text="更新内容:", font=('Arial', 10, 'bold')).pack(anchor='w')
        
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        changelog_text = tk.Text(text_frame, height=8, wrap=tk.WORD, state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(text_frame, command=changelog_text.yview)
        changelog_text.config(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        changelog_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        changelog_text.config(state=tk.NORMAL)
        changelog_text.insert(tk.END, changelog_summary)
        changelog_text.config(state=tk.DISABLED)
        
        button_frame = ttk.Frame(frame)
        button_frame.pack(pady=(10, 0), expand=True)
        
        ttk.Button(button_frame, text="查看更新", 
                   command=lambda: self._open_update_link(download_url, notification_window)).pack(
                       side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="稍后提醒", 
                   command=notification_window.destroy).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="忽略此版本", 
                   command=lambda: self.ignore_version(latest_version, notification_window)).pack(
                       side=tk.LEFT, padx=5)
    
    def _open_update_link(self, url: str, window: tk.Toplevel):
        """打开更新链接"""
        try:
            webbrowser.open(url)
        except Exception as e:
            LogManager.debug_print(f"打开更新链接失败: {str(e)}")
        finally:
            window.destroy()
    
    def ignore_version(self, version: str, notification_window: tk.Toplevel):
        """忽略指定版本"""
        try:
            self.ignored_version = version
            
            config_file = self._get_config_file_path()
            
            if os.path.exists(config_file):
                try:
                    config = load_json(config_file)
                except ValueError:
                    config = {}
            else:
                config = {}
            
            if 'update' not in config:
                config['update'] = {}
            config['update']['ignored_version'] = version
            
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            LogManager.debug_print(f"已忽略版本: {version}")
        except Exception as e:
            LogManager.debug_print(f"忽略版本失败: {str(e)}")
        finally:
            notification_window.destroy()
    
    def show_no_update_notification(self):
        """显示无更新通知"""
        root = self._get_root_window()
        if not root:
            return
        
        notification_window = tk.Toplevel(root)
        notification_window.title("检查更新")
        notification_window.geometry("300x150")
        notification_window.transient(root)
        notification_window.grab_set()
        
        root.update_idletasks()
        root.update()
        
        root_x = root.winfo_rootx()
        root_y = root.winfo_rooty()
        root_width = root.winfo_width()
        root_height = root.winfo_height()
        
        if root_width < 100 or root_height < 100:
            root_width = 1280
            root_height = 800
            root_x = (notification_window.winfo_screenwidth() - root_width) // 2
            root_y = (notification_window.winfo_screenheight() - root_height) // 2
        
        dialog_width = 300
        dialog_height = 150
        pos_x = root_x + (root_width // 2) - (dialog_width // 2)
        pos_y = root_y + (root_height // 2) - (dialog_height // 2)
        
        notification_window.geometry(f"{dialog_width}x{dialog_height}+{pos_x}+{pos_y}")
        
        frame = ttk.Frame(notification_window, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="检查更新", font=('Arial', 12, 'bold')).pack(pady=(0, 10))
        ttk.Label(frame, text="当前已是最新版本！", wraplength=260).pack(pady=(0, 15))
        
        ttk.Button(frame, text="确定", command=notification_window.destroy).pack()
    
    def start_auto_check(self, app):
        """启动自动版本检查（异步，延迟2秒）"""
        def check_delayed():
            time.sleep(2)
            self.check_for_updates(manual=False)
        
        thread = threading.Thread(target=check_delayed, daemon=True)
        thread.start()
