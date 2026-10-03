# -*- coding: utf-8 -*-
"""状态、日志、任务重置"""

import time

from flask import Blueprint, request, jsonify

from config.settings import (
    DOWNLOAD_DIR, FFMPEG_DIR, DEFAULT_TARGET_LUFS,
)
from core.ffmpeg_manager import is_ffmpeg_ready
from core.aria2_manager import is_aria2_ready, get_aria2_exe, get_aria2_status
from core.config_manager import load_config

from .state import TASK_STATE, LOCK, check_task_timeout

bp = Blueprint("api_status", __name__, url_prefix="/api")


@bp.route("/status")
def status():
    check_task_timeout()
    cfg = load_config()
    aria2_ok, aria2_msg = get_aria2_status()
    with LOCK:
        return jsonify({
            "ffmpeg_ready": is_ffmpeg_ready(),
            "ffmpeg_path": str(FFMPEG_DIR),
            "aria2_ready": aria2_ok,
            "aria2_status_msg": aria2_msg,
            "aria2_path": str(get_aria2_exe()),
            "default_save_dir": str(DOWNLOAD_DIR),
            "default_target_lufs": DEFAULT_TARGET_LUFS,
            "config": cfg,
            "task_running": TASK_STATE["running"],
            "result": TASK_STATE["result"],
            "error": TASK_STATE["error"],
            "log_count": len(TASK_STATE["logs"]),
        })


@bp.route("/logs")
def logs():
    since = int(request.args.get("since", 0))
    with LOCK:
        new_logs = TASK_STATE["logs"][since:]
        total = len(TASK_STATE["logs"])
    return jsonify({"logs": new_logs, "total": total})


@bp.route("/task/reset", methods=["POST"])
def task_reset():
    with LOCK:
        TASK_STATE["running"] = False
        TASK_STATE["error"] = None
        TASK_STATE["start_time"] = 0
    return jsonify({"ok": True, "msg": "任务状态已重置"})
