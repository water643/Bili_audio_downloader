# -*- coding: utf-8 -*-
"""页面路由"""

from flask import Blueprint, render_template

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/settings")
def settings():
    return render_template("settings.html")
