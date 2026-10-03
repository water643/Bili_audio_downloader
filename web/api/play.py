# -*- coding: utf-8 -*-
"""本地 MP3 试听（Range 流式播放）"""

import os
import re
import sys
import time
import uuid

from flask import Blueprint, request, jsonify, Response

from config.settings import DOWNLOAD_DIR

from .state import PLAY_CACHE, PLAY_LOCK, PLAY_TTL

bp = Blueprint("api_play", __name__, url_prefix="/api")


@bp.route("/play_token", methods=["POST"])
def play_token():
    data = request.get_json() or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"ok": False, "msg": "缺少路径"}), 400

    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        return jsonify({"ok": False, "msg": "文件不存在"}), 404

    dl_abs = os.path.abspath(str(DOWNLOAD_DIR))
    if sys.platform == "win32":
        in_downloads = abs_path.lower().startswith(dl_abs.lower())
    else:
        in_downloads = abs_path.startswith(dl_abs)
    if not in_downloads:
        return jsonify({"ok": False, "msg": "禁止访问该路径"}), 403

    token = uuid.uuid4().hex
    now = time.time()
    with PLAY_LOCK:
        expired = [k for k, v in PLAY_CACHE.items() if now - v["ts"] > PLAY_TTL]
        for k in expired:
            del PLAY_CACHE[k]
        PLAY_CACHE[token] = {"path": abs_path, "ts": now}

    return jsonify({
        "ok": True,
        "token": token,
        "name": os.path.basename(abs_path),
    })


@bp.route("/play_stream")
def play_stream():
    token = request.args.get("token", "")
    with PLAY_LOCK:
        item = PLAY_CACHE.get(token)

    if not item:
        return Response("播放链接已过期", status=404, mimetype="text/plain")

    path = item["path"]
    if not os.path.exists(path):
        return Response("文件不存在", status=404, mimetype="text/plain")

    file_size = os.path.getsize(path)
    range_header = request.headers.get("Range")

    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size:
                return Response(
                    "Range 不合法", status=416,
                    headers={"Content-Range": "bytes */%d" % file_size},
                )

            length = end - start + 1

            def gen_range():
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return Response(gen_range(), status=206, headers={
                "Content-Type": "audio/mpeg",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Range": "bytes %d-%d/%d" % (start, end, file_size),
                "Cache-Control": "no-cache",
            })

    def gen_full():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    return Response(gen_full(), status=200, headers={
        "Content-Type": "audio/mpeg",
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Cache-Control": "no-cache",
    })
