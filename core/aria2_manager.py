# -*- coding: utf-8 -*-
"""aria2c 下载器管理"""

import os
import sys
import zipfile
import shutil
import subprocess
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config.settings import ARIA2_DIR, DATA_DIR, ARIA2_URLS

# 最小有效文件大小（aria2c 正常约 5MB，小文件说明是占位/损坏）
MIN_VALID_SIZE = 1 * 1024 * 1024


def get_aria2_exe():
    name = "aria2c.exe" if sys.platform == "win32" else "aria2c"
    return ARIA2_DIR / name


def _check_exe_runnable(exe_path):
    """实际执行 aria2c --version，能返回版本号才算有效"""
    if not exe_path.exists():
        return False, "文件不存在"
    if exe_path.stat().st_size < MIN_VALID_SIZE:
        return False, "文件大小异常（%d 字节），可能是空文件" % exe_path.stat().st_size
    try:
        result = subprocess.run(
            [str(exe_path), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        output = (result.stdout or b"").decode("utf-8", errors="ignore")
        if result.returncode == 0 and "aria2" in output.lower():
            return True, output.splitlines()[0] if output else "aria2c"
        return False, "执行失败，返回码 %d" % result.returncode
    except FileNotFoundError:
        return False, "无法执行（缺少依赖 DLL？）"
    except subprocess.TimeoutExpired:
        return False, "执行超时"
    except Exception as e:
        return False, "执行异常: %s" % e


def is_aria2_ready():
    """真正可用（存在 + 能运行）"""
    ok, _ = _check_exe_runnable(get_aria2_exe())
    return ok


def get_aria2_status():
    """返回 (ok: bool, message: str)"""
    return _check_exe_runnable(get_aria2_exe())


def download_aria2(log_func=print, force=False):
    """下载并解压 aria2c。force=True 强制重装"""
    if not force:
        ok, msg = _check_exe_runnable(get_aria2_exe())
        if ok:
            log_func("[OK] aria2c 已就绪: " + msg)
            return str(ARIA2_DIR)
        elif get_aria2_exe().exists():
            log_func("[检测] 现有 aria2c 无效（%s），准备重装..." % msg)

    # 清理旧文件
    if ARIA2_DIR.exists():
        shutil.rmtree(ARIA2_DIR, ignore_errors=True)
    ARIA2_DIR.mkdir(parents=True, exist_ok=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_DIR / "aria2_download.zip"

    last_error = None
    for i, url in enumerate(ARIA2_URLS, 1):
        try:
            log_func("[下载] aria2c 源 %d/%d" % (i, len(ARIA2_URLS)))
            log_func("       %s" % url.split("/")[2])
            headers = {"User-Agent": "Mozilla/5.0"}

            with requests.get(url, stream=True, timeout=(10, 120),
                              headers=headers, verify=False) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                last_report = 0
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 64):
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if done - last_report >= 1024 * 1024:
                            last_report = done
                            if total > 0:
                                pct = done * 100.0 / total
                                log_func("   进度 %.1f%% (%d/%d KB)" % (
                                    pct, done / 1024, total / 1024))

            # 校验 zip 完整性
            if not zipfile.is_zipfile(zip_path):
                raise ValueError("下载的文件不是有效 zip")

            log_func("[解压] 正在解压...")
            temp_dir = DATA_DIR / "_aria2_tmp"
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(temp_dir)

            # 找到 aria2c 所在目录
            src_dir = None
            for root, _dirs, files in os.walk(temp_dir):
                if "aria2c.exe" in files:
                    src_dir = Path(root)
                    break
            if src_dir is None:
                raise FileNotFoundError("压缩包中未找到 aria2c.exe")

            # 复制所有文件（包括 DLL）
            for item in src_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, ARIA2_DIR / item.name)

            # 清理
            shutil.rmtree(temp_dir, ignore_errors=True)
            zip_path.unlink(missing_ok=True)

            # 验证
            ok, msg = _check_exe_runnable(get_aria2_exe())
            if not ok:
                raise RuntimeError("安装后验证失败: %s" % msg)

            log_func("[完成] aria2c 可用: %s" % msg)
            return str(ARIA2_DIR)

        except Exception as e:
            last_error = e
            log_func("[警告] 源 %d 失败: %s" % (i, e))
            zip_path.unlink(missing_ok=True)
            shutil.rmtree(DATA_DIR / "_aria2_tmp", ignore_errors=True)
            continue

    raise RuntimeError("所有 aria2c 下载源均失败。最后错误: %s" % last_error)
