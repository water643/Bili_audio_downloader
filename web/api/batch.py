# -*- coding: utf-8 -*-
"""收藏夹 / 合集批量下载"""

import os
import re
import time
import threading
import traceback

import yt_dlp
from flask import Blueprint, request, jsonify

from config.settings import (
    DOWNLOAD_DIR, QUALITY_CHOICES, DEFAULT_TARGET_LUFS, COOKIES_FILE,
)
from core.ffmpeg_manager import is_ffmpeg_ready
from core.config_manager import load_config
from core.downloader import download_and_process, DownloadError

from .state import TASK_STATE, LOCK, log, check_task_timeout

bp = Blueprint("api_batch", __name__, url_prefix="/api")


# 收藏夹/合集链接特征
BATCH_PATTERNS = [
    r"space\.bilibili\.com/\d+/favlist",
    r"space\.bilibili\.com/\d+/channel/seriesdetail",
    r"space\.bilibili\.com/\d+/lists",
    r"bilibili\.com/medialist/detail",
    r"bilibili\.com/medialist/play",
    r"bilibili\.com/list/",
]


def is_batch_url(url):
    if not url:
        return False
    u = url.lower()
    for p in BATCH_PATTERNS:
        if re.search(p, u):
            return True
    return False


def _build_ydl_opts(flat=True):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if flat:
        opts["extract_flat"] = True
    if COOKIES_FILE.exists():
        try:
            content = COOKIES_FILE.read_text(encoding="utf-8", errors="ignore")
            if "SESSDATA" in content:
                opts["cookiefile"] = str(COOKIES_FILE)
        except Exception:
            pass
    return opts


@bp.route("/batch/parse", methods=["POST"])
def batch_parse():
    """解析收藏夹/合集，返回视频列表（不下载）"""
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"ok": False, "msg": "缺少链接"}), 400

    if not is_batch_url(url):
        return jsonify({
            "ok": False,
            "msg": "不是收藏夹/合集链接。支持：space.bilibili.com/{uid}/favlist 等",
        }), 400

    try:
        ydl_opts = _build_ydl_opts(flat=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"ok": False, "msg": "解析失败: %s" % str(e)[:200]}), 500

    entries = info.get("entries") or []
    if not entries:
        return jsonify({"ok": False, "msg": "未获取到视频列表"}), 500

    videos = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id") or ""
        title = e.get("title") or "(无标题)"
        dur = e.get("duration") or 0
        # 组装标准视频 URL
        if vid:
            vurl = "https://www.bilibili.com/video/%s" % vid
        else:
            vurl = e.get("url") or e.get("webpage_url") or ""
        if not vurl:
            continue
        videos.append({
            "id": vid,
            "title": title,
            "url": vurl,
            "duration": dur,
        })

    return jsonify({
        "ok": True,
        "title": info.get("title") or "收藏夹",
        "uploader": info.get("uploader") or "",
        "count": len(videos),
        "videos": videos,
    })


@bp.route("/batch/download", methods=["POST"])
def batch_download():
    """批量下载"""
    check_task_timeout()

    with LOCK:
        if TASK_STATE["running"]:
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
        videos = data.get("videos") or []
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

        if not videos:
            return jsonify({"ok": False, "msg": "视频列表为空"}), 400

        if quality not in QUALITY_CHOICES:
            quality = "192"

        if use_pulse and (not irs_path or not os.path.exists(irs_path)):
            return jsonify({"ok": False, "msg": "脉冲样本文件无效"}), 400

        if not is_ffmpeg_ready():
            return jsonify({"ok": False, "msg": "FFmpeg 未就绪"}), 400

        cfg = load_config()

        def worker():
            total = len(videos)
            success = 0
            failed = 0
            results = []

            log("批量下载开始，共 %d 个视频" % total, "section")

            for i, v in enumerate(videos, 1):
                title = v.get("title") or "(无标题)"
                url = v.get("url") or ""
                if not url:
                    failed += 1
                    log("[%d/%d] %s（跳过，无链接）" % (i, total, title), "warn")
                    continue

                log("[%d/%d] %s" % (i, total, title), "section")
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
                    success += 1
                    results.append({
                        "title": title,
                        "path": result,
                        "ok": True,
                    })
                except DownloadError as e:
                    failed += 1
                    log("  ✗ 失败: %s" % e, "error")
                    results.append({"title": title, "ok": False, "error": str(e)})
                except Exception as e:
                    failed += 1
                    log("  ✗ 未预期错误: %s" % e, "error")
                    traceback.print_exc()
                    results.append({"title": title, "ok": False, "error": str(e)})

            log("批量下载完成", "section")
            log("  成功 %d / 失败 %d / 共 %d" % (success, failed, total), "ok" if failed == 0 else "warn")

            # 复用 result 字段，返回最后一个成功的文件路径（用于试听）
            last_ok = None
            for r in reversed(results):
                if r.get("ok") and r.get("path"):
                    last_ok = r["path"]
                    break

            with LOCK:
                if last_ok:
                    TASK_STATE["result"] = last_ok
                if failed > 0:
                    TASK_STATE["error"] = "有 %d 个视频下载失败" % failed

        def worker_wrapper():
            try:
                worker()
            except Exception as e:
                with LOCK:
                    TASK_STATE["error"] = str(e)
                log("[失败] 批量下载异常: %s" % e, "error")
                traceback.print_exc()
            finally:
                with LOCK:
                    TASK_STATE["running"] = False
                    TASK_STATE["start_time"] = 0

        threading.Thread(target=worker_wrapper, daemon=True).start()
        started = True
        return jsonify({"ok": True, "msg": "批量任务已启动"})

    except Exception as e:
        log("[失败] batch_download 异常: %s" % e, "error")
        traceback.print_exc()
        return jsonify({"ok": False, "msg": "服务器错误: %s" % e}), 500

    finally:
        if not started:
            with LOCK:
                TASK_STATE["running"] = False
                TASK_STATE["start_time"] = 0
