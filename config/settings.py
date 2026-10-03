# -*- coding: utf-8 -*-
"""全局配置"""

import sys
from pathlib import Path


def get_base_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


BASE_DIR = get_base_dir()
DATA_DIR = BASE_DIR / "data"
DOWNLOAD_DIR = BASE_DIR / "downloads"
FFMPEG_DIR = DATA_DIR / "ffmpeg"
VIPER_DIR = BASE_DIR / "VIPER"
IRS_DIR = DATA_DIR / "irs"
ARIA2_DIR = DATA_DIR / "aria2"
CONFIG_FILE = DATA_DIR / "config.json"

COOKIES_FILE = DATA_DIR / "cookies.txt"
BROWSER_DATA_DIR = DATA_DIR / "browser_data"

FFMPEG_URLS = [
    "https://ghfast.top/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip",
    "https://gh-proxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip",
    "https://ghproxy.net/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip",
]

ARIA2_URLS = [
    "https://ghfast.top/https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip",
    "https://gh-proxy.com/https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip",
    "https://ghproxy.net/https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip",
    "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip",
]

HOST = "127.0.0.1"
PORT = 5000
DEBUG = False

SAMPLE_RATE = 48000
AFIR_DRY = 0.7
AFIR_WET = 1.0
CROSSFEED_RANGE = 0.5
CROSSFEED_SLOPE = 0.5

DEFAULT_TARGET_LUFS = -16.0

QUALITY_CHOICES = ["128", "192", "256", "320"]
