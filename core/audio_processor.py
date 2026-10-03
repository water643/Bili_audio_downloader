# -*- coding: utf-8 -*-
"""音频后处理：音量、脉冲卷积、通道交叉、响度均衡(两遍 loudnorm)"""

import os
import re
import json
import tempfile
import subprocess
from pathlib import Path

from config.settings import (
    SAMPLE_RATE, AFIR_DRY, AFIR_WET,
    CROSSFEED_RANGE, CROSSFEED_SLOPE,
)

FFMPEG_TIMEOUT = 900


def _no_window_flags():
    if os.name == "nt":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _run_ffmpeg(cmd, log_func=None, capture_stderr=False):
    stderr_path = None
    try:
        fd, stderr_path = tempfile.mkstemp(prefix="ffmpeg_stderr_", suffix=".log")
        os.close(fd)

        with open(stderr_path, "wb") as err_f:
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=err_f,
                timeout=FFMPEG_TIMEOUT,
                creationflags=_no_window_flags(),
            )

        try:
            err_text = Path(stderr_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            err_text = ""

        if capture_stderr:
            return result.returncode, err_text

        if result.returncode != 0:
            tail = err_text[-2000:] if len(err_text) > 2000 else err_text
            raise RuntimeError("FFmpeg 返回码 %d\n%s" % (result.returncode, tail))
        return result.returncode

    except subprocess.TimeoutExpired:
        raise RuntimeError("FFmpeg 超时（超过 %d 秒）" % FFMPEG_TIMEOUT)
    finally:
        if stderr_path and os.path.exists(stderr_path):
            try:
                os.remove(stderr_path)
            except Exception:
                pass


def measure_loudness(ffmpeg_exe, input_file, target_lufs, log_func=None):
    """第一遍：测量输入音频的响度"""
    filter_str = "loudnorm=I=%.1f:TP=-1.5:LRA=11:print_format=json" % target_lufs
    cmd = [
        ffmpeg_exe, "-y",
        "-i", input_file,
        "-af", filter_str,
        "-f", "null", "-",
    ]

    if log_func:
        log_func("  [1/2] 分析响度中...", "progress")

    rc, err_text = _run_ffmpeg(cmd, log_func=log_func, capture_stderr=True)

    if rc != 0:
        if log_func:
            log_func("  [1/2] 测量失败，退回单遍模式", "warn")
        return None

    matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', err_text, re.DOTALL)
    if not matches:
        if log_func:
            log_func("  [1/2] 未解析到测量数据，退回单遍模式", "warn")
        return None

    try:
        data = json.loads(matches[-1])
    except Exception as e:
        if log_func:
            log_func("  [1/2] JSON 解析失败: %s" % e, "warn")
        return None

    required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    if not all(k in data for k in required):
        if log_func:
            log_func("  [1/2] 测量数据不完整，退回单遍模式", "warn")
        return None

    if log_func:
        log_func("  [1/2] 源音频 %.2f LUFS / 峰值 %.2f dBTP / 动态 %.2f LU" % (
            float(data["input_i"]),
            float(data["input_tp"]),
            float(data["input_lra"]),
        ), "info")

    return data


def build_loudnorm_filter(target_lufs, measurements):
    if not measurements:
        return "loudnorm=I=%.1f:TP=-1.5:LRA=11:print_format=none" % target_lufs

    return (
        "loudnorm=I=%.1f:TP=-1.5:LRA=11"
        ":measured_I=%s:measured_TP=%s:measured_LRA=%s"
        ":measured_thresh=%s:offset=%s"
        ":linear=true:print_format=none"
    ) % (
        target_lufs,
        measurements["input_i"],
        measurements["input_tp"],
        measurements["input_lra"],
        measurements["input_thresh"],
        measurements["target_offset"],
    )


def build_filter_chain(volume, use_crossfeed, crossfeed_strength,
                       normalize=False, target_lufs=-16.0,
                       measurements=None):
    filters = []

    if normalize:
        filters.append(build_loudnorm_filter(target_lufs, measurements))

    if abs(volume - 1.0) > 1e-6:
        filters.append("volume=%.4f" % volume)

    if use_crossfeed and crossfeed_strength > 0.01:
        filters.append(
            "crossfeed=strength=%.4f:range=%s:slope=%s" % (
                crossfeed_strength, CROSSFEED_RANGE, CROSSFEED_SLOPE)
        )
    return filters


def build_pulse_filter_complex(volume, use_crossfeed, crossfeed_strength,
                               normalize=False, target_lufs=-16.0,
                               measurements=None):
    chain = "[0:a]aresample=%d" % SAMPLE_RATE
    if normalize:
        chain += "," + build_loudnorm_filter(target_lufs, measurements)
    if abs(volume - 1.0) > 1e-6:
        chain += ",volume=%.4f" % volume
    if use_crossfeed and crossfeed_strength > 0.01:
        chain += (
            ",crossfeed=strength=%.4f:range=%s:slope=%s" % (
                crossfeed_strength, CROSSFEED_RANGE, CROSSFEED_SLOPE)
        )
    chain += "[a];"

    return (
        chain
        + "[1:a]aresample=%d[ir];" % SAMPLE_RATE
        + "[a][ir]afir=dry=%s:wet=%s[out]" % (AFIR_DRY, AFIR_WET)
    )


def process_audio(ffmpeg_exe, input_mp3, output_mp3,
                  volume, quality, irs_path=None,
                  use_crossfeed=False, crossfeed_strength=0.0,
                  normalize=False, target_lufs=-16.0,
                  log_func=None):
    need_pulse = bool(irs_path) and Path(irs_path).exists()

    measurements = None
    if normalize:
        measurements = measure_loudness(
            ffmpeg_exe, input_mp3, target_lufs, log_func=log_func
        )

    if log_func:
        log_func("  [2/2] 编码中...", "progress")

    common = ["-threads", "0", "-y"]

    if need_pulse:
        filter_expr = build_pulse_filter_complex(
            volume, use_crossfeed, crossfeed_strength,
            normalize, target_lufs, measurements
        )
        cmd = [ffmpeg_exe] + common + [
            "-i", input_mp3,
            "-i", irs_path,
            "-filter_complex", filter_expr,
            "-map", "[out]",
            "-c:a", "libmp3lame",
            "-b:a", quality + "k",
            output_mp3,
        ]
    else:
        filters = build_filter_chain(
            volume, use_crossfeed, crossfeed_strength,
            normalize, target_lufs, measurements
        )
        cmd = [ffmpeg_exe] + common + [
            "-i", input_mp3,
            "-af", ",".join(filters),
            "-c:a", "libmp3lame",
            "-b:a", quality + "k",
            output_mp3,
        ]

    _run_ffmpeg(cmd, log_func=log_func)
