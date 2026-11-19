const root = document.documentElement;
const themeBtn = document.getElementById("theme-toggle");
const refreshBtn = document.getElementById("refresh-btn");

function applyTheme(theme) {
  root.setAttribute("data-theme", theme);
  localStorage.setItem("saghet-theme", theme);
  themeBtn.textContent = theme === "dark" ? "Tema Claro" : "Tema Oscuro";
}

applyTheme(localStorage.getItem("saghet-theme") || "dark");
themeBtn.addEventListener("click", () => {
  applyTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
});

function metricCard(label, value) {
  return `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value">${value}</div></div>`;
}

function fmtNum(n) {
  return Number(n || 0).toLocaleString("es-ES");
}

async function loadTelemetry() {
  const pill = document.getElementById("health-pill");
  try {
    const res = await fetch("/api/telemetry");
    const data = await res.json();

    pill.textContent = data.opencode_server_up ? "OpenCode Server: Activo" : "OpenCode Server: Inactivo";
    pill.className = `pill ${data.opencode_server_up ? "pill-ok" : "pill-err"}`;

    const gpu = data.gpu || {};
    const ram = data.ram || {};
    document.getElementById("hardware-metrics").innerHTML = [
      metricCard("GPU", gpu.available ? gpu.name.replace("NVIDIA GeForce ", "") : "No detectada"),
      metricCard("VRAM", gpu.available ? `${Math.round(gpu.vram_used_mib)} / ${Math.round(gpu.vram_total_mib)} MiB` : "N/A"),
      metricCard("GPU Uso / Temp", gpu.available ? `${gpu.utilization_pct}% · ${gpu.temp_c}°C` : "N/A"),
      metricCard("RAM Sistema", ram.total_mib ? `${(ram.used_mib / 1024).toFixed(1)} / ${(ram.total_mib / 1024).toFixed(1)} GiB` : "N/A"),
      metricCard("Ollama", data.ollama?.up ? `Activo (${data.ollama.models_count} modelos)` : "Inactivo"),
    ].join("");

    const running = data.ollama?.running || [];
    document.getElementById("ollama-running").innerHTML = running.length
      ? running
          .map(
            (m) =>
              `<strong>En VRAM:</strong> <code>${m.name}</code> · Contexto: ${m.context_length ?? "N/A"} · Tamaño VRAM: ${((m.size_vram || 0) / 1e9).toFixed(2)} GB`
          )
          .join("<br>")
      : "<strong>En VRAM:</strong> Ningún modelo cargado actualmente en Ollama.";

    const tok = data.token_totals || {};
    document.getElementById("token-metrics").innerHTML = [
      metricCard("Input", fmtNum(tok.input)),
      metricCard("Output", fmtNum(tok.output)),
      metricCard("Reasoning", fmtNum(tok.reasoning)),
      metricCard("Cache Read", fmtNum(tok.cache_read)),
    ].join("");

    const tools = [];
    tools.push(
      `<div class="list-item"><span>opencode-mem (Web :4747)</span><span class="tag">${data.opencode_mem_up ? "Activo" : "Inactivo"}</span></div>`
    );
    for (const p of data.config?.plugins || []) {
      tools.push(`<div class="list-item"><span>Plugin: <code>${p}</code></span><span class="tag">Configurado</span></div>`);
    }
    for (const [name, info] of Object.entries(data.config?.mcp || {})) {
      tools.push(
        `<div class="list-item"><span>MCP: <code>${name}</code> (${info.type})</span><span class="tag">${info.enabled ? "Habilitado" : "Deshabilitado"}</span></div>`
      );
    }
    document.getElementById("tools-status").innerHTML = tools.join("");

    const agents = Object.entries(data.config?.agents || {});
    document.getElementById("agents-body").innerHTML = agents
      .map(([name, a]) => {
        const perms = Object.entries(a.tools || {})
          .map(([k, v]) => `${k}:${v}`)
          .join(", ") || "default";
        return `<tr><td><strong>${name}</strong></td><td><span class="tag">${a.mode}</span></td><td><code>${a.model}</code></td><td>${perms}</td></tr>`;
      })
      .join("");

    document.getElementById("sessions-body").innerHTML = (data.sessions || [])
      .slice(0, 12)
      .map((s) => {
        const t = s.tokens || {};
        return `<tr>
          <td><code>${(s.id || "").slice(0, 14)}</code><br><small>${s.title || ""}</small></td>
          <td>${s.agent || "-"}</td>
          <td>${s.parentID ? `<code>${s.parentID.slice(0, 14)}</code>` : "Raíz"}</td>
          <td><span class="tag">${s.outcome || "running"}</span></td>
          <td>${fmtNum(t.input)} / ${fmtNum(t.output)}</td>
          <td><small>${s.location?.directory || ""}</small></td>
        </tr>`;
      })
      .join("");

    document.getElementById("providers-list").innerHTML = (data.providers || [])
      .map(
        (p) => `<div class="metric">
          <div class="metric-label">${p.id}</div>
          <div class="metric-value">${p.name}</div>
          <small>${p.settings?.baseURL || ""} · ${p.activation}</small>
        </div>`
      )
      .join("");
  } catch (err) {
    pill.textContent = "Error de conexión";
    pill.className = "pill pill-err";
  }
}

refreshBtn.addEventListener("click", loadTelemetry);
loadTelemetry();
setInterval(loadTelemetry, 8000);
