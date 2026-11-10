// kubai-shockwave-glow: snapshot-free overlay, warm Halo palette.
// No DOM capture, refraction or text distortion. Nothing draws while idle.
let stopCurrent = () => {};

export function playHomeShockwave() {
  stopCurrent();
  const host = document.getElementById("homeAurora");
  const main = document.getElementById("main");
  const input = document.getElementById("composerShell");
  if (!host || !main || !input) return;
  // Full browser content viewport, independent of the centered workspace width.
  // Include the sidebar and app toolbar; browser chrome is outside this viewport.
  const width = innerWidth;
  const height = innerHeight;
  if (width <= 0 || height <= 0) return;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const ratio = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.ceil(width * ratio);
  canvas.height = Math.ceil(height * ratio);
  Object.assign(canvas.style, { position: "fixed", left: "0px", top: "0px", width: `${width}px`, height: `${height}px` });
  canvas.setAttribute("aria-hidden", "true");
  host.replaceChildren(canvas);
  ctx.scale(ratio, ratio);
  const box = input.getBoundingClientRect();
  const cx = box.left + box.width / 2;
  // The center remains below the viewport, showing a wide light front, not a disk.
  const depth = Math.max(650, width * .65);
  const cy = height + depth;
  const end = Math.max(Math.hypot(cx, cy), Math.hypot(width - cx, cy));
  const band = Math.max(60, Math.min(110, width * .1));
  // Halo / light from the skill, retaining the user's subdued strength.
  const colors = [[255, 140, 50], [255, 175, 60], [245, 200, 80], [255, 225, 150]];
  const feather = (length) => {
    const edge = Math.min(56, length / 4) / length;
    return [[0, "transparent"], [edge, "#000"], [1 - edge, "#000"], [1, "transparent"]];
  };
  const horizontalMask = ctx.createLinearGradient(0, 0, width, 0);
  const verticalMask = ctx.createLinearGradient(0, 0, 0, height);
  for (const [position, color] of feather(width)) horizontalMask.addColorStop(position, color);
  for (const [position, color] of feather(height)) verticalMask.addColorStop(position, color);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const duration = reduced ? 600 : 1000;
  let frame = 0;
  let started;
  const stop = () => {
    cancelAnimationFrame(frame);
    canvas.remove();
    window.removeEventListener("resize", stop);
    document.removeEventListener("visibilitychange", onVisibility);
    if (stopCurrent === stop) stopCurrent = () => {};
  };
  const onVisibility = () => { if (document.hidden) stop(); };
  stopCurrent = stop;
  window.addEventListener("resize", stop, { once: true });
  document.addEventListener("visibilitychange", onVisibility);
  const draw = now => {
    if (!document.getElementById("hero") || main.hidden || document.hidden) { stop(); return; }
    started ??= now;
    const t = Math.min(1, (now - started) / duration);
    ctx.clearRect(0, 0, width, height);
    if (t >= 1) { stop(); return; }
    // Keep the fast launch, but let the full band sweep out before cleanup.
    const progress = reduced ? .45 : (1 - 2 ** (-4.5 * t)) / (1 - 2 ** -4.5);
    const radius = depth + (end - depth + band * 4) * progress;
    const strength = reduced ? Math.sin(Math.PI * t) * .5 : Math.min(1, t / .03) * (1 - t ** 2.2);
    const low = Math.max(0, radius - band * 4);
    const high = radius + band * 4;
    const gradient = ctx.createRadialGradient(cx, cy, low, cx, cy, high);
    for (let i = 0; i <= 64; i++) {
      const distance = low + (high - low) * i / 64;
      const x = (distance - radius) / band;
      const weights = colors.map((_, j) => Math.exp(-(((x - (j - 1.5)) / .8) ** 2)));
      const sum = weights.reduce((a, b) => a + b, 0) || 1;
      const rgb = [0, 1, 2].map(k => Math.round(colors.reduce((s, color, j) => s + color[k] * weights[j], 0) / sum));
      const alpha = (i === 0 || i === 64) ? 0 : strength * Math.exp(-1.1 * (x / 2) ** 2) * .12;
      gradient.addColorStop(i / 64, `rgba(${rgb.join(",")},${alpha})`);
    }
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    // Feather only at the actual viewport edges, never at workspace boundaries.
    ctx.globalCompositeOperation = "destination-in";
    ctx.fillStyle = horizontalMask;
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = verticalMask;
    ctx.fillRect(0, 0, width, height);
    ctx.globalCompositeOperation = "source-over";
    frame = requestAnimationFrame(draw);
  };
  frame = requestAnimationFrame(draw);
}
