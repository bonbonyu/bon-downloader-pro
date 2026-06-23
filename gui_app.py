#!/usr/bin/env python3
"""BonDownloader Pro - macOS 桌面应用"""

import sys, os, re, asyncio, threading, subprocess, time, platform
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QTextEdit,
    QGroupBox, QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

DOWNLOAD_DIR = str(Path.home() / "Downloads" / "DouyinVideos")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

API_BASE = "http://127.0.0.1:5199"


def _find_python():
    for p in ["/usr/bin/python3","/opt/homebrew/bin/python3","/usr/local/bin/python3"]:
        if os.path.exists(p): return p
    return sys.executable


class DownloadThread(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    cancel_flag = False

    def __init__(self, url, token):
        super().__init__()
        self.url = url
        self.token = token

    def cancel(self):
        self.cancel_flag = True

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(self._do_download())
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            loop.close()

    async def _do_download(self):
        import aiohttp
        self.log.emit("🔍 解析视频...")

        # 1. Get task_id from API
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{API_BASE}/api/download",
                             json={"url": self.url},
                             headers={"Authorization": f"Bearer {self.token}"}) as r:
                if r.status != 200:
                    d = await r.json()
                    raise Exception(d.get("error", "请求失败"))
                d = await r.json()
                task_id = d["task_id"]

        # 2. Poll status until done
        async with aiohttp.ClientSession() as s:
            for _ in range(120):
                if self.cancel_flag:
                    return {"status": "cancelled"}
                await asyncio.sleep(1)
                async with s.get(f"{API_BASE}/api/status/{task_id}") as r:
                    t = await r.json()
                    if t.get("status") == "error":
                        raise Exception(t.get("error", "下载失败"))
                    if t.get("status") == "done":
                        # 后端已保存文件，直接返回路径，不再重复下载
                        return {"status": "done", "output_path": t.get("output_path", ""),
                                "filename": t.get("filename", ""), "file_size": t.get("file_size", 0)}
                    p = t.get("progress", 0)
                    self.progress.emit(p)
                    self.log.emit(f"下载中: {p}%")


class LoginWidget(QWidget):
    login_success = pyqtSignal(str, dict)
    show_register = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._ui()

    def _ui(self):
        l = QVBoxLayout()
        title = QLabel("🔐 BonDownloader Pro")
        title.setFont(QFont("Helvetica Neue", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(title)
        l.addSpacing(20)

        self.phone = QLineEdit()
        self.phone.setPlaceholderText("手机号")
        self.phone.setFont(QFont("Helvetica Neue", 14))
        self.phone.setMinimumHeight(44)
        l.addWidget(self.phone)

        self.pw = QLineEdit()
        self.pw.setPlaceholderText("密码")
        self.pw.setFont(QFont("Helvetica Neue", 14))
        self.pw.setMinimumHeight(44)
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        l.addWidget(self.pw)

        self.login_btn = QPushButton("登录")
        self.login_btn.setFont(QFont("Helvetica Neue", 14, QFont.Weight.Bold))
        self.login_btn.setMinimumHeight(48)
        self.login_btn.setStyleSheet("background:#007aff;color:#fff;border-radius:10;")
        self.login_btn.clicked.connect(self._login)
        l.addWidget(self.login_btn)

        reg_btn = QPushButton("没有账号？注册")
        reg_btn.setFont(QFont("Helvetica Neue", 12))
        reg_btn.setStyleSheet("background:transparent;color:#007aff;border:0;")
        reg_btn.clicked.connect(self.show_register.emit)
        l.addWidget(reg_btn)

        l.addStretch()
        self.setLayout(l)

    def _login(self):
        import requests
        p = self.phone.text().strip()
        pw = self.pw.text().strip()
        if not p or not pw:
            QMessageBox.warning(self, "提示", "请输入手机号和密码")
            return
        try:
            r = requests.post(f"{API_BASE}/api/login", json={"phone": p, "password": pw})
            d = r.json()
            if r.status_code != 200:
                raise Exception(d.get("error", "登录失败"))
            self.login_success.emit(d["token"], d["user"])
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))


class RegisterWidget(QWidget):
    register_success = pyqtSignal()
    show_login = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._ui()

    def _ui(self):
        l = QVBoxLayout()
        title = QLabel("📝 注册")
        title.setFont(QFont("Helvetica Neue", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(title)
        l.addSpacing(20)

        self.phone = QLineEdit()
        self.phone.setPlaceholderText("手机号")
        self.phone.setFont(QFont("Helvetica Neue", 14))
        self.phone.setMinimumHeight(44)
        l.addWidget(self.phone)

        self.pw = QLineEdit()
        self.pw.setPlaceholderText("密码（至少6位）")
        self.pw.setFont(QFont("Helvetica Neue", 14))
        self.pw.setMinimumHeight(44)
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        l.addWidget(self.pw)

        self.reg_btn = QPushButton("注册")
        self.reg_btn.setFont(QFont("Helvetica Neue", 14, QFont.Weight.Bold))
        self.reg_btn.setMinimumHeight(48)
        self.reg_btn.setStyleSheet("background:#007aff;color:#fff;border-radius:10;")
        self.reg_btn.clicked.connect(self._register)
        l.addWidget(self.reg_btn)

        login_btn = QPushButton("已有账号？登录")
        login_btn.setFont(QFont("Helvetica Neue", 12))
        login_btn.setStyleSheet("background:transparent;color:#007aff;border:0;")
        login_btn.clicked.connect(self.show_login.emit)
        l.addWidget(login_btn)

        l.addStretch()
        self.setLayout(l)

    def _register(self):
        import requests
        p = self.phone.text().strip()
        pw = self.pw.text().strip()
        if not p or not pw:
            QMessageBox.warning(self, "提示", "请输入手机号和密码")
            return
        try:
            r = requests.post(f"{API_BASE}/api/register", json={"phone": p, "password": pw})
            d = r.json()
            if r.status_code != 200:
                raise Exception(d.get("error", "注册失败"))
            QMessageBox.information(self, "成功", "注册成功，请登录")
            self.register_success.emit()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))


class DownloadWidget(QWidget):
    def __init__(self, token):
        super().__init__()
        self.token = token
        self._ui()
        self._thread = None

    def _ui(self):
        l = QVBoxLayout()
        title = QLabel("🎬 硬BonBon下载 Pro")
        title.setFont(QFont("Helvetica Neue", 20, QFont.Weight.Bold))
        l.addWidget(title)
        l.addSpacing(12)

        url_gb = QGroupBox("抖音视频链接")
        url_l = QVBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("粘贴抖音视频链接...")
        self.url.setFont(QFont("Helvetica Neue", 14))
        self.url.setMinimumHeight(44)
        url_l.addWidget(self.url)

        btn_row = QHBoxLayout()
        self.dl_btn = QPushButton("⬇️ 下载")
        self.dl_btn.setFont(QFont("Helvetica Neue", 14, QFont.Weight.Bold))
        self.dl_btn.setMinimumHeight(44)
        self.dl_btn.setStyleSheet("background:#007aff;color:#fff;border-radius:10;")
        self.dl_btn.clicked.connect(self._download)
        btn_row.addWidget(self.dl_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFont(QFont("Helvetica Neue", 14))
        self.cancel_btn.setMinimumHeight(44)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.cancel_btn)

        self.check_btn = QPushButton("🔧 自检")
        self.check_btn.setFont(QFont("Helvetica Neue", 14))
        self.check_btn.setMinimumHeight(44)
        self.check_btn.setStyleSheet("background:#34c759;color:#fff;border-radius:10;")
        self.check_btn.clicked.connect(self._self_check)
        btn_row.addWidget(self.check_btn)
        url_l.addLayout(btn_row)
        url_gb.setLayout(url_l)
        l.addWidget(url_gb)

        prog_gb = QGroupBox("下载进度")
        prog_l = QVBoxLayout()
        self.prog = QProgressBar()
        self.prog.setMinimumHeight(28)
        prog_l.addWidget(self.prog)
        self.prog_label = QLabel("等待输入链接...")
        self.prog_label.setStyleSheet("color:#8e8e93;")
        prog_l.addWidget(self.prog_label)
        prog_gb.setLayout(prog_l)
        l.addWidget(prog_gb)

        log_gb = QGroupBox("状态")
        log_l = QVBoxLayout()
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Menlo", 11))
        self.log.setStyleSheet("background:#1e1e1e;color:#e5e5ea;")
        log_l.addWidget(self.log)
        log_gb.setLayout(log_l)
        l.addWidget(log_gb)

        self.setLayout(l)

    def _download(self):
        url = self.url.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入链接")
            return
        self.dl_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.prog.setValue(0)
        self.log.clear()
        self._thread = DownloadThread(url, self.token)
        self._thread.log.connect(lambda m: self.log.append(m))
        self._thread.progress.connect(self.prog.setValue)
        self._thread.finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _cancel(self):
        if self._thread:
            self._thread.cancel()
        self._reset()

    def _on_finished(self, res):
        self._reset()
        if res.get("status") == "done":
            self.log.append("✅ 下载完成")
            QMessageBox.information(self, "成功", "视频已保存到 Downloads/DouyinVideos/")

    def _on_error(self, msg):
        self._reset()
        self.log.append(f"❌ {msg}")

    def _self_check(self):
        self.log.clear()
        self.log.append("🔍 正在自检...")
        try:
            resp = requests.get(f"{SERVER}/api/health", timeout=10)
            if resp.status_code != 200:
                self.log.append(f"❌ 后端无响应: HTTP {resp.status_code}")
                return
            data = resp.json()
            self.log.append(f"整体状态: {'✅ 正常' if data.get('status') == 'ok' else '⚠️ 部分异常'}")
            self.log.append("")
            for name, check in data.get("checks", {}).items():
                icon = "✅" if check.get("ok") else "❌"
                self.log.append(f"{icon} {name}: {check.get('path', '?')}")
            self.log.append("")
            self.log.append("💡 如果 Chromium 显示 ❌，说明浏览器组件缺失，需要重新安装。")
            self.log.append("💡 如果后端无响应，请检查防火墙是否阻止了本程序。")
        except Exception as e:
            self.log.append(f"❌ 自检失败: {e}")
            self.log.append("💡 后端服务可能未启动，请尝试重启程序。")
        QMessageBox.critical(self, "错误", msg)

    def _reset(self):
        self.dl_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.prog.setValue(0)


class AdminWidget(QWidget):
    def __init__(self, token):
        super().__init__()
        self.token = token
        self._ui()

    def _ui(self):
        l = QVBoxLayout()
        title = QLabel("🔧 管理面板")
        title.setFont(QFont("Helvetica Neue", 20, QFont.Weight.Bold))
        l.addWidget(title)
        l.addSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._logs_tab(), "📊 下载记录")
        self.tabs.addTab(self._users_tab(), "👥 用户列表")
        self.tabs.addTab(self._stats_tab(), "📈 统计")
        l.addWidget(self.tabs)
        self.setLayout(l)

    def _logs_tab(self):
        w = QWidget()
        l = QVBoxLayout()
        self.logs_table = QTableWidget()
        self.logs_table.setColumnCount(6)
        self.logs_table.setHorizontalHeaderLabels(["用户", "链接", "作者", "分辨率", "大小", "时间"])
        self.logs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._load_logs()
        l.addWidget(self.logs_table)
        w.setLayout(l)
        return w

    def _users_tab(self):
        w = QWidget()
        l = QVBoxLayout()
        self.users_table = QTableWidget()
        self.users_table.setColumnCount(4)
        self.users_table.setHorizontalHeaderLabels(["ID", "手机号", "管理员", "注册时间"])
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._load_users()
        l.addWidget(self.users_table)
        w.setLayout(l)
        return w

    def _stats_tab(self):
        w = QWidget()
        l = QVBoxLayout()
        self.stats_label = QLabel("加载中...")
        self.stats_label.setFont(QFont("Helvetica Neue", 16))
        self.stats_label.setStyleSheet("color:#1d1d1f;")
        self._load_stats()
        l.addWidget(self.stats_label)
        l.addStretch()
        w.setLayout(l)
        return w

    def _load_logs(self):
        import requests
        try:
            r = requests.get(f"{API_BASE}/api/admin/all_logs", headers={"Authorization": f"Bearer {self.token}"})
            d = r.json()
            logs = d.get("logs", [])
            self.logs_table.setRowCount(len(logs))
            for i, log in enumerate(logs):
                self.logs_table.setItem(i, 0, QTableWidgetItem(log.get("phone", "")))
                self.logs_table.setItem(i, 1, QTableWidgetItem(log.get("url", "")))
                self.logs_table.setItem(i, 2, QTableWidgetItem(log.get("author", "")))
                self.logs_table.setItem(i, 3, QTableWidgetItem(log.get("resolution", "")))
                self.logs_table.setItem(i, 4, QTableWidgetItem(str(log.get("file_size", ""))))
                self.logs_table.setItem(i, 5, QTableWidgetItem(log.get("created_at", "")))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _load_users(self):
        import requests
        try:
            r = requests.get(f"{API_BASE}/api/admin/users", headers={"Authorization": f"Bearer {self.token}"})
            d = r.json()
            users = d.get("users", [])
            self.users_table.setRowCount(len(users))
            for i, u in enumerate(users):
                self.users_table.setItem(i, 0, QTableWidgetItem(str(u.get("id", ""))))
                self.users_table.setItem(i, 1, QTableWidgetItem(u.get("phone", "")))
                self.users_table.setItem(i, 2, QTableWidgetItem("是" if u.get("is_admin") else "否"))
                self.users_table.setItem(i, 3, QTableWidgetItem(u.get("created_at", "")))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _load_stats(self):
        import requests
        try:
            r = requests.get(f"{API_BASE}/api/admin/stats", headers={"Authorization": f"Bearer {self.token}"})
            d = r.json()
            self.stats_label.setText(
                f"👥 总用户: {d.get('total_users', 0)}\n"
                f"📊 总下载: {d.get('total_downloads', 0)}\n"
                f"📈 今日下载: {d.get('today_downloads', 0)}\n"
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._start_backend()
        self.setWindowTitle("BonDownloader Pro")
        self.setMinimumSize(720, 560)
        self._show_login()

    def _start_backend(self):
        # 在 App 进程内启动 Flask 后端（线程），无需外部 Python
        import server as backend_server
        t = threading.Thread(target=backend_server.run_server, args=(5199,), daemon=True)
        t.start()
        time.sleep(2)

    def _show_login(self):
        self.login = LoginWidget()
        self.login.login_success.connect(self._on_login)
        self.login.show_register.connect(self._show_register)
        self.setCentralWidget(self.login)

    def _show_register(self):
        self.reg = RegisterWidget()
        self.reg.register_success.connect(self._show_login)
        self.reg.show_login.connect(self._show_login)
        self.setCentralWidget(self.reg)

    def _on_login(self, token, user):
        if user.get("is_admin"):
            tabs = QTabWidget()
            tabs.addTab(DownloadWidget(token), "🎬 下载")
            tabs.addTab(AdminWidget(token), "🔧 管理")
            self.setCentralWidget(tabs)
        else:
            self.setCentralWidget(DownloadWidget(token))


def _ensure_env():
    python = _find_python()
    try:
        import playwright
    except ImportError:
        subprocess.check_call([python, "-m", "pip", "install", "playwright", "aiohttp", "requests", "PyQt6", "--user", "-q"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import glob
    if not glob.glob(os.path.join(PLAYWRIGHT_CACHE, "chromium_headless_shell-*", "chrome-headless-shell-mac-arm64", "chrome-headless-shell")):
        subprocess.check_call([python, "-m", "playwright", "install", "chromium"],
                            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": PLAYWRIGHT_CACHE},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    _ensure_env()
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
