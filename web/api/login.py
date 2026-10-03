# -*- coding: utf-8 -*-
"""B站登录：内置浏览器 + Cookie 检测"""

import os
import sys
import time
import subprocess

import requests
from flask import Blueprint, request, jsonify

from config.settings import COOKIES_FILE, BASE_DIR

from .state import LOGIN_STATE

bp = Blueprint("api_login", __name__, url_prefix="/api")


def _check_cookies_file():
    if not COOKIES_FILE.exists():
        return False, "未找到 cookies.txt"
    try:
        text = COOKIES_FILE.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return False, "读取失败: %s" % e
    if "SESSDATA" not in text:
        return False, "cookies.txt 中没有 SESSDATA"
    return True, "cookies.txt 有效"


def _verify_bili_login():
    if not COOKIES_FILE.exists():
        return None, "未找到 cookies.txt"

    cookies = {}
    try:
        for line in COOKIES_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    except Exception as e:
        return None, "解析失败: %s" % e

    if "SESSDATA" not in cookies:
        return None, "没有 SESSDATA"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    }
    try:
        r = requests.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=headers, cookies=cookies, timeout=10,
        )
        data = r.json()
    except Exception as e:
        return None, "请求 B站 API 失败: %s" % str(e)[:120]

    if data.get("code") != 0:
        return None, "API 错误: %s" % data.get("message", "未知")

    info = data.get("data") or {}
    if not info.get("isLogin"):
        return None, "Cookie 已失效，请重新登录"

    return {
        "username": info.get("uname", ""),
        "is_vip": info.get("vipStatus", 0) == 1,
        "vip_type": info.get("vipType", 0),
    }, "已登录"


def _reset_login_state():
    if LOGIN_STATE["proc"] is not None:
        try:
            if LOGIN_STATE["proc"].poll() is None:
                LOGIN_STATE["proc"].terminate()
        except Exception:
            pass
    LOGIN_STATE.update({
        "running": False,
        "proc": None,
        "finished": False,
        "success": False,
        "finish_msg": "",
        "info": None,
        "start_time": 0,
    })


@bp.route("/bili/browser_login", methods=["POST"])
def browser_login():
    if LOGIN_STATE["running"] and LOGIN_STATE["proc"] is not None:
        try:
            if LOGIN_STATE["proc"].poll() is None:
                return jsonify({"ok": False, "msg": "登录窗口已打开，请先完成或关闭它"}), 409
        except Exception:
            pass

    _reset_login_state()

    if COOKIES_FILE.exists():
        try:
            COOKIES_FILE.unlink()
        except Exception:
            pass

    try:
        import PySide6  # noqa: F401
    except ImportError:
        return jsonify({
            "ok": False,
            "msg": "未安装 PySide6，请运行: pip install PySide6",
        }), 500

    try:
        cmd = [sys.executable, "-m", "core.browser_login", str(COOKIES_FILE)]
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_CONSOLE

        proc = subprocess.Popen(
            cmd, cwd=str(BASE_DIR),
            creationflags=creation_flags,
        )
    except Exception as e:
        return jsonify({"ok": False, "msg": "启动失败: %s" % e}), 500

    time.sleep(1.5)
    if proc.poll() is not None:
        LOGIN_STATE["running"] = False
        LOGIN_STATE["finished"] = True
        LOGIN_STATE["success"] = False
        LOGIN_STATE["finish_msg"] = "内置浏览器启动失败（进程立即退出），请检查是否安装了 PySide6"
        return jsonify({
            "ok": False,
            "msg": "内置浏览器启动失败，请检查 PySide6 是否正常安装",
        }), 500

    LOGIN_STATE["running"] = True
    LOGIN_STATE["proc"] = proc
    LOGIN_STATE["finished"] = False
    LOGIN_STATE["success"] = False
    LOGIN_STATE["finish_msg"] = ""
    LOGIN_STATE["info"] = None
    LOGIN_STATE["start_time"] = time.time()

    return jsonify({"ok": True, "msg": "登录窗口已打开，请在弹出的窗口中登录 B站"})


@bp.route("/bili/browser_login_status")
def browser_login_status():
    if LOGIN_STATE["finished"]:
        return jsonify({
            "ok": True,
            "finished": True,
            "success": LOGIN_STATE["success"],
            "msg": LOGIN_STATE["finish_msg"],
            "info": LOGIN_STATE["info"],
        })

    if not LOGIN_STATE["running"]:
        if COOKIES_FILE.exists():
            ok, _msg = _check_cookies_file()
            if ok:
                info, err = _verify_bili_login()
                if info:
                    return jsonify({
                        "ok": True, "finished": True,
                        "success": True, "msg": "已登录", "info": info,
                    })
        return jsonify({
            "ok": True, "finished": False,
            "success": False, "msg": "未启动", "info": None,
        })

    if COOKIES_FILE.exists():
        ok, _msg = _check_cookies_file()
        if ok:
            info, err = _verify_bili_login()
            if info:
                LOGIN_STATE["running"] = False
                LOGIN_STATE["finished"] = True
                LOGIN_STATE["success"] = True
                LOGIN_STATE["finish_msg"] = "登录成功"
                LOGIN_STATE["info"] = info
                return jsonify({
                    "ok": True, "finished": True,
                    "success": True, "msg": "登录成功", "info": info,
                })

    proc = LOGIN_STATE["proc"]
    if proc is not None:
        exit_code = proc.poll()
        if exit_code is not None:
            LOGIN_STATE["running"] = False
            LOGIN_STATE["finished"] = True

            if COOKIES_FILE.exists():
                ok, _msg = _check_cookies_file()
                if ok:
                    info, err = _verify_bili_login()
                    if info:
                        LOGIN_STATE["success"] = True
                        LOGIN_STATE["finish_msg"] = "登录成功"
                        LOGIN_STATE["info"] = info
                        return jsonify({
                            "ok": True, "finished": True,
                            "success": True, "msg": "登录成功", "info": info,
                        })

            LOGIN_STATE["success"] = False
            LOGIN_STATE["finish_msg"] = "登录窗口已关闭，未检测到有效 Cookie（可能未完成登录）"
            return jsonify({
                "ok": True, "finished": True, "success": False,
                "msg": LOGIN_STATE["finish_msg"], "info": None,
            })

    if time.time() - LOGIN_STATE["start_time"] > 360:
        LOGIN_STATE["running"] = False
        LOGIN_STATE["finished"] = True
        LOGIN_STATE["success"] = False
        LOGIN_STATE["finish_msg"] = "登录超时（6 分钟）"
        return jsonify({
            "ok": True, "finished": True, "success": False,
            "msg": LOGIN_STATE["finish_msg"], "info": None,
        })

    return jsonify({
        "ok": True, "finished": False,
        "success": False, "msg": "等待登录...", "info": None,
    })


@bp.route("/bili/check_cookies")
def check_cookies():
    if not COOKIES_FILE.exists():
        return jsonify({"ok": True, "has_cookies": False, "msg": "未登录"})

    info, err = _verify_bili_login()
    if info:
        return jsonify({
            "ok": True, "has_cookies": True, "info": info,
            "msg": "已登录: %s%s" % (
                info["username"],
                "（大会员）" if info["is_vip"] else "（普通用户）",
            ),
        })
    return jsonify({
        "ok": True, "has_cookies": False, "msg": err or "Cookie 无效",
    })


@bp.route("/bili/clear_cookies", methods=["POST"])
def clear_cookies():
    if COOKIES_FILE.exists():
        try:
            COOKIES_FILE.unlink()
        except Exception as e:
            return jsonify({"ok": False, "msg": "删除失败: %s" % e}), 500
    _reset_login_state()
    return jsonify({"ok": True, "msg": "已清除"})
