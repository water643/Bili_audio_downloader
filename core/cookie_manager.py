# -*- coding: utf-8 -*-
"""B站 Cookie 检测与管理"""

import json
import time
from urllib.parse import urlencode

import requests

try:
    from yt_dlp.cookies import (
        extract_cookies_from_browser,
        SUPPORTED_BROWSERS,
    )
    YTDLP_OK = True
except ImportError:
    YTDLP_OK = False
    SUPPORTED_BROWSERS = []

BILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

# 浏览器显示名
BROWSER_LABELS = {
    "chrome": "Chrome",
    "edge": "Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "chromium": "Chromium",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "safari": "Safari",
    "whale": "Whale",
}

# 优先检测的浏览器顺序
PREFERRED_ORDER = ["chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi"]


def get_browser_label(name):
    return BROWSER_LABELS.get(name, name.capitalize())


def _cookies_to_header(jar):
    """CookieJar -> Cookie 请求头字符串"""
    parts = []
    for c in jar:
        if "bilibili.com" in (c.domain or ""):
            parts.append("%s=%s" % (c.name, c.value))
    return "; ".join(parts)


def check_browser(browser):
    """
    检测单个浏览器的 B站登录状态
    返回: {
        browser, label, ok, logged_in, is_vip, vip_type,
        username, msg
    }
    """
    result = {
        "browser": browser,
        "label": get_browser_label(browser),
        "ok": False,
        "logged_in": False,
        "is_vip": False,
        "vip_type": 0,
        "username": "",
        "msg": "",
    }

    if not YTDLP_OK:
        result["msg"] = "yt-dlp 未安装，无法读取浏览器 Cookie"
        return result

    try:
        jar = extract_cookies_from_browser(browser)
    except Exception as e:
        err = str(e)
        if "database is locked" in err.lower() or "lock" in err.lower():
            result["msg"] = "浏览器正在运行，请完全关闭 %s 后重试" % result["label"]
        elif "could not find" in err.lower() or "not found" in err.lower():
            result["msg"] = "未检测到 %s 的配置目录（可能未安装）" % result["label"]
        else:
            result["msg"] = "读取失败: %s" % err[:120]
        return result

    # 检查 SESSDATA
    has_sessdata = any(c.name == "SESSDATA" for c in jar)
    if not has_sessdata:
        result["ok"] = True
        result["msg"] = "未登录（无 SESSDATA）"
        return result

    # 调 B站 API 验证
    cookie_header = _cookies_to_header(jar)
    headers = {
        "Cookie": cookie_header,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    }

    try:
        r = requests.get(BILI_NAV_URL, headers=headers, timeout=10)
        data = r.json()
    except Exception as e:
        result["msg"] = "请求 B站 API 失败: %s" % str(e)[:120]
        return result

    if data.get("code") != 0:
        result["msg"] = "API 错误 (%s): %s" % (
            data.get("code"), data.get("message", "未知"))
        return result

    info = data.get("data") or {}
    is_login = info.get("isLogin", False)

    if not is_login:
        result["ok"] = True
        result["msg"] = "SESSDATA 已失效，需重新登录"
        return result

    result["ok"] = True
    result["logged_in"] = True
    result["username"] = info.get("uname", "")
    result["is_vip"] = info.get("vipStatus", 0) == 1
    result["vip_type"] = info.get("vipType", 0)

    if result["is_vip"]:
        result["msg"] = "已登录: %s（大会员）" % result["username"]
    else:
        result["msg"] = "已登录: %s（普通用户）" % result["username"]

    return result


def detect_all_browsers():
    """
    检测所有可用浏览器，返回排序后的结果列表
    优先级: VIP > 已登录 > 其他
    """
    results = []
    seen = set()

    for name in PREFERRED_ORDER:
        if name in SUPPORTED_BROWSERS:
            results.append(check_browser(name))
            seen.add(name)

    for name in SUPPORTED_BROWSERS:
        if name not in seen and name in BROWSER_LABELS:
            results.append(check_browser(name))

    # 排序: VIP > 已登录 > 其他
    def score(r):
        if r["is_vip"]:
            return 0
        if r["logged_in"]:
            return 1
        if r["ok"]:
            return 2
        return 3

    results.sort(key=score)
    return results


def pick_best_browser(results):
    """
    从检测结果里挑出最优的浏览器
    返回 browser 名称，或 None
    """
    for r in results:
        if r.get("is_vip"):
            return r["browser"]
    for r in results:
        if r.get("logged_in"):
            return r["browser"]
    return None


def check_browser_login_only(browser):
    """只返回这个浏览器是否已登录（供下载时调用）"""
    if not browser:
        return False, "未指定浏览器"
    r = check_browser(browser)
    if r["logged_in"]:
        return True, r["msg"]
    return False, r["msg"]
