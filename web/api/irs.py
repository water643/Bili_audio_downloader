# -*- coding: utf-8 -*-
"""剪贴板解析 + 脉冲样本文件管理"""

import os
import re
import uuid

from flask import Blueprint, request, jsonify

from config.settings import VIPER_DIR, IRS_DIR

bp = Blueprint("api_irs", __name__, url_prefix="/api")


@bp.route("/paste_url", methods=["POST"])
def paste_url():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "msg": "剪贴板为空"}), 400
    m = re.search(r"https?://[^\s]+", text)
    if not m:
        return jsonify({"ok": False, "msg": "未找到链接"}), 400
    return jsonify({"ok": True, "url": m.group(0)})


@bp.route("/upload_irs", methods=["POST"])
def upload_irs():
    if "file" not in request.files:
        return jsonify({"ok": False, "msg": "没有文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".irs", ".wav"):
        return jsonify({"ok": False, "msg": "只支持 .irs 或 .wav"}), 400
    IRS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = uuid.uuid4().hex + ext
    save_path = IRS_DIR / safe_name
    f.save(str(save_path))
    return jsonify({
        "ok": True, "path": str(save_path),
        "name": f.filename, "msg": "上传成功",
    })


@bp.route("/scan_irs")
def scan_irs():
    try:
        VIPER_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "msg": "无法创建 VIPER 目录: %s" % e}), 500

    files = []
    for ext in (".irs", ".wav"):
        for p in VIPER_DIR.rglob("*" + ext):
            if p.is_file():
                try:
                    rel = p.relative_to(VIPER_DIR)
                    size = p.stat().st_size
                except Exception:
                    continue
                files.append({
                    "name": p.name,
                    "rel": str(rel).replace("\\", "/"),
                    "path": str(p),
                    "size": size,
                })

    files.sort(key=lambda x: x["rel"].lower())
    return jsonify({
        "ok": True, "dir": str(VIPER_DIR),
        "files": files, "count": len(files),
    })
