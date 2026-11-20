/**
 * SAGHET // MATRIX PROTOCOL — Desktop Visual Overlay
 * 1. Renders Matrix digital rain ONLY in the empty left/right margins below the topbar.
 * 2. Renders animated Matrix glyphs masked inside the central `opencode` SVG logo.
 * 3. Displays the `SAGHET EDITION` badge beside the logo on the start/new-session screen.
 * Purely visual (pointer-events: none); zero changes to app functionality.
 */
(function () {
  if (window.__saghetDesktopMatrixInit) return;
  window.__saghetDesktopMatrixInit = true;

  const GLYPHS =
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789ABCDEF$#@*+<>";

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion) return;

  const TOPBAR_H = 44;

  const style = document.createElement("style");
  style.id = "saghet-desktop-matrix-style";
  style.textContent = `
    #saghet-desktop-matrix {
      position: fixed;
      top: ${TOPBAR_H}px;
      left: 0;
      width: 100vw;
      height: calc(100vh - ${TOPBAR_H}px);
      z-index: 9998;
      pointer-events: none;
      opacity: 0.55;
      mix-blend-mode: screen;
    }
    #saghet-logo-matrix-wrap {
      position: fixed;
      z-index: 1;
      pointer-events: none;
      display: none;
      filter: drop-shadow(0 0 3px rgba(0, 255, 102, 0.22));
    }
    #saghet-logo-matrix-canvas {
      width: 100%;
      height: 100%;
      display: block;
      -webkit-mask-size: 100% 100%;
      mask-size: 100% 100%;
      -webkit-mask-repeat: no-repeat;
      mask-repeat: no-repeat;
      -webkit-mask-position: center;
      mask-position: center;
    }
    #saghet-logo-outline {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      overflow: visible;
    }
    #saghet-edition-badge {
      position: fixed;
      z-index: 1;
      pointer-events: none;
      display: none;
      font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", "IBM Plex Mono", monospace;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.14em;
      color: #D1FAE5;
      background: rgba(8, 44, 27, 0.85);
      border: 1px solid rgba(52, 211, 153, 0.55);
      border-radius: 4px;
      padding: 3px 9px;
      box-shadow: 0 0 6px rgba(0, 255, 102, 0.14);
      white-space: nowrap;
      user-select: none;
    }
    html[data-color-scheme="light"] #saghet-desktop-matrix,
    html[data-color-scheme="light"] #saghet-logo-matrix-wrap,
    html[data-color-scheme="light"] #saghet-edition-badge {
      display: none !important;
    }
  `;
  document.head.appendChild(style);

  // 1. Lateral background canvas
  const canvas = document.createElement("canvas");
  canvas.id = "saghet-desktop-matrix";
  canvas.setAttribute("aria-hidden", "true");
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d", { alpha: true });

  // 2. Logo interior Matrix canvas + mask wrapper + crisp vector outline
  const logoWrap = document.createElement("div");
  logoWrap.id = "saghet-logo-matrix-wrap";
  logoWrap.setAttribute("aria-hidden", "true");
  const logoCanvas = document.createElement("canvas");
  logoCanvas.id = "saghet-logo-matrix-canvas";
  logoWrap.appendChild(logoCanvas);
  const logoOutlineSlot = document.createElement("div");
  logoOutlineSlot.id = "saghet-logo-outline";
  logoWrap.appendChild(logoOutlineSlot);
  document.body.appendChild(logoWrap);
  const logoCtx = logoCanvas.getContext("2d", { alpha: true });

  // 3. Saghet Edition badge
  const badge = document.createElement("div");
  badge.id = "saghet-edition-badge";
  badge.textContent = "SAGHET EDITION";
  document.body.appendChild(badge);

  let width = 0;
  let height = 0;
  let columns = [];
  let logoCols = [];
  let logoW = 0;
  let logoH = 0;
  let currentLogoSvg = null;
  let logoVisible = false;
  let rafId = null;
  let lastFrame = 0;
  const FPS = 24;

  function getSafeCenterBounds() {
    const promptEl =
      document.querySelector('[data-component="prompt-input"]') ||
      document.querySelector("textarea");
    if (promptEl) {
      const r = promptEl.getBoundingClientRect();
      if (r.width > 240 && r.width < width * 0.88) {
        return {
          left: Math.max(0, r.left - 28),
          right: Math.min(width, r.right + 28),
        };
      }
    }
    const centerW = Math.min(960, Math.max(560, width * 0.62));
    const pad = Math.max(0, (width - centerW) / 2);
    return { left: pad, right: width - pad };
  }

  function findOpencodeLogoSvg() {
    const svgs = document.querySelectorAll("svg");
    const midX = window.innerWidth / 2;
    for (let i = 0; i < svgs.length; i++) {
      const svg = svgs[i];
      if (svg.closest("#saghet-logo-matrix-wrap")) continue;
      const r = svg.getBoundingClientRect();
      if (
        r.width >= 150 &&
        r.width <= 600 &&
        r.height >= 24 &&
        r.height <= 120 &&
        r.top > TOPBAR_H &&
        r.bottom < window.innerHeight * 0.72 &&
        Math.abs((r.left + r.right) / 2 - midX) < 140
      ) {
        return { svg, rect: r };
      }
    }
    return null;
  }

  function isForegroundGlyphEl(el) {
    const cs = window.getComputedStyle(el);
    if (!cs || cs.display === "none" || cs.visibility === "hidden") return false;
    const fill = cs.fill;
    if (!fill || fill === "none" || fill === "transparent") return false;
    const match = fill.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/i);
    if (!match) return true;
    const r = Number(match[1]);
    const g = Number(match[2]);
    const b = Number(match[3]);
    const a = match[4] !== undefined ? Number(match[4]) : 1;
    const fillOp = parseFloat(cs.fillOpacity || "1");
    const op = parseFloat(cs.opacity || "1");
    const effectiveAlpha = a * fillOp * op;
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    // Exclude dark/semi-transparent tile boxes ("cuadros") so they match the app background
    return effectiveAlpha >= 0.35 && lum * effectiveAlpha >= 0.25;
  }

  function buildSvgMaskUrl(svg) {
    const origEls = svg.querySelectorAll("path, rect, polygon, circle, ellipse, g");
    const clone = svg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const cloneEls = clone.querySelectorAll("path, rect, polygon, circle, ellipse, g");
    cloneEls.forEach((el, idx) => {
      if (el.tagName.toLowerCase() === "g") {
        el.removeAttribute("opacity");
        return;
      }
      const orig = origEls[idx];
      if (orig && !isForegroundGlyphEl(orig)) {
        el.setAttribute("fill", "none");
        el.setAttribute("stroke", "none");
      } else if (el.getAttribute("fill") !== "none") {
        el.setAttribute("fill", "#ffffff");
      }
      el.removeAttribute("fill-opacity");
      el.removeAttribute("opacity");
    });
    const serialized = new XMLSerializer().serializeToString(clone);
    return `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(serialized)}")`;
  }

  function buildSvgOutlineEl(svg) {
    const origEls = svg.querySelectorAll("path, rect, polygon, circle, ellipse, polyline, line");
    const clone = svg.cloneNode(true);
    clone.removeAttribute("id");
    clone.removeAttribute("class");
    clone.removeAttribute("style");
    clone.setAttribute("width", "100%");
    clone.setAttribute("height", "100%");
    clone.setAttribute("preserveAspectRatio", "none");
    clone.style.display = "block";
    clone.style.width = "100%";
    clone.style.height = "100%";
    const cloneEls = clone.querySelectorAll("path, rect, polygon, circle, ellipse, polyline, line");
    cloneEls.forEach((el, idx) => {
      const orig = origEls[idx];
      if (orig && !isForegroundGlyphEl(orig)) {
        el.setAttribute("fill", "none");
        el.setAttribute("stroke", "none");
        return;
      }
      if (el.getAttribute("fill") !== "none") {
        el.setAttribute("fill", "none");
      }
      el.setAttribute("stroke", "#4ADE80");
      el.setAttribute("stroke-width", "1.35");
      el.setAttribute("stroke-opacity", "0.92");
      el.setAttribute("vector-effect", "non-scaling-stroke");
      el.removeAttribute("opacity");
    });
    return clone;
  }

  function hideLogoOverlay() {
    logoVisible = false;
    logoWrap.style.display = "none";
    badge.style.display = "none";
    if (currentLogoSvg) {
      currentLogoSvg.style.opacity = "";
    }
  }

  function hasOpenPopup() {
    return Boolean(document.querySelector('[role="dialog"], [role="listbox"], [role="menu"]'));
  }

  function syncLogoOverlay() {
    if (document.documentElement.dataset.colorScheme === "light" || hasOpenPopup()) {
      hideLogoOverlay();
      return;
    }

    const found = findOpencodeLogoSvg();
    if (!found) {
      hideLogoOverlay();
      currentLogoSvg = null;
      return;
    }

    const { svg, rect } = found;
    logoVisible = true;

    if (svg !== currentLogoSvg) {
      if (currentLogoSvg) currentLogoSvg.style.opacity = "";
      currentLogoSvg = svg;
      const maskUrl = buildSvgMaskUrl(svg);
      logoCanvas.style.webkitMaskImage = maskUrl;
      logoCanvas.style.maskImage = maskUrl;
      logoOutlineSlot.replaceChildren(buildSvgOutlineEl(svg));
    }
    currentLogoSvg.style.opacity = "0";

    const rw = Math.round(rect.width);
    const rh = Math.round(rect.height);
    const topY = Math.min(Math.round(rect.top), 74);
    const leftX = Math.round(rect.left);

    logoWrap.style.display = "block";
    logoWrap.style.left = `${leftX}px`;
    logoWrap.style.top = `${topY}px`;
    logoWrap.style.width = `${rw}px`;
    logoWrap.style.height = `${rh}px`;

    // Place SAGHET EDITION badge at the bottom-right corner next to the elevated logo
    badge.style.display = "block";
    badge.style.left = `${Math.round(leftX + rw + 12)}px`;
    badge.style.top = `${Math.round(topY + rh - 21)}px`;

    if (rw !== logoW || rh !== logoH) {
      logoW = rw;
      logoH = rh;
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      logoCanvas.width = Math.max(1, Math.floor(rw * dpr));
      logoCanvas.height = Math.max(1, Math.floor(rh * dpr));
      logoCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const step = 11;
      const cnt = Math.max(1, Math.ceil(rw / step));
      logoCols = [];
      for (let i = 0; i < cnt; i++) {
        logoCols.push({
          x: i * step + 1,
          y: Math.random() * rh,
          speed: 0.65 + Math.random() * 0.85,
        });
      }
      logoCtx.fillStyle = "#0F4D30";
      logoCtx.fillRect(0, 0, rw, rh);
    }
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    width = window.innerWidth;
    height = Math.max(1, window.innerHeight - TOPBAR_H);
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const step = 18;
    const count = Math.floor(width / step);
    columns = [];
    for (let i = 0; i < count; i++) {
      const depth = Math.random();
      columns.push({
        x: i * step + 4,
        y: Math.random() * height,
        speed: 1.1 + depth * 2.4,
        fontSize: Math.round(12 + depth * 5),
        alpha: 0.3 + depth * 0.65,
      });
    }
    syncLogoOverlay();
  }

  function drawLateralRain() {
    const { left, right } = getSafeCenterBounds();
    ctx.clearRect(left, 0, Math.max(0, right - left), height);
    ctx.fillStyle = "rgba(3, 7, 5, 0.14)";
    ctx.fillRect(0, 0, left, height);
    ctx.fillRect(right, 0, Math.max(0, width - right), height);

    for (let i = 0; i < columns.length; i++) {
      const col = columns[i];
      if (col.x >= left - 12 && col.x <= right + 4) continue;

      const ch = GLYPHS[(Math.random() * GLYPHS.length) | 0];
      ctx.font = `${col.fontSize}px "JetBrainsMono Nerd Font", "JetBrains Mono", monospace`;

      ctx.fillStyle = `rgba(229, 245, 234, ${Math.min(0.95, col.alpha + 0.15)})`;
      ctx.fillText(ch, col.x, col.y);

      const prevCh = GLYPHS[(Math.random() * GLYPHS.length) | 0];
      ctx.fillStyle = `rgba(0, 255, 102, ${col.alpha * 0.85})`;
      ctx.fillText(prevCh, col.x, col.y - col.fontSize);

      col.y += col.speed * (col.fontSize * 0.45);
      if (col.y > height + col.fontSize * 2 && Math.random() > 0.96) {
        col.y = 0;
      }
    }
  }

  function drawLogoRain() {
    if (!logoVisible || logoW <= 0 || logoH <= 0) return;
    // Solid emerald-jade body keeps letterforms readable against dark background
    logoCtx.fillStyle = "rgba(13, 68, 42, 0.28)";
    logoCtx.fillRect(0, 0, logoW, logoH);

    logoCtx.font = '600 8px "JetBrainsMono Nerd Font", "JetBrains Mono", monospace';
    for (let i = 0; i < logoCols.length; i++) {
      const c = logoCols[i];
      const ch = GLYPHS[(Math.random() * GLYPHS.length) | 0];
      logoCtx.fillStyle = "rgba(209, 250, 229, 0.34)";
      logoCtx.fillText(ch, c.x, c.y);

      const prev = GLYPHS[(Math.random() * GLYPHS.length) | 0];
      logoCtx.fillStyle = "rgba(52, 211, 153, 0.24)";
      logoCtx.fillText(prev, c.x, c.y - 9);

      c.y += c.speed * 2.4;
      if (c.y > logoH + 10 && Math.random() > 0.88) {
        c.y = 0;
      }
    }
  }

  let tick = 0;
  function loop(now) {
    if (document.hidden) {
      rafId = null;
      return;
    }
    const interval = 1000 / FPS;
    if (now - lastFrame >= interval) {
      lastFrame = now - ((now - lastFrame) % interval);
      if (document.documentElement.dataset.colorScheme !== "light") {
        drawLateralRain();
        if (tick % 8 === 0) syncLogoOverlay();
        drawLogoRain();
        tick++;
      }
    }
    rafId = requestAnimationFrame(loop);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !rafId) {
      lastFrame = performance.now();
      rafId = requestAnimationFrame(loop);
    }
  });

  const observer = new MutationObserver(() => syncLogoOverlay());
  observer.observe(document.body, { childList: true, subtree: true });

  window.addEventListener("resize", resize, { passive: true });
  resize();
  rafId = requestAnimationFrame(loop);
})();
