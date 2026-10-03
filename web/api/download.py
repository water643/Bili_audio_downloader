# -*- coding: utf-8 -*-
"""下载任务"""

import os
import time
import threading
import traceback

from flask import Blueprint, request, jsonify

from config.settings import (
    DOWNLOAD_DIR, QUALITY_CHOICES, DEFAULT_TARGET_LUFS,
)
from core.ffmpeg_manager import is_ffmpeg_ready
from core.config_manager import load_config
from core.downloader import download_and_process, DownloadError

from .state import (
    TASK_STATE, LOCK, log, is_valid_bili_url, check_task_timeout,
)

bp = Blueprint("api_download", __name__, url_prefix="/api")

IDEMPOTENT_WINDOW = 3.0


@bp.route("/download", methods=["POST"])
def download():
    check_task_timeout()

    with LOCK:
        if TASK_STATE["running"]:
            elapsed = time.time() - TASK_STATE.get("start_time", 0)
            if elapsed < IDEMPOTENT_WINDOW:
                return jsonify({
                    "ok": True,
                    "msg": "任务已在进行中（重复请求已忽略）",
                    "duplicate": True,
                })
            return jsonify({
                "ok": False,
                "msg": "已有任务正在进行（如确认卡死可点“重置任务”）",
                "can_reset": True,
            }), 409

        TASK_STATE["running"] = True
        TASK_STATE["logs"] = []
        TASK_STATE["result"] = None
        TASK_STATE["error"] = None
        TASK_STATE["start_time"] = time.time()

    started = False
    try:
        data = request.get_json() or {}
        url = (data.get("url") or "").strip()
        save_dir = (data.get("save_dir") or str(DOWNLOAD_DIR)).strip()
        try:
            volume = float(data.get("volume", 1.0))
            crossfeed_strength = float(data.get("crossfeed_strength", 0.3))
            target_lufs = float(data.get("target_lufs", DEFAULT_TARGET_LUFS))
        except (ValueError, TypeError) as e:
            return jsonify({"ok": False, "msg": "参数格式错误: %s" % e}), 400

        quality = str(data.get("quality", "192"))
        use_pulse = bool(data.get("use_pulse", False))
        irs_path = (data.get("irs_path") or "").strip()
        use_crossfeed = bool(data.get("use_crossfeed", True))
        normalize = bool(data.get("normalize", False))

        if not use_pulse:
            use_crossfeed = False

        if not is_valid_bili_url(url):
            return jsonify({"ok": False, "msg": "请输入有效的 B站链接"}), 400

        if quality not in QUALITY_CHOICES:
            quality = "192"

        if use_pulse and (not irs_path or not os.path.exists(irs_path)):
            return jsonify({"ok": False, "msg": "脉冲样本文件无效"}), 400

        if not is_ffmpeg_ready():
            return jsonify({"ok": False, "msg": "FFmpeg 未就绪"}), 400

        cfg = load_config()

        def worker():
            try:
                result = download_and_process(
                    url=url, save_dir=save_dir,
                    volume=volume, quality=quality,
                    use_pulse=use_pulse, irs_path=irs_path,
                    use_crossfeed=use_crossfeed,
                    crossfeed_strength=crossfeed_strength,
                    normalize=normalize,
                    target_lufs=target_lufs,
                    log_func=log,
                    config=cfg,
                )
                with LOCK:
                    TASK_STATE["result"] = result
            except DownloadError as e:
                with LOCK:
                    TASK_STATE["error"] = str(e)
                log("[失败] " + str(e), "error")
            except Exception as e:
                with LOCK:
                    TASK_STATE["error"] = str(e)
                log("[失败] 未预期错误: " + str(e), "error")
                traceback.print_exc()
            finally:
                with LOCK:
                    TASK_STATE["running"] = False
                    TASK_STATE["start_time"] = 0

        threading.Thread(target=worker, daemon=True).start()
        started = True
        return jsonify({"ok": True, "msg": "任务已启动"})

    except Exception as e:
        log("[失败] download 处理异常: %s" % e, "error")
        traceback.print_exc()
        return jsonify({"ok": False, "msg": "服务器错误: %s" % e}), 500

    finally:
        if not started:
            with LOCK:
                TASK_STATE["running"] = False
                TASK_STATE["start_time"] = 0
