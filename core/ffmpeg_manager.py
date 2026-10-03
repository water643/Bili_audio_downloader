# -*- coding: utf-8 -*-
"""FFmpeg 下载、检测、路径管理（多线程 + 实时进度）"""

import os
import sys
import time
import zipfile
import shutil
import threading
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config.settings import FFMPEG_DIR, DATA_DIR, FFMPEG_URLS

# 下载参数
THREADS = 8                 # 分块下载线程数
CHUNK_SIZE = 1024 * 512     # 每次读取 512KB
SOURCE_TIMEOUT = 300        # 单个源最长下载时间（秒）
READ_TIMEOUT = 20           # 单次读取超时（秒）
PROGRESS_INTERVAL = 0.5     # 进度刷新间隔（秒）


def get_ffmpeg_exe():
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    return FFMPEG_DIR / name


def get_ffprobe_exe():
    name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    return FFMPEG_DIR / name


def is_ffmpeg_ready():
    return get_ffmpeg_exe().exists() and get_ffprobe_exe().exists()


def _format_size(num_bytes):
    """格式化文件大小"""
    if num_bytes < 1024:
        return "%d B" % num_bytes
    elif num_bytes < 1024 * 1024:
        return "%.1f KB" % (num_bytes / 1024)
    elif num_bytes < 1024 * 1024 * 1024:
        return "%.1f MB" % (num_bytes / 1024 / 1024)
    else:
        return "%.2f GB" % (num_bytes / 1024 / 1024 / 1024)


def _format_time(seconds):
    """格式化剩余时间"""
    if seconds < 0 or seconds > 3600:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return "%02d:%02d" % (m, s)
    h, m = divmod(m, 60)
    return "%d:%02d:%02d" % (h, m, s)


def _get_file_size(url):
    """获取远程文件大小（返回 int，失败返回 0）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.head(url, timeout=10, headers=headers, verify=False,
                          allow_redirects=True)
        size = int(r.headers.get("content-length", 0))
        return size
    except Exception:
        return 0


def _download_chunk(url, start, end, chunk_path, progress, lock, log_func,
                    stop_flag):
    """下载文件的一个分块"""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Range": "bytes=%d-%d" % (start, end),
    }
    try:
        with requests.get(url, headers=headers, stream=True,
                          timeout=(10, READ_TIMEOUT), verify=False) as r:
            r.raise_for_status()
            with open(chunk_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if stop_flag.is_set():
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
                    with lock:
                        progress["done"] += len(chunk)
    except Exception as e:
        with lock:
            progress["error"] = str(e)
        stop_flag.set()


def _download_multithread(url, save_path, total_size, log_func):
    """多线程分块下载，返回 True/False"""
    if total_size <= 0:
        return False

    # 计算每个分块的大小
    chunk_size = total_size // THREADS
    ranges = []
    for i in range(THREADS):
        start = i * chunk_size
        end = start + chunk_size - 1 if i < THREADS - 1 else total_size - 1
        ranges.append((start, end))

    # 临时分块文件
    tmp_dir = save_path.parent / "_ffmpeg_chunks"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    progress = {"done": 0, "error": None}
    lock = threading.Lock()
    stop_flag = threading.Event()

    start_time = time.time()
    last_report = [0.0]

    def progress_reporter():
        while not stop_flag.is_set():
            time.sleep(PROGRESS_INTERVAL)
            with lock:
                done = progress["done"]
            elapsed = time.time() - start_time
            if elapsed <= 0:
                continue
            speed = done / elapsed
            if speed > 0:
                remain = (total_size - done) / speed
            else:
                remain = 0
            pct = done * 100 / total_size
            log_func("  进度 %.1f%% | %s/%s | %s/s | 剩余 %s" % (
                pct,
                _format_size(done),
                _format_size(total_size),
                _format_size(int(speed)) + "/s",
                _format_time(remain),
            ))

    reporter = threading.Thread(target=progress_reporter, daemon=True)
    reporter.start()

    threads = []
    chunk_files = []
    for i, (start, end) in enumerate(ranges):
        chunk_path = tmp_dir / ("part_%02d" % i)
        chunk_files.append(chunk_path)
        t = threading.Thread(
            target=_download_chunk,
            args=(url, start, end, chunk_path, progress, lock, log_func,
                  stop_flag),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # 等待所有线程完成
    for t in threads:
        t.join(timeout=SOURCE_TIMEOUT)

    stop_flag.set()
    time.sleep(PROGRESS_INTERVAL + 0.1)

    if progress["error"]:
        log_func("  分块下载失败: %s" % progress["error"])
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    with lock:
        done = progress["done"]
    if done < total_size:
        log_func("  文件不完整 (%s/%s)，放弃" % (
            _format_size(done), _format_size(total_size)))
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    # 合并分块
    log_func("  合并分块...")
    with open(save_path, "wb") as out:
        for chunk_path in chunk_files:
            with open(chunk_path, "rb") as f:
                shutil.copyfileobj(f, out, length=1024 * 1024)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    elapsed = time.time() - start_time
    avg_speed = total_size / elapsed if elapsed > 0 else 0
    log_func("  下载完成，用时 %.1fs，平均速度 %s/s" % (
        elapsed, _format_size(int(avg_speed))))

    return True


def _download_single(url, save_path, log_func):
    """单线程下载（兜底，用于不支持 Range 的服务器）"""
    headers = {"User-Agent": "Mozilla/5.0"}
    start_time = time.time()

    try:
        with requests.get(url, stream=True, timeout=(10, READ_TIMEOUT),
                          headers=headers, verify=False) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            last_report = 0.0

            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)

                    elapsed = time.time() - start_time
                    if elapsed > SOURCE_TIMEOUT:
                        log_func("  超时 %d 秒，放弃" % SOURCE_TIMEOUT)
                        return False

                    now = time.time()
                    if now - last_report >= PROGRESS_INTERVAL:
                        last_report = now
                        speed = done / elapsed if elapsed > 0 else 0
                        remain = (total - done) / speed if speed > 0 else 0
                        pct = done * 100 / total if total > 0 else 0
                        log_func("  进度 %.1f%% | %s/%s | %s/s | 剩余 %s" % (
                            pct,
                            _format_size(done),
                            _format_size(total),
                            _format_size(int(speed)) + "/s",
                            _format_time(remain),
                        ))

            if total > 0 and done < total:
                log_func("  文件不完整 (%d/%d)，放弃" % (done, total))
                return False

        return True

    except Exception as e:
        log_func("  下载失败: %s" % e)
        return False


def download_ffmpeg(log_func=print):
    if is_ffmpeg_ready():
        log_func("[OK] FFmpeg 已存在，无需下载。")
        return str(FFMPEG_DIR)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_DIR / "ffmpeg_download.zip"
    target_dir = FFMPEG_DIR

    last_error = None
    for i, url in enumerate(FFMPEG_URLS, 1):
        log_func("")
        log_func("[源 %d/%d] %s" % (i, len(FFMPEG_URLS), url.split("/")[2]))

        zip_path.unlink(missing_ok=True)

        # 获取文件大小
        total_size = _get_file_size(url)
        if total_size > 0:
            log_func("  文件大小: %s" % _format_size(total_size))
        else:
            log_func("  无法获取文件大小，使用单线程下载")

        # 优先多线程
        if total_size > 0:
            ok = _download_multithread(url, zip_path, total_size, log_func)
        else:
            ok = _download_single(url, zip_path, log_func)

        if not ok:
            zip_path.unlink(missing_ok=True)
            continue

        # 解压
        try:
            log_func("[解压] 正在解压...")
            temp_dir = DATA_DIR / "_ffmpeg_tmp"
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(temp_dir)

            bin_src = None
            for root, _dirs, files in os.walk(temp_dir):
                if ("ffmpeg.exe" in files) or ("ffmpeg" in files):
                    bin_src = Path(root)
                    break

            if bin_src is None:
                raise FileNotFoundError("压缩包中未找到 ffmpeg")

            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(bin_src), str(target_dir))

            shutil.rmtree(temp_dir, ignore_errors=True)
            zip_path.unlink(missing_ok=True)

            log_func("[完成] FFmpeg 安装完成: " + str(target_dir))
            return str(target_dir)

        except Exception as e:
            last_error = e
            log_func("[警告] 解压失败: %s" % e)
            zip_path.unlink(missing_ok=True)
            shutil.rmtree(DATA_DIR / "_ffmpeg_tmp", ignore_errors=True)
            continue

    raise RuntimeError("所有下载源均失败。最后错误: %s" % last_error)