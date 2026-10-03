var $ = function(id) { return document.getElementById(id); };

var DEFAULT_CONFIG = {
    audio_quality: "hires",
    use_aria2: true,
    aria2_threads: 16,
    aria2_splits: 16,
    default_save_dir: "",
    default_volume: 1.0,
    default_quality: "192",
    default_target_lufs: -16.0,
};

/* ============ 配置 ============ */
function loadConfig() {
    fetch("/api/config")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.ok) applyConfig(data.config);
        })
        .catch(function(e) { console.error("加载配置失败:", e); });
}

function applyConfig(cfg) {
    var q = cfg.audio_quality || "hires";
    var radios = document.querySelectorAll('input[name="audioQuality"]');
    for (var i = 0; i < radios.length; i++) {
        radios[i].checked = (radios[i].value === q);
    }
    var ua = $("useAria2");
    if (ua) {
        ua.checked = !!cfg.use_aria2;
        $("aria2Options").style.display = ua.checked ? "block" : "none";
    }
    if ($("aria2Threads")) {
        $("aria2Threads").value = cfg.aria2_threads || 16;
        $("aria2ThreadsLabel").textContent = cfg.aria2_threads || 16;
    }
    if ($("aria2Splits")) {
        $("aria2Splits").value = cfg.aria2_splits || 16;
        $("aria2SplitsLabel").textContent = cfg.aria2_splits || 16;
    }
    if ($("defaultSaveDir")) {
        $("defaultSaveDir").value = cfg.default_save_dir || "";
    }
    if ($("defaultVolume")) {
        $("defaultVolume").value = cfg.default_volume || 1.0;
        $("defaultVolumeLabel").textContent = parseFloat(cfg.default_volume || 1.0).toFixed(2) + "x";
    }
    var dq = cfg.default_quality || "192";
    var dqRadios = document.querySelectorAll('input[name="defaultQuality"]');
    for (var j = 0; j < dqRadios.length; j++) {
        dqRadios[j].checked = (dqRadios[j].value === dq);
    }
    if ($("defaultTargetLufs")) {
        $("defaultTargetLufs").value = cfg.default_target_lufs || -16;
        $("defaultTargetLufsLabel").textContent = parseFloat(cfg.default_target_lufs || -16).toFixed(1);
    }
}

function saveSettings() {
    var qEl = document.querySelector('input[name="audioQuality"]:checked');
    var dqEl = document.querySelector('input[name="defaultQuality"]:checked');

    var payload = {
        audio_quality: qEl ? qEl.value : "hires",
        use_aria2: $("useAria2") ? $("useAria2").checked : false,
        aria2_threads: parseInt($("aria2Threads").value, 10) || 16,
        aria2_splits: parseInt($("aria2Splits").value, 10) || 16,
        default_save_dir: $("defaultSaveDir") ? $("defaultSaveDir").value.trim() : "",
        default_volume: $("defaultVolume") ? parseFloat($("defaultVolume").value) : 1.0,
        default_quality: dqEl ? dqEl.value : "192",
        default_target_lufs: $("defaultTargetLufs") ? parseFloat($("defaultTargetLufs").value) : -16.0,
    };

    fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        var hint = $("saveHint");
        if (data.ok) {
            hint.className = "file-hint ok";
            hint.textContent = "已保存";
            setTimeout(function() { hint.textContent = ""; }, 2500);
        } else {
            hint.className = "file-hint err";
            hint.textContent = "保存失败: " + (data.msg || "");
        }
    })
    .catch(function(e) {
        var hint = $("saveHint");
        hint.className = "file-hint err";
        hint.textContent = "保存失败: " + e;
    });
}

function resetSettings() {
    if (!confirm("确定要重置为默认设置吗？")) return;
    applyConfig(DEFAULT_CONFIG);
    saveSettings();
}

/* ============ B站登录 ============ */
var loginPollTimer = null;

function _stopLoginPolling() {
    if (loginPollTimer) {
        clearInterval(loginPollTimer);
        loginPollTimer = null;
    }
    var btn = $("browserLoginBtn");
    if (btn) {
        btn.disabled = false;
        btn.textContent = "打开内置浏览器登录";
    }
}

function openBuiltinBrowserLogin() {
    var btn = $("browserLoginBtn");
    var hint = $("loginHint");

    // 先停掉旧的轮询（如果有）
    _stopLoginPolling();

    if (btn) { btn.disabled = true; btn.textContent = "启动中..."; }
    hint.className = "file-hint";
    hint.textContent = "正在启动内置浏览器...";

    fetch("/api/bili/browser_login", { method: "POST" })
        .then(function(res) { return res.json().then(function(d) { return {ok: res.ok, data: d}; }); })
        .then(function(r) {
            if (!r.ok || !r.data.ok) {
                hint.className = "file-hint err";
                hint.textContent = (r.data && r.data.msg) || "启动失败";
                _stopLoginPolling();
                return;
            }
            hint.className = "file-hint ok";
            hint.textContent = "登录窗口已打开，请在弹出的窗口中登录 B站";
            if (btn) btn.textContent = "等待登录...";
            startLoginPolling();
        })
        .catch(function(e) {
            hint.className = "file-hint err";
            hint.textContent = "请求失败: " + e;
            _stopLoginPolling();
        });
}

function startLoginPolling() {
    if (loginPollTimer) clearInterval(loginPollTimer);
    var hint = $("loginHint");

    loginPollTimer = setInterval(function() {
        fetch("/api/bili/browser_login_status")
            .then(function(res) { return res.json(); })
            .then(function(data) {
                // 后端明确说结束了
                if (data.finished) {
                    _stopLoginPolling();
                    if (data.success) {
                        hint.className = "file-hint ok";
                        hint.textContent = "登录成功！";
                        updateAccountStatus(data.info, "登录成功");
                        var btn = $("browserLoginBtn");
                        if (btn) btn.textContent = "重新登录";
                    } else {
                        hint.className = "file-hint err";
                        hint.textContent = data.msg || "登录失败";
                        updateAccountStatus(null, "");
                    }
                    return;
                }
                // 还在等，更新提示
                if (data.msg && data.msg !== "等待登录...") {
                    hint.className = "file-hint";
                    hint.textContent = data.msg;
                }
            })
            .catch(function() {
                // 网络错误时不做处理，继续轮询
            });
    }, 1500);
}

function checkCookies() {
    var hint = $("loginHint");
    hint.className = "file-hint";
    hint.textContent = "正在检查...";

    fetch("/api/bili/check_cookies")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.has_cookies) {
                hint.className = "file-hint ok";
                hint.textContent = data.msg;
                updateAccountStatus(data.info, data.msg);
            } else {
                hint.className = "file-hint err";
                hint.textContent = data.msg || "未登录";
                updateAccountStatus(null, "");
            }
        })
        .catch(function(e) {
            hint.className = "file-hint err";
            hint.textContent = "检查失败: " + e;
        });
}

function clearCookies() {
    if (!confirm("确定要清除 Cookie 吗？")) return;
    _stopLoginPolling();
    fetch("/api/bili/clear_cookies", { method: "POST" })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            var hint = $("loginHint");
            hint.className = "file-hint";
            hint.textContent = data.msg || "已清除";
            updateAccountStatus(null, "");
        })
        .catch(function(e) {
            alert("清除失败: " + e);
        });
}

function updateAccountStatus(info, msg) {
    var dot = document.querySelector(".account-dot");
    var text = $("accountText");
    if (!text) return;

    if (info) {
        if (info.is_vip) {
            text.textContent = "✔ " + info.username + "（大会员）";
            if (dot) dot.className = "account-dot vip";
        } else {
            text.textContent = "✔ " + info.username + "（普通用户）";
            if (dot) dot.className = "account-dot logged";
        }
    } else {
        text.textContent = msg || "未登录";
        if (dot) dot.className = "account-dot error";
    }
}

/* ============ aria2 ============ */
function installAria2() {
    var hint = $("aria2Hint");
    hint.className = "file-hint";
    hint.textContent = "正在强制重装 aria2c ...";

    var btn = $("installAria2Btn");
    if (btn) { btn.disabled = true; btn.textContent = "安装中..."; }

    fetch("/api/aria2/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: true }),
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        hint.className = "file-hint ok";
        hint.textContent = data.msg || "已开始下载";
        startStatusPolling();
    })
    .catch(function(e) {
        hint.className = "file-hint err";
        hint.textContent = "请求失败: " + e;
        if (btn) { btn.disabled = false; btn.textContent = "安装 / 重装 aria2c"; }
    });
}

var aria2PollTimer = null;

function startStatusPolling() {
    if (aria2PollTimer) return;
    var hint = $("aria2Hint");
    var btn = $("installAria2Btn");
    var count = 0;

    aria2PollTimer = setInterval(function() {
        count++;
        checkAria2Status();
        fetch("/api/status")
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (data.aria2_ready) {
                    clearInterval(aria2PollTimer);
                    aria2PollTimer = null;
                    if (btn) { btn.disabled = false; btn.textContent = "安装 / 重装 aria2c"; }
                    hint.className = "file-hint ok";
                    hint.textContent = "aria2c 安装成功: " + (data.aria2_status_msg || "");
                    checkAria2Status();
                } else if (count > 60) {
                    clearInterval(aria2PollTimer);
                    aria2PollTimer = null;
                    if (btn) { btn.disabled = false; btn.textContent = "安装 / 重装 aria2c"; }
                    hint.className = "file-hint err";
                    hint.textContent = "安装超时，请检查网络或查看主页日志";
                }
            })
            .catch(function() {});
    }, 1500);
}

function checkAria2Status() {
    fetch("/api/status")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            var el = $("aria2Status");
            if (!el) return;
            if (data.aria2_ready) {
                el.className = "file-hint ok";
                el.textContent = "aria2c 可用: " + (data.aria2_status_msg || data.aria2_path);
            } else {
                el.className = "file-hint err";
                el.textContent = "aria2c 不可用：" + (data.aria2_status_msg || "未安装");
            }
        })
        .catch(function() {});
}

/* ============ 初始化 ============ */
document.addEventListener("DOMContentLoaded", function() {
    var th = $("aria2Threads");
    if (th) {
        th.addEventListener("input", function() {
            $("aria2ThreadsLabel").textContent = th.value;
        });
    }
    var sp = $("aria2Splits");
    if (sp) {
        sp.addEventListener("input", function() {
            $("aria2SplitsLabel").textContent = sp.value;
        });
    }
    var dv = $("defaultVolume");
    if (dv) {
        dv.addEventListener("input", function() {
            $("defaultVolumeLabel").textContent = parseFloat(dv.value).toFixed(2) + "x";
        });
    }
    var dl = $("defaultTargetLufs");
    if (dl) {
        dl.addEventListener("input", function() {
            $("defaultTargetLufsLabel").textContent = parseFloat(dl.value).toFixed(1);
        });
    }
    var ua = $("useAria2");
    if (ua) {
        ua.addEventListener("change", function() {
            $("aria2Options").style.display = ua.checked ? "block" : "none";
        });
    }

    loadConfig();
    checkAria2Status();
    checkCookies();
});
