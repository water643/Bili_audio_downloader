# -*- coding: utf-8 -*-
"""内置浏览器登录窗口（PySide6 + QtWebEngine）

用法:
    python -m core.browser_login <cookies输出路径>

打开一个内置浏览器窗口加载 B站登录页。
用户在窗口里完成登录后，程序自动抓取所有 Cookie（包括 HttpOnly），
保存成 Netscape cookies.txt 格式，然后窗口自动关闭。
窗口内还提供一个"手动保存"按钮作为兜底。
"""

import sys
from pathlib import Path


def run_login_window(cookies_output_path):
    from PySide6.QtCore import QUrl, QTimer, Qt
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QLabel, QWidget, QVBoxLayout,
        QHBoxLayout, QPushButton,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage

    from config.settings import BROWSER_DATA_DIR

    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = BROWSER_DATA_DIR / "storage"
    cache_path = BROWSER_DATA_DIR / "cache"
    storage_path.mkdir(parents=True, exist_ok=True)
    cache_path.mkdir(parents=True, exist_ok=True)

    output_path = Path(cookies_output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    class LoginWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("B站登录")
            self.resize(980, 740)

            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # 顶部提示条
            top = QWidget()
            top_layout = QHBoxLayout(top)
            top_layout.setContentsMargins(12, 8, 12, 8)

            self.tip = QLabel("请登录 B站，登录成功后窗口会自动关闭")
            self.tip.setStyleSheet("color: white; font-size: 12px;")
            top_layout.addWidget(self.tip, 1)

            self.save_btn = QPushButton("我已登录，保存 Cookie")
            self.save_btn.setStyleSheet(
                "background: white; color: #7c5cff; border: none; "
                "padding: 6px 14px; border-radius: 4px; font-size: 12px; "
                "font-weight: bold;"
            )
            self.save_btn.setCursor(Qt.PointingHandCursor)
            self.save_btn.clicked.connect(self.manual_save)
            top_layout.addWidget(self.save_btn, 0)

            top.setStyleSheet("background: #7c5cff;")
            layout.addWidget(top)

            self.view = QWebEngineView()

            # 持久化 profile
            self.profile = QWebEngineProfile("bili_login", self)
            self.profile.setPersistentStoragePath(str(storage_path))
            self.profile.setCachePath(str(cache_path))
            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile.ForcePersistentCookies
            )
            page = QWebEnginePage(self.profile, self.view)
            self.view.setPage(page)

            layout.addWidget(self.view, 1)
            self.setCentralWidget(container)

            # cookie 收集
            self.cookies = {}
            self.cookie_store = self.profile.cookieStore()
            self.cookie_store.cookieAdded.connect(self.on_cookie_added)

            # 加载登录页
            self.view.load(QUrl("https://passport.bilibili.com/login"))

            # 每 1.5 秒检查登录状态
            self.timer = QTimer()
            self.timer.timeout.connect(self.check_login)
            self.timer.start(1500)

            # 页面加载完成后，再延迟 3 秒检查一次（等 cookie store 稳定）
            self.view.loadFinished.connect(self._on_load_finished)

            self.done = False
            self.checks = 0

        def _on_load_finished(self, ok):
            if self.done:
                return
            # 页面加载完，延迟检查
            QTimer.singleShot(3000, self.check_login)

        def on_cookie_added(self, cookie):
            try:
                name = bytes(cookie.name()).decode("utf-8", errors="ignore")
                domain = cookie.domain() or ""
                if "bilibili.com" in domain:
                    self.cookies[name] = cookie
            except Exception:
                pass

        def check_login(self):
            if self.done:
                return
            self.checks += 1

            # 检查关键 cookie
            has_sess = "SESSDATA" in self.cookies
            has_jct = "bili_jct" in self.cookies

            if has_sess and has_jct:
                self.finish("自动检测到登录成功")
                return

            # 检查 URL 是否跳转到主站（说明已登录）
            url = self.view.url().toString()
            if ("www.bilibili.com" in url or "bilibili.com/video" in url) and has_sess:
                self.finish("检测到已跳转到主站，登录成功")
                return

            # 通过 JS 检查登录状态作为兜底
            # 若页面里能拿到 DedeUserID 就说明已登录
            if self.checks % 4 == 0:  # 每 6 秒检查一次
                try:
                    self.view.page().runJavaScript(
                        "document.cookie.indexOf('DedeUserID') >= 0",
                        self._on_js_check,
                    )
                except Exception:
                    pass

            # 更新提示
            if not has_sess:
                self.tip.setText("请登录 B站，登录成功后窗口会自动关闭")
            else:
                self.tip.setText("检测到 SESSDATA，等待其他 cookie...")

        def _on_js_check(self, result):
            if self.done:
                return
            if result is True and "SESSDATA" in self.cookies:
                self.finish("通过 JS 检测到登录成功")

        def manual_save(self):
            """用户手动点击保存"""
            if self.done:
                return
            if "SESSDATA" not in self.cookies:
                self.tip.setText("未检测到 SESSDATA，请确认已登录 B站")
                return
            self.finish("已手动保存")

        def finish(self, reason):
            if self.done:
                return
            self.done = True
            try:
                self.save_cookies()
                print("[OK] Cookie 已保存到: %s （%s）" % (output_path, reason))
            except Exception as e:
                print("[错误] 保存 Cookie 失败: %s" % e)
            self.tip.setText("登录成功，窗口即将关闭...")
            QTimer.singleShot(500, self.close)

        def save_cookies(self):
            lines = [
                "# Netscape HTTP Cookie File",
                "# Generated by bili_audio_downloader",
                "",
            ]
            for name, cookie in self.cookies.items():
                try:
                    domain = cookie.domain() or ".bilibili.com"
                    if not domain.startswith("."):
                        domain = "." + domain
                    path = cookie.path() or "/"
                    secure = "TRUE" if cookie.isSecure() else "FALSE"
                    expiry = 0
                    if not cookie.isSessionCookie():
                        dt = cookie.expirationDate()
                        if dt.isValid():
                            expiry = int(dt.toSecsSinceEpoch())
                    value = bytes(cookie.value()).decode("utf-8", errors="ignore")
                    lines.append("\t".join([
                        domain, "TRUE", path, secure, str(expiry), name, value,
                    ]))
                except Exception:
                    continue
            output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        def closeEvent(self, event):
            # 如果窗口被手动关闭，让保存逻辑也跑一下（有 cookie 就存）
            if not self.done and "SESSDATA" in self.cookies:
                try:
                    self.save_cookies()
                    print("[OK] 关闭窗口时保存 Cookie 到: %s" % output_path)
                except Exception as e:
                    print("[警告] 关闭窗口时保存失败: %s" % e)
            event.accept()

    app = QApplication(sys.argv)
    win = LoginWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m core.browser_login <cookies输出路径>")
        sys.exit(1)
    run_login_window(sys.argv[1])
