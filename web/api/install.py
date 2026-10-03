# -*- coding: utf-8 -*-
"""FFmpeg / aria2c 安装"""

import threading

from flask import Blueprint, request, jsonify

from core.ffmpeg_manager import is_ffmpeg_ready, download_ffmpeg
from core.aria2_manager import is_aria2_ready, download_aria2

from .state import log

bp = Blueprint("api_install", __name__, url_prefix="/api")


@bp.route("/ffmpeg/install", methods=["POST"])
def install_ffmpeg():
    if is_ffmpeg_ready():
        return jsonify({"ok": True, "msg": "FFmpeg 已就绪"})

    def worker():
        try:
            download_ffmpeg(log_func=log)
        except Exception as e:
            log("[错误] FFmpeg 下载失败: %s" % e)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "msg": "已开始下载 FFmpeg"})


@bp.route("/aria2/install", methods=["POST"])
def install_aria2():
    data = request.get_json() or {}
    force = bool(data.get("force", False))

    if not force and is_aria2_ready():
        return jsonify({"ok": True, "msg": "aria2c 已就绪"})

    def worker():
        try:
            download_aria2(log_func=log, force=True)
        except Exception as e:
            log("[错误] aria2c 下载失败: %s" % e)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "msg": "已开始下载 aria2c（强制重装）"})
