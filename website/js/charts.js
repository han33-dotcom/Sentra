/* Sentra mini charts — Canvas 2D, theme-aware, animated only while visible.
   All data here is illustrative. */
(function () {
  "use strict";
  var root = document.documentElement;
  var still = root.classList.contains("static") || matchMedia("(prefers-reduced-motion: reduce)").matches;
  var P = {};
  var charts = [];

  function readPalette() {
    var cs = getComputedStyle(root);
    var keys = ["ink", "ink-2", "muted", "line", "bg", "bg-2", "card-solid", "accent", "ok", "amber", "red", "grey",
      "s-hr", "s-sleep", "s-hrv", "s-br", "s-temp", "s-move", "map", "map-zone", "map-line", "map-road", "f-mono", "f-body", "f-display"];
    keys.forEach(function (k) { P[k] = cs.getPropertyValue("--" + k).trim(); });
  }

  /* ---------- helpers ---------- */
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function ease(x) { x = clamp(x, 0, 1); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function alpha(hex, a) {
    if (!hex) return "rgba(0,0,0," + a + ")";
    if (hex.indexOf("rgb") === 0) return hex.replace(/rgba?\(([^)]+)\)/, function (m, inner) { var p = inner.split(","); return "rgba(" + p[0] + "," + p[1] + "," + p[2] + "," + a + ")"; });
    var h = hex.replace("#", ""); if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var n = parseInt(h, 16); return "rgba(" + (n >> 16 & 255) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + a + ")";
  }
  function rr(c, x, y, w, h, r) { r = Math.min(r, w / 2, h / 2); c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }
  function font(c, size, weight, fam) { c.font = (weight || 400) + " " + size + "px " + (fam || P["f-body"]); }
  function mono(c, size, weight) { font(c, size, weight || 500, P["f-mono"]); }
  function txt(c, s, x, y, color, align, base) { c.fillStyle = color; c.textAlign = align || "left"; c.textBaseline = base || "alphabetic"; c.fillText(s, x, y); }
  function dash(c, on) { c.setLineDash(on ? [4, 4] : []); }
  function seeded(seed) { var s = seed; return function () { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; }; }
  function hatch(c, x, y, w, h, color) {
    c.save(); c.beginPath(); c.rect(x, y, w, h); c.clip();
    c.strokeStyle = color; c.lineWidth = 1.2;
    for (var i = -h; i < w + h; i += 5) { c.beginPath(); c.moveTo(x + i, y + h); c.lineTo(x + i + h, y); c.stroke(); }
    c.restore();
  }

  /* ---------- chart: personal baseline vs population ---------- */
  function drawBaseline(c, w, h, t, done) {
    var L = Math.min(84, w * .22), R = w - 10, axY = h - 22;
    var lo = 50, hi = 86;
    function X(v) { return L + (v - lo) / (hi - lo) * (R - L); }
    var cyc = done ? 99 : (t % 6.5);
    var rows = [
      { name: "Worker A", band: [55, 63], verdict: "Above own normal: check-in", col: P.amber },
      { name: "Worker B", band: [68, 77], verdict: "Within own normal", col: P.ok }
    ];
    // population line
    var popX = X(68);
    c.strokeStyle = P.muted; c.lineWidth = 1; dash(c, true);
    c.beginPath(); c.moveTo(popX, 10); c.lineTo(popX, axY); c.stroke(); dash(c, false);
    mono(c, 10); txt(c, "population avg", popX + 5, 16, P.muted);
    rows.forEach(function (r, i) {
      var y = 52 + i * 62;
      font(c, 13, 600); txt(c, r.name, 0, y + 4, P.ink, "left", "middle");
      // track
      c.fillStyle = alpha(P.ink, .06); rr(c, L, y - 9, R - L, 18, 9); c.fill();
      // own band
      var a = ease((cyc - .1 - i * .15) / .8);
      var bx = X(r.band[0]), bw = (X(r.band[1]) - bx) * a;
      c.fillStyle = alpha(P.accent, .28); rr(c, bx, y - 9, Math.max(bw, 0.1), 18, 9); c.fill();
      if (a > .9) { mono(c, 10); txt(c, "own normal " + r.band[0] + "–" + r.band[1], bx, y - 16, P.accent); }
      // today marker
      var m = ease((cyc - 1.0 - i * .25) / 1.1);
      var mx = lerp(L, X(70), m);
      if (m > 0) {
        c.fillStyle = P["card-solid"]; c.beginPath(); c.arc(mx, y, 8, 0, 6.283); c.fill();
        c.fillStyle = m > .98 ? r.col : P.ink; c.beginPath(); c.arc(mx, y, 5.5, 0, 6.283); c.fill();
      }
      var v = ease((cyc - 2.2 - i * .25) / .6);
      if (v > 0) {
        c.globalAlpha = v; font(c, 12, 600);
        var vt = "70 bpm · " + r.verdict;
        var tw = c.measureText(vt).width;
        var vx = clamp(X(70) - tw / 2, L, R - tw);
        txt(c, vt, vx, y + 24, r.col);
        c.globalAlpha = 1;
      }
    });
    // axis
    c.strokeStyle = P.line; c.lineWidth = 1; c.beginPath(); c.moveTo(L, axY); c.lineTo(R, axY); c.stroke();
    mono(c, 10, 400);
    [50, 60, 70, 80].forEach(function (v) { txt(c, v + "", X(v), axY + 14, P.muted, "center"); });
    txt(c, "bpm", R, axY + 14, P.muted, "right");
  }

  /* ---------- chart: fit-for-shift readiness ---------- */
  var mornings = [
    { day: "Sun", sleep: .4, rhr: 1, hrv: -3, state: "GREEN", label: "Ready for shift", col: "ok" },
    { day: "Mon", sleep: 2.1, rhr: 6, hrv: -18, state: "AMBER", label: "Supervisor check-in suggested", col: "amber" },
    { day: "Tue", sleep: 3.6, rhr: 11, hrv: -31, state: "RED", label: "Talk before high-risk work", col: "red" }
  ];
  function drawReady(c, w, h, t, done) {
    var per = 3.4, idx = done ? 1 : Math.floor(t / per) % 3, f = done ? 1 : (t % per) / per;
    var a = mornings[(idx + 2) % 3], b = mornings[idx];
    var k = done ? 1 : ease(f / .22);
    var cur = { sleep: lerp(a.sleep, b.sleep, k), rhr: lerp(a.rhr, b.rhr, k), hrv: lerp(a.hrv, b.hrv, k) };
    var rows = [
      { name: "Sleep debt", v: cur.sleep, min: 0, max: 4, zone: [0, 1], fmt: cur.sleep.toFixed(1) + " h" },
      { name: "Resting HR vs own normal", v: cur.rhr, min: -6, max: 14, zone: [-3, 3], fmt: (cur.rhr >= 0 ? "+" : "") + Math.round(cur.rhr) + " bpm" },
      { name: "HRV vs own normal", v: cur.hrv, min: -40, max: 20, zone: [-10, 10], fmt: (cur.hrv >= 0 ? "+" : "") + Math.round(cur.hrv) + "%" }
    ];
    var L = 0, R = w;
    rows.forEach(function (r, i) {
      var y = 14 + i * 44;
      font(c, 12.5, 500); txt(c, r.name, L, y, P["ink-2"]);
      mono(c, 12, 500); txt(c, r.fmt, R, y, P.ink, "right");
      var ty = y + 10, th = 8;
      function X(v) { return L + (clamp(v, r.min, r.max) - r.min) / (r.max - r.min) * (R - L); }
      c.fillStyle = alpha(P.ink, .07); rr(c, L, ty, R - L, th, 4); c.fill();
      c.fillStyle = alpha(P.accent, .3); rr(c, X(r.zone[0]), ty, X(r.zone[1]) - X(r.zone[0]), th, 4); c.fill();
      var mx = X(r.v);
      var off = r.v < r.zone[0] ? r.zone[0] - r.v : r.v > r.zone[1] ? r.v - r.zone[1] : 0;
      var sev = off / ((r.max - r.min) * .25);
      var col = sev < .25 ? P.ok : sev < 1 ? P.amber : P.red;
      c.fillStyle = P["card-solid"]; c.beginPath(); c.arc(mx, ty + th / 2, 8, 0, 6.283); c.fill();
      c.fillStyle = col; c.beginPath(); c.arc(mx, ty + th / 2, 5.5, 0, 6.283); c.fill();
    });
    // status chip
    var cy = h - 34;
    var col = P[b.col];
    var ca = done ? 1 : ease((f - .18) / .12);
    c.globalAlpha = .35 + .65 * ca;
    c.fillStyle = alpha(col, .14); rr(c, 0, cy, w, 32, 9); c.fill();
    c.strokeStyle = alpha(col, .55); c.lineWidth = 1; rr(c, .5, cy + .5, w - 1, 31, 9); c.stroke();
    c.fillStyle = col; c.beginPath(); c.arc(16, cy + 16, 5, 0, 6.283); c.fill();
    mono(c, 12, 600); txt(c, b.day + " · " + b.state, 30, cy + 17, col, "left", "middle");
    var sx = 30 + c.measureText(b.day + " · " + b.state).width + 10;
    font(c, 12.5, 500);
    var lab = b.label; while (c.measureText(lab).width > w - sx - 10 && lab.length > 4) lab = lab.slice(0, -2);
    if (lab !== b.label) lab = lab.trim() + "…";
    txt(c, lab, sx, cy + 17, P.ink, "left", "middle");
    c.globalAlpha = 1;
  }

  /* ---------- chart: exertion watch ---------- */
  function hrAt(m) {
    var v = 92 + Math.sin(m * .9) * 2.5 + Math.sin(m * .23) * 3;
    if (m > 35 && m < 80) v += 28 * ease((m - 35) / 8) * (1 - ease((m - 74) / 6));
    if (m > 118 && m < 170) v += 55 * ease((m - 118) / 12);
    if (m >= 170) v += 55 * Math.exp(-(m - 170) / 5.5);
    if (m > 215 && m < 270) v += 22 * ease((m - 215) / 8) * (1 - ease((m - 262) / 8));
    return v;
  }
  function drawExert(c, w, h, t, done) {
    var L = 30, R = w - 4, T = 14, B = h - 22;
    var lo = 60, hi = 170;
    function X(m) { return L + m / 300 * (R - L); }
    function Y(v) { return B - (v - lo) / (hi - lo) * (B - T); }
    var cyc = done ? 99 : t % 9;
    var prog = done ? 1 : clamp(cyc / 6.5, 0, 1);
    var mEnd = 300 * prog;
    // grid
    mono(c, 10, 400);
    [80, 120, 160].forEach(function (v) { c.strokeStyle = P.line; c.lineWidth = 1; c.beginPath(); c.moveTo(L, Y(v)); c.lineTo(R, Y(v)); c.stroke(); txt(c, v, L - 6, Y(v) + 3, P.muted, "right"); });
    ["07:00", "08:00", "09:00", "10:00", "11:00", "12:00"].forEach(function (s, i) { txt(c, s, X(i * 60), h - 6, P.muted, i === 0 ? "left" : i === 5 ? "right" : "center"); });
    // personal high zone
    var zy = Y(138);
    c.fillStyle = alpha(P.amber, .1); c.fillRect(L, T, R - L, zy - T);
    c.strokeStyle = alpha(P.amber, .8); dash(c, true); c.beginPath(); c.moveTo(L, zy); c.lineTo(R, zy); c.stroke(); dash(c, false);
    mono(c, 10); txt(c, "personal high zone", R - 4, T + 11, P.amber, "right");
    // line
    var grad = c.createLinearGradient(0, T, 0, B);
    grad.addColorStop(0, alpha(P["s-hr"], .28)); grad.addColorStop(1, alpha(P["s-hr"], 0));
    c.beginPath(); c.moveTo(X(0), B);
    for (var m = 0; m <= mEnd; m += 1.5) c.lineTo(X(m), Y(hrAt(m)));
    c.lineTo(X(mEnd), B); c.closePath(); c.fillStyle = grad; c.fill();
    c.beginPath();
    for (m = 0; m <= mEnd; m += 1.5) { if (m === 0) c.moveTo(X(m), Y(hrAt(m))); else c.lineTo(X(m), Y(hrAt(m))); }
    c.strokeStyle = P["s-hr"]; c.lineWidth = 2; c.lineJoin = "round"; c.stroke();
    // head dot
    if (prog < 1) { c.fillStyle = P["s-hr"]; c.beginPath(); c.arc(X(mEnd), Y(hrAt(mEnd)), 4, 0, 6.283); c.fill(); }
    // sustained marker
    if (mEnd > 150) {
      var x1 = X(131), x2 = X(Math.min(mEnd, 170));
      c.strokeStyle = P.amber; c.lineWidth = 2; c.beginPath(); c.moveTo(x1, T + 20); c.lineTo(x2, T + 20); c.stroke();
      c.beginPath(); c.moveTo(x1, T + 16); c.lineTo(x1, T + 24); c.moveTo(x2, T + 16); c.lineTo(x2, T + 24); c.stroke();
      font(c, 11.5, 600); txt(c, "Sustained high · flag", x1, T + 36, P.amber);
    }
    if (mEnd > 190) {
      var rx = X(170), rx2 = X(186);
      c.strokeStyle = P.ok; c.lineWidth = 2; c.beginPath(); c.moveTo(rx, Y(100)); c.lineTo(rx2, Y(100)); c.stroke();
      font(c, 11.5, 600); txt(c, "Break → recovered in ~9 min", rx2 + 6, Y(100) + 4, P.ok);
    }
  }

  /* ---------- chart: lone-worker check ---------- */
  var moveData = (function () { var r = seeded(7), a = []; for (var i = 0; i < 50; i++) { var v = .25 + r() * .75; if (i >= 20 && i < 31) v = 0; if (i === 31) v = .5; a.push(v); } return a; })();
  function drawLone(c, w, h, t, done) {
    var tight = w < 480;
    var L = 0, R = w, T = tight ? 66 : 50, B = h - 24;
    var n = moveData.length, bw = (R - L) / n;
    var cyc = done ? 99 : t % 9;
    var prog = done ? 1 : clamp(cyc / 6.8, 0, 1);
    var shown = Math.floor(prog * n);
    for (var i = 0; i < n; i++) {
      var v = moveData[i];
      var x = L + i * bw;
      if (i < shown) {
        c.fillStyle = v === 0 ? alpha(P.muted, .35) : alpha(P["s-move"], .85);
        var bh = v === 0 ? 2 : v * (B - T);
        rr(c, x + 1, B - bh, bw - 2, bh, 2); c.fill();
      } else { c.fillStyle = alpha(P.ink, .05); rr(c, x + 1, B - 2, bw - 2, 2, 1); c.fill(); }
    }
    mono(c, 10, 400);
    ["12:30", "13:00", "13:30", "14:00"].forEach(function (s, k) { txt(c, s, L + k * 15 * bw, h - 6, P.muted, k === 0 ? "left" : "center"); });
    // still stretch bracket
    var startI = 20;
    if (shown > startI) {
      var endI = Math.min(shown, 31);
      var mins = (endI - startI) * 2;
      var x1 = L + startI * bw, x2 = L + endI * bw;
      var over = mins >= 20;
      var col = over ? P.amber : P.muted;
      c.fillStyle = alpha(col, .1); c.fillRect(x1, T - 8, x2 - x1, B - T + 8);
      c.strokeStyle = col; c.lineWidth = 1.5; c.beginPath(); c.moveTo(x1, T - 8); c.lineTo(x1, B); c.moveTo(x2, T - 8); c.lineTo(x2, B); c.stroke();
      mono(c, 11, 600); txt(c, "no movement " + mins + " min", x1 + 6, T + 6, col);
      // threshold tick at 20 min
      var tx = L + (startI + 10) * bw;
      c.strokeStyle = alpha(P.amber, .7); dash(c, true); c.beginPath(); c.moveTo(tx, T - 8); c.lineTo(tx, B); c.stroke(); dash(c, false);
    }
    var pinY = 14;
    if (shown >= 30) {
      var px = L + 30 * bw;
      chip(c, px, pinY, "13:30 check-in prompt", P.amber, "right");
    }
    if (shown >= 32) {
      var qx = L + 32 * bw;
      chip(c, qx, tight ? pinY + 26 : pinY, "13:32 tapped \"I'm OK\"", P.ok, "left");
    }
    function chip(c, x, y, s, col, side) {
      font(c, 11, 600);
      var tw = c.measureText(s).width + 16;
      var bx = side === "right" ? x - tw - 3 : x + 3;
      bx = clamp(bx, 0, w - tw);
      c.fillStyle = alpha(col, .14); rr(c, bx, y - 11, tw, 22, 6); c.fill();
      txt(c, s, bx + 8, y + 4, col);
    }
  }

  /* ---------- chart: early-warning trends ---------- */
  var nightsBR = [15.1, 14.9, 15.3, 15.0, 14.8, 15.2, 15.4, 15.0, 15.1, 15.3, 16.0, 16.3, 16.5, 16.7];
  var nightsT = [0.0, -.1, .1, .05, -.08, .12, .02, -.04, .1, .08, .38, .46, .52, .6];
  function drawTrend(c, w, h, t, done) {
    var cyc = done ? 99 : t % 8;
    var shown = done ? 14 : clamp(Math.floor(cyc / 4.5 * 14) + 1, 1, 14);
    var L = 0, R = w;
    var rowH = (h - 34) / 2;
    function panel(y0, label, vals, lo, hi, band, unit, col) {
      var T = y0 + 18, B = y0 + rowH - 6;
      function X(i) { return L + 8 + i / 13 * (R - L - 16); }
      function Y(v) { return B - (v - lo) / (hi - lo) * (B - T); }
      font(c, 12, 600); txt(c, label, L, y0 + 10, P["ink-2"]);
      c.fillStyle = alpha(P.accent, .16); c.fillRect(L, Y(band[1]), R - L, Y(band[0]) - Y(band[1]));
      mono(c, 9.5, 400); txt(c, "own range", R, Y(band[1]) - 3, P.accent, "right");
      c.beginPath();
      for (var i = 0; i < shown; i++) { if (!i) c.moveTo(X(i), Y(vals[i])); else c.lineTo(X(i), Y(vals[i])); }
      c.strokeStyle = col; c.lineWidth = 1.8; c.stroke();
      for (i = 0; i < shown; i++) {
        var outside = vals[i] > band[1] || vals[i] < band[0];
        c.fillStyle = outside ? P.amber : col;
        c.beginPath(); c.arc(X(i), Y(vals[i]), outside ? 3.6 : 2.6, 0, 6.283); c.fill();
      }
      mono(c, 10, 500); txt(c, unit, L + 2, B + 2, P.muted, "left", "top");
      return X;
    }
    panel(0, "Breathing rate, nightly", nightsBR, 14.2, 17.2, [14.6, 15.6], "br/min", P["s-br"]);
    var X = panel(rowH, "Skin temperature vs own normal", nightsT, -.4, .8, [-.2, .2], "°C", P["s-temp"]);
    if (shown >= 13) {
      var x1 = X(10) - 6, x2 = X(13) + 6;
      var y = h - 22;
      c.strokeStyle = P.amber; c.lineWidth = 1.5;
      c.beginPath(); c.moveTo(x1, y); c.lineTo(x2, y); c.moveTo(x1, y - 4); c.lineTo(x1, y + 4); c.moveTo(x2, y - 4); c.lineTo(x2, y + 4); c.stroke();
      font(c, 11.5, 600);
      txt(c, "4 nights drifting → flag for check-in", x2, y + 16, P.amber, "right");
    }
    mono(c, 10, 400); txt(c, "night 1", L, h - 2, P.muted);
  }

  /* ---------- chart: wear compliance ---------- */
  var days = [
    { d: "Sat", seg: [[0, 10]] },
    { d: "Sun", seg: [[0, 9.7]] },
    { d: "Mon", seg: [[0, 3.4], [7.3, 10]] },
    { d: "Tue", seg: [[.4, 10]] },
    { d: "Wed", seg: [[0, 9.6]] },
    { d: "Thu", seg: [[0, 10]] }
  ];
  function drawWear(c, w, h, t, done) {
    var L = 38, R = w - 52, T = 6;
    var rowH = (h - 26 - T) / days.length;
    var cyc = done ? 99 : t % 8;
    var total = 0;
    days.forEach(function (day, i) {
      var y = T + i * rowH, bh = Math.min(14, rowH - 7);
      var k = done ? 1 : ease((cyc - i * .18) / 1.1);
      mono(c, 11, 500); txt(c, day.d, 0, y + bh / 2 + 4, P["ink-2"]);
      // shift background = gap (hatched)
      c.fillStyle = alpha(P.amber, .08); rr(c, L, y, R - L, bh, 4); c.fill();
      hatch(c, L, y, (R - L) * k, bh, alpha(P.amber, .45));
      var worn = 0;
      day.seg.forEach(function (s) {
        worn += s[1] - s[0];
        var x1 = L + s[0] / 10 * (R - L), x2 = L + Math.min(s[1], 10 * k) / 10 * (R - L);
        if (x2 > x1) { c.fillStyle = P.accent; rr(c, x1, y, x2 - x1, bh, 4); c.fill(); }
      });
      total += worn;
      var pct = Math.round(worn * 10);
      mono(c, 11, 600); txt(c, Math.round(pct * k) + "%", w, y + bh / 2 + 4, pct < 85 ? P.amber : P.ink, "right");
      if (pct < 85 && k > .95) { font(c, 11, 600); txt(c, "3.9 h gap", L + 3.5 / 10 * (R - L) + 4, y + bh / 2 + 4, P.amber); }
    });
    mono(c, 10, 400);
    txt(c, "06:00", L, h - 6, P.muted); txt(c, "11:00", (L + R) / 2, h - 6, P.muted, "center"); txt(c, "16:00", R, h - 6, P.muted, "right");
    txt(c, "week " + Math.round(total / 60 * 100) + "% worn", w, h - 6, P.ink, "right");
  }

  /* ---------- chart: crew map (static fallback only) ---------- */
  function drawCrew(c, w, h, t) {
    c.fillStyle = P.map; rr(c, 0, 0, w, h, 10); c.fill();
    c.fillStyle = P["map-zone"];
    [[.06, .1, .3, .38], [.42, .08, .24, .3], [.72, .14, .22, .5], [.08, .6, .4, .3], [.54, .56, .14, .34]].forEach(function (z) { rr(c, z[0] * w, z[1] * h, z[2] * w, z[3] * h, 6); c.fill(); });
    var r = seeded(11);
    for (var i = 0; i < 31; i++) {
      var x = (.08 + r() * .84) * w, y = (.12 + r() * .76) * h;
      var col = i < 4 ? P.amber : i === 4 ? P.grey : P.accent;
      c.fillStyle = alpha(col, .2); c.beginPath(); c.arc(x, y, 9, 0, 6.283); c.fill();
      c.fillStyle = col; c.beginPath(); c.arc(x, y, 4, 0, 6.283); c.fill();
    }
  }

  /* ---------- chart: dashboard readiness by site ---------- */
  var sites = [
    { n: "Tower", k: "accent", v: [84, 85, 83, 86, 87, 86, 88, 90] },
    { n: "Plant", k: "s-sleep", v: [80, 82, 84, 83, 85, 87, 86, 88] },
    { n: "Yard", k: "s-br", v: [86, 84, 85, 87, 86, 88, 89, 89] },
    { n: "Depot", k: "s-temp", v: [76, 78, 77, 80, 79, 82, 81, 84] }
  ];
  function drawDash(c, w, h, t, done) {
    var L = 30, R = w - 6, T = 8, B = h - 22;
    var lo = 70, hi = 95;
    function X(i) { return L + i / 7 * (R - L); }
    function Y(v) { return B - (v - lo) / (hi - lo) * (B - T); }
    mono(c, 10, 400);
    [75, 85, 95].forEach(function (v) { c.strokeStyle = P.line; c.lineWidth = 1; c.beginPath(); c.moveTo(L, Y(v)); c.lineTo(R, Y(v)); c.stroke(); txt(c, v + "%", L - 6, Y(v) + 3, P.muted, "right"); });
    for (var i = 0; i < 8; i++) txt(c, "W" + (32 + i), X(i), h - 6, P.muted, i === 0 ? "left" : i === 7 ? "right" : "center");
    var k = done ? 1 : ease((t % 10) / 2.2);
    sites.forEach(function (s) {
      var col = P[s.k];
      c.beginPath();
      var n = 1 + k * 7;
      for (var j = 0; j <= Math.floor(n); j++) { var x = X(j), y = Y(s.v[j]); if (!j) c.moveTo(x, y); else c.lineTo(x, y); }
      var fj = Math.floor(n); if (fj < 7) { var f = n - fj; c.lineTo(lerp(X(fj), X(fj + 1), f), lerp(Y(s.v[fj]), Y(s.v[fj + 1]), f)); }
      c.strokeStyle = col; c.lineWidth = 2; c.lineJoin = "round"; c.stroke();
      if (k > .99) { c.fillStyle = col; c.beginPath(); c.arc(X(7), Y(s.v[7]), 3.2, 0, 6.283); c.fill(); }
    });
  }

  var drawers = { baseline: drawBaseline, ready: drawReady, exert: drawExert, lone: drawLone, trend: drawTrend, wear: drawWear, crew: drawCrew, dash: drawDash };

  function size(ch) {
    var el = ch.el, dpr = Math.min(window.devicePixelRatio || 1, 2);
    var cssW = el.clientWidth || el.parentNode.clientWidth;
    var cssH = ch.h;
    if (!cssW) return false;
    el.style.height = cssH + "px";
    el.width = Math.round(cssW * dpr); el.height = Math.round(cssH * dpr);
    ch.w = cssW; ch.dpr = dpr;
    return true;
  }
  function draw(ch, t, done) {
    if (!ch.w && !size(ch)) return;
    var c = ch.ctx;
    c.setTransform(ch.dpr, 0, 0, ch.dpr, 0, 0);
    c.clearRect(0, 0, ch.w, ch.h);
    ch.fn(c, ch.w, ch.h, t, done);
  }

  function legend() {
    var el = document.getElementById("dashLegend"); if (!el) return;
    el.innerHTML = sites.map(function (s) { return '<span><i style="--c:var(--' + s.k + ')"></i>' + s.n + "</span>"; }).join("");
  }

  function init() {
    readPalette();
    legend();
    document.querySelectorAll("canvas[data-chart]").forEach(function (el) {
      var fn = drawers[el.getAttribute("data-chart")]; if (!fn) return;
      var ch = { el: el, ctx: el.getContext("2d"), fn: fn, h: +el.getAttribute("height") || 180, visible: false, t0: 0 };
      charts.push(ch);
    });
    function all() { charts.forEach(function (ch) { ch.w = 0; size(ch); draw(ch, 0, true); }); }
    all();
    var rt; addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(all, 120); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(all);
    if (still) return;
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        var ch = charts.find(function (c) { return c.el === e.target; });
        if (!ch) return;
        if (e.isIntersecting && !ch.visible) ch.t0 = performance.now();
        ch.visible = e.isIntersecting;
      });
    }, { threshold: .15 });
    charts.forEach(function (ch) { io.observe(ch.el); });
    function loop(now) {
      charts.forEach(function (ch) { if (ch.visible) draw(ch, (now - ch.t0) / 1000, false); });
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);
  }

  window.SentraCharts = {
    init: init,
    retheme: function () { readPalette(); charts.forEach(function (ch) { draw(ch, ch.visible && !still ? (performance.now() - ch.t0) / 1000 : 0, !ch.visible || still); }); }
  };
})();
