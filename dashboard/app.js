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
function getCsrfToken() {
  return document.querySelector('meta[name="saghet-csrf-token"]')?.getAttribute("content") || "";
}

function authHeaders(extra = {}) {
  const tok = getCsrfToken();
  return {
    "Content-Type": "application/json",
    ...(tok ? { "X-Saghet-Token": tok, "X-CSRF-Token": tok } : {}),
    ...extra,
  };
}

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

  const projs = data.projects || [];
  const currentProj = projSel.value;
  if (projs.length && (!projSel.options.length || projSel.options.length !== projs.length)) {
    projSel.innerHTML = projs
      .map((p) => `<option value="${esc(p.directory)}">${esc(p.name || p.directory)} — ${esc(p.directory)}</option>`)
      .join("");
    if (currentProj) projSel.value = currentProj;
  }
}

// Module 5: Render Session Messages
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
    alerts.push({ level: "ok", text: "Todos los servicios (OpenCode, Ollama, GPU, Gentle AI, Harness ACP) operan normalmente." });
  }

  const badge = document.getElementById("notif-badge");
  const warnCount = alerts.filter((a) => a.level !== "ok").length;
  badge.textContent = String(warnCount);
  badge.classList.toggle("hidden", warnCount === 0);

  document.getElementById("notif-list").innerHTML = alerts
    .map((a) => `<div class="list-row"><span>${esc(a.text)}</span><span class="tag tag-${a.level}">${a.level.toUpperCase()}</span></div>`)
    .join("");
}

// Render Module 1: Agent Command Center (Delegation Tree & Supervisor Decisions)
function renderAgentCommandCenter(data) {
  const sessions = data.sessions || [];
  const roots = sessions.filter((s) => !s.parentID).slice(0, 8);
  const childrenByParent = {};
  sessions.forEach((s) => {
    if (s.parentID) {
      (childrenByParent[s.parentID] = childrenByParent[s.parentID] || []).push(s);
    }
  });

  const treeEl = document.getElementById("delegation-tree-list");
  if (treeEl) {
    treeEl.innerHTML = roots.length
      ? roots
          .map((r) => {
            const kids = childrenByParent[r.id] || [];
            const kidsHtml = kids.length
              ? `<div class="tree-branch">${kids
                  .map(
                    (k) => `<div class="list-row clickable" data-open-sid="${esc(k.id)}" data-title="${esc(k.title || k.id)}">
                      <span>↳ <strong>${esc(k.agent || "subagent")}</strong> · <small>${esc((k.title || k.id).slice(0, 32))}</small></span>
                      <span class="tag ${k.outcome === "succeeded" ? "tag-ok" : ""}">${esc(k.outcome || "running")}</span>
                    </div>`
                  )
                  .join("")}</div>`
              : "";
            return `<div>
              <div class="list-row clickable" data-open-sid="${esc(r.id)}" data-title="${esc(r.title || r.id)}">
                <span><strong>${esc(r.agent || "saghet-orchestrator")}</strong> · ${esc((r.title || r.id).slice(0, 36))}</span>
                <span class="tag tag-ok">${kids.length} sub</span>
              </div>
              ${kidsHtml}
            </div>`;
          })
          .join("")
      : `<div class="empty-state">Sin árbol de delegaciones registrado aún.</div>`;
  }

  const decisions = data.supervisor?.decisions || [];
  const supEl = document.getElementById("supervisor-decisions-list");
  if (supEl) {
    supEl.innerHTML = decisions.length
      ? decisions
          .slice(0, 10)
          .map((d) => {
            const v = d.verdict || "PLANNED";
            const cls = v === "ACCEPT" || v === "PLANNED" ? "tag-ok" : v === "CORRECT" ? "tag-warn" : "tag-err";
            const errs = [...(d.reasoning_errors || []), ...(d.missing_evidence || [])];
            return `<div class="list-row">
              <span>
                <strong>${esc(d.agent || d.primary_specialist || "supervisor")}</strong> · ${esc(d.phase || "gate")}
                ${d.iteration ? `(Intento ${d.iteration}/${d.max_iterations || 3})` : ""}
                <br><small>${esc(errs.length ? errs[0].slice(0, 75) : `Modelo: ${d.selected_model || "ollama/qwen3.5:9b"}`)}</small>
              </span>
              <span class="tag ${cls}">${esc(v)}</span>
            </div>`;
          })
          .join("")
      : `<div class="empty-state">Sin decisiones registradas en el Supervisor.</div>`;
  }
}

// Render Module 2: Model Intelligence
function renderModelIntelligence(data) {
  const modelsMap = data.evaluation_matrix?.models || {};
  const entries = Object.entries(modelsMap);

  const specTable = document.getElementById("specialty-scores-table");
  if (specTable) {
    specTable.innerHTML = entries.length
      ? `<table>
          <thead><tr><th>Modelo</th><th>Params</th><th>Classification</th><th>Coding</th><th>Architecture</th><th>Indep. Review</th><th>Security Audit</th></tr></thead>
          <tbody>${entries
            .map(([name, m]) => {
              const sc = m.specialty_scores || {};
              return `<tr>
                <td><code>${esc(name)}</code></td>
                <td>${esc(m.parameter_size || "-")}</td>
                <td><strong>${sc.classification ?? "-"}</strong></td>
                <td><strong>${sc.coding ?? "-"}</strong></td>
                <td><strong>${sc.architecture ?? "-"}</strong></td>
                <td><strong>${sc.independent_review ?? "-"}</strong></td>
                <td><strong>${sc.security_audit ?? "-"}</strong></td>
              </tr>`;
            })
            .join("")}</tbody></table>`
      : `<div class="empty-state">Sin matriz de evaluación cargada.</div>`;
  }

  const metricsTable = document.getElementById("model-intel-table");
  if (metricsTable) {
    metricsTable.innerHTML = entries.length
      ? `<table>
          <thead><tr>
            <th>Modelo</th><th>Calidad Código</th><th>First-Pass</th><th>Test Pass</th><th>Regresión</th>
            <th>Tool-Call</th><th>tok/s</th><th>TTFT</th><th>VRAM Pico</th><th>Recup. Error</th><th>Razonamiento</th>
          </tr></thead>
          <tbody>${entries
            .map(([name, m]) => {
              const mt = m.metrics || {};
              const vramWarn = (mt.peak_vram_mib || 0) > 7800;
              return `<tr>
                <td><code>${esc(name)}</code></td>
                <td>${mt.code_quality_score}%</td>
                <td>${mt.first_pass_success_pct}%</td>
                <td>${mt.test_pass_rate_pct}%</td>
                <td>${mt.regression_rate_pct}%</td>
                <td>${mt.tool_calling_reliability_pct}%</td>
                <td><strong>${mt.tok_per_s}</strong></td>
                <td>${mt.ttft_ms} ms</td>
                <td><span class="tag ${vramWarn ? "tag-err" : "tag-ok"}">${mt.peak_vram_mib} MiB</span></td>
                <td>${mt.error_recovery_rate_pct}%</td>
                <td>${mt.reasoning_planning_score}%</td>
              </tr>`;
            })
            .join("")}</tbody></table>`
      : `<div class="empty-state">Sin métricas disponibles.</div>`;
  }
}

// Render Module 3 & 4: Workflow Orchestration (DAG) & Task Board
function renderWorkflowsAndTaskBoard(data) {
  const tasks = data.harness?.task_board || [];
  const traces = data.harness?.traces || [];

  const dagFlow = document.getElementById("dag-visual-flow");
  if (dagFlow) {
    const sampleNodes = tasks.length
      ? tasks.slice(0, 6).reverse()
      : [
          { task_id: "step_1", title: "1. Gentle AI Clasificación", specialist: "saghet-orchestrator", status: "DONE" },
          { task_id: "step_2", title: "2. Diseño & Contratos", specialist: "architect", status: "DONE" },
          { task_id: "step_3", title: "3. Implementación Worktree", specialist: "senior-developer", status: "DONE" },
          { task_id: "step_4", title: "4. Revisión Independiente", specialist: "code-reviewer", status: "DONE" },
          { task_id: "step_5", title: "5. Verificación QA", specialist: "qa-engineer", status: "DONE" },
        ];
    dagFlow.innerHTML = sampleNodes
      .map((n, idx) => {
        const st = n.status || "PENDING";
        const tagCls = st === "DONE" || st === "RECOVERED" ? "tag-ok" : st === "FAILED" || st === "BLOCKED" ? "tag-err" : "tag-warn";
        const nodeHtml = `<div class="dag-node">
          <div><strong>${esc(n.title || n.task_id)}</strong></div>
          <div class="view-sub"><code>${esc(n.specialist || "agent")}</code></div>
          <div style="margin-top:4px;"><span class="tag ${tagCls}">${esc(st)}</span></div>
        </div>`;
        return idx < sampleNodes.length - 1 ? `${nodeHtml}<span class="dag-arrow">──►</span>` : nodeHtml;
      })
      .join("");
  }

  const tracesEl = document.getElementById("harness-traces-list");
  if (tracesEl) {
    tracesEl.innerHTML = traces.length
      ? traces
          .slice(0, 15)
          .map(
            (t) => `<div class="list-row">
              <span>
                <strong>${esc(t.event_type)}</strong> · <code>${esc(t.workflow_id || "")}</code>
                ${t.node_id ? `· Nodo: <code>${esc(t.node_id)}</code>` : ""}
                <br><small>${esc(JSON.stringify(t.details || {}).slice(0, 110))}</small>
              </span>
              <span class="tag">${esc((t.timestamp || "").slice(11, 19))}</span>
            </div>`
          )
          .join("")
      : `<div class="empty-state">Sin trazas de ejecución registradas. Pulsa "Ejecutar Workflow DAG Verificado" para generar trazas.</div>`;
  }

  // Task Board columns
  const pending = tasks.filter((t) => t.status === "PENDING" || t.status === "READY");
  const running = tasks.filter((t) => t.status === "IN_PROGRESS" || t.status === "VERIFYING");
  const done = tasks.filter((t) => t.status === "DONE" || t.status === "RECOVERED");
  const failed = tasks.filter((t) => t.status === "FAILED" || t.status === "BLOCKED");

  const renderTaskCard = (t, variant = "") => `<div class="task-card ${variant}">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <strong>${esc(t.title || t.task_id)}</strong>
      <span class="tag">${esc(t.status)}</span>
    </div>
    <div><small>Agente: <code>${esc(t.specialist)}</code> · Intento: ${t.attempts ?? 1}</small></div>
    <div><small>Sesión: <code>${esc((t.opencode_session_id || "").slice(0, 16))}</code></small></div>
    ${t.error ? `<div style="color:var(--error);"><small>${esc(t.error)}</small></div>` : ""}
  </div>`;

  document.getElementById("cnt-tb-pending").textContent = String(pending.length);
  document.getElementById("cnt-tb-running").textContent = String(running.length);
  document.getElementById("cnt-tb-done").textContent = String(done.length);
  document.getElementById("cnt-tb-failed").textContent = String(failed.length);

  document.getElementById("col-tb-pending").innerHTML = pending.length ? pending.map((t) => renderTaskCard(t)).join("") : `<div class="empty-state">Vacío</div>`;
  document.getElementById("col-tb-running").innerHTML = running.length ? running.map((t) => renderTaskCard(t, "warn")).join("") : `<div class="empty-state">Vacío</div>`;
  document.getElementById("col-tb-done").innerHTML = done.length ? done.map((t) => renderTaskCard(t)).join("") : `<div class="empty-state">Vacío</div>`;
  document.getElementById("col-tb-failed").innerHTML = failed.length ? failed.map((t) => renderTaskCard(t, "err")).join("") : `<div class="empty-state">Vacío</div>`;
}

// Render Module 6: Memory Explorer
function renderMemoryExplorer(data) {
  const mem = data.memory || {};
  const tiers = mem.tiers || {};
  const eco = mem.ecosystem || {};

  const metricsEl = document.getElementById("memory-tiers-metrics");
  if (metricsEl) {
    metricsEl.innerHTML = [
      metricCard("Tier: Sesión", `${tiers.session?.count ?? 0} rec`),
      metricCard("Tier: Proyecto", `${tiers.project?.count ?? 0} rec`),
      metricCard("Tier: Experiencias", `${tiers.experience?.count ?? 0} rec`),
      metricCard("Tier: Usuario", `${tiers.user?.count ?? 0} rec`),
      metricCard("opencode-mem (:4747)", data.opencode_mem_up ? `Activo (${eco.opencode_mem?.model || "9b"})` : "Inactivo"),
      metricCard("DCP Protect User", eco.dcp?.protect_user_messages ? "PROTEGIDO" : "OFF"),
    ].join("");
  }

  const recentEl = document.getElementById("memory-recent-list");
  if (recentEl) {
    const rec = mem.recent_memories || [];
    recentEl.innerHTML = rec.length
      ? rec
          .map(
            (m) => `<div class="list-row">
              <span>
                <strong>[${esc(m.tier.toUpperCase())} · ${esc(m.category)}]</strong> ${esc(m.title)}
                <br><small>${esc(m.content.slice(0, 120))} — Procedencia: <code>${esc(m.provenance)}</code> · ${esc(m.updated_at)}</small>
              </span>
              <span class="tag tag-ok">Conf: ${Math.round((m.confidence || 0) * 100)}% (x${m.occurrence_count || 1})</span>
            </div>`
          )
          .join("")
      : `<div class="empty-state">Sin recuerdos registrados aún.</div>`;
  }
}

// Render Module 8: Security Center
function renderSecurityCenter(data) {
  const sec = data.security || {};
  const grid = document.getElementById("security-posture-grid");
  if (grid) {
    grid.innerHTML = [
      metricCard("Token Auth 256-bit", sec.auth_enabled ? "ACTIVO" : "OFF"),
      metricCard("Anti-CSRF / Origin", sec.csrf_protection ? "ACTIVO" : "OFF"),
      metricCard("DNS Rebinding Guard", sec.dns_rebinding_guard ? "ACTIVO" : "OFF"),
      metricCard("Max Jobs GPU (8GB)", `${sec.max_concurrent_jobs ?? 1} job`),
      metricCard("Worktrees Activos", `${(sec.worktrees || []).length}`),
    ].join("");
  }

  const auditEl = document.getElementById("security-audit-list");
  if (auditEl) {
    const events = sec.audit_events || [];
    auditEl.innerHTML = events.length
      ? events
          .slice(0, 15)
          .map((ev) => {
            const st = ev.status || "ok";
            const cls = st === "denied" || st === "error" ? "tag-err" : st === "running" ? "tag-warn" : "tag-ok";
            return `<div class="list-row">
              <span>
                <strong>${esc(ev.action)}</strong> · <small>${esc(ev.timestamp)}</small>
                <br><small>${esc(JSON.stringify(ev.details || {}).slice(0, 100))}</small>
              </span>
              <span class="tag ${cls}">${esc(st.toUpperCase())}</span>
            </div>`;
          })
          .join("")
      : `<div class="empty-state">Sin eventos de auditoría registrados.</div>`;
  }

  const wtEl = document.getElementById("security-worktrees-list");
  if (wtEl) {
    const wts = sec.worktrees || [];
    wtEl.innerHTML = [
      ...wts.map(
        (w) => `<div class="list-row"><span><strong>Worktree:</strong> <code>${esc(w.path)}</code><br><small>${esc(w.branch || w.head || "")}</small></span><span class="tag tag-ok">Aislado</span></div>`
      ),
      `<div class="list-row"><span><strong>Protección de Secretos:</strong> <code>.env*</code>, <code>*.key</code>, <code>service.json</code>, <code>.saghet-dashboard-token</code></span><span class="tag tag-ok">DENY</span></div>`,
      `<div class="list-row"><span><strong>Árbol de Procesos:</strong> <code>start_new_session + os.killpg</code></span><span class="tag tag-ok">ACTIVO</span></div>`,
    ].join("");
  }
}

// Render Module 10: Integration Manager
function renderIntegrationManager(data) {
  const gentle = data.gentle_ai || {};
  const harness = data.harness?.status || {};
  const coreEl = document.getElementById("integrations-core-list");
  if (coreEl) {
    coreEl.innerHTML = [
      `<div class="list-row"><span><strong>Motor Principal:</strong> OpenCode v2.3.2 (<code>opencode acp</code>: ${harness.acp_probe?.opencode_acp_available ? "Disponible" : "N/A"})</span><span class="tag tag-ok">PRIMARIO</span></div>`,
      `<div class="list-row"><span><strong>Capa de Inteligencia:</strong> Gentle AI (<code>${esc(gentle.version || "4.5.0")}</code> · Skills: ${gentle.skills_discovered ?? 0})</span><span class="tag ${gentle.available ? "tag-ok" : "tag-warn"}">${gentle.available ? "ACTIVO" : "OFF"}</span></div>`,
      `<div class="list-row"><span><strong>DeepSeek Harness ACP Adapter:</strong> Desacoplado (Cordis en core: <code>false</code>)</span><span class="tag ${harness.enabled ? "tag-ok" : "tag-warn"}">${harness.enabled ? "HABILITADO" : "DESHABILITADO"}</span></div>`,
    ].join("");
  }
  const toggleBtn = document.getElementById("toggle-harness-btn");
  if (toggleBtn) {
    toggleBtn.textContent = harness.enabled ? "Desactivar DeepSeek Harness ACP" : "Activar DeepSeek Harness ACP";
  }
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

    // Full sessions list (Module 5)
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

    // Module 1, 2, 3, 4, 6, 8, 10
    renderAgentCommandCenter(data);
    renderModelIntelligence(data);
    renderWorkflowsAndTaskBoard(data);
    renderMemoryExplorer(data);
    renderSecurityCenter(data);
    renderIntegrationManager(data);
    renderProjectsGrid();

    document.querySelectorAll("[data-open-sid]").forEach((row) => {
      row.addEventListener("click", () => openSessionDetail(row.getAttribute("data-open-sid"), row.getAttribute("data-title")));
    });

    // Agents grid (Module 1)
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
          <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px;">${perms || '<span class="tag">R/W/Bash (Guardrails)</span>'}</div>
        </div>`;
      })
      .join("");

    // Module 7: Performance Lab
    document.getElementById("perf-hw-grid").innerHTML = [
      metricCard("CPU Uso", `${cpu.usage_pct ?? 0}% (Load ${cpu.load_1m ?? 0})`),
      metricCard("RAM Usada", ram.total_mib ? `${(ram.used_mib / 1024).toFixed(1)} / ${(ram.total_mib / 1024).toFixed(1)} GiB` : "N/A"),
      metricCard("GPU Uso", gpu.available ? `${gpu.utilization_pct}%` : "N/A"),
      metricCard("GPU Temp / Power", gpu.available ? `${gpu.temp_c}°C · ${gpu.power_w}W` : "N/A"),
      metricCard("Matrix Canvas FPS", matrixEngine.intensity === "off" ? "OFF" : `${matrixEngine.measuredFps || matrixEngine.fpsCap} fps`),
    ].join("");

    const tokGrid = document.getElementById("token-breakdown-grid");
    if (tokGrid) {
      tokGrid.innerHTML = [
        metricCard("Tokens Input", fmtNum(data.token_totals?.input)),
        metricCard("Tokens Output", fmtNum(data.token_totals?.output)),
        metricCard("Tokens Reasoning", fmtNum(data.token_totals?.reasoning)),
        metricCard("Cache Read", fmtNum(data.token_totals?.cache_read)),
      ].join("");
    }

    if (gpu.available) {
      const pct = Math.min(100, Math.round((gpu.vram_used_mib / gpu.vram_total_mib) * 100));
      document.getElementById("perf-vram-bar-wrap").innerHTML = `
        <div class="hud-bar-head"><span>VRAM (${esc(gpu.name)})</span><span>${Math.round(gpu.vram_used_mib)} / ${Math.round(gpu.vram_total_mib)} MiB (${pct}%)</span></div>
        <div class="progress-track"><div class="progress-fill ${pct > 85 ? "warn" : ""}" style="width:${pct}%"></div></div>`;
    }

    const running = data.ollama?.running || [];
    document.getElementById("perf-ollama-ps").innerHTML = running.length
      ? running
          .map((m) => `<strong>En VRAM:</strong> <code>${esc(m.name)}</code> · Contexto: ${m.context_length ?? "16384"} · VRAM: ${((m.size_vram || 0) / 1e9).toFixed(2)} GB`)
          .join("<br>")
      : "<strong>Ollama VRAM:</strong> Ningún modelo cargado actualmente en GPU.";

    document.getElementById("ollama-models-table").innerHTML = `<table>
      <thead><tr><th>Modelo</th><th>Tamaño</th><th>Parámetros</th><th>Quant</th></tr></thead>
      <tbody>${(data.ollama?.models || [])
        .map((m) => `<tr><td><code>${esc(m.name)}</code></td><td>${m.size_gb} GB</td><td>${esc(m.parameter_size || "-")}</td><td>${esc(m.quantization || "-")}</td></tr>`)
        .join("")}</tbody></table>`;

    // Module 9: Benchmark Center
    const benches = data.benchmarks?.benchmarks || [];
    document.getElementById("benchmarks-table").innerHTML = benches.length
      ? `<table><thead><tr><th>Modelo</th><th>tok/s</th><th>TTFT</th><th>VRAM</th></tr></thead>
        <tbody>${benches
          .map((b) => `<tr><td><code>${esc(b.model)}</code></td><td><strong>${b.tok_per_s}</strong></td><td>${b.ttft_ms} ms</td><td>${b.vram_used_mib} MiB</td></tr>`)
          .join("")}</tbody></table>`
      : `<div class="empty-state">Sin benchmarks registrados.</div>`;

    // Module 10: Plugins, Tools, Databases, MCP
    document.getElementById("plugins-list").innerHTML = [
      `<div class="card"><h2>saghet-tui (Local)</h2><p class="view-sub">Plugin TUI nativo con identidad Matrix Protocol.</p><span class="tag tag-ok">Activo</span></div>`,
      `<div class="card"><h2>opencode-mem (:4747)</h2><p class="view-sub">Memoria persistente local (qwen3.5:9b).</p><span class="tag ${data.opencode_mem_up ? "tag-ok" : "tag-warn"}">${data.opencode_mem_up ? "Activo" : "Inactivo"}</span></div>`,
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

// Prompt execution
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
  statusTag.textContent = "CLASIFICANDO CON GENTLE AI...";
  statusTag.className = "tag tag-warn";
  outCard.classList.remove("hidden");
  outPre.textContent = "Clasificando riesgo/complejidad y conectando con OpenCode + Ollama...";
  runPromptBtn.disabled = true;

  try {
    const res = await fetch("/api/session/prompt", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        prompt,
        agent: document.getElementById("select-agent").value,
        model: document.getElementById("select-model").value,
        directory: document.getElementById("select-project").value,
        isolate_worktree: Boolean(document.getElementById("chk-isolate-worktree")?.checked),
      }),
    });
    const data = await res.json();
    if (!data.ok || !data.job_id) {
      statusTag.textContent = "BLOQUEADO / ERROR";
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
        const supEval = job.supervisor_evaluation;
        const supLine = supEval
          ? `\n\n═══ SUPERVISOR DE CALIDAD: Veredicto [${supEval.verdict}] · Acción: ${supEval.next_action} ═══`
          : "";
        if (job.output || subs || supLine) {
          const footer = job.status === "running" && subs ? `\n\n▸ Procesando ahora: ${subs}` : "";
          outPre.textContent = (job.output || "Iniciando ejecución...") + footer + supLine;
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
          if (!job.output) outPre.textContent = "Ejecución completada." + supLine;
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
    headers: authHeaders(),
    body: JSON.stringify({ id: activeJobId }),
  });
});

document.getElementById("clear-output-btn").addEventListener("click", () => {
  document.getElementById("live-output-card").classList.add("hidden");
});

// Interactive actions for Modules 2, 3, 6, 9, 10
document.getElementById("run-router-sim-btn")?.addEventListener("click", async () => {
  const spec = document.getElementById("router-sim-specialty").value;
  const avoidSwap = document.getElementById("router-sim-avoid-swap").checked;
  const outEl = document.getElementById("router-sim-output");
  outEl.textContent = "Calculando ruta verificable...";
  try {
    const res = await fetch("/api/models/route", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ specialty: spec, avoid_vram_swap: avoidSwap }),
    });
    const data = await res.json();
    const r = data.route || {};
    outEl.innerHTML = `<strong>Modelo Seleccionado:</strong> <code>${esc(r.selected_model)}</code> · <strong>Score Verificable:</strong> <code>${esc(r.verifiable_score)}/100</code><br>
      <strong>Motivo:</strong> ${esc(r.reason)}<br>
      <strong>Fallback Chain:</strong> <code>${esc((r.fallback_chain || []).join(" → "))}</code>`;
  } catch (err) {
    outEl.textContent = `Error: ${err.message}`;
  }
});

document.getElementById("run-sample-dag-btn")?.addEventListener("click", async () => {
  const btn = document.getElementById("run-sample-dag-btn");
  btn.disabled = true;
  btn.textContent = "Ejecutando DAG...";
  try {
    await fetch("/api/harness/workflow", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        title: "Saghet Matrix Verification DAG",
        nodes: [
          { id: "dag_arch", title: "1. Arquitectura & Contratos", specialist: "architect", dependencies: [] },
          { id: "dag_impl", title: "2. Implementación Verificada", specialist: "senior-developer", dependencies: ["dag_arch"] },
          { id: "dag_rev", title: "3. Revisión Independiente", specialist: "code-reviewer", dependencies: ["dag_impl"] },
          { id: "dag_sec", title: "4. Auditoría Seguridad P0", specialist: "platform-security-engineer", dependencies: ["dag_impl"] },
          { id: "dag_qa", title: "5. Certificación QA", specialist: "qa-engineer", dependencies: ["dag_rev", "dag_sec"] },
        ],
      }),
    });
    await loadTelemetry();
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ Ejecutar Workflow DAG Verificado";
  }
});

document.getElementById("memory-search-btn")?.addEventListener("click", async () => {
  const q = document.getElementById("memory-search-input").value.trim();
  const resEl = document.getElementById("memory-search-results");
  if (!q) return;
  resEl.innerHTML = `<div class="empty-state">Buscando recuerdos relevantes...</div>`;
  try {
    const res = await fetch("/api/memory/query", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ query: q }),
    });
    const data = await res.json();
    const list = data.memories || [];
    resEl.innerHTML = list.length
      ? list
          .map(
            (m) => `<div class="list-row">
              <span><strong>[${esc(m.tier)}] ${esc(m.title)}</strong><br><small>${esc(m.content)}</small></span>
              <span class="tag tag-ok">Rel: ${m.relevance_score}</span>
            </div>`
          )
          .join("")
      : `<div class="empty-state">0 recuerdos superaron el umbral de relevancia (sin ruido).</div>`;
  } catch (err) {
    resEl.innerHTML = `<div class="empty-state">Error: ${esc(err.message)}</div>`;
  }
});

document.getElementById("memory-store-btn")?.addEventListener("click", async () => {
  const tier = document.getElementById("mem-add-tier").value;
  const category = document.getElementById("mem-add-cat").value;
  const title = document.getElementById("mem-add-title").value.trim();
  const content = document.getElementById("mem-add-content").value.trim();
  const msg = document.getElementById("memory-store-msg");
  if (!title || !content) {
    msg.textContent = "Completa título y contenido.";
    return;
  }
  try {
    const res = await fetch("/api/memory/store", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ tier, category, title, content, provenance: "control-center:user", confidence: 0.92 }),
    });
    const out = await res.json();
    if (out.ok) {
      msg.textContent = out.deduplicated
        ? `Fusionado por deduplicación (${out.id}, x${out.occurrence_count})`
        : `Recuerdo almacenado (${out.id})`;
      document.getElementById("mem-add-title").value = "";
      document.getElementById("mem-add-content").value = "";
      await loadTelemetry();
    } else {
      msg.textContent = `Error: ${out.error}`;
    }
  } catch (err) {
    msg.textContent = `Error: ${err.message}`;
  }
});

document.getElementById("run-live-probe-btn")?.addEventListener("click", async () => {
  const model = document.getElementById("probe-model-select").value;
  const out = document.getElementById("live-probe-output");
  const btn = document.getElementById("run-live-probe-btn");
  btn.disabled = true;
  out.textContent = `Ejecutando sonda verificable en vivo sobre ${model} en RTX 4060...`;
  try {
    const res = await fetch("/api/models/evaluate", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ model }),
    });
    const data = await res.json();
    out.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    out.textContent = String(err);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("toggle-harness-btn")?.addEventListener("click", async () => {
  const current = Boolean(lastTelemetry?.harness?.status?.enabled);
  await fetch("/api/harness/toggle", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ enabled: !current }),
  });
  await loadTelemetry();
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
      headers: authHeaders(),
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
