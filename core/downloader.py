# -*- coding: utf-8 -*-
"""yt-dlp 下载 + 后处理调度"""

import os
import time
from pathlib import Path

import yt_dlp

from config.settings import COOKIES_FILE
from core.ffmpeg_manager import get_ffmpeg_exe, is_ffmpeg_ready
from core.audio_processor import process_audio
from core.aria2_manager import get_aria2_exe, is_aria2_ready


class DownloadError(Exception):
    pass


QUALITY_FORMAT_MAP = {
    "hires": "bestaudio[ext=m4a]/bestaudio/best",
    "standard": "bestaudio[ext=m4a]/bestaudio",
    "mp3": "bestaudio/best",
    "best": "bestaudio/best",
}


def _fmt_duration(sec):
    sec = int(sec)
    if sec < 60:
        return "%ds" % sec
    m, s = divmod(sec, 60)
    if m < 60:
        return "%dm%02ds" % (m, s)
    h, m = divmod(m, 60)
    return "%dh%02dm" % (h, m)


def download_and_process(url, save_dir, volume, quality,
                         use_pulse, irs_path, use_crossfeed,
                         crossfeed_strength,
                         normalize=False, target_lufs=-16.0,
                         log_func=print, config=None):
    if not is_ffmpeg_ready():
        raise DownloadError("FFmpeg 尚未就绪，请等待自动下载完成。")

    if config is None:
        from core.config_manager import load_config
        config = load_config()

    save_dir = os.path.abspath(save_dir)
    os.makedirs(save_dir, exist_ok=True)

    ffmpeg_exe = str(get_ffmpeg_exe())
    ffmpeg_dir = str(Path(ffmpeg_exe).parent)

    total_start = time.time()

    # ========== 任务配置 ==========
    log_func("任务配置", "section")
    log_func("  链接: %s" % url, "info")
    log_func("  保存到: %s" % save_dir, "info")
    log_func("  音量: %.2fx   码率: %skbps" % (volume, quality), "info")

    audio_quality = config.get("audio_quality", "hires")
    fmt = QUALITY_FORMAT_MAP.get(audio_quality, "bestaudio/best")
    log_func("  音质: %s" % audio_quality, "info")

    if normalize:
        log_func("  响度均衡: 开启 → 目标 %.1f LUFS" % target_lufs, "info")

    if use_pulse:
        log_func("  脉冲反馈: 开启", "info")
        log_func("  脉冲样本: %s" % os.path.basename(irs_path), "info")
        if use_crossfeed:
            log_func("  通道交叉: 开启（强度 %.2f）" % crossfeed_strength, "info")

    ydl_opts = {
        "format": fmt,
        "ffmpeg_location": ffmpeg_dir,
        "outtmpl": os.path.join(save_dir, "%(title)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": quality,
        }],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    # 下载引擎
    use_aria2 = config.get("use_aria2", False)
    if use_aria2 and is_aria2_ready():
        threads = str(int(config.get("aria2_threads", 16)))
        splits = str(int(config.get("aria2_splits", 16)))
        aria2_exe = str(get_aria2_exe())
        ydl_opts["external_downloader"] = aria2_exe
        ydl_opts["external_downloader_args"] = [
            "-x", threads, "-s", splits,
            "-k", "1M", "-c",
            "--console-log-level=warn",
            "--summary-interval=0",
        ]
        log_func("  引擎: aria2c (多线程 -x%s -s%s)" % (threads, splits), "info")
    else:
        log_func("  引擎: yt-dlp 内置", "info")

    # Cookie
    if COOKIES_FILE.exists():
        try:
            content = COOKIES_FILE.read_text(encoding="utf-8", errors="ignore")
            if "SESSDATA" in content:
                ydl_opts["cookiefile"] = str(COOKIES_FILE)
                log_func("  Cookie: cookies.txt（已登录）", "ok")
            else:
                log_func("  Cookie: cookies.txt 无效（无 SESSDATA）", "warn")
        except Exception as e:
            log_func("  Cookie: 读取失败 (%s)" % e, "warn")
    else:
        log_func("  Cookie: 未配置（Hi-Res 不可用）", "warn")

    # ========== 阶段 1：下载 ==========
    log_func("下载音频", "section")
    t0 = time.time()
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            raw_path = ydl.prepare_filename(info)
            base, _ = os.path.splitext(raw_path)
    except Exception as e:
        raise DownloadError("下载失败: %s" % e)

    dt_download = time.time() - t0

    title = info.get("title") or "(未知标题)"
    log_func("  ✓ %s" % title, "ok")
    log_func("  下载完成，耗时 %s" % _fmt_duration(dt_download), "info")

    mp3_path = base + ".mp3"
    if not os.path.exists(mp3_path):
        for ext in (".mp3", ".m4a", ".opus", ".webm", ".flac", ".aac"):
            p = base + ext
            if os.path.exists(p):
                mp3_path = p
                break

    if not os.path.exists(mp3_path):
        raise DownloadError("未找到生成的音频文件")

    # ========== 阶段 2：后处理 ==========
    need_volume = abs(volume - 1.0) > 1e-6
    need_pulse = use_pulse and bool(irs_path) and os.path.exists(irs_path)
    need_crossfeed = use_crossfeed and crossfeed_strength > 0.01
    need_normalize = normalize
    need_reencode = (mp3_path != base + ".mp3")

    has_post = (need_volume or need_pulse or need_crossfeed
                or need_normalize or need_reencode)

    final_path = base + ".mp3"

    if has_post:
        log_func("后处理", "section")

        steps = []
        if need_normalize:
            steps.append("响度均衡")
        if need_volume:
            steps.append("音量 %.2fx" % volume)
        if need_pulse:
            steps.append("脉冲反馈")
        if need_crossfeed:
            steps.append("通道交叉")
        if need_reencode:
            steps.append("重编码")
        if steps:
            log_func("  处理项: %s" % " → ".join(steps), "info")

        t1 = time.time()
        tmp_path = base + "_fx.mp3"

        try:
            process_audio(
                ffmpeg_exe=ffmpeg_exe,
                input_mp3=mp3_path,
                output_mp3=tmp_path,
                volume=volume,
                quality=quality,
                irs_path=irs_path if need_pulse else None,
                use_crossfeed=need_crossfeed,
                crossfeed_strength=crossfeed_strength,
                normalize=need_normalize,
                target_lufs=target_lufs,
                log_func=log_func,
            )
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise DownloadError("后处理失败: %s" % e)

        dt_post = time.time() - t1

        if mp3_path != final_path and os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except Exception:
                pass

        os.replace(tmp_path, final_path)

        log_func("  后处理完成，耗时 %s" % _fmt_duration(dt_post), "info")
    else:
        log_func("无需后处理", "section")
        log_func("  音频已就绪", "info")

    # ========== 完成 ==========
    total_dt = time.time() - total_start
    log_func("完成", "section")
    log_func("  📁 %s" % os.path.basename(final_path), "ok")
    log_func("  ⏱ 总耗时 %s" % _fmt_duration(total_dt), "info")

    return final_path
