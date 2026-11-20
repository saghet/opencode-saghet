const root = document.documentElement;
let lastTelemetry = null;
let selectedSessionId = null;

// Initialize Matrix Rain Engine
const matrixCanvas = document.getElementById("matrix-canvas");
const matrixEngine = new window.SaghetMatrixRain(matrixCanvas);
matrixEngine.start();

// Theme & Settings initialization
function applyTheme(theme) {
  root.setAttribute("data-theme", theme);
  localStorage.setItem("saghet-theme", theme);
  const sel = document.getElementById("cfg-theme");
  if (sel) sel.value = theme;
}

applyTheme(localStorage.getItem("saghet-theme") || "dark");

const cfgIntensity = document.getElementById("cfg-matrix-intensity");
const cfgFps = document.getElementById("cfg-matrix-fps");
const cfgTheme = document.getElementById("cfg-theme");
const cfgHudVisible = document.getElementById("cfg-hud-visible");
const rightHud = document.getElementById("right-hud");

cfgIntensity.value = matrixEngine.intensity;
cfgFps.value = String(matrixEngine.fpsCap);

cfgIntensity.addEventListener("change", () => matrixEngine.setConfig({ intensity: cfgIntensity.value }));
cfgFps.addEventListener("change", () => matrixEngine.setConfig({ fpsCap: Number(cfgFps.value) }));
cfgTheme.addEventListener("change", () => applyTheme(cfgTheme.value));
cfgHudVisible.addEventListener("change", () => {
  rightHud.classList.toggle("collapsed", !cfgHudVisible.checked);
});

const hudToggleBtn = document.getElementById("hud-toggle");
hudToggleBtn.classList.add("active");
hudToggleBtn.addEventListener("click", () => {
  const collapsed = rightHud.classList.toggle("collapsed");
  cfgHudVisible.checked = !collapsed;
  hudToggleBtn.classList.toggle("active", !collapsed);
});

document.getElementById("sidebar-toggle").addEventListener("click", () => {
  document.getElementById("sidebar").classList.toggle("collapsed");
});

// Navigation
function switchView(viewId) {
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((el) => el.classList.remove("active"));
  const target = document.getElementById(`view-${viewId}`);
  if (target) target.classList.add("active");
  const navBtn = document.querySelector(`.nav-item[data-nav="${viewId}"]`);
  if (navBtn) navBtn.classList.add("active");
  matrixEngine.setConfig({ activeView: viewId });
  if (window.location.hash !== `#${viewId}`) {
    history.replaceState(null, "", `#${viewId}`);
  }
}

document.querySelectorAll("[data-nav]").forEach((el) => {
  el.addEventListener("click", (e) => {
    e.preventDefault();
    switchView(el.getAttribute("data-nav"));
  });
});

if (window.location.hash) {
  const h = window.location.hash.slice(1);
  if (document.getElementById(`view-${h}`)) switchView(h);
}

// Notifications popover
const notifPopover = document.getElementById("notif-popover");
const notifBtn = document.getElementById("notif-btn");
notifBtn.addEventListener("click", () => {
  const hidden = notifPopover.classList.toggle("hidden");
  notifBtn.classList.toggle("active", !hidden);
});
document.getElementById("notif-close").addEventListener("click", () => {
  notifPopover.classList.add("hidden");
  notifBtn.classList.remove("active");
});

// Quick actions
const QUICK_PROMPTS = {
  create: "Diseña y crea la estructura inicial de un nuevo módulo siguiendo las convenciones del proyecto actual.",
  analyze: "Analiza la arquitectura y calidad del código del proyecto actual e identifica posibles mejoras.",
  tests: "Ejecuta la suite de pruebas del proyecto y resume cualquier fallo o cobertura pendiente.",
  research: "Investiga las dependencias, APIs y documentación relevantes en el repositorio actual.",
  optimize: "Revisa cuellos de botella de rendimiento, uso de memoria/VRAM y propone optimizaciones concretas.",
  security: "Realiza una auditoría de seguridad estática buscando secretos expuestos, permisos inseguros o vulnerabilidades.",
};

const promptInput = document.getElementById("prompt-input");
const quickChips = document.querySelectorAll(".quick-chip");

quickChips.forEach((btn) => {
  btn.setAttribute("aria-pressed", "false");
  btn.addEventListener("click", () => {
    const key = btn.getAttribute("data-quick");
    quickChips.forEach((c) => {
      c.classList.remove("active");
      c.setAttribute("aria-pressed", "false");
    });
    btn.classList.add("active");
    btn.setAttribute("aria-pressed", "true");
    promptInput.value = QUICK_PROMPTS[key] || "";
    promptInput.focus();
  });
});

promptInput.addEventListener("input", () => {
  const val = promptInput.value.trim();
  quickChips.forEach((c) => {
    const isMatch = val && val === (QUICK_PROMPTS[c.getAttribute("data-quick")] || "");
    c.classList.toggle("active", Boolean(isMatch));
    c.setAttribute("aria-pressed", isMatch ? "true" : "false");
  });
});

// Helpers
function fmtNum(n) {
  return Number(n || 0).toLocaleString("es-ES");
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function metricCard(label, value) {
  return `<div class="metric"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(value)}</div></div>`;
}

// Populate Composer Selectors
function syncComposerSelectors(data) {
  const agentSel = document.getElementById("select-agent");
  const modelSel = document.getElementById("select-model");
  const provSel = document.getElementById("select-provider");
  const projSel = document.getElementById("select-project");

  if (!agentSel.options.length) {
    const agents = Object.keys(data.config?.agents || {});
    agentSel.innerHTML = agents
      .map((a) => `<option value="${esc(a)}" ${a === data.config?.default_agent ? "selected" : ""}>${esc(a)}</option>`)
      .join("");
  }

  if (!modelSel.options.length) {
    const models = (data.ollama?.models || []).map((m) => `ollama/${m.name}`);
    const defModel = data.config?.model || models[0] || "";
    if (defModel && !models.includes(defModel)) models.unshift(defModel);
    modelSel.innerHTML = models
      .map((m) => `<option value="${esc(m)}" ${m === defModel ? "selected" : ""}>${esc(m)}</option>`)
      .join("");
  }

  if (!provSel.options.length) {
    const provs = data.providers || [];
    provSel.innerHTML = provs.length
      ? provs.map((p) => `<option value="${esc(p.id)}">${esc(p.name || p.id)}</option>`).join("")
      : `<option value="ollama">Ollama (Local)</option>`;
  }

  // Sync project selector whenever new projects appear
  const projs = data.projects || [];
  const currentProj = projSel.value;
  if (projs.length && (!projSel.options.length || projSel.options.length !== projs.length)) {
    projSel.innerHTML = projs
      .map((p) => `<option value="${esc(p.directory)}">${esc(p.name || p.directory)} — ${esc(p.directory)}</option>`)
      .join("");
    if (currentProj) projSel.value = currentProj;
  }
}

// Render Session Messages
async function openSessionDetail(sessionId, title) {
  selectedSessionId = sessionId;
  switchView("sessions");
  document.getElementById("session-detail-title").textContent = title || sessionId.slice(0, 16);
  document.getElementById("session-detail-meta").textContent = sessionId.slice(0, 18);
  const stream = document.getElementById("session-messages-view");
  stream.innerHTML = `<div class="empty-state">Cargando mensajes de la sesión...</div>`;

  try {
    const res = await fetch(`/api/session/messages?id=${encodeURIComponent(sessionId)}`);
    const payload = await res.json();
    const msgs = payload.data || [];
    if (!msgs.length) {
      stream.innerHTML = `<div class="empty-state">No hay mensajes registrados en esta sesión.</div>`;
      return;
    }
    stream.innerHTML = msgs
      .map((m) => {
        const info = m.info || {};
        const role = info.role || "assistant";
        const parts = (m.parts || [])
          .map((p) => {
            if (p.type === "text") return `<pre class="code-block">${esc(p.text || "")}</pre>`;
            if (p.type === "tool") {
              return `<div class="subpanel"><strong>Tool:</strong> <code>${esc(p.tool || "tool")}</code> <span class="tag">${esc(p.state?.status || "")}</span></div>`;
            }
            return `<div class="subpanel"><span class="tag">${esc(p.type)}</span></div>`;
          })
          .join("");
        return `<div class="msg-bubble ${esc(role)}">
          <div class="msg-meta"><span><strong>${esc(role.toUpperCase())}</strong> · ${esc(info.agent || "")}</span><span>${esc(info.modelID || "")}</span></div>
          ${parts || '<div class="empty-state">Sin contenido textual</div>'}
        </div>`;
      })
      .join("");
  } catch (err) {
    stream.innerHTML = `<div class="empty-state">Error al consultar mensajes: ${esc(err.message)}</div>`;
  }
}

// Render Notifications
function renderNotifications(data) {
  const alerts = [];
  if (!data.opencode_server_up) {
    alerts.push({ level: "err", text: "OpenCode Server (127.0.0.1:49374) no responde." });
  }
  if (!data.ollama?.up) {
    alerts.push({ level: "err", text: "Ollama (127.0.0.1:11434) no está activo." });
  }
  const gpu = data.gpu || {};
  if (gpu.available && gpu.vram_total_mib > 0) {
    const pct = (gpu.vram_used_mib / gpu.vram_total_mib) * 100;
    if (pct > 85) {
      alerts.push({ level: "warn", text: `Uso elevado de VRAM: ${Math.round(pct)}% (${Math.round(gpu.vram_used_mib)} MiB).` });
    }
  }
  const failed = (data.sessions || []).filter((s) => s.outcome === "failed" || s.outcome === "error");
  if (failed.length) {
    alerts.push({ level: "warn", text: `${failed.length} sesión(es) reciente(s) finalizaron con error.` });
  }
  if (!alerts.length) {
    alerts.push({ level: "ok", text: "Todos los servicios (OpenCode, Ollama, GPU) operan dentro de parámetros normales." });
  }

  const badge = document.getElementById("notif-badge");
  const warnCount = alerts.filter((a) => a.level !== "ok").length;
  badge.textContent = String(warnCount);
  badge.classList.toggle("hidden", warnCount === 0);

  document.getElementById("notif-list").innerHTML = alerts
    .map((a) => `<div class="list-row"><span>${esc(a.text)}</span><span class="tag tag-${a.level}">${a.level.toUpperCase()}</span></div>`)
    .join("");
}

// Main Telemetry Render
async function loadTelemetry() {
  try {
    const res = await fetch("/api/telemetry");
    const data = await res.json();
    lastTelemetry = data;

    // Topbar pills
    const pillOllama = document.getElementById("pill-ollama");
    pillOllama.className = `hud-pill ${data.ollama?.up ? "ok" : "err"}`;
    pillOllama.innerHTML = `<span class="dot"></span><span>Ollama: ${data.ollama?.up ? `${data.ollama.models_count} mod` : "OFF"}</span>`;

    const gpu = data.gpu || {};
    const pillGpu = document.getElementById("pill-gpu");
    if (gpu.available) {
      const vramPct = Math.round((gpu.vram_used_mib / gpu.vram_total_mib) * 100);
      pillGpu.className = `hud-pill ${vramPct > 85 ? "warn" : "ok"}`;
      pillGpu.textContent = `VRAM: ${Math.round(gpu.vram_used_mib)}/${Math.round(gpu.vram_total_mib)} MiB`;
    } else {
      pillGpu.className = "hud-pill err";
      pillGpu.textContent = "GPU: N/A";
    }

    const ram = data.ram || {};
    const pillRam = document.getElementById("pill-ram");
    pillRam.className = "hud-pill ok";
    pillRam.textContent = ram.total_mib ? `RAM: ${(ram.used_mib / 1024).toFixed(1)}/${(ram.total_mib / 1024).toFixed(0)}G` : "RAM: N/A";

    const srvLine = document.getElementById("server-status-line");
    srvLine.innerHTML = `<span class="dot ${data.opencode_server_up ? "ok" : "err"}"></span><span>${data.opencode_server_up ? "OpenCode API: Activo" : "OpenCode API: Inactivo"}</span>`;

    syncComposerSelectors(data);
    renderNotifications(data);

    // Session tabs in topbar
    const sessions = data.sessions || [];
    document.getElementById("session-tabs").innerHTML = sessions
      .slice(0, 4)
      .map(
        (s) =>
          `<button class="session-tab ${s.id === selectedSessionId ? "active" : ""}" data-sid="${esc(s.id)}">${esc((s.title || s.id).slice(0, 20))}</button>`
      )
      .join("");
    document.querySelectorAll(".session-tab").forEach((tab) => {
      tab.addEventListener("click", () => openSessionDetail(tab.getAttribute("data-sid"), tab.textContent));
    });

    // Home HW summary
    const cpu = data.cpu || {};
    document.getElementById("home-hw-metrics").innerHTML = [
      metricCard("CPU", `${cpu.usage_pct ?? 0}% (${cpu.cores ?? "-"}c)`),
      metricCard("GPU", gpu.available ? `${gpu.utilization_pct}% · ${gpu.temp_c}°C` : "N/A"),
      metricCard("VRAM", gpu.available ? `${Math.round(gpu.vram_used_mib)} MiB` : "N/A"),
      metricCard("Tokens In/Out", `${fmtNum(data.token_totals?.input)} / ${fmtNum(data.token_totals?.output)}`),
    ].join("");

    // Home recent sessions
    document.getElementById("home-recent-sessions").innerHTML = sessions.length
      ? sessions
          .slice(0, 5)
          .map(
            (s) => `<div class="list-row clickable" data-open-sid="${esc(s.id)}" data-title="${esc(s.title || s.id)}">
              <span><strong>${esc(s.title || s.id.slice(0, 14))}</strong><br><small>${esc(s.agent || "default")}</small></span>
              <span class="tag ${s.outcome === "succeeded" ? "tag-ok" : ""}">${esc(s.outcome || "running")}</span>
            </div>`
          )
          .join("")
      : `<div class="empty-state">Sin sesiones recientes.</div>`;

    // Full sessions list
    document.getElementById("sessions-full-list").innerHTML = sessions.length
      ? sessions
          .map(
            (s) => `<div class="list-row clickable ${s.id === selectedSessionId ? "selected" : ""}" data-open-sid="${esc(s.id)}" data-title="${esc(s.title || s.id)}">
              <span><strong>${esc((s.title || s.id).slice(0, 28))}</strong><br><small>${esc(s.agent || "-")} · ${esc(s.parentID ? "Subagente" : "Raíz")}</small></span>
              <span class="tag ${s.outcome === "succeeded" ? "tag-ok" : s.outcome === "failed" ? "tag-err" : ""}">${esc(s.outcome || "running")}</span>
            </div>`
          )
          .join("")
      : `<div class="empty-state">No hay sesiones registradas.</div>`;

    document.querySelectorAll("[data-open-sid]").forEach((row) => {
      row.addEventListener("click", () => openSessionDetail(row.getAttribute("data-open-sid"), row.getAttribute("data-title")));
    });

    // Projects
    renderProjectsGrid();

    // Agents
    const agents = Object.entries(data.config?.agents || {});
    document.getElementById("agents-cards-grid").innerHTML = agents
      .map(([name, a]) => {
        const perms = Object.entries(a.tools || {})
          .map(([k, v]) => `<span class="tag ${v ? "tag-ok" : "tag-err"}">${esc(k)}:${v ? "on" : "off"}</span>`)
          .join(" ");
        return `<div class="card">
          <div class="card-head"><h2>${esc(name)}</h2><span class="tag tag-ok">${esc(a.mode)}</span></div>
          <p class="view-sub">${esc(a.description || "Especialista OpenCode-Saghet")}</p>
          <div class="subpanel">Modelo: <code>${esc(a.model)}</code></div>
          <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px;">${perms || '<span class="tag">default</span>'}</div>
        </div>`;
      })
      .join("");

    // Performance & Ollama
    document.getElementById("perf-hw-grid").innerHTML = [
      metricCard("CPU Uso", `${cpu.usage_pct ?? 0}% (Load ${cpu.load_1m ?? 0})`),
      metricCard("RAM Usada", ram.total_mib ? `${(ram.used_mib / 1024).toFixed(1)} / ${(ram.total_mib / 1024).toFixed(1)} GiB` : "N/A"),
      metricCard("GPU Uso", gpu.available ? `${gpu.utilization_pct}%` : "N/A"),
      metricCard("GPU Temp / Power", gpu.available ? `${gpu.temp_c}°C · ${gpu.power_w}W` : "N/A"),
      metricCard("Matrix Canvas FPS", matrixEngine.intensity === "off" ? "OFF" : `${matrixEngine.measuredFps || matrixEngine.fpsCap} fps`),
    ].join("");

    if (gpu.available) {
      const pct = Math.min(100, Math.round((gpu.vram_used_mib / gpu.vram_total_mib) * 100));
      document.getElementById("perf-vram-bar-wrap").innerHTML = `
        <div class="hud-bar-head"><span>VRAM (${esc(gpu.name)})</span><span>${Math.round(gpu.vram_used_mib)} / ${Math.round(gpu.vram_total_mib)} MiB (${pct}%)</span></div>
        <div class="progress-track"><div class="progress-fill ${pct > 85 ? "warn" : ""}" style="width:${pct}%"></div></div>`;
    }

    const running = data.ollama?.running || [];
    document.getElementById("perf-ollama-ps").innerHTML = running.length
      ? running
          .map((m) => `<strong>En VRAM:</strong> <code>${esc(m.name)}</code> · Contexto: ${m.context_length ?? "N/A"} · VRAM: ${((m.size_vram || 0) / 1e9).toFixed(2)} GB`)
          .join("<br>")
      : "<strong>Ollama VRAM:</strong> Ningún modelo cargado actualmente en GPU.";

    document.getElementById("ollama-models-table").innerHTML = `<table>
      <thead><tr><th>Modelo</th><th>Tamaño</th><th>Parámetros</th><th>Quant</th></tr></thead>
      <tbody>${(data.ollama?.models || [])
        .map((m) => `<tr><td><code>${esc(m.name)}</code></td><td>${m.size_gb} GB</td><td>${esc(m.parameter_size || "-")}</td><td>${esc(m.quantization || "-")}</td></tr>`)
        .join("")}</tbody></table>`;

    const benches = data.benchmarks?.benchmarks || [];
    document.getElementById("benchmarks-table").innerHTML = benches.length
      ? `<table><thead><tr><th>Modelo</th><th>tok/s</th><th>TTFT</th><th>VRAM</th></tr></thead>
        <tbody>${benches
          .map((b) => `<tr><td><code>${esc(b.model)}</code></td><td><strong>${b.tok_per_s}</strong></td><td>${b.ttft_ms} ms</td><td>${b.vram_used_mib} MiB</td></tr>`)
          .join("")}</tbody></table>`
      : `<div class="empty-state">Sin benchmarks registrados.</div>`;

    // Plugins, Tools, Databases, MCP
    document.getElementById("plugins-list").innerHTML = [
      `<div class="card"><h2>saghet-tui (Local)</h2><p class="view-sub">Plugin TUI nativo con identidad Matrix Protocol.</p><span class="tag tag-ok">Activo</span></div>`,
      `<div class="card"><h2>opencode-mem (:4747)</h2><p class="view-sub">Memoria persistente local.</p><span class="tag ${data.opencode_mem_up ? "tag-ok" : "tag-warn"}">${data.opencode_mem_up ? "Activo" : "Inactivo"}</span></div>`,
      ...(data.config?.plugins || []).map(
        (p) => `<div class="card"><h2>${esc(p)}</h2><p class="view-sub">Plugin declarado en opencode.json</p><span class="tag tag-ok">Configurado</span></div>`
      ),
    ].join("");

    document.getElementById("skills-list").innerHTML = (data.skills || [])
      .map((s) => `<div class="list-row"><span><strong>${esc(s.name)}</strong><br><small>${esc(s.path)}</small></span><span class="tag tag-ok">Instalada</span></div>`)
      .join("");

    document.getElementById("providers-list").innerHTML = (data.providers || [])
      .map((p) => `<div class="list-row"><span><strong>${esc(p.name || p.id)}</strong><br><small>${esc(p.settings?.baseURL || "")}</small></span><span class="tag tag-ok">${esc(p.activation || "enabled")}</span></div>`)
      .join("");

    const dbs = data.databases || [];
    document.getElementById("databases-list").innerHTML = dbs.length
      ? dbs
          .map(
            (d) => `<div class="card"><h2>${esc(d.id || "source")}</h2><p class="view-sub">Tipo: ${esc(d.type || "-")} · Readonly: ${esc(d.readonly || "true")}</p><span class="tag tag-ok">DBHub</span></div>`
          )
          .join("")
      : `<div class="card"><h2>Sin fuentes activas</h2><p class="view-sub">Configura tus bases de datos en ~/.config/opencode/dbhub.toml.</p></div>`;

    document.getElementById("mcp-list").innerHTML = Object.entries(data.config?.mcp || {})
      .map(
        ([name, info]) => `<div class="card"><h2>${esc(name)}</h2><p class="view-sub">Tipo: ${esc(info.type)}</p><span class="tag ${info.enabled ? "tag-ok" : "tag-err"}">${info.enabled ? "Habilitado" : "Deshabilitado"}</span></div>`
      )
      .join("");

    // Settings summary
    document.getElementById("settings-summary").innerHTML = [
      `<div class="list-row"><span>Agente por defecto</span><code>${esc(data.config?.default_agent || "-")}</code></div>`,
      `<div class="list-row"><span>Modelo principal</span><code>${esc(data.config?.model || "-")}</code></div>`,
      `<div class="list-row"><span>OpenCode Server</span><span class="tag ${data.opencode_server_up ? "tag-ok" : "tag-err"}">${data.opencode_server_up ? "127.0.0.1:49374" : "Offline"}</span></div>`,
      `<div class="list-row"><span>Reduced Motion OS</span><span class="tag">${matrixEngine.reducedMotion ? "Activo" : "Inactivo"}</span></div>`,
    ].join("");

    // Right HUD
    const runningSess = sessions.filter((s) => !s.outcome || s.outcome === "running").length;
    const okSess = sessions.filter((s) => s.outcome === "succeeded").length;
    const waitSess = Math.max(0, agents.length - runningSess);
    document.getElementById("hud-agent-counts").innerHTML = `
      <div class="hud-stat"><span>Activos</span><strong>${agents.length}</strong></div>
      <div class="hud-stat"><span>Ejecutando</span><strong>${runningSess}</strong></div>
      <div class="hud-stat"><span>Esperando</span><strong>${waitSess}</strong></div>
      <div class="hud-stat"><span>Finalizados</span><strong>${okSess}</strong></div>`;

    const ramPct = ram.total_mib ? Math.round((ram.used_mib / ram.total_mib) * 100) : 0;
    const vramPct = gpu.available ? Math.round((gpu.vram_used_mib / gpu.vram_total_mib) * 100) : 0;
    const benchTop = benches.find((b) => b.model === (running[0]?.name || "qwen3.5:9b"));
    document.getElementById("hud-hw-bars").innerHTML = `
      <div><div class="hud-bar-head"><span>CPU</span><span>${cpu.usage_pct ?? 0}%</span></div><div class="progress-track"><div class="progress-fill" style="width:${Math.min(100, cpu.usage_pct ?? 0)}%"></div></div></div>
      <div><div class="hud-bar-head"><span>RAM</span><span>${ramPct}%</span></div><div class="progress-track"><div class="progress-fill" style="width:${ramPct}%"></div></div></div>
      <div><div class="hud-bar-head"><span>VRAM</span><span>${vramPct}%</span></div><div class="progress-track"><div class="progress-fill ${vramPct > 85 ? "warn" : ""}" style="width:${vramPct}%"></div></div></div>
      <div class="hud-bar-head"><span>GPU / Tok·s</span><span>${gpu.available ? `${gpu.utilization_pct}%` : "N/A"} · ${benchTop ? `${benchTop.tok_per_s} t/s` : "--"}</span></div>`;

    document.getElementById("hud-ollama-box").innerHTML = running.length
      ? running.map((m) => `<div class="hud-item"><code>${esc(m.name)}</code><br><small>VRAM: ${((m.size_vram || 0) / 1e9).toFixed(2)} GB</small></div>`).join("")
      : `<div class="hud-item">Estado: <strong>${data.ollama?.up ? "En espera" : "Inactivo"}</strong><br><small>Sin modelo cargado en VRAM</small></div>`;

    const delegated = sessions.filter((s) => s.parentID).slice(0, 4);
    document.getElementById("hud-delegations").innerHTML = delegated.length
      ? delegated.map((s) => `<div class="hud-item"><strong>${esc(s.agent || "subagent")}</strong><br><small>${esc((s.title || s.id).slice(0, 28))}</small></div>`).join("")
      : `<div class="hud-item">Sin delegaciones recientes.</div>`;

    document.getElementById("hud-activity").innerHTML = sessions
      .slice(0, 4)
      .map((s) => `<div class="hud-item"><strong>${esc((s.title || s.id).slice(0, 24))}</strong><br><small>${esc(s.agent || "-")} · ${esc(s.outcome || "running")}</small></div>`)
      .join("");
  } catch (err) {
    console.error("Telemetry error:", err);
  }
}

// Prompt execution (async streaming job without artificial 90s timeout)
let activeJobId = null;
let jobPollTimer = null;

const runPromptBtn = document.getElementById("run-prompt-btn");
const cancelJobBtn = document.getElementById("cancel-job-btn");

function stopJobPolling() {
  if (jobPollTimer) {
    clearInterval(jobPollTimer);
    jobPollTimer = null;
  }
  cancelJobBtn?.classList.add("hidden");
  runPromptBtn.disabled = false;
}

runPromptBtn.addEventListener("click", async () => {
  const prompt = document.getElementById("prompt-input").value.trim();
  if (!prompt) return;

  stopJobPolling();
  const statusTag = document.getElementById("composer-status");
  const outCard = document.getElementById("live-output-card");
  const outPre = document.getElementById("live-output-pre");
  statusTag.textContent = "INICIANDO...";
  statusTag.className = "tag tag-warn";
  outCard.classList.remove("hidden");
  outPre.textContent = "Conectando con OpenCode y cargando modelo local en VRAM...";
  runPromptBtn.disabled = true;

  try {
    const res = await fetch("/api/session/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        agent: document.getElementById("select-agent").value,
        model: document.getElementById("select-model").value,
        directory: document.getElementById("select-project").value,
      }),
    });
    const data = await res.json();
    if (!data.ok || !data.job_id) {
      statusTag.textContent = "ERROR";
      statusTag.className = "tag tag-err";
      outPre.textContent = data.error || "No se pudo iniciar la ejecución.";
      runPromptBtn.disabled = false;
      return;
    }

    activeJobId = data.job_id;
    cancelJobBtn?.classList.remove("hidden");

    const pollJob = async () => {
      if (!activeJobId) return;
      try {
        const jr = await fetch(`/api/session/job?id=${encodeURIComponent(activeJobId)}`);
        const job = await jr.json();
        const subs = (job.active_subagents || [])
          .map((s) => `${s.agent || "agente"}${s.title ? ` (${s.title})` : ""}`)
          .join(", ");
        if (job.output || subs) {
          const footer = job.status === "running" && subs ? `\n\n▸ Procesando ahora: ${subs}` : "";
          outPre.textContent = (job.output || "Iniciando ejecución...") + footer;
          outPre.scrollTop = outPre.scrollHeight;
        }
        if (job.status === "running") {
          statusTag.textContent = `EJECUTANDO · ${Math.round(job.elapsed_s || 0)}s`;
          statusTag.className = "tag tag-warn";
          return;
        }
        stopJobPolling();
        if (job.status === "succeeded") {
          statusTag.textContent = `COMPLETADO (${Math.round(job.elapsed_s || 0)}s)`;
          statusTag.className = "tag tag-ok";
          if (!job.output) outPre.textContent = "Ejecución completada sin salida adicional.";
        } else if (job.status === "cancelled") {
          statusTag.textContent = "DETENIDO";
          statusTag.className = "tag tag-warn";
        } else {
          statusTag.textContent = "ERROR";
          statusTag.className = "tag tag-err";
        }
        loadTelemetry();
      } catch (e) {
        stopJobPolling();
        statusTag.textContent = "ERROR";
        statusTag.className = "tag tag-err";
        outPre.textContent = String(e);
      }
    };

    jobPollTimer = setInterval(pollJob, 1200);
    pollJob();
  } catch (err) {
    stopJobPolling();
    statusTag.textContent = "ERROR";
    statusTag.className = "tag tag-err";
    outPre.textContent = String(err);
  }
});

cancelJobBtn?.addEventListener("click", async () => {
  if (!activeJobId) return;
  await fetch("/api/session/job/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: activeJobId }),
  });
});

document.getElementById("clear-output-btn").addEventListener("click", () => {
  document.getElementById("live-output-card").classList.add("hidden");
});

document.getElementById("run-doctor-btn").addEventListener("click", async () => {
  const out = document.getElementById("diagnostics-output");
  out.textContent = "Ejecutando doctor.sh...";
  try {
    const res = await fetch("/api/diagnostics");
    const data = await res.json();
    out.textContent = data.output || "Sin salida.";
  } catch (err) {
    out.textContent = String(err);
  }
});

function renderProjectsGrid() {
  const grid = document.getElementById("projects-grid");
  if (!grid || !lastTelemetry) return;
  const q = (document.getElementById("projects-search")?.value || "").trim().toLowerCase();
  const projects = (lastTelemetry.projects || []).filter((p) => {
    if (!q) return true;
    return (p.name || "").toLowerCase().includes(q) || (p.directory || "").toLowerCase().includes(q);
  });

  if (!projects.length) {
    grid.innerHTML = `<div class="card"><div class="empty-state">No se encontraron proyectos que coincidan con "${esc(q)}".</div></div>`;
    return;
  }

  const activeProject = document.getElementById("select-project")?.value || "";
  grid.innerHTML = projects
    .map((p) => {
      const isSelected = p.directory === activeProject;
      return `<div class="card ${isSelected ? "selected-project" : ""}">
        <div class="card-head">
          <h2>${esc(p.name || p.directory.split("/").pop() || p.directory)}</h2>
          <div style="display:flex;gap:6px;align-items:center;">
            ${isSelected ? `<span class="tag tag-ok">ACTIVO</span>` : ""}
            ${p.vcs ? `<span class="tag tag-ok">${esc(p.vcs)}</span>` : `<span class="tag">local</span>`}
          </div>
        </div>
        <p class="view-sub"><code>${esc(p.directory)}</code></p>
        <div class="subpanel" style="display:flex;justify-content:space-between;align-items:center;">
          <span>Sesiones: <strong>${p.sessions ?? 0}</strong></span>
          <button class="btn ${isSelected ? "active" : "btn-primary"}" data-use-project="${esc(p.directory)}">${isSelected ? "Contexto activo" : "Usar contexto →"}</button>
        </div>
      </div>`;
    })
    .join("");

  grid.querySelectorAll("[data-use-project]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dir = btn.getAttribute("data-use-project");
      const projSel = document.getElementById("select-project");
      if (projSel) projSel.value = dir;
      switchView("home");
      document.getElementById("prompt-input")?.focus();
    });
  });
}

document.getElementById("projects-search")?.addEventListener("input", renderProjectsGrid);
document.getElementById("select-project")?.addEventListener("change", renderProjectsGrid);
const toggleAddProjBtn = document.getElementById("toggle-add-project-btn");
toggleAddProjBtn?.addEventListener("click", () => {
  const hidden = document.getElementById("add-project-panel")?.classList.toggle("hidden");
  toggleAddProjBtn.classList.toggle("active", !hidden);
});
document.getElementById("submit-add-project-btn")?.addEventListener("click", async () => {
  const dir = document.getElementById("add-project-path")?.value.trim();
  const create = document.getElementById("add-project-create")?.checked;
  const msg = document.getElementById("add-project-msg");
  if (!dir) {
    msg.textContent = "Introduce una ruta válida.";
    return;
  }
  msg.textContent = "Registrando proyecto en OpenCode...";
  try {
    const res = await fetch("/api/projects/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ directory: dir, create_if_missing: Boolean(create) }),
    });
    const out = await res.json();
    if (out.ok) {
      msg.textContent = `Proyecto añadido: ${out.directory}`;
      document.getElementById("add-project-path").value = "";
      await loadTelemetry();
    } else {
      msg.textContent = `Error: ${out.error || out.output || "No se pudo añadir"}`;
    }
  } catch (err) {
    msg.textContent = `Error: ${err.message}`;
  }
});

document.getElementById("refresh-btn").addEventListener("click", loadTelemetry);
loadTelemetry();
setInterval(loadTelemetry, 8000);
