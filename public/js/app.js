/**
 * Apple Habit & Abit UI Style Pi LED Controller (v2.4 - Clean Edition)
 * Features:
 * - CIE 1931 / Gamma 2.2 Smooth Perception & Sine Breathing
 * - Touch/Click to Toggle Bulb & Optimistic UI
 * - Smart Timer & Gradual Fade-Out Progress Bar
 * - Custom Pattern Studio & Timeline Runner
 * - Hardware Dynamic Pin Remapping & Polarity Setting
 * - Audit Logs CSV / JSON Instant Export
 * - Local OAuth2 JWT & Dynamic Device Tokens
 */

const state = {
    token: localStorage.getItem("pi_led_token") || "",
    ws: null,
    wsConnected: false,
    snapshot: null,
    theme: localStorage.getItem("pi_led_theme") || "auto",
    currentTab: "control",
    deviceFilter: "all",
    logs: [],
    tokens: [],
    patterns: {},
    hardware: { pins: { red: 22, yellow: 27, green: 17 }, active_high: true, gamma_correction: true, gamma_value: 2.2 },
    charts: { trend: null, devices: null, states: null }
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ==================== 主题与导航 ====================
function initTheme() {
    if (state.theme === "dark" || state.theme === "light") {
        document.documentElement.setAttribute("data-theme", state.theme);
    } else {
        document.documentElement.removeAttribute("data-theme");
    }
    updateThemeIcon();
    if (state.charts.trend) updateChartsTheme();
}

function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme");
    let next = current === "dark" ? "light" : (current === "light" ? "auto" : "dark");
    state.theme = next;
    localStorage.setItem("pi_led_theme", next);
    initTheme();
    showToast(`主题切换为: ${next === 'auto' ? '跟随系统' : next.toUpperCase()}`);
}

function updateThemeIcon() {
    const btn = $("#btn-theme");
    if (!btn) return;
    const isDark = document.documentElement.getAttribute("data-theme") === "dark" || 
        (!document.documentElement.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
    btn.innerHTML = isDark 
        ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`
        : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
}

function switchTab(tabId, title, btnElem) {
    state.currentTab = tabId;
    $$(".dock-btn").forEach(btn => btn.classList.remove("active"));
    if (btnElem) {
        btnElem.classList.add("active");
    } else {
        const found = $(`.dock-btn[data-tab="${tabId}"]`);
        if (found) found.classList.add("active");
    }

    $$(".view-section").forEach(sec => {
        sec.classList.toggle("active", sec.id === `view-${tabId}`);
    });

    if (tabId === "charts") {
        fetchStatsAndRenderCharts();
    } else if (tabId === "logs") {
        fetchAuditLogs();
    } else if (tabId === "auth") {
        fetchAuthInfo();
        fetchTokensList();
        fetchHardwareConfig();
    }
}

// Toast
let toastTimer = null;
function showToast(message, type = "info") {
    const toast = $("#toast");
    if (!toast) return;
    clearTimeout(toastTimer);
    $("#toast-msg").textContent = message;
    toast.className = `toast show ${type}`;
    toastTimer = setTimeout(() => { toast.className = "toast"; }, 2400);
}

// API Fetch Helper
async function apiRequest(endpoint, method = "GET", body = null) {
    const headers = { "Content-Type": "application/json" };
    if (state.token) {
        if (state.token.startsWith("ey")) {
            headers["Authorization"] = `Bearer ${state.token}`;
        } else {
            headers["X-API-Key"] = state.token;
        }
    }
    
    const options = { method, headers };
    if (body && method !== "GET") {
        options.body = JSON.stringify(body);
    }

    try {
        const res = await fetch(endpoint, options);
        if (res.status === 401) {
            showToast("⚠️ 需要控制权限：请先输入密码登录或提供 Token", "danger");
            switchTab("auth");
            const pwdInput = document.querySelector("#oauth-password");
            if (pwdInput) {
                pwdInput.focus();
                pwdInput.scrollIntoView({ behavior: "smooth", block: "center" });
            }
            throw new Error("Unauthorized");
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: "请求失败" }));
            throw new Error(err.detail || "请求失败");
        }
        return await res.json();
    } catch (err) {
        if (err.message !== "Unauthorized") {
            showToast(`错误: ${err.message}`, "danger");
        }
        throw err;
    }
}

// ==================== WebSocket ====================
function connectWebSocket() {
    const loc = window.location;
    const proto = loc.protocol === "https:" ? "wss:" : "ws:";
    let url = `${proto}//${loc.host}/ws/status`;
    if (state.token) {
        url += `?token=${encodeURIComponent(state.token)}`;
    }

    try {
        state.ws = new WebSocket(url);
        state.ws.onopen = () => {
            state.wsConnected = true;
            updateWsBadge(true);
        };

        state.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === "state_update" && msg.data) {
                    renderSnapshot(msg.data);
                } else if (msg.type === "new_log" && msg.data) {
                    appendAuditLog(msg.data);
                    if (state.currentTab === "charts") {
                        fetchStatsAndRenderCharts();
                    }
                }
            } catch (_) {}
        };

        state.ws.onclose = () => {
            state.wsConnected = false;
            updateWsBadge(false);
            setTimeout(connectWebSocket, 3000);
        };

        state.ws.onerror = () => {
            state.wsConnected = false;
            updateWsBadge(false);
        };
    } catch (_) {
        setTimeout(connectWebSocket, 3000);
    }
}

function updateWsBadge(online) {
    const badge = $("#ws-badge");
    if (!badge) return;
    if (online) {
        badge.className = "badge badge-success";
        badge.innerHTML = `<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#34c759;"></span> 实时在线`;
    } else {
        badge.className = "badge badge-warning";
        badge.innerHTML = `<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#ff9500;"></span> 正在重连`;
    }
}

// ==================== 控制台渲染 ====================
function renderSnapshot(data) {
    if (!data || !data.channels) return;
    state.snapshot = data;

    // 1. Bulb Glow
    ["red", "yellow", "green"].forEach((color) => {
        const bulb = $(`#bulb-${color}`);
        const levelLabel = $(`#bulb-level-${color}`);
        const ch = data.channels[color];
        if (!bulb || !ch) return;

        const val = typeof ch.value === "number" ? ch.value : (ch.action === "off" ? 0.0 : 1.0);
        if (val > 0.02) {
            bulb.classList.add("active");
            bulb.style.opacity = Math.max(0.4, val);
            if (levelLabel) levelLabel.textContent = `${Math.round(val * 100)}%`;
        } else {
            bulb.classList.remove("active");
            bulb.style.opacity = "1";
            if (levelLabel) levelLabel.textContent = "关闭";
        }

        const sliderVal = $(`#slider-val-${color}`);
        const sliderInput = $(`#slider-${color}`);
        if (sliderVal) sliderVal.textContent = `${Math.round(val * 100)}%`;
        if (sliderInput && document.activeElement !== sliderInput) {
            sliderInput.value = val;
        }

        $$(`.seg-${color}`).forEach((btn) => {
            btn.classList.toggle("active", btn.dataset.action === ch.action);
        });
    });

    // 2. State Badge
    const stateBadge = $("#current-state-badge");
    if (stateBadge) {
        const raw = data.current_state || "off";
        let text = raw, cls = "badge-neutral";
        if (raw.includes("thinking")) { text = "🟡 思考中 (Thinking)"; cls = "badge-warning"; }
        else if (raw.includes("breathing")) { text = "🟡 任务执行中 (Breathing)"; cls = "badge-warning"; }
        else if (raw.includes("restarting")) { text = "🟡 重启中 (Restarting)"; cls = "badge-warning"; }
        else if (raw.includes("success")) { text = "🟢 任务成功 (Success)"; cls = "badge-success"; }
        else if (raw.includes("error")) { text = "🔴 发生异常 (Error)"; cls = "badge-danger"; }
        else if (raw.includes("startup")) { text = "✨ 启动自检 (Startup)"; cls = "badge-accent"; }
        else if (raw.includes("pattern")) { text = `🎭 动效 (${raw.replace('pattern_', '')})`; cls = "badge-accent"; }
        else if (raw === "off") { text = "⏹️ 全部熄灭 (Off)"; cls = "badge-neutral"; }
        stateBadge.className = `badge ${cls}`;
        stateBadge.textContent = text;
    }

    // 3. Hardware Mode & Pins
    const hwBadge = $("#hardware-badge");
    if (hwBadge && data.hardware) {
        hwBadge.textContent = `GPIO: ${data.hardware.mode || 'MOCK'} ${data.hardware.gamma_correction ? '(Gamma 2.2)' : ''}`;
        if (data.hardware.pins) {
            $("#pin-label-red").textContent = `GPIO ${data.hardware.pins.red}`;
            $("#pin-label-yellow").textContent = `GPIO ${data.hardware.pins.yellow}`;
            $("#pin-label-green").textContent = `GPIO ${data.hardware.pins.green}`;
        }
    }

    // 4. Smart Timer Rendering
    renderSmartTimer(data.smart_timer);
}

function renderSmartTimer(st) {
    const badge = $("#timer-badge");
    const cancelBtn = $("#btn-cancel-timer");
    const progressWrap = $("#timer-progress-wrap");
    const progressBar = $("#timer-progress-bar");
    if (!badge) return;

    if (st && st.active) {
        badge.className = "badge badge-success";
        const mins = Math.floor(st.remaining_seconds / 60);
        const secs = st.remaining_seconds % 60;
        badge.textContent = `⏱️ 倒计时: ${mins}:${secs < 10 ? '0' : ''}${secs}`;
        if (cancelBtn) cancelBtn.style.display = "inline-block";
        if (progressWrap) progressWrap.style.display = "block";
        if (progressBar) {
            const pct = Math.max(0, Math.min(100, (st.remaining_seconds / st.total_duration) * 100));
            progressBar.style.width = `${pct}%`;
            progressBar.style.background = st.remaining_seconds <= 10 ? "var(--warning)" : "var(--success)";
        }
    } else {
        badge.className = "badge badge-neutral";
        badge.textContent = "未激活";
        if (cancelBtn) cancelBtn.style.display = "none";
        if (progressWrap) progressWrap.style.display = "none";
    }
}

// ==================== 拟真灯泡直接点击交互 ====================
async function toggleBulbColor(color) {
    const currentVal = state.snapshot?.channels?.[color]?.value || 0;
    const isCurrentlyOn = currentVal > 0.05;
    const nextAction = isCurrentlyOn ? "off" : "on";
    const nextVal = isCurrentlyOn ? 0.0 : 1.0;

    if (state.snapshot?.channels?.[color]) {
        state.snapshot.channels[color].action = nextAction;
        state.snapshot.channels[color].value = nextVal;
        renderSnapshot(state.snapshot);
    }

    try {
        await apiRequest("/api/led", "POST", { color, action: nextAction, value: nextVal, exclusive: false });
        showToast(`${color.toUpperCase()} -> ${nextAction.toUpperCase()}`, "info");
    } catch (_) {}
}

// ==================== 智能倒计时引擎 ====================
async function startQuickTimer(color, durationSec) {
    try {
        await apiRequest("/api/timer", "POST", { color, duration_sec: durationSec, fade_out_sec: 5 });
        showToast(`已启动 ${durationSec} 秒倒计时 (结束前渐暗关灯)`, "success");
    } catch (_) {}
}

async function cancelActiveTimer() {
    try {
        await apiRequest("/api/timer", "DELETE");
        showToast("倒计时已取消，所有指示灯已熄灭", "info");
    } catch (_) {}
}

// ==================== 自定义动效库管理 ====================
async function fetchPatterns() {
    try {
        const res = await apiRequest("/api/patterns");
        state.patterns = res.patterns || {};
        renderPatternsBar(state.patterns);
    } catch (_) {}
}

function renderPatternsBar(patterns) {
    const container = $("#patterns-container");
    if (!container) return;

    const patternKeys = Object.keys(patterns);
    if (patternKeys.length === 0) return;

    container.innerHTML = patternKeys.map(k => {
        const p = patterns[k];
        return `<button class="btn-pattern" onclick="triggerPattern('${p.name}')">${p.title || p.name}</button>`;
    }).join("");
}

function openCreatePatternModal() {
    $("#pattern-modal").classList.add("active");
    $("#input-pattern-id").value = `pattern_${Date.now().toString().slice(-4)}`;
    $("#input-pattern-title").value = "✨ 炫彩动效";
    $("#input-pattern-repeat").value = "5";
    
    const list = $("#pattern-frames-list");
    list.innerHTML = "";
    addPatternFrameRow(1.0, 0.0, 0.0, 0.2);
    addPatternFrameRow(0.0, 1.0, 0.0, 0.2);
    addPatternFrameRow(0.0, 0.0, 1.0, 0.2);
}

function closeCreatePatternModal() {
    $("#pattern-modal").classList.remove("active");
}

function addPatternFrameRow(r = 0.0, y = 0.0, g = 0.0, dur = 0.2) {
    const list = $("#pattern-frames-list");
    const idx = list.children.length + 1;
    const row = document.createElement("div");
    row.className = "pattern-frame-row";
    row.style.cssText = "display:flex; align-items:center; gap:8px; background:var(--card-sec); padding:6px 10px; border-radius:var(--radius-sm); font-size:0.8rem;";
    row.innerHTML = `
        <span style="font-weight:700; color:var(--text-sec);">#${idx}</span>
        <label style="color:var(--danger)">🔴 <input type="number" class="frame-r input-field" value="${r}" min="0" max="1" step="0.1" style="width:50px; padding:4px;"></label>
        <label style="color:var(--warning)">🟡 <input type="number" class="frame-y input-field" value="${y}" min="0" max="1" step="0.1" style="width:50px; padding:4px;"></label>
        <label style="color:var(--success)">🟢 <input type="number" class="frame-g input-field" value="${g}" min="0" max="1" step="0.1" style="width:50px; padding:4px;"></label>
        <label style="color:var(--text-sec)">⏱️ <input type="number" class="frame-dur input-field" value="${dur}" min="0.05" max="10" step="0.05" style="width:55px; padding:4px;">s</label>
        <button type="button" onclick="this.parentElement.remove()" style="border:none; background:none; color:var(--danger); cursor:pointer; font-weight:bold;">✕</button>
    `;
    list.appendChild(row);
}

async function handlePatternSubmit(e) {
    e.preventDefault();
    const name = $("#input-pattern-id").value.trim();
    const title = $("#input-pattern-title").value.trim();
    const repeat = parseInt($("#input-pattern-repeat").value || "1");

    const frames = [];
    $$(".pattern-frame-row").forEach(row => {
        frames.push({
            red: parseFloat(row.querySelector(".frame-r").value || "0"),
            yellow: parseFloat(row.querySelector(".frame-y").value || "0"),
            green: parseFloat(row.querySelector(".frame-g").value || "0"),
            duration: parseFloat(row.querySelector(".frame-dur").value || "0.2")
        });
    });

    if (frames.length === 0) {
        showToast("请至少添加一帧动效", "danger");
        return;
    }

    try {
        await apiRequest("/api/patterns", "POST", { name, title, repeat, frames });
        showToast(`动效 ${title} 已成功保存`, "success");
        closeCreatePatternModal();
        fetchPatterns();
    } catch (err) {
        showToast(`保存失败: ${err.message}`, "danger");
    }
}

// ==================== 硬件配置热重载 ====================
async function fetchHardwareConfig() {
    try {
        const res = await apiRequest("/api/hardware/config");
        state.hardware = res.config || state.hardware;
        $("#input-pin-red").value = state.hardware.pins?.red || 22;
        $("#input-pin-yellow").value = state.hardware.pins?.yellow || 27;
        $("#input-pin-green").value = state.hardware.pins?.green || 17;
        $("#input-hw-activehigh").checked = state.hardware.active_high ?? true;
        $("#input-hw-gamma").checked = state.hardware.gamma_correction ?? true;
    } catch (_) {}
}

function openHardwareModal() {
    fetchHardwareConfig();
    $("#hardware-modal").classList.add("active");
}

function closeHardwareModal() {
    $("#hardware-modal").classList.remove("active");
}

async function handleHardwareSubmit(e) {
    e.preventDefault();
    const red = parseInt($("#input-pin-red").value);
    const yellow = parseInt($("#input-pin-yellow").value);
    const green = parseInt($("#input-pin-green").value);
    const active_high = $("#input-hw-activehigh").checked;
    const gamma_correction = $("#input-hw-gamma").checked;

    try {
        await apiRequest("/api/hardware/config", "POST", {
            pins: { red, yellow, green },
            active_high,
            gamma_correction,
            gamma_value: 2.2
        });
        showToast("硬件引脚配置已保存并热重载", "success");
        closeHardwareModal();
        apiRequest("/api/status").then(renderSnapshot);
    } catch (err) {
        showToast(`保存失败: ${err.message}`, "danger");
    }
}

// ==================== 审计日志与数据导出 ====================
function exportLogs(format = "csv") {
    window.location.href = `/api/logs/export?format=${format}`;
    showToast(`正在导出 ${format.toUpperCase()} 审计日志...`, "info");
}

function getDeviceIcon(name) {
    if (!name) return "📱";
    if (name.includes("飞书")) return "🤖";
    if (name.includes("iPhone") || name.includes("iOS") || name.includes("快捷指令") || name.includes("iPad")) return "🍏";
    if (name.includes("Home") || name.includes("HA")) return "🏠";
    if (name.includes("Web") || name.includes("管理员")) return "🌐";
    if (name.includes("未授权")) return "🚫";
    return "📱";
}

function renderAuditLogs(logs) {
    const container = $("#audit-log-list");
    if (!container) return;

    state.logs = logs || [];
    const countBadge = $("#log-count-badge");
    if (countBadge) countBadge.textContent = `${state.logs.length} 条记录`;

    const filtered = state.deviceFilter === "all" 
        ? state.logs 
        : state.logs.filter(l => l.device_name === state.deviceFilter);

    if (filtered.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding:32px 0; color:var(--text-sec); font-size:0.88rem;">暂无调用记录</div>`;
        return;
    }

    container.innerHTML = filtered.map(log => {
        const isSuccess = log.success;
        const devIcon = getDeviceIcon(log.device_name);
        const payloadSummary = log.payload ? Object.entries(log.payload).map(([k, v]) => `${k}=${v}`).join(", ") : "无参数";
        
        return `
            <div class="log-item">
                <div class="log-left">
                    <div style="font-size: 1.3rem;">${devIcon}</div>
                    <div class="log-info">
                        <div class="log-title">
                            <span class="badge ${log.device_name.includes("未授权") ? "badge-danger" : "badge-accent"}">${log.device_name}</span>
                            <span style="font-size: 0.85rem;">${log.endpoint}</span>
                        </div>
                        <div class="log-sub">
                            <span>参数: <code>${payloadSummary}</code></span>
                            <span>IP: ${log.client_ip}</span>
                            ${log.token_masked ? `<span>Key: <code>${log.token_masked}</code></span>` : ""}
                            ${log.error ? `<span style="color:var(--danger)">错误: ${log.error}</span>` : ""}
                        </div>
                    </div>
                </div>

                <div class="log-right">
                    <span class="badge ${isSuccess ? "badge-success" : "badge-danger"}">${log.status_code} ${isSuccess ? "OK" : "ERR"}</span>
                    <span class="log-time">${log.timestamp.split(" ")[1] || log.timestamp}</span>
                </div>
            </div>
        `;
    }).join("");

    updateDeviceFilterPills();
}

function appendAuditLog(newLog) {
    state.logs.unshift(newLog);
    if (state.logs.length > 500) state.logs.pop();
    renderAuditLogs(state.logs);
}

function updateDeviceFilterPills() {
    const filterContainer = $("#device-filter-pills");
    if (!filterContainer) return;

    const devices = Array.from(new Set(state.logs.map(l => l.device_name))).filter(Boolean);
    let html = `<button class="filter-pill ${state.deviceFilter === 'all' ? 'active' : ''}" onclick="setDeviceFilter('all')">全部设备 (${state.logs.length})</button>`;
    devices.forEach(d => {
        const cnt = state.logs.filter(l => l.device_name === d).length;
        html += `<button class="filter-pill ${state.deviceFilter === d ? 'active' : ''}" onclick="setDeviceFilter('${d}')">${getDeviceIcon(d)} ${d} (${cnt})</button>`;
    });
    filterContainer.innerHTML = html;
}

window.setDeviceFilter = function(dev) {
    state.deviceFilter = dev;
    renderAuditLogs(state.logs);
};

async function fetchAuditLogs() {
    try {
        const res = await apiRequest("/api/logs?limit=80");
        renderAuditLogs(res.logs || []);
    } catch (_) {}
}

async function clearAuditLogs() {
    if (!confirm("确定要清空内存中的调用记录吗？")) return;
    try {
        await apiRequest("/api/logs", "DELETE");
        state.logs = [];
        renderAuditLogs([]);
        showToast("调用记录已清空", "info");
    } catch (_) {}
}

// ==================== 动态创建与管理 Token ====================
function openCreateTokenModal() {
    $("#create-token-modal").classList.add("active");
    $("#input-token-devicename").value = "";
    $("#input-token-custom").value = "";
    $("#input-token-expires").value = "0";
}

function closeCreateTokenModal() {
    $("#create-token-modal").classList.remove("active");
}

async function handleCreateTokenSubmit(e) {
    e.preventDefault();
    const deviceName = $("#input-token-devicename").value.trim();
    const customToken = $("#input-token-custom").value.trim();
    const expiresDays = parseInt($("#input-token-expires").value || "0");

    if (!deviceName) {
        showToast("请输入设备或服务名称", "danger");
        return;
    }

    try {
        const res = await apiRequest("/api/tokens/create", "POST", {
            device_name: deviceName,
            custom_token: customToken || null,
            expires_days: expiresDays
        });

        closeCreateTokenModal();
        openTokenSuccessModal(res);
        fetchTokensList();
    } catch (err) {
        showToast(`创建失败: ${err.message}`, "danger");
    }
}

function openTokenSuccessModal(res) {
    $("#success-modal-token").value = res.token;
    $("#success-modal-device").textContent = res.device_name;
    $("#success-modal-created").textContent = res.created_at;
    $("#token-success-modal").classList.add("active");
}

function closeTokenSuccessModal() {
    $("#token-success-modal").classList.remove("active");
}

async function fetchTokensList() {
    const container = $("#tokens-card-list");
    if (!container) return;

    try {
        const res = await apiRequest("/api/tokens");
        state.tokens = res.tokens || [];
        
        if (state.tokens.length === 0) {
            container.innerHTML = `<div style="text-align:center; padding:24px 0; color:var(--text-sec); font-size:0.88rem;">暂无配置的访问令牌，点击上方按钮创建</div>`;
            return;
        }

        container.innerHTML = state.tokens.map(tok => `
            <div class="token-card">
                <div class="token-card-left">
                    <div style="font-size: 1.4rem;">${getDeviceIcon(tok.device_name)}</div>
                    <div class="token-card-info">
                        <div class="token-card-name">
                            <span>${tok.device_name}</span>
                            <span class="badge ${tok.type === 'dynamic' ? 'badge-accent' : 'badge-neutral'}">
                                ${tok.type === 'dynamic' ? '动态颁发' : '配置文件'}
                            </span>
                        </div>
                        <div class="token-card-sub">
                            <span>令牌: <code>${tok.token_masked}</code></span>
                            <span>•</span>
                            <span>创建时间: ${tok.created_at}</span>
                        </div>
                    </div>
                </div>

                <div class="token-card-right">
                    ${tok.can_delete ? `
                        <button class="filter-pill" style="color:var(--danger); border-color:var(--danger-bg); background:var(--danger-bg); padding:6px 12px;" onclick="handleDeleteToken('${tok.id}')">
                            撤销
                        </button>
                    ` : '<span style="font-size:0.75rem; color:var(--text-ter); padding: 4px 8px;">只读配置</span>'}
                </div>
            </div>
        `).join("");
    } catch (_) {}
}

async function handleDeleteToken(tokenId) {
    if (!confirm("确定要撤销此设备的访问令牌吗？撤销后该设备将无法调用控制接口。")) return;
    try {
        await apiRequest(`/api/tokens/${tokenId}`, "DELETE");
        showToast("令牌已成功撤销", "success");
        fetchTokensList();
    } catch (err) {
        showToast(`撤销失败: ${err.message}`, "danger");
    }
}

// ==================== OAuth2 认证管理 ====================
async function handleOAuthLogin(e) {
    e.preventDefault();
    const username = $("#oauth-username").value.trim();
    const password = $("#oauth-password").value.trim();

    try {
        const res = await fetch("/api/oauth/token", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({ username, password, grant_type: "password" })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: "登录失败" }));
            throw new Error(err.detail || "用户名或密码/令牌错误");
        }

        const data = await res.json();
        state.token = data.access_token;
        localStorage.setItem("pi_led_token", data.access_token);
        showToast(`登录成功: ${data.device_name}`, "success");

        if (state.ws) state.ws.close();
        connectWebSocket();
        fetchAuthInfo();
        fetchTokensList();
    } catch (err) {
        showToast(err.message, "danger");
    }
}

function handleOAuthLogout() {
    state.token = "";
    localStorage.removeItem("pi_led_token");
    showToast("已登出凭证", "info");
    if (state.ws) state.ws.close();
    connectWebSocket();
    fetchAuthInfo();
}

async function fetchAuthInfo() {
    const infoCard = $("#auth-user-info");
    if (!infoCard) return;

    if (state.token) {
        try {
            const res = await apiRequest("/api/oauth/userinfo");
            infoCard.innerHTML = `
                <div class="badge badge-success" style="padding: 8px 14px; font-size: 0.9rem; margin-bottom: 10px;">
                    ✓ 已认证: ${res.device_name}
                </div>
                <div style="font-size: 0.84rem; color: var(--text-sec); display: flex; flex-direction: column; gap: 6px;">
                    <div>认证协议: <code>${res.auth_type}</code></div>
                    <div>客户端 IP: <code>${res.client_ip}</code></div>
                    <div style="display: flex; gap: 10px; margin-top: 10px;">
                        <button class="btn-preset danger-btn" onclick="handleOAuthLogout()" style="padding: 8px 16px;">登出凭证</button>
                        <button class="btn-preset" onclick="copyToClipboard('${state.token}')" style="padding: 8px 16px;">复制 JWT 令牌</button>
                    </div>
                </div>
            `;
        } catch (_) {
            renderAnonymousAuth();
        }
    } else {
        renderAnonymousAuth();
    }
}

function renderAnonymousAuth() {
    const infoCard = $("#auth-user-info");
    if (infoCard) {
        infoCard.innerHTML = `
            <div class="badge badge-neutral" style="padding: 8px 14px; font-size: 0.9rem; margin-bottom: 10px;">
                ⚪ 当前未登录或使用匿名访问
            </div>
            <p style="font-size:0.84rem; color:var(--text-sec); line-height:1.5;">可使用管理员账号或设备 Token 登录，换取高速访问令牌。</p>
        `;
    }
}

function copyToClipboard(text) {
    if (text) {
        navigator.clipboard.writeText(text);
        showToast("已成功复制到剪贴板", "success");
    }
}

// ==================== 图表与统计中心 ====================
function getChartColors() {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark" || 
        (!document.documentElement.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
    return {
        textColor: isDark ? "#98989d" : "#8e8e93",
        gridColor: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)",
        accent: "#007aff",
        accentBg: "rgba(0,122,255,0.2)",
        palette: ["#007aff", "#34c759", "#ff9500", "#ff3b30", "#af52de", "#5856d6", "#5ac8fa"]
    };
}

async function fetchStatsAndRenderCharts() {
    try {
        const data = await apiRequest("/api/stats/summary");
        renderHardwareStats(data);
        renderCharts(data);
    } catch (_) {}
}

function renderHardwareStats(data) {
    if (!data) return;
    $("#stat-total-calls").textContent = data.total_calls || 0;
    $("#stat-success-rate").textContent = `${data.success_rate || 100}%`;
    
    if (data.system_metrics) {
        const sm = data.system_metrics;
        $("#stat-cpu-percent").textContent = `${sm.cpu_percent || 0}%`;
        $("#stat-temp").textContent = sm.temp_c ? `${sm.temp_c}°C` : "N/A";
        $("#stat-ram-percent").textContent = `${sm.ram_percent || 0}%`;
    }
}

function renderCharts(data) {
    if (typeof Chart === "undefined") return;
    const colors = getChartColors();

    const trendCtx = document.getElementById("chart-hourly-trend");
    if (trendCtx && data.hourly_timeline) {
        const labels = data.hourly_timeline.map(item => item.hour);
        const values = data.hourly_timeline.map(item => item.count);

        if (state.charts.trend) {
            state.charts.trend.data.labels = labels;
            state.charts.trend.data.datasets[0].data = values;
            state.charts.trend.update();
        } else {
            state.charts.trend = new Chart(trendCtx, {
                type: "line",
                data: {
                    labels: labels,
                    datasets: [{
                        label: "调用次数",
                        data: values,
                        borderColor: colors.accent,
                        backgroundColor: colors.accentBg,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 3,
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { color: colors.gridColor }, ticks: { color: colors.textColor, font: { size: 10 } } },
                        y: { grid: { color: colors.gridColor }, ticks: { color: colors.textColor, font: { size: 10 }, precision: 0 }, beginAtZero: true }
                    }
                }
            });
        }
    }

    const deviceCtx = document.getElementById("chart-device-dist");
    if (deviceCtx && data.device_distribution) {
        const labels = Object.keys(data.device_distribution);
        const values = Object.values(data.device_distribution);

        if (state.charts.devices) {
            state.charts.devices.data.labels = labels;
            state.charts.devices.data.datasets[0].data = values;
            state.charts.devices.update();
        } else {
            state.charts.devices = new Chart(deviceCtx, {
                type: "doughnut",
                data: {
                    labels: labels.length ? labels : ["暂无数据"],
                    datasets: [{
                        data: values.length ? values : [1],
                        backgroundColor: values.length ? colors.palette : ["#8e8e93"],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: "right", labels: { color: colors.textColor, font: { size: 11 } } } },
                    cutout: "68%"
                }
            });
        }
    }

    const stateCtx = document.getElementById("chart-state-dist");
    if (stateCtx && data.state_distribution) {
        const labels = Object.keys(data.state_distribution).map(k => k.replace(/_/g, " "));
        const values = Object.values(data.state_distribution);

        if (state.charts.states) {
            state.charts.states.data.labels = labels;
            state.charts.states.data.datasets[0].data = values;
            state.charts.states.update();
        } else {
            state.charts.states = new Chart(stateCtx, {
                type: "bar",
                data: {
                    labels: labels.length ? labels : ["暂无数据"],
                    datasets: [{
                        label: "触发次数",
                        data: values.length ? values : [0],
                        backgroundColor: "#34c759",
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: colors.textColor, font: { size: 10 } } },
                        y: { grid: { color: colors.gridColor }, ticks: { color: colors.textColor, font: { size: 10 }, precision: 0 }, beginAtZero: true }
                    }
                }
            });
        }
    }
}

function updateChartsTheme() {
    const colors = getChartColors();
    [state.charts.trend, state.charts.devices, state.charts.states].forEach(ch => {
        if (ch) {
            if (ch.options.scales?.x) ch.options.scales.x.ticks.color = colors.textColor;
            if (ch.options.scales?.y) ch.options.scales.y.ticks.color = colors.textColor;
            if (ch.options.scales?.x) ch.options.scales.x.grid.color = colors.gridColor;
            if (ch.options.scales?.y) ch.options.scales.y.grid.color = colors.gridColor;
            ch.update();
        }
    });
}

// Action Triggers (with Optimistic UI Instant Response)
async function triggerPreset(stateName, duration = 300) {
    const optimisticSnap = {
        current_state: stateName,
        hardware: state.snapshot?.hardware || { mode: "GPIOZERO_LGPIO" },
        channels: {
            red: { action: stateName === "error" ? "on" : "off", value: stateName === "error" ? 1.0 : 0.0, frequency: 1.0 },
            yellow: { action: ["thinking", "breathing", "restarting"].includes(stateName) ? "on" : "off", value: ["thinking", "breathing", "restarting"].includes(stateName) ? 1.0 : 0.0, frequency: 1.0 },
            green: { action: ["success", "startup"].includes(stateName) ? "on" : "off", value: ["success", "startup"].includes(stateName) ? 1.0 : 0.0, frequency: 1.0 }
        }
    };
    renderSnapshot(optimisticSnap);

    try {
        await apiRequest("/api/state", "POST", { state: stateName, duration });
        showToast(`状态已切换: ${stateName.toUpperCase()}`, "success");
    } catch (err) {
        if (state.snapshot) renderSnapshot(state.snapshot);
    }
}

async function triggerChannel(color, action, value = 1.0, frequency = 1.0) {
    if (state.snapshot?.channels?.[color]) {
        state.snapshot.channels[color].action = action;
        state.snapshot.channels[color].value = action === "off" ? 0.0 : parseFloat(value);
        state.snapshot.channels[color].frequency = parseFloat(frequency);
        renderSnapshot(state.snapshot);
    }

    try {
        await apiRequest("/api/led", "POST", { color, action, value: parseFloat(value), frequency: parseFloat(frequency), exclusive: false });
        showToast(`${color.toUpperCase()} -> ${action.toUpperCase()}`, "info");
    } catch (_) {}
}

async function triggerPattern(type) {
    try {
        await apiRequest("/api/pattern", "POST", { name: type });
        showToast(`播放动效: ${type}`, "info");
    } catch (_) {}
}

async function turnOffAll() {
    renderSnapshot({
        current_state: "off",
        hardware: state.snapshot?.hardware || { mode: "GPIOZERO_LGPIO" },
        channels: {
            red: { action: "off", value: 0.0, frequency: 1.0 },
            yellow: { action: "off", value: 0.0, frequency: 1.0 },
            green: { action: "off", value: 0.0, frequency: 1.0 }
        }
    });

    try {
        await apiRequest("/api/off", "POST");
        showToast("所有指示灯已熄灭", "info");
    } catch (_) {}
}

// Initialization
document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    $("#btn-theme").addEventListener("click", toggleTheme);
    $("#btn-refresh-logs").addEventListener("click", fetchAuditLogs);
    $("#btn-clear-logs").addEventListener("click", clearAuditLogs);
    $("#btn-refresh-charts").addEventListener("click", fetchStatsAndRenderCharts);
    $("#oauth-form").addEventListener("submit", handleOAuthLogin);
    $("#form-create-token").addEventListener("submit", handleCreateTokenSubmit);
    $("#form-hardware-config").addEventListener("submit", handleHardwareSubmit);
    $("#form-create-pattern").addEventListener("submit", handlePatternSubmit);

    ["red", "yellow", "green"].forEach((color) => {
        const slider = $(`#slider-${color}`);
        if (slider) {
            slider.addEventListener("input", (e) => {
                $(`#slider-val-${color}`).textContent = `${Math.round(parseFloat(e.target.value) * 100)}%`;
            });
            slider.addEventListener("change", (e) => {
                triggerChannel(color, "pwm", e.target.value);
            });
        }
    });

    ["red", "yellow", "green"].forEach((color) => {
        const freqSlider = $(`#freq-${color}`);
        if (freqSlider) {
            freqSlider.addEventListener("input", (e) => {
                $(`#freq-val-${color}`).textContent = `${parseFloat(e.target.value).toFixed(1)} Hz`;
            });
            freqSlider.addEventListener("change", (e) => {
                const currentAction = state.snapshot?.channels[color]?.action || "breath";
                triggerChannel(color, currentAction === "blink" ? "blink" : "breath", state.snapshot?.channels[color]?.value || 1.0, e.target.value);
            });
        }
    });

    connectWebSocket();
    apiRequest("/api/status").then(renderSnapshot).catch(() => {});
    fetchPatterns();
    fetchAuditLogs();
});
