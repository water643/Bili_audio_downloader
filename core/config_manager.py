# -*- coding: utf-8 -*-
"""配置管理（读写 data/config.json）"""

import json
from config.settings import CONFIG_FILE, DOWNLOAD_DIR, DEFAULT_TARGET_LUFS

DEFAULT_CONFIG = {
    "audio_quality": "hires",       # hires / standard / mp3
    "use_aria2": True,
    "aria2_threads": 16,
    "aria2_splits": 16,
    "cookies_browser": "",          # "" / chrome / edge / firefox
    "default_save_dir": "",
    "default_volume": 1.0,
    "default_quality": "192",
    "default_target_lufs": DEFAULT_TARGET_LUFS,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in data.items():
                if k in cfg:
                    cfg[k] = v
        except Exception:
            pass
    if not cfg.get("default_save_dir"):
        cfg["default_save_dir"] = str(DOWNLOAD_DIR)
    return cfg


def save_config(new_data):
    merged = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            old = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in old.items():
                if k in merged:
                    merged[k] = v
        except Exception:
            pass
    for k, v in (new_data or {}).items():
        if k in merged:
            merged[k] = v
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged
