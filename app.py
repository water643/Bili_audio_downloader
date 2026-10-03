# -*- coding: utf-8 -*-
"""B站音频下载器 - WebUI 入口"""

import threading
import webbrowser

from flask import Flask

from config.settings import HOST, PORT, DEBUG
from core.ffmpeg_manager import is_ffmpeg_ready, download_ffmpeg

from web.routes import bp as routes_bp
from web.api.status import bp as status_bp
from web.api.install import bp as install_bp
from web.api.config_api import bp as config_bp
from web.api.play import bp as play_bp
from web.api.login import bp as login_bp
from web.api.irs import bp as irs_bp
from web.api.download import bp as download_bp
from web.api.batch import bp as batch_bp


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.register_blueprint(routes_bp)
    app.register_blueprint(status_bp)
    app.register_blueprint(install_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(play_bp)
    app.register_blueprint(login_bp)
    app.register_blueprint(irs_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(batch_bp)

    @app.after_request
    def add_header(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    return app


def auto_prepare_ffmpeg():
    if is_ffmpeg_ready():
        print("[FFmpeg] 已就绪")
        return
    print("[FFmpeg] 未检测到，开始自动下载...")
    try:
        download_ffmpeg(log_func=lambda m: print("[FFmpeg] " + m))
    except Exception as e:
        print("[FFmpeg] 下载失败: %s" % e)


def open_browser():
    webbrowser.open("http://%s:%d/" % (HOST, PORT))


def main():
    threading.Thread(target=auto_prepare_ffmpeg, daemon=True).start()
    app = create_app()
    threading.Timer(1.5, open_browser).start()
    print("服务启动: http://%s:%d/" % (HOST, PORT))
    app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)


if __name__ == "__main__":
    main()
