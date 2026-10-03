# -*- coding: utf-8 -*-
"""配置读写"""

from flask import Blueprint, request, jsonify

from core.config_manager import load_config, save_config

bp = Blueprint("api_config", __name__, url_prefix="/api")


@bp.route("/config", methods=["GET"])
def get_config():
    cfg = load_config()
    return jsonify({"ok": True, "config": cfg})


@bp.route("/config", methods=["POST"])
def set_config():
    data = request.get_json() or {}
    cfg = save_config(data)
    return jsonify({"ok": True, "config": cfg})
