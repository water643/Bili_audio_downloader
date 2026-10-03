# -*- coding: utf-8 -*-
"""共享状态和辅助函数"""

import threading
import time
from datetime import datetime

TASK_TIMEOUT = 30 * 60

TASK_STATE = {
    "running": False,
    "logs": [],
    "result": None,
    "error": None,
    "start_time": 0,
}
LOCK = threading.Lock()

LOGIN_STATE = {
    "running": False,
    "proc": None,
    "finished": False,
    "success": False,
    "finish_msg": "",
    "info": None,
    "start_time": 0,
}

PLAY_CACHE = {}
PLAY_LOCK = threading.Lock()
PLAY_TTL = 3600


def log(msg, level="info"):
    """
    追加日志。
    level: info / ok / warn / error / section / progress
    存储结构: {"ts": "HH:MM:SS", "level": "info", "msg": "..."}
    """
    entry = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "msg": str(msg),
    }
    with LOCK:
        TASK_STATE["logs"].append(entry)


def is_valid_bili_url(url):
    if not url:
        return False
    u = url.lower()
    return ("bilibili.com" in u) or ("b23.tv" in u)


def check_task_timeout():
    with LOCK:
        if TASK_STATE["running"]:
            elapsed = time.time() - TASK_STATE.get("start_time", 0)
            if elapsed > TASK_TIMEOUT:
                TASK_STATE["running"] = False
                TASK_STATE["error"] = "上一次任务超时（超过 %d 分钟），已自动重置" % (TASK_TIMEOUT // 60)
                return True
    return False
