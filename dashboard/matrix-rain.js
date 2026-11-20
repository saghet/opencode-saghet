/**
 * SAGHET // MATRIX PROTOCOL — Efficient Canvas 2D Rain Engine
 * Features:
 * - Japanese Katakana, digits & code symbols
 * - Multi-depth layers with variable fall speed and opacity
 * - Configurable FPS cap, intensity & view-aware attenuation
 * - Auto-pause when tab/window is hidden (visibilitychange)
 * - Respects prefers-reduced-motion & low-resource throttling
 */
(function () {
  const GLYPHS =
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789ABCDEF$#@*+<>[]{}";

  const INTENSITY_PRESETS = {
    off: { density: 0, homeAlpha: 0, workAlpha: 0 },
    subtle: { density: 0.45, homeAlpha: 0.28, workAlpha: 0.06 },
    balanced: { density: 0.72, homeAlpha: 0.48, workAlpha: 0.1 },
    prominent: { density: 1.0, homeAlpha: 0.72, workAlpha: 0.14 },
  };

  class MatrixRainEngine {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d", { alpha: true });
      this.rafId = null;
      this.lastFrameTime = 0;
      this.fpsCap = Number(localStorage.getItem("saghet-matrix-fps") || 24);
      this.intensity = localStorage.getItem("saghet-matrix-intensity") || "balanced";
      this.activeView = "home";
      this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.lowPower = (navigator.hardwareConcurrency || 8) <= 4;
      this.columns = [];
      this.measuredFps = 0;
      this._fpsFrames = 0;
      this._fpsTimer = performance.now();
      this._paused = false;

      if (this.reducedMotion) {
        this.intensity = "off";
      }

      this._onResize = this.resize.bind(this);
      this._onVisibility = this._handleVisibility.bind(this);
      window.addEventListener("resize", this._onResize, { passive: true });
      document.addEventListener("visibilitychange", this._onVisibility);
      this.resize();
    }

    _handleVisibility() {
      if (document.hidden) {
        this._paused = true;
        if (this.rafId) {
          cancelAnimationFrame(this.rafId);
          this.rafId = null;
        }
      } else {
        this._paused = false;
        this.lastFrameTime = performance.now();
        this.start();
      }
    }

    setConfig({ fpsCap, intensity, activeView }) {
      if (fpsCap !== undefined) {
        this.fpsCap = Math.max(10, Math.min(60, Number(fpsCap)));
        localStorage.setItem("saghet-matrix-fps", String(this.fpsCap));
      }
      if (intensity !== undefined && INTENSITY_PRESETS[intensity]) {
        this.intensity = intensity;
        localStorage.setItem("saghet-matrix-intensity", intensity);
        this.resize();
      }
      if (activeView !== undefined) {
        this.activeView = activeView;
      }
      this._applyCanvasOpacity();
      if (this.intensity === "off") {
        this.stop();
        this.clear();
      } else if (!this.rafId && !document.hidden) {
        this.start();
      }
    }

    _applyCanvasOpacity() {
      const preset = INTENSITY_PRESETS[this.intensity] || INTENSITY_PRESETS.balanced;
      const alpha = this.activeView === "home" ? preset.homeAlpha : preset.workAlpha;
      this.canvas.style.opacity = String(alpha);
    }

    resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const w = window.innerWidth;
      const h = window.innerHeight;
      this.width = w;
      this.height = h;
      this.canvas.width = Math.floor(w * dpr);
      this.canvas.height = Math.floor(h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const preset = INTENSITY_PRESETS[this.intensity] || INTENSITY_PRESETS.balanced;
      const step = this.lowPower ? 26 : 18;
      const count = Math.floor((w / step) * preset.density);
      this.columns = [];
      for (let i = 0; i < count; i++) {
        const depth = Math.random(); // 0 = far, 1 = near
        const fontSize = Math.round(11 + depth * 6);
        this.columns.push({
          x: (i / Math.max(1, count)) * w + (Math.random() * 8 - 4),
          y: Math.random() * h,
          speed: 1.2 + depth * 2.8,
          fontSize,
          alpha: 0.25 + depth * 0.65,
        });
      }
      this._applyCanvasOpacity();
    }

    clear() {
      if (!this.ctx) return;
      this.ctx.clearRect(0, 0, this.width, this.height);
    }

    start() {
      if (this.intensity === "off" || this._paused || this.rafId) return;
      const loop = (now) => {
        if (this.intensity === "off" || this._paused) {
          this.rafId = null;
          return;
        }
        const interval = 1000 / this.fpsCap;
        if (now - this.lastFrameTime >= interval) {
          this.lastFrameTime = now - ((now - this.lastFrameTime) % interval);
          this._draw();
          this._fpsFrames++;
          if (now - this._fpsTimer >= 1000) {
            this.measuredFps = this._fpsFrames;
            this._fpsFrames = 0;
            this._fpsTimer = now;
          }
        }
        this.rafId = requestAnimationFrame(loop);
      };
      this.rafId = requestAnimationFrame(loop);
    }

    stop() {
      if (this.rafId) {
        cancelAnimationFrame(this.rafId);
        this.rafId = null;
      }
      this.measuredFps = 0;
    }

    _draw() {
      const ctx = this.ctx;
      ctx.fillStyle = "rgba(3, 7, 5, 0.14)";
      ctx.fillRect(0, 0, this.width, this.height);

      for (let i = 0; i < this.columns.length; i++) {
        const col = this.columns[i];
        const ch = GLYPHS[(Math.random() * GLYPHS.length) | 0];
        ctx.font = `${col.fontSize}px "JetBrainsMono Nerd Font", "JetBrains Mono", monospace`;

        // Bright head character
        ctx.fillStyle = `rgba(229, 245, 234, ${Math.min(0.95, col.alpha + 0.2)})`;
        ctx.fillText(ch, col.x, col.y);

        // Trailing phosphor green glyph just above
        const prevCh = GLYPHS[(Math.random() * GLYPHS.length) | 0];
        ctx.fillStyle = `rgba(0, 255, 102, ${col.alpha * 0.85})`;
        ctx.fillText(prevCh, col.x, col.y - col.fontSize);

        col.y += col.speed * (col.fontSize * 0.45);
        if (col.y > this.height + col.fontSize * 2 && Math.random() > 0.96) {
          col.y = -col.fontSize;
        }
      }
    }
  }

  window.SaghetMatrixRain = MatrixRainEngine;
})();
