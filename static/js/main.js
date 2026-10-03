var $ = function(id) { return document.getElementById(id); };

var logSince = 0;
var pollTimer = null;
var ffmpegReady = false;
var userConfig = null;
var lastPlayPath = "";
var __startingDownload = false;

// 后端存活检测
var __statusFailCount = 0;
var SERVER_DOWN_THRESHOLD = 4;  // 连续失败 4 次（约 12 秒）
var __serverDownHandled = false;

var LS_KEY = "bili_audio_ui_state";

function loadUIState() {
    try {
        var raw = localStorage.getItem(LS_KEY);
        if (!raw) return {};
        return JSON.parse(raw) || {};
    } catch (e) {
        return {};
    }
}

function saveUIState(patch) {
    try {
        var s = loadUIState();
        for (var k in patch) {
            if (patch.hasOwnProperty(k)) {
                s[k] = patch[k];
            }
        }
        localStorage.setItem(LS_KEY, JSON.stringify(s));
    } catch (e) {}
}

function isValidBiliUrl(url) {
    if (!url) return false;
    var u = url.toLowerCase();
    return u.indexOf("bilibili.com") >= 0 || u.indexOf("b23.tv") >= 0;
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(2) + " MB";
}

/* ============ 后端关闭处理 ============ */
function handleServerDown() {
    // 停止所有轮询
    stopLogPolling();
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

    // 显示遮罩
    showServerDownOverlay();

    // 尝试关闭窗口（大多数浏览器会拒绝，遮罩作为兜底）
    setTimeout(function() {
        try {
            window.close();
        } catch (e) {}
    }, 300);
}

function showServerDownOverlay() {
    if ($("serverDownOverlay")) return;

    var overlay = document.createElement("div");
    overlay.id = "serverDownOverlay";

    var box = document.createElement("div");
    box.className = "server-down-box";

    var icon = document.createElement("div");
    icon.className = "server-down-icon";
    icon.textContent = "⏻";

    var title = document.createElement("div");
    title.className = "server-down-title";
    title.textContent = "服务已关闭";

    var msg = document.createElement("div");
    msg.className = "server-down-msg";
    msg.textContent = "后端服务已停止运行，此页面即将关闭";

    var btn = document.createElement("button");
    btn.className = "btn-primary";
    btn.textContent = "立即关闭";
    btn.onclick = function() {
        try { window.close(); } catch (e) {}
        // 如果关不掉，给个提示
        btn.textContent = "请手动关闭标签页 (Ctrl+W)";
    };

    box.appendChild(icon);
    box.appendChild(title);
    box.appendChild(msg);
    box.appendChild(btn);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
}

/* ============ 日志 ============ */
function appendLogs(entries) {
    var el = $("log");
    if (!el) return;
    for (var i = 0; i < entries.length; i++) {
        var e = entries[i];
        var line = document.createElement("div");
        line.className = "log-line log-" + (e.level || "info");

        var ts = document.createElement("span");
        ts.className = "log-ts";
        ts.textContent = e.ts || "";

        var msg = document.createElement("span");
        msg.className = "log-msg";
        msg.textContent = e.msg || String(e);

        line.appendChild(ts);
        line.appendChild(msg);
        el.appendChild(line);
    }
    el.scrollTop = el.scrollHeight;
}

function pollLogs() {
    if (__serverDownHandled) return;
    fetch("/api/logs?since=" + logSince)
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.logs && data.logs.length > 0) {
                appendLogs(data.logs);
                logSince = data.total;
            }
        })
        .catch(function() {});
}

function startLogPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(pollLogs, 800);
}

function stopLogPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function updateStartButton(running) {
    var btn = $("startBtn");
    if (!btn) return;
    if (running) {
        btn.disabled = true;
        btn.textContent = "处理中...";
    } else {
        btn.disabled = !ffmpegReady;
        btn.textContent = "开始下载";
    }
    var installBtn = $("installFfmpegBtn");
    if (installBtn) {
        installBtn.style.display = ffmpegReady ? "none" : "inline-block";
    }
}

function applyLocalUIState() {
    var s = loadUIState();

    if (typeof s.volume === "number" && $("volume")) {
        $("volume").value = s.volume;
        if ($("volumeLabel")) {
            $("volumeLabel").textContent = s.volume.toFixed(2) + "x";
        }
    }
    if (s.quality) {
        var qRadios = document.querySelectorAll('input[name="quality"]');
        for (var i = 0; i < qRadios.length; i++) {
            qRadios[i].checked = (qRadios[i].value === s.quality);
        }
    }
    if (typeof s.normalize === "boolean" && $("normalize")) {
        $("normalize").checked = s.normalize;
        if ($("lufsField")) {
            $("lufsField").style.display = s.normalize ? "block" : "none";
        }
    }
    if (typeof s.target_lufs === "number" && $("targetLufs")) {
        $("targetLufs").value = s.target_lufs;
        if ($("targetLufsLabel")) {
            $("targetLufsLabel").textContent = s.target_lufs.toFixed(1);
        }
    }
    if (typeof s.enable_pulse === "boolean" && $("enablePulse")) {
        $("enablePulse").checked = s.enable_pulse;
        if ($("pulseOptions")) {
            $("pulseOptions").style.display = s.enable_pulse ? "block" : "none";
        }
    }
    if (typeof s.crossfeed === "number" && $("crossfeed")) {
        $("crossfeed").value = s.crossfeed;
        if ($("crossfeedLabel")) {
            $("crossfeedLabel").textContent = s.crossfeed.toFixed(2);
        }
    }
    if (s.save_dir && $("saveDir") && !$("saveDir").value) {
        $("saveDir").value = s.save_dir;
    }
}

function checkStatus() {
    if (__serverDownHandled) return;

    fetch("/api/status")
        .then(function(res) {
            if (!res.ok) throw new Error("HTTP " + res.status);
            return res.json();
        })
        .then(function(data) {
            // 成功：重置失败计数
            __statusFailCount = 0;

            ffmpegReady = !!data.ffmpeg_ready;

            var el = $("ffmpegStatus");
            if (el) {
                if (ffmpegReady) {
                    el.className = "ffmpeg-status ready";
                    el.querySelector(".text").textContent = "FFmpeg 就绪";
                } else {
                    el.className = "ffmpeg-status";
                    el.querySelector(".text").textContent = "FFmpeg 未就绪";
                }
            }

            updateStartButton(!!data.task_running);

            if (data.task_running) {
                startLogPolling();
            } else {
                stopLogPolling();
            }

            if (data.result) {
                showPlaySection(data.result);
            }

            if (data.config && !window.__cfgApplied) {
                window.__cfgApplied = true;
                userConfig = data.config;

                var s = loadUIState();

                if (!s.save_dir && data.config.default_save_dir && $("saveDir")) {
                    if (!$("saveDir").value) {
                        $("saveDir").value = data.config.default_save_dir;
                    }
                }
                if (typeof s.volume !== "number" && data.config.default_volume && $("volume")) {
                    $("volume").value = data.config.default_volume;
                    if ($("volumeLabel")) {
                        $("volumeLabel").textContent = parseFloat(data.config.default_volume).toFixed(2) + "x";
                    }
                }
                if (!s.quality && data.config.default_quality) {
                    var qRadios = document.querySelectorAll('input[name="quality"]');
                    for (var i = 0; i < qRadios.length; i++) {
                        qRadios[i].checked = (qRadios[i].value === data.config.default_quality);
                    }
                }
                if (typeof s.target_lufs !== "number" && data.config.default_target_lufs && $("targetLufs")) {
                    $("targetLufs").value = data.config.default_target_lufs;
                    if ($("targetLufsLabel")) {
                        $("targetLufsLabel").textContent = parseFloat(data.config.default_target_lufs).toFixed(1);
                    }
                }
            }
        })
        .catch(function(err) {
            __statusFailCount++;
            console.warn("[checkStatus] 失败 (" + __statusFailCount + "/" + SERVER_DOWN_THRESHOLD + "):", err && err.message ? err.message : err);

            if (__statusFailCount >= SERVER_DOWN_THRESHOLD && !__serverDownHandled) {
                __serverDownHandled = true;
                console.warn("[checkStatus] 后端已关闭，即将关闭页面");
                handleServerDown();
            }
        });
}

function togglePulseOptions() {
    var enablePulseCheck = $("enablePulse");
    var pulseOptions = $("pulseOptions");
    if (!enablePulseCheck || !pulseOptions) return;
    pulseOptions.style.display = enablePulseCheck.checked ? "block" : "none";
}

function showPlaySection(path) {
    if (!path) return;
    if (lastPlayPath === path) return;
    lastPlayPath = path;

    var card = $("playCard");
    var player = $("playPlayer");
    var titleEl = $("playTitle");
    var hint = $("playHint");
    var dlLink = $("playDownloadLink");
    if (!card) return;

    card.style.display = "block";
    var fname = path.replace(/\\/g, "/").split("/").pop();
    titleEl.textContent = fname;
    hint.className = "file-hint";
    hint.textContent = "正在准备播放...";

    fetch("/api/play_token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path }),
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (!data.ok) {
            hint.className = "file-hint err";
            hint.textContent = "无法播放: " + (data.msg || "未知错误");
            return;
        }
        player.src = "/api/play_stream?token=" + data.token;
        player.load();
        dlLink.href = "/api/play_stream?token=" + data.token;
        dlLink.download = data.name || fname;
        dlLink.style.display = "inline-block";
        hint.className = "file-hint ok";
        hint.textContent = "点下方播放按钮试听";
        var p = player.play();
        if (p && p.catch) {
            p.catch(function() {
                hint.className = "file-hint";
                hint.textContent = "浏览器阻止了自动播放，请点播放按钮";
            });
        }
    })
    .catch(function(e) {
        hint.className = "file-hint err";
        hint.textContent = "请求失败: " + e;
    });
}

function closePlaySection() {
    var card = $("playCard");
    var player = $("playPlayer");
    if (!card) return;
    try {
        player.pause();
        player.removeAttribute("src");
        player.load();
    } catch (e) {}
    card.style.display = "none";
    lastPlayPath = "";
}

function startDownload() {
    if (__startingDownload) return;
    if (__serverDownHandled) {
        alert("后端服务已关闭，请重新启动 python app.py");
        return;
    }

    var url = $("url").value.trim();
    if (!isValidBiliUrl(url)) {
        alert("请输入有效的 B站视频链接\n\n支持格式:\n- https://www.bilibili.com/video/BV...\n- https://b23.tv/xxxxxx");
        return;
    }

    if (!ffmpegReady) {
        alert("FFmpeg 尚未就绪，请等待自动下载完成");
        return;
    }

    var qualityEl = document.querySelector('input[name="quality"]:checked');
    var quality = qualityEl ? qualityEl.value : "192";

    var normalizeEl = $("normalize");
    var targetLufsEl = $("targetLufs");
    var enablePulseEl = $("enablePulse");
    var irsPathEl = $("irsPath");
    var crossfeedEl = $("crossfeed");
    var volEl = $("volume");

    var usePulse = enablePulseEl ? enablePulseEl.checked : false;
    var useCrossfeed = usePulse;

    var curVolume = volEl ? parseFloat(volEl.value) : 1.0;
    var curNormalize = normalizeEl ? normalizeEl.checked : false;
    var curTargetLufs = targetLufsEl ? parseFloat(targetLufsEl.value) : -16.0;
    var curCrossfeed = crossfeedEl ? parseFloat(crossfeedEl.value) : 0.3;
    var curSaveDir = $("saveDir").value.trim();

    saveUIState({
        volume: curVolume, quality: quality,
        normalize: curNormalize, target_lufs: curTargetLufs,
        enable_pulse: usePulse, crossfeed: curCrossfeed,
        save_dir: curSaveDir
    });

    var payload = {
        url: url, save_dir: curSaveDir, volume: curVolume,
        quality: quality, use_pulse: usePulse,
        irs_path: irsPathEl ? irsPathEl.value.trim() : "",
        use_crossfeed: useCrossfeed,
        crossfeed_strength: curCrossfeed,
        normalize: curNormalize, target_lufs: curTargetLufs,
    };

    if (payload.use_pulse && !payload.irs_path) {
        alert("请先选择脉冲样本文件");
        return;
    }

    __startingDownload = true;
    console.log("[startDownload] payload:", JSON.stringify(payload));
    closePlaySection();

    var btn = $("startBtn");
    btn.disabled = true;
    btn.textContent = "提交中...";

    var resetTimer = setTimeout(function() {
        __startingDownload = false;
        updateStartButton(false);
    }, 10000);

    function unlock() {
        clearTimeout(resetTimer);
        __startingDownload = false;
    }

    fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    })
    .then(function(res) {
        return res.json().then(function(d) {
            return { status: res.status, data: d };
        });
    })
    .then(function(r) {
        unlock();
        if (!r.data.ok) {
            var msg = r.data.msg || "启动失败";
            if (r.data.can_reset) {
                if (confirm(msg + "\n\n是否重置任务状态？")) {
                    resetTask();
                }
            } else {
                alert(msg);
            }
            updateStartButton(false);
            return;
        }
        startLogPolling();
        setTimeout(checkStatus, 500);
    })
    .catch(function(e) {
        unlock();
        alert("请求失败: " + e);
        updateStartButton(false);
    });
}

function resetTask() {
    fetch("/api/task/reset", { method: "POST" })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            alert(data.msg || "已重置");
            __startingDownload = false;
            updateStartButton(false);
            checkStatus();
        })
        .catch(function(e) { alert("重置失败: " + e); });
}

function installFFmpeg() {
    fetch("/api/ffmpeg/install", { method: "POST" })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            alert(data.msg || "已请求");
            startLogPolling();
        })
        .catch(function(e) { alert("请求失败: " + e); });
}

function clearLog() {
    var el = $("log");
    if (el) el.textContent = "";
    logSince = 0;
}

function pasteUrlFromClipboard() {
    var urlInput = $("url");
    if (!urlInput) return;

    if (navigator.clipboard && navigator.clipboard.readText) {
        navigator.clipboard.readText()
            .then(function(text) { handlePastedText(text, urlInput); })
            .catch(function(err) {
                console.warn("clipboard.readText 失败:", err);
                fallbackManualPaste(urlInput);
            });
    } else {
        fallbackManualPaste(urlInput);
    }
}

function fallbackManualPaste(urlInput) {
    urlInput.focus();
    urlInput.select();
    alert("浏览器不允许自动读取剪贴板。\n\n输入框已聚焦，请按 Ctrl+V 手动粘贴。");
}

function handlePastedText(text, urlInput) {
    if (!text || !text.trim()) { alert("剪贴板为空"); return; }
    text = text.trim();
    var patterns = [
        /https?:\/\/b23\.tv\/[A-Za-z0-9]+/,
        /https?:\/\/www\.bilibili\.com\/video\/[A-Za-z0-9]+/,
        /https?:\/\/bilibili\.com\/video\/[A-Za-z0-9]+/,
        /https?:\/\/[A-Za-z0-9\-._~:\/?#\[\]@!$&'()*+,;=%]+/
    ];
    for (var i = 0; i < patterns.length; i++) {
        var m = text.match(patterns[i]);
        if (m) { urlInput.value = m[0]; return; }
    }
    urlInput.value = text;
}

function chooseIrsFile() {
    var input = $("irsFileInput");
    if (input) input.click();
}

function onIrsFileSelected() {
    var input = $("irsFileInput");
    var file = input.files[0];
    if (!file) return;

    var hint = $("irsHint");
    hint.className = "file-hint";
    hint.textContent = "正在上传 " + file.name + " ...";

    var formData = new FormData();
    formData.append("file", file);

    fetch("/api/upload_irs", { method: "POST", body: formData })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (data.ok) {
            $("irsPath").value = data.path;
            hint.className = "file-hint ok";
            hint.textContent = "已上传: " + data.name;
        } else {
            hint.className = "file-hint err";
            hint.textContent = "上传失败: " + (data.msg || "未知错误");
            $("irsPath").value = "";
        }
    })
    .catch(function(e) {
        hint.className = "file-hint err";
        hint.textContent = "上传失败: " + e;
        $("irsPath").value = "";
    });

    input.value = "";
}

function scanIrsFiles() {
    var listEl = $("irsList");
    var bodyEl = $("irsListBody");
    var countEl = $("irsListCount");
    var titleEl = $("irsListTitle");
    var hint = $("irsHint");

    hint.className = "file-hint";
    hint.textContent = "正在扫描 VIPER 目录...";

    fetch("/api/scan_irs")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (!data.ok) {
                hint.className = "file-hint err";
                hint.textContent = "扫描失败: " + (data.msg || "未知错误");
                return;
            }
            countEl.textContent = data.count + " 个";
            titleEl.textContent = "VIPER 目录: " + data.dir;

            while (bodyEl.firstChild) bodyEl.removeChild(bodyEl.firstChild);

            if (data.count === 0) {
                var empty = document.createElement("div");
                empty.className = "irs-list-empty";
                empty.textContent = "VIPER 目录下没有 .irs 或 .wav 文件";
                bodyEl.appendChild(empty);
            } else {
                for (var i = 0; i < data.files.length; i++) {
                    (function(f) {
                        var item = document.createElement("div");
                        item.className = "irs-list-item";
                        item.setAttribute("data-path", f.path);

                        var nameEl = document.createElement("div");
                        nameEl.className = "irs-item-name";
                        nameEl.textContent = f.rel;
                        nameEl.title = f.rel;

                        var sizeEl = document.createElement("div");
                        sizeEl.className = "irs-item-size";
                        sizeEl.textContent = formatSize(f.size);

                        item.appendChild(nameEl);
                        item.appendChild(sizeEl);

                        item.addEventListener("click", function() {
                            $("irsPath").value = f.path;
                            hint.className = "file-hint ok";
                            hint.textContent = "已选择: " + f.rel;
                            var items = bodyEl.querySelectorAll(".irs-list-item");
                            for (var j = 0; j < items.length; j++) {
                                items[j].classList.remove("selected");
                            }
                            item.classList.add("selected");
                        });

                        bodyEl.appendChild(item);
                    })(data.files[i]);
                }
            }
            listEl.style.display = "flex";
            hint.className = "file-hint";
            hint.textContent = "共找到 " + data.count + " 个文件，点击列表项选择";
        })
        .catch(function(e) {
            hint.className = "file-hint err";
            hint.textContent = "扫描失败: " + e;
        });
}

document.addEventListener("DOMContentLoaded", function() {
    applyLocalUIState();

    var volume = $("volume");
    if (volume) {
        volume.addEventListener("input", function() {
            var v = parseFloat(volume.value);
            $("volumeLabel").textContent = v.toFixed(2) + "x";
            saveUIState({ volume: v });
        });
    }

    var quickBtns = document.querySelectorAll("[data-vol]");
    for (var i = 0; i < quickBtns.length; i++) {
        quickBtns[i].addEventListener("click", function() {
            var v = parseFloat(this.getAttribute("data-vol"));
            volume.value = v;
            $("volumeLabel").textContent = v.toFixed(2) + "x";
            saveUIState({ volume: v });
        });
    }

    var cf = $("crossfeed");
    if (cf) {
        cf.addEventListener("input", function() {
            var v = parseFloat(cf.value);
            $("crossfeedLabel").textContent = v.toFixed(2);
            saveUIState({ crossfeed: v });
        });
    }

    var normalizeCheck = $("normalize");
    var lufsField = $("lufsField");
    if (normalizeCheck && lufsField) {
        normalizeCheck.addEventListener("change", function() {
            lufsField.style.display = normalizeCheck.checked ? "block" : "none";
            saveUIState({ normalize: normalizeCheck.checked });
        });
    }

    var targetLufs = $("targetLufs");
    if (targetLufs) {
        targetLufs.addEventListener("input", function() {
            var v = parseFloat(targetLufs.value);
            $("targetLufsLabel").textContent = v.toFixed(1);
            saveUIState({ target_lufs: v });
        });
    }

    var qRadios = document.querySelectorAll('input[name="quality"]');
    for (var j = 0; j < qRadios.length; j++) {
        qRadios[j].addEventListener("change", function() {
            saveUIState({ quality: this.value });
        });
    }

    var enablePulseCheck = $("enablePulse");
    if (enablePulseCheck) {
        enablePulseCheck.addEventListener("change", function() {
            togglePulseOptions();
            saveUIState({ enable_pulse: enablePulseCheck.checked });
        });
    }

    var saveDirEl = $("saveDir");
    if (saveDirEl) {
        saveDirEl.addEventListener("change", function() {
            saveUIState({ save_dir: saveDirEl.value.trim() });
        });
    }

    function bindClick(id, handler) {
        var el = $(id);
        if (!el) return;
        if (el.getAttribute("onclick")) return;
        el.addEventListener("click", handler);
    }

    bindClick("startBtn", startDownload);
    bindClick("resetTaskBtn", resetTask);
    bindClick("installFfmpegBtn", installFFmpeg);
    bindClick("clearLogBtn", clearLog);
    bindClick("pasteUrlBtn", pasteUrlFromClipboard);
    bindClick("chooseIrsBtn", chooseIrsFile);
    bindClick("scanIrsBtn", scanIrsFiles);

    var fileInput = $("irsFileInput");
    if (fileInput) { fileInput.addEventListener("change", onIrsFileSelected); }

    togglePulseOptions();

    checkStatus();
    setInterval(checkStatus, 3000);
});

/* ============ 批量下载 ============ */
var __batchVideos = [];

function isBatchUrl(url) {
    if (!url) return false;
    var u = url.toLowerCase();
    var pats = [
        "space.bilibili.com", "medialist/detail", "medialist/play",
        "/list/", "channel/seriesdetail", "/lists"
    ];
    for (var i = 0; i < pats.length; i++) {
        if (u.indexOf(pats[i]) >= 0) return true;
    }
    return false;
}

function parseBatch() {
    var url = $("url").value.trim();
    if (!url) { alert("请先输入收藏夹链接"); return; }
    if (!isBatchUrl(url)) {
        alert("不是收藏夹/合集链接");
        return;
    }

    var hint = $("urlHint");
    hint.className = "file-hint";
    hint.textContent = "正在解析收藏夹...";

    fetch("/api/batch/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url }),
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (!data.ok) {
            hint.className = "file-hint err";
            hint.textContent = data.msg || "解析失败";
            return;
        }

        __batchVideos = data.videos || [];
        renderBatchList(data.title, data.uploader, __batchVideos);

        hint.className = "file-hint ok";
        hint.textContent = "已解析 " + data.count + " 个视频";
    })
    .catch(function(e) {
        hint.className = "file-hint err";
        hint.textContent = "请求失败: " + e;
    });
}

function renderBatchList(title, uploader, videos) {
    var card = $("batchCard");
    var titleEl = $("batchTitle");
    var metaEl = $("batchMeta");
    var listEl = $("batchList");
    var hint = $("batchHint");

    card.style.display = "block";
    titleEl.textContent = title || "收藏夹";

    var totalDur = 0;
    for (var i = 0; i < videos.length; i++) {
        totalDur += videos[i].duration || 0;
    }

    var parts = [];
    if (uploader) parts.push(uploader);
    parts.push(videos.length + " 个视频");
    if (totalDur > 0) parts.push("总时长 " + fmtDur(totalDur));
    metaEl.textContent = parts.join("  ·  ");

    listEl.innerHTML = "";
    for (var j = 0; j < videos.length; j++) {
        (function(v, idx) {
            var item = document.createElement("label");
            item.className = "batch-item";

            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = true;
            cb.setAttribute("data-idx", idx);
            cb.addEventListener("change", updateBatchCount);

            var info = document.createElement("div");
            info.className = "batch-item-info";

            var t = document.createElement("div");
            t.className = "batch-item-title";
            t.textContent = (idx + 1) + ". " + (v.title || "(无标题)");
            t.title = v.title;

            var m = document.createElement("div");
            m.className = "batch-item-meta";
            m.textContent = v.duration ? fmtDur(v.duration) : "";

            info.appendChild(t);
            info.appendChild(m);

            item.appendChild(cb);
            item.appendChild(info);
            listEl.appendChild(item);
        })(videos[j], j);
    }

    updateBatchCount();
}

function fmtDur(sec) {
    sec = Math.floor(sec);
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    if (m < 60) return m + ":" + (s < 10 ? "0" : "") + s;
    var h = Math.floor(m / 60);
    m = m % 60;
    return h + ":" + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
}

function updateBatchCount() {
    var boxes = document.querySelectorAll("#batchList input[type=checkbox]");
    var checked = 0;
    for (var i = 0; i < boxes.length; i++) {
        if (boxes[i].checked) checked++;
    }
    $("batchHint").textContent = "已选 " + checked + " / " + boxes.length + " 个视频";
}

function getBatchSelected() {
    var boxes = document.querySelectorAll("#batchList input[type=checkbox]");
    var selected = [];
    for (var i = 0; i < boxes.length; i++) {
        if (boxes[i].checked) {
            var idx = parseInt(boxes[i].getAttribute("data-idx"), 10);
            if (__batchVideos[idx]) selected.push(__batchVideos[idx]);
        }
    }
    return selected;
}

function batchSelectAll(flag) {
    var boxes = document.querySelectorAll("#batchList input[type=checkbox]");
    for (var i = 0; i < boxes.length; i++) {
        boxes[i].checked = flag;
    }
    updateBatchCount();
}

/* ============ 修改 startDownload 支持批量 ============ */
function startDownload() {
    if (__startingDownload) return;
    if (__serverDownHandled) {
        alert("后端服务已关闭，请重新启动 python app.py");
        return;
    }

    var url = $("url").value.trim();
    var isBatch = isBatchUrl(url) && __batchVideos.length > 0;

    if (!isBatch) {
        // 单曲流程，沿用原逻辑
        if (!isValidBiliUrl(url)) {
            alert("请输入有效的 B站视频链接");
            return;
        }
    }

    if (!ffmpegReady) {
        alert("FFmpeg 尚未就绪");
        return;
    }

    var qualityEl = document.querySelector('input[name="quality"]:checked');
    var quality = qualityEl ? qualityEl.value : "192";

    var normalizeEl = $("normalize");
    var targetLufsEl = $("targetLufs");
    var enablePulseEl = $("enablePulse");
    var irsPathEl = $("irsPath");
    var crossfeedEl = $("crossfeed");
    var volEl = $("volume");

    var usePulse = enablePulseEl ? enablePulseEl.checked : false;
    var useCrossfeed = usePulse;

    var curVolume = volEl ? parseFloat(volEl.value) : 1.0;
    var curNormalize = normalizeEl ? normalizeEl.checked : false;
    var curTargetLufs = targetLufsEl ? parseFloat(targetLufsEl.value) : -16.0;
    var curCrossfeed = crossfeedEl ? parseFloat(crossfeedEl.value) : 0.3;
    var curSaveDir = $("saveDir").value.trim();

    var payload = {
        save_dir: curSaveDir, volume: curVolume, quality: quality,
        use_pulse: usePulse,
        irs_path: irsPathEl ? irsPathEl.value.trim() : "",
        use_crossfeed: useCrossfeed,
        crossfeed_strength: curCrossfeed,
        normalize: curNormalize, target_lufs: curTargetLufs,
    };

    if (payload.use_pulse && !payload.irs_path) {
        alert("请先选择脉冲样本文件");
        return;
    }

    __startingDownload = true;

    var endpoint;
    if (isBatch) {
        var selected = getBatchSelected();
        if (selected.length === 0) {
            __startingDownload = false;
            alert("请至少勾选一个视频");
            return;
        }
        payload.videos = selected;
        endpoint = "/api/batch/download";
        console.log("[startDownload] 批量模式，共 " + selected.length + " 个视频");
    } else {
        payload.url = url;
        endpoint = "/api/download";
        console.log("[startDownload] 单曲模式:", url);
    }

    closePlaySection();

    var btn = $("startBtn");
    btn.disabled = true;
    btn.textContent = isBatch ? "提交批量任务..." : "提交中...";

    var resetTimer = setTimeout(function() {
        __startingDownload = false;
        updateStartButton(false);
    }, 10000);

    function unlock() {
        clearTimeout(resetTimer);
        __startingDownload = false;
    }

    fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    })
    .then(function(res) {
        return res.json().then(function(d) {
            return { status: res.status, data: d };
        });
    })
    .then(function(r) {
        unlock();
        if (!r.data.ok) {
            var msg = r.data.msg || "启动失败";
            if (r.data.can_reset) {
                if (confirm(msg + "\n\n是否重置任务状态？")) resetTask();
            } else {
                alert(msg);
            }
            updateStartButton(false);
            return;
        }
        startLogPolling();
        setTimeout(checkStatus, 500);
    })
    .catch(function(e) {
        unlock();
        alert("请求失败: " + e);
        updateStartButton(false);
    });
}

/* 当用户输入收藏夹链接时，自动解析 */
function onUrlChange() {
    var url = $("url").value.trim();
    if (isBatchUrl(url)) {
        $("urlHint").className = "file-hint";
        $("urlHint").textContent = "检测到收藏夹/合集链接，正在解析...";
        parseBatch();
    } else if (url && isValidBiliUrl(url)) {
        $("urlHint").className = "file-hint";
        $("urlHint").textContent = "单曲模式";
        $("batchCard").style.display = "none";
        __batchVideos = [];
    }
}

/* 追加事件绑定到 DOMContentLoaded */
(function() {
    function addBatchListeners() {
        var urlInput = document.getElementById("url");
        if (urlInput) {
            var timer = null;
            urlInput.addEventListener("input", function() {
                if (timer) clearTimeout(timer);
                timer = setTimeout(onUrlChange, 800);
            });
        }

        var selAll = document.getElementById("batchSelectAllBtn");
        if (selAll) selAll.addEventListener("click", function() { batchSelectAll(true); });

        var unselAll = document.getElementById("batchUnselectAllBtn");
        if (unselAll) unselAll.addEventListener("click", function() { batchSelectAll(false); });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", addBatchListeners);
    } else {
        addBatchListeners();
    }
})();
