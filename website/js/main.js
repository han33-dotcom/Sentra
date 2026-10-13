/* =========================================================
   Sentra — scroll story engine
   Camera zooms out: device → person → data → team → institution.
   Lenis + GSAP ScrollTrigger + render loop share one clock (gsap.ticker).
   Scroll sets a target pose from live layout; frames damp toward it.
   ========================================================= */
(function () {
  "use strict";
  var root = document.documentElement;
  var REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var panels = [].slice.call(document.querySelectorAll(".panel"));
  var railItems = [].slice.call(document.querySelectorAll(".rail li"));
  var navClock = document.getElementById("navClock");
  var screenHook = function () {};

  /* ---------------- theme ---------------- */
  var themeListeners = [];
  (function initTheme() {
    var btn = document.getElementById("themeBtn"), txt = document.getElementById("themeTxt");
    function label() { var t = root.getAttribute("data-theme"); txt.textContent = t === "dark" ? "Dark" : t === "light" ? "Light" : "Auto"; }
    label();
    btn.addEventListener("click", function () {
      var t = root.getAttribute("data-theme");
      var sysDark = matchMedia("(prefers-color-scheme: dark)").matches;
      var next = !t ? (sysDark ? "light" : "dark") : t === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("sentra-theme", next); } catch (e) {}
      label();
    });
    function fire() { requestAnimationFrame(function () { themeListeners.forEach(function (f) { f(); }); }); }
    new MutationObserver(fire).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    var mq = matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", fire); else if (mq.addListener) mq.addListener(fire);
  })();

  if (window.SentraCharts) { SentraCharts.init(); themeListeners.push(SentraCharts.retheme); }

  /* ---------------- form ---------------- */
  (function initForm() {
    var form = document.getElementById("pilotForm"); if (!form) return;
    var done = document.getElementById("formDone");
    function setErr(input, msg) {
      var f = input.closest(".field"); f.classList.toggle("has-err", !!msg);
      f.querySelector(".err").textContent = msg || "";
      input.setAttribute("aria-invalid", msg ? "true" : "false");
    }
    function check(input) {
      var v = input.value.trim(), msg = "";
      if (!v) msg = input.tagName === "SELECT" ? "Please choose one." : "Please fill this in.";
      else if (input.type === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v)) msg = "That email doesn't look right.";
      setErr(input, msg); return !msg;
    }
    [].forEach.call(form.elements, function (el) {
      if (el.name) el.addEventListener("blur", function () { if (el.value) check(el); });
      if (el.name) el.addEventListener("input", function () { if (el.closest(".field").classList.contains("has-err")) check(el); });
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ok = true, first = null;
      [].forEach.call(form.elements, function (el) { if (el.name && !check(el)) { ok = false; first = first || el; } });
      if (!ok) { first.focus(); return; }
      var data = Object.fromEntries(new FormData(form).entries());
      // TODO: send `data` to the real endpoint (Formspree, EmailJS or our API), e.g.
      // fetch("https://formspree.io/f/XXXX", { method: "POST", headers: { Accept: "application/json" }, body: new FormData(form) })
      document.getElementById("doneOrg").textContent = data.organization;
      form.hidden = true; done.hidden = false;
      screenHook("sent");
    });
  })();

  /* ---------------- layout progress (shared by 3D, clock, rail) ---------------- */
  function easeCos(p) { return (1 - Math.cos(Math.PI * Math.max(0, Math.min(1, p)))) / 2; }
  function layoutProgress() {
    var vh = innerHeight, cur = 0, p = 1;
    for (var i = 1; i < panels.length; i++) {
      var top = panels[i].getBoundingClientRect().top;
      var pi = (0.95 * vh - top) / (0.7 * vh);
      if (pi > 0) { cur = i; p = Math.min(1, pi); }
    }
    return { prev: cur > 0 ? cur - 1 : 0, cur: cur, p: cur > 0 ? easeCos(p) : 1, raw: p };
  }
  function toMin(s) { var a = s.split(":"); return +a[0] * 60 + +a[1]; }
  function fmt(m) { m = Math.round(m); var h = Math.floor(m / 60), mm = m % 60; return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm; }
  var clockStr = "05:30";
  var lastScale = "", lastDim = null, lastClock = "";
  function updateChrome() {
    var L = layoutProgress();
    var a = panels[L.prev], b = panels[L.cur];
    var m = toMin(a.dataset.time) + (toMin(b.dataset.time) - toMin(a.dataset.time)) * L.p;
    clockStr = fmt(m);
    if (clockStr !== lastClock) { navClock.textContent = clockStr; lastClock = clockStr; }
    var active = L.p > .5 ? b : a;
    var sc = active.dataset.scale;
    if (sc !== lastScale) { railItems.forEach(function (li) { li.classList.toggle("is-active", li.dataset.scale === sc); }); lastScale = sc; }
    var dim = !!active.dataset.dim;
    if (dim !== lastDim) { document.body.classList.toggle("is-dim", dim); lastDim = dim; }
    return L;
  }

  /* data signals list reveal */
  var sigList = document.querySelector(".signals");
  if (sigList && "IntersectionObserver" in window) {
    new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) sigList.classList.add("is-on"); }); }, { threshold: .4 }).observe(sigList);
  }

  /* ---------------- static fallback path ---------------- */
  function goStatic() {
    root.classList.remove("motion"); root.classList.add("static");
    addEventListener("scroll", updateChrome, { passive: true });
    updateChrome();
  }
  if (root.classList.contains("static") || !window.THREE || !window.gsap) { goStatic(); return; }

  try { init3D(); } catch (err) { console.error("3D init failed, using static fallback", err); goStatic(); }

  /* ======================================================= */
  function init3D() {
    gsap.registerPlugin(ScrollTrigger);
    var stage = document.getElementById("stage");
    var canvas = document.getElementById("gl");
    var labelsEl = document.getElementById("labels");
    var narrow = innerWidth <= 900;

    /* ---- smooth scroll on one clock ---- */
    var lenis = null;
    if (!REDUCE && window.Lenis) {
      lenis = new Lenis({ lerp: 0.075, wheelMultiplier: 0.9, smoothWheel: true });
      lenis.on("scroll", ScrollTrigger.update);
      gsap.ticker.add(function (t) { lenis.raf(t * 1000); });
      gsap.ticker.lagSmoothing(0);
      document.querySelectorAll('a[href^="#"]').forEach(function (a) {
        a.addEventListener("click", function (e) {
          var id = a.getAttribute("href"); var el = id.length > 1 && document.querySelector(id);
          if (!el) return; e.preventDefault();
          lenis.scrollTo(el, { duration: 1.6 });
        });
      });
    }

    /* ---- renderer ---- */
    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, narrow ? 1.75 : 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.physicallyCorrectLights = true;
    renderer.setClearColor(0x000000, 0);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(30, 1, 0.1, 1000);

    /* environment: gradient + softboxes → PMREM */
    (function env() {
      var c = document.createElement("canvas"); c.width = 1024; c.height = 512;
      var g = c.getContext("2d");
      var gr = g.createLinearGradient(0, 0, 0, 512);
      gr.addColorStop(0, "#e9eef0"); gr.addColorStop(.45, "#9aa4a9"); gr.addColorStop(.55, "#6c757a"); gr.addColorStop(1, "#22282c");
      g.fillStyle = gr; g.fillRect(0, 0, 1024, 512);
      g.fillStyle = "#ffffff"; g.fillRect(120, 80, 240, 120); g.fillRect(610, 50, 320, 90);
      g.globalAlpha = .6; g.fillRect(420, 300, 180, 70);
      var tex = new THREE.CanvasTexture(c);
      tex.mapping = THREE.EquirectangularReflectionMapping; tex.encoding = THREE.sRGBEncoding;
      var pm = new THREE.PMREMGenerator(renderer);
      scene.environment = pm.fromEquirectangular(tex).texture;
      tex.dispose(); pm.dispose();
    })();
    var hemi = new THREE.HemisphereLight(0xf4f1ea, 0x30383d, 1.3); scene.add(hemi);
    var key = new THREE.DirectionalLight(0xfff1de, 2.6); key.position.set(5, 8, 7); scene.add(key);
    var rim = new THREE.DirectionalLight(0xcfe6ff, 1.6); rim.position.set(-6, 3, -5); scene.add(rim);

    /* ---- tokens → linear colours ---- */
    function tok(name) {
      var v = getComputedStyle(root).getPropertyValue("--" + name).trim() || "#888888";
      var c = new THREE.Color();
      if (v.indexOf("rgb") === 0) { var p = v.match(/[\d.]+/g); c.setRGB(p[0] / 255, p[1] / 255, p[2] / 255); }
      else c.set(v);
      return c.convertSRGBToLinear();
    }
    function css(name) { return getComputedStyle(root).getPropertyValue("--" + name).trim(); }

    /* ---- geometry helpers ---- */
    function rrShape(w, h, r) {
      var s = new THREE.Shape(), x = -w / 2, y = -h / 2;
      s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
      s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
      s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
      return s;
    }
    function capsuleGeo(r, len, seg) {
      var pts = [], n = 8, i, a;
      for (i = 0; i <= n; i++) { a = -Math.PI / 2 + i / n * Math.PI / 2; pts.push(new THREE.Vector2(Math.max(1e-4, r * Math.cos(a)), -len / 2 + r * Math.sin(a))); }
      for (i = 0; i <= n; i++) { a = i / n * Math.PI / 2; pts.push(new THREE.Vector2(Math.max(1e-4, r * Math.cos(a)), len / 2 + r * Math.sin(a))); }
      return new THREE.LatheGeometry(pts, seg || 24);
    }
    var Y = new THREE.Vector3(0, 1, 0);
    function limb(a, b, r, mat) {
      var d = new THREE.Vector3().subVectors(b, a), len = d.length();
      var m = new THREE.Mesh(capsuleGeo(r, Math.max(0.01, len)), mat);
      m.position.copy(a).add(b).multiplyScalar(.5);
      m.quaternion.setFromUnitVectors(Y, d.normalize());
      return m;
    }
    function blob(r, pos, scale, mat, segs) {
      var m = new THREE.Mesh(new THREE.SphereGeometry(r, segs || 32, Math.round((segs || 32) * .6)), mat);
      m.position.copy(pos); if (scale) m.scale.copy(scale); return m;
    }
    var V = function (x, y, z) { return new THREE.Vector3(x, y, z); };

    /* ================= the band ================= */
    var rig = new THREE.Group(); scene.add(rig);
    var band = new THREE.Group(); rig.add(band);
    var parts = [];
    function part(obj, off, rot, delay) {
      band.add(obj);
      parts.push({ o: obj, p0: obj.position.clone(), r0: obj.rotation.clone(), off: off, rot: rot || V(0, 0, 0), d: delay });
    }
    var M = {};
    M.housing = new THREE.MeshPhysicalMaterial({ color: tok("housing"), metalness: .75, roughness: .3, clearcoat: .6, clearcoatRoughness: .2 });
    M.strap = new THREE.MeshPhysicalMaterial({ color: tok("strap"), metalness: 0, roughness: .62, clearcoat: .25, side: THREE.DoubleSide });
    M.keeper = new THREE.MeshPhysicalMaterial({ color: tok("accent"), metalness: .1, roughness: .45, clearcoat: .4 });
    M.dark = new THREE.MeshStandardMaterial({ color: 0x12171a, metalness: .3, roughness: .5 });
    M.glass = new THREE.MeshPhysicalMaterial({ color: 0x070a0c, metalness: 0, roughness: .06, clearcoat: 1, clearcoatRoughness: .04, reflectivity: .6 });
    M.gold = new THREE.MeshStandardMaterial({ color: 0xd9b25c, metalness: 1, roughness: .25 });
    M.pcb = new THREE.MeshStandardMaterial({ color: 0x1d4a3f, metalness: .2, roughness: .6 });
    M.chip = new THREE.MeshStandardMaterial({ color: 0x1a1d20, metalness: .4, roughness: .35 });
    M.batt = new THREE.MeshStandardMaterial({ color: 0xb9c0c4, metalness: .85, roughness: .3 });
    M.led = new THREE.MeshBasicMaterial({ color: 0x38ff8c });

    // pebble
    var pebGeo = new THREE.ExtrudeGeometry(rrShape(.5, 1.22, .22), { depth: .15, bevelEnabled: true, bevelThickness: .055, bevelSize: .055, bevelSegments: 6, curveSegments: 28 });
    pebGeo.center();
    var pebble = new THREE.Mesh(pebGeo, M.housing);
    part(pebble, V(0, 0, -.15), V(0, 0, 0), .3);
    // glass
    var glassGeo = new THREE.ExtrudeGeometry(rrShape(.47, 1.17, .21), { depth: .01, bevelEnabled: true, bevelThickness: .006, bevelSize: .006, bevelSegments: 2, curveSegments: 24 });
    glassGeo.center();
    var glass = new THREE.Mesh(glassGeo, M.glass); glass.position.z = .14;
    part(glass, V(0, .1, 1.3), V(.35, 0, 0), .5);
    // screen
    var scr = document.createElement("canvas"); scr.width = 264; scr.height = 640;
    var sg = scr.getContext("2d");
    var scrTex = new THREE.CanvasTexture(scr); scrTex.encoding = THREE.sRGBEncoding; scrTex.anisotropy = 4;
    var scrGeo = new THREE.ShapeGeometry(rrShape(.4, 1.0, .16), 20);
    (function remap() { var p = scrGeo.attributes.position, uv = scrGeo.attributes.uv; for (var i = 0; i < p.count; i++) uv.setXY(i, (p.getX(i) + .2) / .4, (p.getY(i) + .5) / 1.0); uv.needsUpdate = true; })();
    var screenMat = new THREE.MeshBasicMaterial({ map: scrTex, toneMapped: false, transparent: true });
    var screen = new THREE.Mesh(scrGeo, screenMat); screen.position.z = .158;
    part(screen, V(0, .15, 1.8), V(.45, .2, 0), .62);
    // side button
    var btn = new THREE.Mesh(new THREE.BoxGeometry(.04, .18, .07), M.housing); btn.position.set(.31, .12, 0);
    part(btn, V(.7, .1, 0), V(0, 0, .5), .42);
    // internals
    var board = new THREE.Group();
    board.add(new THREE.Mesh(new THREE.BoxGeometry(.38, .95, .022), M.pcb));
    [[0, .22, .1, .14], [-.08, -.05, .12, .1], [.09, -.12, .09, .09], [0, -.33, .16, .06]].forEach(function (c) {
      var m = new THREE.Mesh(new THREE.BoxGeometry(c[2], c[3], .025), M.chip); m.position.set(c[0], c[1], .022); board.add(m);
    });
    board.position.z = .03;
    part(board, V(1.25, .25, .55), V(0, .7, .25), .2);
    var batt = new THREE.Mesh(new THREE.BoxGeometry(.34, .56, .06), M.batt); batt.position.z = -.05;
    part(batt, V(-1.25, -.1, .45), V(0, -.6, -.2), .25);
    var motor = new THREE.Mesh(new THREE.CylinderGeometry(.06, .06, .1, 20), M.chip); motor.position.set(0, -.44, -.04); motor.rotation.x = Math.PI / 2;
    part(motor, V(1.0, -.85, -.1), V(.5, .5, 0), .15);
    // back sensor
    var sensor = new THREE.Group();
    var domeGeo = new THREE.SphereGeometry(.17, 28, 12, 0, Math.PI * 2, 0, Math.PI / 2); domeGeo.rotateX(-Math.PI / 2);
    var dome = new THREE.Mesh(domeGeo, M.glass); dome.scale.z = .45; dome.position.set(0, .06, -.128); sensor.add(dome);
    var leds = [];
    [[-.07, .26], [.07, .26]].forEach(function (p) { var l = new THREE.Mesh(new THREE.CircleGeometry(.024, 16), M.led); l.position.set(p[0], p[1], -.137); l.rotation.y = Math.PI; sensor.add(l); leds.push(l); });
    [[-.06, -.1], [.06, -.1]].forEach(function (p) { var d = new THREE.Mesh(new THREE.PlaneGeometry(.05, .05), M.dark); d.position.set(p[0], p[1], -.136); d.rotation.y = Math.PI; sensor.add(d); });
    [-.06, .06].forEach(function (x) { var g = new THREE.Mesh(new THREE.CylinderGeometry(.018, .018, .02, 12), M.gold); g.rotation.x = Math.PI / 2; g.position.set(x, -.42, -.134); sensor.add(g); });
    part(sensor, V(0, 0, -1.25), V(-.4, 0, 0), .1);
    // connectors
    [-1, 1].forEach(function (s) {
      var c = new THREE.Mesh(new THREE.BoxGeometry(.46, .09, .13), M.dark); c.position.set(0, s * .655, -.2);
      part(c, V(0, s * .55, -.1), V(0, 0, 0), .35);
    });
    // strap — rectangular cross-section swept around an ellipse
    var SA = 1.0, SB = .72, SC = -.84, HW = .25, HT = .035;
    function ell(f, out) {
      var s = Math.sin(f), c = Math.cos(f), ny = s / SA, nz = c / SB, nl = Math.hypot(ny, nz);
      ny /= nl; nz /= nl;
      return { y: SA * s + ny * out, z: SC + SB * c + nz * out, ny: ny, nz: nz, ty: SA * c, tz: -SB * s };
    }
    function strapGeo(f0, f1, out, N) {
      var pos = [], idx = [], rings = [];
      for (var i = 0; i <= N; i++) {
        var e = ell(f0 + (f1 - f0) * i / N, out);
        rings.push([[-HW, e.y + e.ny * HT, e.z + e.nz * HT], [HW, e.y + e.ny * HT, e.z + e.nz * HT], [HW, e.y - e.ny * HT, e.z - e.nz * HT], [-HW, e.y - e.ny * HT, e.z - e.nz * HT]]);
      }
      for (var k = 0; k < 4; k++) {
        var base = pos.length / 3;
        for (i = 0; i <= N; i++) { pos.push.apply(pos, rings[i][k]); pos.push.apply(pos, rings[i][(k + 1) % 4]); }
        for (i = 0; i < N; i++) { var a = base + i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); }
      }
      [0, N].forEach(function (ri) { var b = pos.length / 3; rings[ri].forEach(function (p) { pos.push.apply(pos, p); }); idx.push(b, b + 1, b + 2, b, b + 2, b + 3); });
      var g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
      return g;
    }
    var strap1 = new THREE.Mesh(strapGeo(.7, Math.PI + .55, 0, 90), M.strap);
    part(strap1, V(0, .95, -.2), V(.5, 0, 0), 0);
    var strap2 = new THREE.Group();
    strap2.add(new THREE.Mesh(strapGeo(-.7, -(Math.PI + .55), .072, 90), M.strap));
    [-1.75, -2.0, -2.25, -2.5, -2.75].forEach(function (f) {
      var e = ell(f, .072 + HT + .002);
      var h = new THREE.Mesh(new THREE.CircleGeometry(.04, 16), M.dark);
      h.position.set(0, e.y, e.z); h.lookAt(0, e.y + e.ny, e.z + e.nz); strap2.add(h);
    });
    part(strap2, V(0, -1.0, -.3), V(-.5, 0, 0), .05);
    // keeper loop
    (function keeper() {
      var sh = rrShape(.6, .22, .05), hole = rrShape(.52, .15, .03);
      sh.holes.push(hole);
      var g = new THREE.ExtrudeGeometry(sh, { depth: .09, bevelEnabled: false, curveSegments: 8 }); g.translate(0, .04, -.045);
      var k = new THREE.Mesh(g, M.keeper);
      var f = Math.PI + .3, e = ell(f, 0);
      var n = V(0, e.ny, e.nz), t = V(0, e.ty, e.tz).normalize();
      k.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(V(1, 0, 0), n, t));
      k.position.set(0, e.y, e.z);
      part(k, V(0, -.8, -1.3), V(0, 0, .6), .08);
    })();

    /* ================= the worker (stylized, faceless) ================= */
    var worker = new THREE.Group(); rig.add(worker);
    M.figure = new THREE.MeshPhysicalMaterial({ color: tok("figure"), roughness: .58, metalness: 0, clearcoat: .08, clearcoatRoughness: .6 });
    M.pants = new THREE.MeshStandardMaterial({ color: tok("figure-2"), roughness: .86, metalness: 0 });
    M.vest = new THREE.MeshStandardMaterial({ color: tok("vest"), roughness: .74, metalness: 0, side: THREE.DoubleSide });
    M.reflect = new THREE.MeshStandardMaterial({ color: 0xdfe5e8, roughness: .3, metalness: .45, emissive: 0x1e2427 });
    M.hat = new THREE.MeshPhysicalMaterial({ color: tok("hat"), roughness: .32, clearcoat: .7 });
    M.boot = new THREE.MeshStandardMaterial({ color: new THREE.Color("#2a2622").convertSRGBToLinear(), roughness: .7, metalness: .05 });
    M.shadow = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, opacity: 0, map: (function () {
      var c = document.createElement("canvas"); c.width = c.height = 128; var g = c.getContext("2d");
      var r = g.createRadialGradient(64, 64, 0, 64, 64, 64); r.addColorStop(0, "rgba(0,0,0,.42)"); r.addColorStop(.55, "rgba(0,0,0,.16)"); r.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = r; g.fillRect(0, 0, 128, 128); return new THREE.CanvasTexture(c);
    })() });
    var workerMats = [M.figure, M.pants, M.vest, M.reflect, M.hat, M.boot];
    // tapered capsule: radius r1 at p, r2 at q
    function taperGeo(r1, r2, len, seg) {
      var pts = [], n = 8, i, ang;
      for (i = 0; i <= n; i++) { ang = -Math.PI / 2 + i / n * Math.PI / 2; pts.push(new THREE.Vector2(Math.max(1e-4, r1 * Math.cos(ang)), -len / 2 + r1 * Math.sin(ang))); }
      for (i = 0; i <= n; i++) { ang = i / n * Math.PI / 2; pts.push(new THREE.Vector2(Math.max(1e-4, r2 * Math.cos(ang)), len / 2 + r2 * Math.sin(ang))); }
      return new THREE.LatheGeometry(pts, seg || 28);
    }
    function tlimb(p, q, r1, r2, mat) {
      var d = new THREE.Vector3().subVectors(q, p), len = d.length();
      var m = new THREE.Mesh(taperGeo(r1, r2, Math.max(.01, len)), mat);
      m.position.copy(p).add(q).multiplyScalar(.5); m.quaternion.setFromUnitVectors(Y, d.normalize()); return m;
    }
    /* Real proportions at the band's scale (1 unit ≈ 3 cm, so the figure is ≈ 1.75 m).
       Faceless mannequin in workwear: hard hat, hi-vis vest, work trousers, boots. */
    var BX = -2.7, BZ_ = -6;
    (function buildWorker() {
      var Wk = worker;
      // forearm along x, wrist at origin (strap fits around it); muscle bulge toward the elbow
      var fprof = [[0, -.15], [.98, 0], [1.0, .5], [1.1, 2.6], [1.32, 5.2], [1.48, 7.4], [1.46, 8.6], [1.2, 9.2], [.01, 9.35]];
      var fa = new THREE.LatheGeometry(fprof.map(function (p) { return new THREE.Vector2(Math.max(1e-4, p[0]), p[1]); }), 36);
      fa.rotateZ(Math.PI / 2); fa.scale(1, .92, .66); fa.translate(.35, 0, SC);
      Wk.add(new THREE.Mesh(fa, M.figure));
      Wk.add(blob(1, V(.4, 0, SC), V(.62, .9, .64), M.figure));
      // hand: back of hand to camera, fingers gently curled toward the chest
      Wk.add(blob(1, V(2.15, .05, SC - .05), V(1.78, 1.3, .5), M.figure));
      [[.93, 2.2, .31], [.31, 2.55, .34], [-.31, 2.45, .33], [-.9, 1.95, .29]].forEach(function (f) {
        var k = V(3.65, f[0], SC - .05), m1 = V(3.65 + f[1] * .55, f[0] * 1.02, SC - .3), tip = V(3.65 + f[1] * .85, f[0] * 1.03, SC - 1.05);
        Wk.add(tlimb(k, m1, f[2] * 1.05, f[2], M.figure)); Wk.add(tlimb(m1, tip, f[2], f[2] * .85, M.figure));
      });
      Wk.add(tlimb(V(1.0, 1.05, SC - .15), V(2.5, 1.85, SC - .45), .46, .38, M.figure));
      Wk.add(tlimb(V(2.5, 1.85, SC - .45), V(3.4, 2.05, SC - .95), .38, .32, M.figure));
      // elbow, upper arm, shoulder
      var E = V(-8.9, 0, -1.05), S = V(-8.7, 8.1, -6);
      Wk.add(blob(1.42, E, V(1, 1, .9), M.figure));
      Wk.add(tlimb(E, S, 1.42, 1.85, M.figure));
      Wk.add(blob(2.05, S, V(1, 1, .95), M.figure));
      // torso (lathe, flattened front-to-back)
      var prof = [[-11.4, 0], [-11.4, 4.6], [-10, 5.6], [-7, 5.3], [-4, 5.0], [0, 5.5], [3, 6.15], [6, 6.45], [8, 6.3], [9.4, 5.1], [10.2, 3.1], [10.6, 0]];
      function torsoR(y) { for (var i = 1; i < prof.length; i++) if (y <= prof[i][0]) { var a = prof[i - 1], b = prof[i]; return a[1] + (b[1] - a[1]) * (y - a[0]) / (b[0] - a[0]); } return 0; }
      var torso = new THREE.Mesh(new THREE.LatheGeometry(prof.map(function (p) { return new THREE.Vector2(Math.max(1e-4, p[1]), p[0]); }), 48), M.figure);
      torso.scale.z = .6; torso.position.set(BX, 0, BZ_); Wk.add(torso);
      // hi-vis vest with reflective tape
      var vp = []; for (var y = -8.2; y <= 8.4; y += .4) vp.push(new THREE.Vector2(torsoR(y) * 1.045 + .06, y));
      var vest = new THREE.Mesh(new THREE.LatheGeometry(vp, 48), M.vest); vest.scale.z = .6; vest.position.copy(torso.position); Wk.add(vest);
      [-4.1, -1.9].forEach(function (yy) {
        var r = torsoR(yy) * 1.055 + .09;
        var s = new THREE.Mesh(new THREE.CylinderGeometry(r, r, .75, 48, 1, true), M.reflect);
        s.scale.z = .6; s.position.set(BX, yy, BZ_); Wk.add(s);
      });
      // neck and head (egg-shaped, faceless)
      Wk.add(tlimb(V(BX, 9.4, BZ_ - .2), V(BX, 11.8, BZ_ + .1), 2.05, 1.85, M.figure));
      var hprof = [[0, -3.7], [1.0, -3.45], [1.85, -2.8], [2.35, -1.7], [2.6, 0], [2.65, 1.5], [2.3, 2.7], [1.4, 3.5], [.01, 3.8]];
      var head = new THREE.Mesh(new THREE.LatheGeometry(hprof.map(function (p) { return new THREE.Vector2(Math.max(1e-4, p[0]), p[1]); }), 40), M.figure);
      head.scale.z = 1.18; head.position.set(BX, 14.4, BZ_ + .3); Wk.add(head);
      // hard hat: dome, front peak, ridge
      var hat = new THREE.Mesh(new THREE.SphereGeometry(3.05, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), M.hat);
      hat.position.set(BX, 15.55, BZ_ + .3); hat.scale.set(.97, .92, 1.16); Wk.add(hat);
      var brim = new THREE.Mesh(new THREE.CylinderGeometry(3.45, 3.5, .16, 48), M.hat); brim.position.set(BX, 15.6, BZ_ + .65); brim.scale.z = 1.2; Wk.add(brim);
      var ridge = new THREE.Mesh(new THREE.BoxGeometry(.45, .22, 5.8), M.hat); ridge.position.set(BX, 18.02, BZ_ + .3); Wk.add(ridge);
      // relaxed other arm
      var S2 = V(3.3, 8.1, -6), E2 = V(4.3, -1.7, -5.5), W2 = V(4.6, -10.4, -5.0);
      Wk.add(blob(2.05, S2, V(1, 1, .95), M.figure));
      Wk.add(tlimb(S2, E2, 1.85, 1.42, M.figure)); Wk.add(blob(1.4, E2, null, M.figure));
      Wk.add(tlimb(E2, W2, 1.45, 1.0, M.figure));
      Wk.add(blob(1, V(4.72, -11.95, -5.0), V(.6, 2.0, 1.25), M.figure));
      // pelvis, legs, boots
      Wk.add(blob(1, V(BX, -10.6, BZ_), V(5.75, 2.8, 3.55), M.pants));
      [-2.8, 2.8].forEach(function (dx) {
        var x = BX + dx, hip = V(x, -11.2, BZ_), knee = V(x + dx * .04, -25.6, BZ_ + .5), ank = V(x + dx * .06, -37.6, BZ_ - .1);
        Wk.add(tlimb(hip, knee, 2.75, 1.95, M.pants));
        Wk.add(blob(1.95, knee, null, M.pants));
        Wk.add(tlimb(knee, ank, 1.9, 1.25, M.pants));
        Wk.add(blob(1, V(ank.x, -38.9, BZ_ + 1.1), V(1.8, 1.25, 3.55), M.boot));
      });
      var sh = new THREE.Mesh(new THREE.PlaneGeometry(32, 26), M.shadow); sh.rotation.x = -Math.PI / 2; sh.position.set(BX, -40.12, BZ_ + .6); Wk.add(sh);
    })();
    var GROUND = -40.15;

    /* ================= data streams ================= */
    var STREAMS = [
      { k: "s-hr", name: "Heart rate", val: "74 bpm" },
      { k: "s-sleep", name: "Sleep", val: "6 h 10 m" },
      { k: "s-hrv", name: "HRV", val: "48 ms" },
      { k: "s-br", name: "Breathing rate", val: "15 br/min" },
      { k: "s-temp", name: "Skin temp", val: "+0.1 °C" },
      { k: "s-move", name: "Movement", val: "412 steps" }
    ];
    var NPER = narrow ? 70 : 110;
    var curves = STREAMS.map(function (s, i) {
      var o = i - 2.5;
      return new THREE.CatmullRomCurve3([V(.1, -.25 + i * .1, .2), V(1.1, .2 + o * .22, 1.0), V(2.6, .9 + o * .55, 1.1), V(4.4, 1.3 + o * .85, .7), V(6.2, 1.5 + o * 1.05, .2)]);
    });
    var curvePts = curves.map(function (c) { return c.getSpacedPoints(200); });
    var sGeo = new THREE.BufferGeometry();
    var sPos = new Float32Array(STREAMS.length * NPER * 3), sCol = new Float32Array(STREAMS.length * NPER * 3);
    sGeo.setAttribute("position", new THREE.BufferAttribute(sPos, 3));
    sGeo.setAttribute("color", new THREE.BufferAttribute(sCol, 3));
    var sU = new Float32Array(STREAMS.length * NPER), sJ = new Float32Array(STREAMS.length * NPER * 2);
    (function seed() { for (var i = 0; i < sU.length; i++) { sU[i] = Math.random(); sJ[i * 2] = Math.random() * 2 - 1; sJ[i * 2 + 1] = Math.random() * 2 - 1; } })();
    function dotTexture() {
      var c = document.createElement("canvas"); c.width = c.height = 64; var g = c.getContext("2d");
      var r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(.45, "rgba(255,255,255,.9)"); r.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = r; g.fillRect(0, 0, 64, 64); var t = new THREE.CanvasTexture(c); return t;
    }
    var sMat = new THREE.PointsMaterial({ size: .13, sizeAttenuation: true, vertexColors: true, map: dotTexture(), transparent: true, depthWrite: false, opacity: 0 });
    var points = new THREE.Points(sGeo, sMat); points.frustumCulled = false; rig.add(points);
    function colorStreams() {
      STREAMS.forEach(function (s, i) { var c = tok(s.k); for (var j = 0; j < NPER; j++) { var q = (i * NPER + j) * 3; sCol[q] = c.r; sCol[q + 1] = c.g; sCol[q + 2] = c.b; } });
      sGeo.attributes.color.needsUpdate = true;
    }
    colorStreams();
    // baseline corridor
    var base = new THREE.Group(); rig.add(base);
    var BX0 = 1.1, BX1 = 6.9, BY = 1.0, BZ = .55, BH = .9;
    M.corr = new THREE.MeshBasicMaterial({ color: tok("accent"), transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide });
    M.corrEdge = new THREE.MeshBasicMaterial({ color: tok("accent"), transparent: true, opacity: 0, depthWrite: false });
    M.pop = new THREE.MeshBasicMaterial({ color: tok("muted"), transparent: true, opacity: 0, depthWrite: false });
    var corr = new THREE.Mesh(new THREE.PlaneGeometry(BX1 - BX0, BH), M.corr); corr.position.set((BX0 + BX1) / 2, BY, BZ); base.add(corr);
    [-1, 1].forEach(function (s) { var e = new THREE.Mesh(new THREE.PlaneGeometry(BX1 - BX0, .025), M.corrEdge); e.position.set((BX0 + BX1) / 2, BY + s * BH / 2, BZ + .001); base.add(e); });
    for (var di = 0; di < 22; di++) { var d = new THREE.Mesh(new THREE.PlaneGeometry(.18, .025), M.pop); d.position.set(BX0 + .1 + di * (BX1 - BX0) / 22, BY + 1.75, BZ); base.add(d); }

    /* ================= site map, crew, sites, dome ================= */
    var world = new THREE.Group(); scene.add(world);
    var MW = 900, MH = 580;
    var WU = .22, WV = .3; // worker position on the map (normalized)
    var MCX = BX - (WU - .5) * MW, MCZ = BZ_ + .6 - (WV - .5) * MH;
    var SITE_ZONES = [
      ["BLOCK A · CORE", .07, .1, .27, .36], ["BLOCK B", .4, .1, .2, .3], ["LAYDOWN YARD", .68, .08, .25, .34],
      ["BATCHING", .07, .6, .2, .3], ["SITE OFFICE", .34, .66, .16, .2], ["WORKSHOP", .56, .56, .18, .3], ["GATE 2", .82, .76, .12, .15]
    ];
    function seeded(seed) { var s = seed; return function () { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; }; }
    function drawSite(c, W, H, zones, dots, title) {
      var g = c.getContext("2d");
      g.clearRect(0, 0, W, H);
      var rad = W * .03;
      g.fillStyle = css("map"); g.beginPath(); g.moveTo(rad, 0); g.arcTo(W, 0, W, H, rad); g.arcTo(W, H, 0, H, rad); g.arcTo(0, H, 0, 0, rad); g.arcTo(0, 0, W, 0, rad); g.fill();
      g.save(); g.clip();
      g.strokeStyle = css("map-line"); g.lineWidth = Math.max(1, W / 1400);
      var step = W / 28;
      for (var x = step; x < W; x += step) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
      for (var y = step; y < H; y += step) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
      g.strokeStyle = css("map-road"); g.lineWidth = W * .028; g.lineCap = "round";
      g.beginPath(); g.moveTo(0, H * .52); g.lineTo(W, H * .52); g.moveTo(W * .365, H * .52); g.lineTo(W * .365, H); g.moveTo(W * .655, 0); g.lineTo(W * .655, H * .52); g.stroke();
      zones.forEach(function (z) {
        var zx = z[1] * W, zy = z[2] * H, zw = z[3] * W, zh = z[4] * H, r = W * .008;
        g.fillStyle = css("map-zone"); g.beginPath(); g.moveTo(zx + r, zy); g.arcTo(zx + zw, zy, zx + zw, zy + zh, r); g.arcTo(zx + zw, zy + zh, zx, zy + zh, r); g.arcTo(zx, zy + zh, zx, zy, r); g.arcTo(zx, zy, zx + zw, zy, r); g.fill();
        g.fillStyle = css("muted"); g.font = "500 " + Math.round(W * .0125) + "px " + css("f-mono"); g.textBaseline = "top";
        g.fillText(z[0], zx + W * .008, zy + W * .008);
      });
      if (dots) dots.forEach(function (d) {
        var col = d.s === "a" ? css("amber") : d.s === "g" ? css("grey") : css("accent");
        g.fillStyle = col; g.globalAlpha = .22; g.beginPath(); g.arc(d.u * W, d.v * H, W * .016, 0, 6.283); g.fill();
        g.globalAlpha = 1; g.beginPath(); g.arc(d.u * W, d.v * H, W * .0075, 0, 6.283); g.fill();
      });
      if (title) { g.fillStyle = css("ink"); g.font = "600 " + Math.round(W * .03) + "px " + css("f-display"); g.textBaseline = "bottom"; g.fillText(title, W * .03, H * .97); }
      g.restore();
      g.strokeStyle = css("map-line"); g.lineWidth = W / 600;
      g.beginPath(); g.moveTo(rad, 1); g.arcTo(W - 1, 1, W - 1, H - 1, rad); g.arcTo(W - 1, H - 1, 1, H - 1, rad); g.arcTo(1, H - 1, 1, 1, rad); g.arcTo(1, 1, W - 1, 1, rad); g.stroke();
    }
    var mapRes = narrow ? 1024 : 2048;
    var mapCanvas = document.createElement("canvas"); mapCanvas.width = mapRes; mapCanvas.height = Math.round(mapRes * MH / MW);
    var mapTex = new THREE.CanvasTexture(mapCanvas); mapTex.encoding = THREE.sRGBEncoding; mapTex.anisotropy = 8;
    M.map = new THREE.MeshBasicMaterial({ map: mapTex, transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
    var mapPlane = new THREE.Mesh(new THREE.PlaneGeometry(MW, MH), M.map);
    mapPlane.rotation.x = -Math.PI / 2; mapPlane.position.set(MCX, GROUND - .05, MCZ); mapPlane.renderOrder = -2;
    world.add(mapPlane);
    // crew
    var crew = [{ u: WU, v: WV, s: "c", me: true }];
    (function placeCrew() {
      var r = seeded(23), tries = 0;
      var states = ["a", "a", "a", "a", "g"];
      while (crew.length < 31 && tries++ < 4000) {
        var u = .06 + r() * .88, v = .1 + r() * .82, ok = true;
        for (var i = 0; i < crew.length; i++) { var du = (crew[i].u - u) * MW, dv = (crew[i].v - v) * MH; if (du * du + dv * dv < 40 * 40) { ok = false; break; } }
        if (ok) crew.push({ u: u, v: v, s: states[crew.length - 1] || "c" });
      }
    })();
    M.dotC = new THREE.MeshBasicMaterial({ color: tok("accent"), transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
    M.dotA = new THREE.MeshBasicMaterial({ color: tok("amber"), transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
    M.dotG = new THREE.MeshBasicMaterial({ color: tok("grey"), transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
    M.haloC = M.dotC.clone(); M.haloA = M.dotA.clone(); M.haloG = M.dotG.clone();
    M.ring = M.dotA.clone();
    var dotGeo = new THREE.CircleGeometry(5.6, 28), haloGeo = new THREE.CircleGeometry(13, 32), ringGeo = new THREE.RingGeometry(11.5, 13.5, 40);
    dotGeo.rotateX(-Math.PI / 2); haloGeo.rotateX(-Math.PI / 2); ringGeo.rotateX(-Math.PI / 2);
    var rings = [];
    crew.forEach(function (c) {
      var x = MCX + (c.u - .5) * MW, z = MCZ + (c.v - .5) * MH;
      c.x = x; c.z = z;
      var dm = c.s === "a" ? M.dotA : c.s === "g" ? M.dotG : M.dotC, hm = c.s === "a" ? M.haloA : c.s === "g" ? M.haloG : M.haloC;
      var h = new THREE.Mesh(haloGeo, hm); h.position.set(x, GROUND + .02, z); world.add(h);
      var d = new THREE.Mesh(dotGeo, dm); d.position.set(x, GROUND + .04, z); world.add(d);
      if (c.s === "a") { var rg = new THREE.Mesh(ringGeo, M.ring); rg.position.set(x, GROUND + .03, z); world.add(rg); rings.push(rg); }
    });
    // other sites
    var otherSites = [
      { dx: 1030, dz: 0, title: "Site 3 · Yard", seed: 31, n: 24 },
      { dx: 0, dz: 690, title: "Site 1 · Tower", seed: 41, n: 38 },
      { dx: 1030, dz: 690, title: "Site 4 · Depot", seed: 53, n: 19 }
    ];
    var siteZonesAlt = [
      [["STOCKYARD", .06, .08, .34, .3], ["CRANE BAY", .46, .1, .22, .32], ["STORES", .74, .1, .18, .28], ["LOADING", .08, .6, .26, .28], ["OFFICE", .44, .64, .14, .2], ["GATE 1", .7, .62, .2, .24]],
      [["TOWER CORE", .1, .08, .3, .4], ["PODIUM", .46, .08, .26, .34], ["HOIST", .78, .1, .14, .2], ["LAYDOWN", .08, .6, .24, .3], ["WELFARE", .4, .62, .18, .24], ["GATE 3", .72, .66, .2, .2]],
      [["WAREHOUSE", .06, .08, .4, .34], ["FLEET", .52, .1, .4, .3], ["DOCKS", .08, .6, .3, .3], ["OFFICE", .46, .62, .16, .22], ["FUEL BAY", .7, .6, .2, .28]]
    ];
    M.sites = [];
    var siteCanvases = [];
    otherSites.forEach(function (s, i) {
      var c = document.createElement("canvas"); c.width = 1024; c.height = Math.round(1024 * MH / MW);
      var r = seeded(s.seed), dots = [];
      for (var k = 0; k < s.n; k++) dots.push({ u: .06 + r() * .88, v: .1 + r() * .8, s: k < 2 + (i % 2) ? "a" : k === 5 ? "g" : "c" });
      s.dots = dots; s.zones = siteZonesAlt[i];
      var t = new THREE.CanvasTexture(c); t.encoding = THREE.sRGBEncoding; t.anisotropy = 4;
      var m = new THREE.MeshBasicMaterial({ map: t, transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
      var pl = new THREE.Mesh(new THREE.PlaneGeometry(MW, MH), m);
      pl.rotation.x = -Math.PI / 2; pl.position.set(MCX + s.dx, GROUND - .05, MCZ + s.dz); pl.renderOrder = -2;
      world.add(pl); M.sites.push(m); siteCanvases.push({ c: c, t: t, s: s });
    });
    function drawMaps() {
      drawSite(mapCanvas, mapCanvas.width, mapCanvas.height, SITE_ZONES, null, null);
      mapTex.needsUpdate = true;
      siteCanvases.forEach(function (o) { drawSite(o.c, o.c.width, o.c.height, o.s.zones, o.s.dots, null); o.t.needsUpdate = true; });
    }
    drawMaps();
    var CX = MCX + 515, CZ = MCZ + 345;
    // data-residency dome + on-prem node
    var domeG = new THREE.Group(); world.add(domeG); domeG.position.set(CX, GROUND, CZ);
    var DR = 1150;
    M.domeLine = new THREE.LineBasicMaterial({ color: tok("accent"), transparent: true, opacity: 0, depthWrite: false });
    M.domeFill = new THREE.MeshBasicMaterial({ color: tok("accent"), transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
    (function buildDome() {
      var pts = [], i, j, a, b;
      for (i = 1; i <= 5; i++) { var el = i / 6 * Math.PI / 2, r = DR * Math.cos(el), y = DR * Math.sin(el); for (j = 0; j < 96; j++) { a = j / 96 * 6.283; b = (j + 1) / 96 * 6.283; pts.push(r * Math.cos(a), y, r * Math.sin(a), r * Math.cos(b), y, r * Math.sin(b)); } }
      for (j = 0; j < 16; j++) { a = j / 16 * 6.283; for (i = 0; i < 24; i++) { var e1 = i / 24 * Math.PI / 2, e2 = (i + 1) / 24 * Math.PI / 2; pts.push(DR * Math.cos(e1) * Math.cos(a), DR * Math.sin(e1), DR * Math.cos(e1) * Math.sin(a), DR * Math.cos(e2) * Math.cos(a), DR * Math.sin(e2), DR * Math.cos(e2) * Math.sin(a)); } }
      var g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      domeG.add(new THREE.LineSegments(g, M.domeLine));
      var fill = new THREE.Mesh(new THREE.SphereGeometry(DR, 48, 16, 0, 6.283, 0, Math.PI / 2), M.domeFill); domeG.add(fill);
      var ring = new THREE.Mesh(new THREE.RingGeometry(DR - 6, DR + 6, 128), M.domeFill.clone()); ring.rotation.x = -Math.PI / 2; ring.position.y = .5; domeG.add(ring); M.domeRing = ring.material;
      // on-prem node
      M.node = new THREE.MeshStandardMaterial({ color: tok("housing"), roughness: .4, metalness: .6, transparent: true, opacity: 0 });
      M.nodeGlow = new THREE.MeshBasicMaterial({ color: tok("accent"), transparent: true, opacity: 0, toneMapped: false });
      for (i = 0; i < 3; i++) {
        var bx = new THREE.Mesh(new THREE.BoxGeometry(35, 74, 35), M.node); bx.position.set(-48 + i * 48, 37, 0); domeG.add(bx);
        for (j = 0; j < 4; j++) { var st = new THREE.Mesh(new THREE.BoxGeometry(35.6, 2.4, 35.6), M.nodeGlow); st.position.set(-48 + i * 48, 13 + j * 16, 0); domeG.add(st); }
      }
    })();

    /* ================= HTML labels ================= */
    var labels = [];
    function label(html, cls, getPos, getVis, anchor) {
      var el = document.createElement("div"); el.className = "lbl " + (cls || ""); el.innerHTML = html; labelsEl.appendChild(el);
      labels.push({ el: el, pos: getPos, vis: getVis, anchor: anchor || "left", last: -1 });
    }
    var cur = {}; // current damped pose (filled later)
    var tmp = new THREE.Vector3();
    STREAMS.forEach(function (s, i) {
      var p = curvePts[i][Math.round(200 * (.6 + (i % 2) * .09))];
      label('<i style="--c:var(--' + s.k + ')"></i>' + s.name + ' <small>' + s.val + "</small>", "", function () { return rig.localToWorld(tmp.copy(p)); },
        function () { return Math.max(0, Math.min(1, cur.sf * 1.8 - i * .14)) * (1 - cur.bl); });
    });
    label('<i></i>Personal normal <small>last 28 days</small>', "lbl--big", function () { return rig.localToWorld(tmp.set(BX0, BY + BH / 2 + .32, BZ)); }, function () { return cur.bl * cur.sf; });
    label('<i style="--c:var(--muted)"></i>Population average <small>not used</small>', "", function () { return rig.localToWorld(tmp.set(BX0, BY + 1.75 + .3, BZ)); }, function () { return cur.bl * cur.sf * .9; });
    label('<i></i>W-0114 <small>ready</small>', "", function () { return tmp.set(BX, 24, BZ_); }, function () { return cur.crew * (1 - cur.sites); }, "center");
    label('<i style="--c:var(--ink)"></i>Site 2 · Plant <small>31 on shift</small>', "lbl--big", function () { return tmp.set(MCX - MW / 2 + 6, GROUND, MCZ + MH / 2 + 16); }, function () { return cur.crew; });
    otherSites.forEach(function (s) {
      label('<i style="--c:var(--ink)"></i>' + s.title + ' <small>' + s.n + " on shift</small>", "", function () { return tmp.set(MCX + s.dx - MW / 2 + 6, GROUND, MCZ + s.dz + MH / 2 + 16); }, function () { return cur.sites; });
    });
    label('<i></i>In-region hosting <small>GCC data residency</small>', "lbl--big", function () { return tmp.set(CX, GROUND + DR + 30, CZ); }, function () { return cur.dome; }, "center");
    label('<i></i>On-prem AI model', "", function () { return tmp.set(CX + 70, GROUND + 100, CZ); }, function () { return cur.dome; });

    /* ================= poses ================= */
    var D = { tx: 0, ty: 0, tz: 0, d: 8, yaw: 0, pitch: .05, e: 0, rx: 0, ry: 0, rz: 0, wk: 1, sf: 0, bl: 0, crew: 0, sites: 0, dome: 0, ox: .25 };
    function P(o) { var r = {}; for (var k in D) r[k] = (k in o) ? o[k] : D[k]; return r; }
    var POSES = {
      hero: P({ d: 10.4, pitch: .04, e: 1, rx: .22, ry: -.6, rz: .08, wk: 0 }),
      worker: P({ tx: -1.6, ty: -10.5, tz: -4, d: 138, yaw: .42, pitch: .08 }),
      data: P({ tx: 3.0, ty: 1.0, tz: 0, d: 19, yaw: .2, pitch: .1, sf: 1, wk: .2 }),
      baseline: P({ tx: 3.9, ty: 1.6, tz: .3, d: 17, yaw: .06, pitch: .05, sf: 1, bl: 1, wk: .2 }),
      ready: P({ d: 6.0, yaw: -.34, pitch: .16 }),
      exertion: P({ d: 5.6, yaw: .3, pitch: .1 }),
      lone: P({ d: 5.7, yaw: -.12, pitch: .34 }),
      trends: P({ d: 5.8, yaw: .38, pitch: .2 }),
      wear: P({ d: 5.9, yaw: -.42, pitch: .08 }),
      team: P({ tx: BX + 95, ty: GROUND, tz: BZ_ + 65, d: 900, yaw: .35, pitch: .92, crew: 1 }),
      institution: P({ tx: CX, ty: GROUND, tz: CZ, d: 1650, yaw: .22, pitch: 1.05, crew: 1, sites: 1, ox: 0 }),
      trust: P({ tx: CX, ty: GROUND + 190, tz: CZ, d: 4200, yaw: .62, pitch: .5, crew: 1, sites: 1, dome: 1 }),
      pilot: P({ tx: -1.6, ty: -10.5, tz: -4, d: 138, yaw: -.42, pitch: .1 }),
      cta: P({ d: 7.4, pitch: .05, rx: .14, ry: -.5, rz: .05, wk: 0 })
    };
    // the canvas now only covers the visual column, so the subject is centred in it
    for (var pk0 in POSES) { POSES[pk0].ox = 0; }
    POSES.institution.d = 4000;
    if (narrow) {
      // phones: canvas is the top strip; centre the subject and give it a little more room
      for (var pk in POSES) { POSES[pk].ox = 0; }
      POSES.hero.d = 11; POSES.cta.d = 7.6;
      POSES.data.tx = 3.4; POSES.data.d = 24; POSES.baseline.d = 19;
      POSES.team.tx = MCX + 50; POSES.team.tz = MCZ; POSES.team.d = 1150;
      POSES.institution.d = 4000; POSES.trust.d = 5600;
      POSES.worker.d = 118; POSES.pilot.d = 118;
    }
    var KEYS = Object.keys(D);
    function targetPose() {
      var L = layoutProgress();
      var a = POSES[panels[L.prev].dataset.pose] || D, b = POSES[panels[L.cur].dataset.pose] || D, t = L.p, out = {};
      KEYS.forEach(function (k) {
        if (k === "d") out.d = Math.log(a.d) + (Math.log(b.d) - Math.log(a.d)) * t;
        else out[k] = a[k] + (b[k] - a[k]) * t;
      });
      return out;
    }
    var tgt0 = targetPose(); KEYS.forEach(function (k) { cur[k] = tgt0[k]; });

    /* ================= screen (Canvas 2D) ================= */
    var SC_ = { bg: "#04070a", ink: "#e9f3f1", dim: "#8ba29d", acc: "#5ccab5", ok: "#58c98a", amb: "#f1b44c", red: "#f07162", line: "rgba(233,243,241,.12)" };
    var screenState = { mode: "shift", next: null, fade: 1, bootAt: -1, sent: false };
    var SW = 264, SH = 640;
    function fitText(s, x, y, maxW, size, weight, family, color, align) {
      sg.font = (weight || 600) + " " + size + "px " + (family || "IBM Plex Sans, system-ui, sans-serif");
      var w = sg.measureText(s).width, sx = w > maxW ? maxW / w : 1;
      sg.save(); sg.translate(x, y); sg.scale(sx, 1); sg.fillStyle = color || SC_.ink; sg.textAlign = align || "center"; sg.textBaseline = "alphabetic"; sg.fillText(s, 0, 0); sg.restore();
    }
    var MONO = "IBM Plex Mono, ui-monospace, monospace", COND = "Barlow Condensed, Arial Narrow, sans-serif";
    function ring(cx, cy, r, w, frac, col, track) {
      sg.lineCap = "round"; sg.lineWidth = w;
      sg.strokeStyle = track || SC_.line; sg.beginPath(); sg.arc(cx, cy, r, 0, 6.283); sg.stroke();
      if (frac > 0) { sg.strokeStyle = col; sg.beginPath(); sg.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + 6.283 * Math.min(frac, 1)); sg.stroke(); }
    }
    function pill(x, y, w, h, col, fill) { sg.beginPath(); var r = h / 2; sg.moveTo(x + r, y); sg.arcTo(x + w, y, x + w, y + h, r); sg.arcTo(x + w, y + h, x, y + h, r); sg.arcTo(x, y + h, x, y, r); sg.arcTo(x, y, x + w, y, r); if (fill) { sg.fillStyle = col; sg.fill(); } else { sg.strokeStyle = col; sg.lineWidth = 3; sg.stroke(); } }
    function statusBar() {
      fitText(clockStr, 26, 54, 120, 26, 500, MONO, SC_.ink, "left");
      sg.strokeStyle = SC_.dim; sg.lineWidth = 2; sg.strokeRect(196, 36, 36, 18); sg.fillStyle = SC_.dim; sg.fillRect(233, 41, 3, 8);
      sg.fillStyle = SC_.ok; sg.fillRect(199, 39, 24, 12);
    }
    var T = 0;
    var SCREENS = {
      off: function () { },
      boot: function (k) {
        var cx = SW / 2;
        sg.strokeStyle = SC_.acc; sg.lineWidth = 6; sg.lineJoin = "round"; sg.lineCap = "round";
        sg.beginPath(); sg.moveTo(cx - 52, 280); sg.lineTo(cx - 22, 280); sg.lineTo(cx - 8, 248); sg.lineTo(cx + 10, 314); sg.lineTo(cx + 24, 280); sg.lineTo(cx + 52, 280); sg.stroke();
        fitText("SENTRA", cx, 372, 200, 40, 600, COND, SC_.ink);
        pill(62, 420, 140, 10, SC_.line, true); pill(62, 420, Math.max(10, 140 * k), 10, SC_.acc, true);
      },
      shift: function () {
        fitText("ON SHIFT", SW / 2, 150, 200, 22, 500, MONO, SC_.acc);
        fitText(clockStr, SW / 2, 270, 220, 92, 600, COND);
        fitText("Site 2 · Crew B", SW / 2, 316, 220, 22, 500, null, SC_.dim);
        pill(52, 380, 160, 52, SC_.ok, false);
        fitText("CLOCKED IN", SW / 2, 414, 130, 20, 600, MONO, SC_.ok);
        fitText("Shift ends 18:00", SW / 2, 500, 210, 20, 400, null, SC_.dim);
      },
      sync: function () {
        fitText("SYNCING", SW / 2, 130, 200, 22, 500, MONO, SC_.acc);
        var labs = ["HR", "SLEEP", "HRV", "BR", "TEMP", "MOVE"], cols = ["#f07a6c", "#9198e6", "#53c4b2", "#6ab6e6", "#eab250", "#8cc56a"];
        labs.forEach(function (l, i) {
          var y = 190 + i * 62;
          sg.fillStyle = cols[i]; sg.beginPath(); sg.arc(46, y, 9, 0, 6.283); sg.fill();
          fitText(l, 66, y + 8, 80, 21, 500, MONO, SC_.ink, "left");
          for (var b = 0; b < 6; b++) { var h = 6 + 16 * Math.abs(Math.sin(T * 3 + i + b * .8)); sg.fillStyle = cols[i]; sg.globalAlpha = .75; sg.fillRect(150 + b * 13, y + 8 - h, 7, h); }
          sg.globalAlpha = 1;
        });
      },
      base: function () {
        fitText("YOUR NORMAL", SW / 2, 140, 210, 22, 500, MONO, SC_.acc);
        fitText("28 days", SW / 2, 200, 200, 44, 600, COND);
        var x0 = 34, x1 = 230;
        sg.fillStyle = "rgba(92,202,181,.22)"; sg.fillRect(x0, 280, x1 - x0, 110);
        sg.strokeStyle = SC_.acc; sg.lineWidth = 2; sg.beginPath(); sg.moveTo(x0, 280); sg.lineTo(x1, 280); sg.moveTo(x0, 390); sg.lineTo(x1, 390); sg.stroke();
        sg.strokeStyle = SC_.ink; sg.lineWidth = 3; sg.beginPath();
        for (var i = 0; i <= 28; i++) { var x = x0 + i / 28 * (x1 - x0), y = 335 + Math.sin(i * 1.3) * 18 + Math.sin(i * .5) * 10; if (!i) sg.moveTo(x, y); else sg.lineTo(x, y); }
        sg.stroke();
        sg.fillStyle = SC_.ok; sg.beginPath(); sg.arc(x1, 335 + Math.sin(28 * 1.3) * 18 + Math.sin(14) * 10, 9, 0, 6.283); sg.fill();
        fitText("Today: within normal", SW / 2, 452, 220, 20, 500, null, SC_.ok);
      },
      ready: function () {
        var st = [["GREEN", SC_.ok, "Ready for shift", .92], ["AMBER", SC_.amb, "Check-in suggested", .62], ["RED", SC_.red, "Talk before high-risk work", .3]][Math.floor(T / 3.4) % 3];
        fitText("READINESS", SW / 2, 120, 200, 22, 500, MONO, SC_.dim);
        ring(SW / 2, 260, 86, 16, st[3], st[1]);
        fitText(st[0], SW / 2, 278, 140, 44, 600, COND, st[1]);
        fitText(st[2], SW / 2, 400, 224, 21, 600, null, SC_.ink);
        fitText("vs your own baseline", SW / 2, 436, 220, 18, 400, null, SC_.dim);
        fitText("Sleep · RHR · HRV", SW / 2, 500, 220, 18, 500, MONO, SC_.dim);
      },
      exert: function () {
        var bpm = Math.round(146 + Math.sin(T * .7) * 3);
        var beat = (T * 2.4) % 1, pulse = 1 + .15 * Math.exp(-beat * 9);
        sg.save(); sg.translate(SW / 2, 136); sg.scale(pulse, pulse); sg.fillStyle = "#f07a6c";
        sg.beginPath(); sg.moveTo(0, 14); sg.bezierCurveTo(-30, -6, -16, -30, 0, -14); sg.bezierCurveTo(16, -30, 30, -6, 0, 14); sg.fill(); sg.restore();
        fitText(String(bpm), SW / 2, 262, 200, 96, 600, COND);
        fitText("BPM", SW / 2, 296, 100, 20, 500, MONO, SC_.dim);
        sg.lineWidth = 12; sg.lineCap = "round"; sg.strokeStyle = SC_.line; sg.beginPath(); sg.arc(SW / 2, 420, 80, Math.PI * .85, Math.PI * 2.15); sg.stroke();
        var f = (bpm - 60) / 120; sg.strokeStyle = SC_.amb; sg.beginPath(); sg.arc(SW / 2, 420, 80, Math.PI * .85, Math.PI * (.85 + 1.3 * f)); sg.stroke();
        var th = Math.PI * (.85 + 1.3 * ((138 - 60) / 120)); sg.strokeStyle = SC_.ink; sg.lineWidth = 3; sg.beginPath(); sg.moveTo(SW / 2 + Math.cos(th) * 66, 420 + Math.sin(th) * 66); sg.lineTo(SW / 2 + Math.cos(th) * 94, 420 + Math.sin(th) * 94); sg.stroke();
        pill(30, 500, 204, 54, SC_.amb, true);
        fitText("HIGH · 18 MIN", SW / 2, 535, 180, 22, 600, MONO, "#1d1404");
        fitText("Pause when you can", SW / 2, 590, 220, 19, 500, null, SC_.dim);
      },
      lone: function () {
        var c = (T % 30) / 30;
        fitText("STILL OK?", SW / 2, 140, 210, 46, 600, COND);
        ring(SW / 2, 290, 78, 12, 1 - c, c > .75 ? SC_.red : SC_.amb);
        fitText(String(Math.ceil(30 - (T % 30))), SW / 2, 312, 120, 64, 600, COND);
        fitText("No movement 20 min", SW / 2, 412, 220, 19, 500, null, SC_.dim);
        pill(36, 460, 192, 76, SC_.acc, true);
        fitText("I'M OK", SW / 2, 510, 160, 34, 600, COND, "#04211b");
      },
      trend: function () {
        fitText("TRENDS", SW / 2, 120, 200, 22, 500, MONO, SC_.dim);
        function spark(y, col, name, vals) {
          fitText(name, 30, y, 200, 20, 600, null, SC_.ink, "left");
          sg.fillStyle = "rgba(92,202,181,.16)"; sg.fillRect(30, y + 24, 204, 52);
          sg.strokeStyle = col; sg.lineWidth = 4; sg.lineJoin = "round"; sg.beginPath();
          vals.forEach(function (v, i) { var x = 30 + i / (vals.length - 1) * 204, yy = y + 100 - v * 70; if (!i) sg.moveTo(x, yy); else sg.lineTo(x, yy); }); sg.stroke();
          sg.fillStyle = SC_.amb; sg.beginPath(); sg.arc(234, y + 100 - vals[vals.length - 1] * 70, 8, 0, 6.283); sg.fill();
        }
        spark(170, "#6ab6e6", "Breathing ↑", [.42, .38, .45, .4, .36, .44, .47, .41, .43, .46, .7, .78, .84, .9]);
        spark(330, "#eab250", "Skin temp ↑", [.4, .36, .44, .41, .37, .45, .4, .38, .44, .42, .66, .72, .78, .85]);
        fitText("4 nights · trend only", SW / 2, 520, 220, 19, 500, null, SC_.amb);
        fitText("Check-in suggested", SW / 2, 556, 220, 19, 500, null, SC_.dim);
      },
      wear: function () {
        fitText("WORN TODAY", SW / 2, 130, 200, 22, 500, MONO, SC_.dim);
        ring(SW / 2, 270, 84, 16, .92, SC_.acc);
        fitText("9.2 h", SW / 2, 284, 140, 52, 600, COND);
        fitText("of 10 h shift · 92%", SW / 2, 400, 220, 20, 500, null, SC_.ink);
        for (var i = 0; i < 6; i++) { var h = [96, 97, 61, 96, 96, 100][i]; sg.fillStyle = h < 85 ? SC_.amb : SC_.acc; sg.fillRect(42 + i * 32, 540 - h, 18, h); }
        fitText("this week", SW / 2, 584, 200, 18, 400, MONO, SC_.dim);
      },
      clock: function () {
        fitText(clockStr, SW / 2, 290, 220, 96, 600, COND);
        fitText("Site 2 · Plant", SW / 2, 340, 220, 22, 500, null, SC_.dim);
        sg.fillStyle = SC_.ok; sg.beginPath(); sg.arc(SW / 2 - 52, 418, 9, 0, 6.283); sg.fill();
        fitText("All good", SW / 2 + 12, 426, 140, 22, 600, null, SC_.ink);
      },
      mine: function () {
        sg.strokeStyle = SC_.acc; sg.lineWidth = 7; sg.beginPath(); sg.arc(SW / 2, 196, 30, Math.PI, 0); sg.stroke();
        pill(SW / 2 - 48, 196, 96, 76, SC_.acc, true);
        fitText("YOUR DATA", SW / 2, 340, 220, 40, 600, COND);
        fitText("Raw signals: only you", SW / 2, 396, 226, 19, 500, null, SC_.ink);
        fitText("Employer: flags only", SW / 2, 432, 226, 19, 500, null, SC_.dim);
        fitText("Hosted in-region", SW / 2, 500, 220, 18, 500, MONO, SC_.acc);
      },
      paired: function () {
        ring(SW / 2, 250, 72, 12, 1, SC_.acc);
        sg.strokeStyle = SC_.acc; sg.lineWidth = 12; sg.lineCap = "round"; sg.lineJoin = "round";
        sg.beginPath(); sg.moveTo(SW / 2 - 30, 252); sg.lineTo(SW / 2 - 6, 276); sg.lineTo(SW / 2 + 34, 226); sg.stroke();
        fitText("PAIRED", SW / 2, 386, 200, 46, 600, COND);
        fitText("Just wear it.", SW / 2, 432, 220, 21, 500, null, SC_.ink);
        fitText("No setup needed", SW / 2, 470, 220, 19, 400, null, SC_.dim);
      },
      final: function () {
        var sent = screenState.sent;
        ring(SW / 2, 250, 80, 14, 1, sent ? SC_.acc : SC_.ok);
        sg.strokeStyle = sent ? SC_.acc : SC_.ok; sg.lineWidth = 13; sg.lineCap = "round"; sg.lineJoin = "round";
        sg.beginPath(); sg.moveTo(SW / 2 - 34, 252); sg.lineTo(SW / 2 - 8, 278); sg.lineTo(SW / 2 + 38, 222); sg.stroke();
        fitText(sent ? "REQUEST SENT" : "FIT FOR SHIFT", SW / 2, 394, 220, 40, 600, COND);
        fitText(sent ? "Talk soon." : "Ready when you are.", SW / 2, 440, 220, 21, 500, null, SC_.dim);
      }
    };
    SCREENS.sent = SCREENS.final;
    function drawScreen(now) {
      var bootK = 1, mode = screenState.mode;
      sg.globalAlpha = 1; sg.fillStyle = SC_.bg; sg.fillRect(0, 0, SW, SH);
      if (cur.e > .3) { mode = "off"; screenState.bootAt = -1; }
      else {
        if (screenState.bootAt < 0) screenState.bootAt = now;
        var bt = (now - screenState.bootAt) / 1000;
        if (bt < 1.7 && !REDUCE) { mode = "boot"; bootK = bt / 1.5; }
      }
      sg.globalAlpha = mode === "boot" ? 1 : screenState.fade;
      if (mode !== "off" && mode !== "boot") statusBar();
      SCREENS[mode](bootK);
      sg.globalAlpha = 1;
      // glare
      var gl = sg.createLinearGradient(0, 0, SW, SH * .6);
      gl.addColorStop(0, "rgba(255,255,255,.10)"); gl.addColorStop(.35, "rgba(255,255,255,.02)"); gl.addColorStop(.36, "rgba(255,255,255,0)");
      sg.fillStyle = gl; sg.fillRect(0, 0, SW, SH);
      scrTex.needsUpdate = true;
    }
    function setMode(m) {
      if (!m || m === screenState.mode || m === screenState.next) return;
      screenState.next = m;
      if (REDUCE) { screenState.mode = m; screenState.next = null; return; }
      gsap.to(screenState, { fade: 0, duration: .18, overwrite: true, onComplete: function () {
        screenState.mode = screenState.next || m; screenState.next = null;
        gsap.to(screenState, { fade: 1, duration: .45 });
      } });
    }
    screenHook = function (m) { if (m === "sent") { screenState.sent = true; } };

    panels.forEach(function (pn) {
      ScrollTrigger.create({ trigger: pn, start: "top 55%", end: "bottom 55%", onToggle: function (self) { if (self.isActive) setMode(pn.dataset.screen); } });
    });
    (function modeFromScroll() {
      var line = innerHeight * .55;
      panels.forEach(function (pn) { var r = pn.getBoundingClientRect(); if (r.top <= line && r.bottom > line) { screenState.mode = pn.dataset.screen; } });
    })();

    /* text panels ease in (never from opacity 0) */
    if (!REDUCE) {
      panels.slice(1).forEach(function (pn) {
        var inner = pn.querySelector(".panel__inner");
        gsap.fromTo(inner, { y: 26, opacity: .25 }, { y: 0, opacity: 1, ease: "none", scrollTrigger: { trigger: pn, start: "top 88%", end: "top 40%", scrub: true } });
      });
    }

    /* ================= theme ================= */
    function retheme() {
      M.housing.color.copy(tok("housing")); M.strap.color.copy(tok("strap")); M.keeper.color.copy(tok("accent"));
      M.figure.color.copy(tok("figure")); M.pants.color.copy(tok("figure-2")); M.vest.color.copy(tok("vest")); M.hat.color.copy(tok("hat"));
      M.corr.color.copy(tok("accent")); M.corrEdge.color.copy(tok("accent")); M.pop.color.copy(tok("muted"));
      [M.dotC, M.haloC].forEach(function (m) { m.color.copy(tok("accent")); });
      [M.dotA, M.haloA, M.ring].forEach(function (m) { m.color.copy(tok("amber")); });
      [M.dotG, M.haloG].forEach(function (m) { m.color.copy(tok("grey")); });
      [M.domeLine, M.domeFill, M.domeRing, M.nodeGlow].forEach(function (m) { m.color.copy(tok("accent")); });
      M.node.color.copy(tok("housing"));
      colorStreams(); drawMaps();
      var dark = getComputedStyle(root).colorScheme.indexOf("dark") > -1;
      hemi.intensity = dark ? 1.0 : 1.3; renderer.toneMappingExposure = dark ? 1.0 : 1.05;
    }
    themeListeners.push(retheme);
    retheme();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(drawMaps);

    /* ================= resize ================= */
    var W = 1, H = 1;
    function resize() {
      narrow = innerWidth <= 900;
      W = stage.clientWidth; H = stage.clientHeight;
      renderer.setSize(W, H, false);
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
    }
    resize();
    var rT; addEventListener("resize", function () { clearTimeout(rT); rT = setTimeout(function () { resize(); ScrollTrigger.refresh(); }, 120); });

    /* ================= loop ================= */
    var buzz = 0, lastBuzz = 0, frames = [], checkedPerf = false, startT = performance.now();
    function applyPose(dt, now) {
      var tgt = targetPose();
      var k = REDUCE ? 1 : 1 - Math.exp(-dt * 4.2);
      KEYS.forEach(function (kk) { cur[kk] += (tgt[kk] - cur[kk]) * k; });
      var t = now / 1000;
      T = t;
      // camera
      var dist = Math.exp(cur.d) * (narrow ? Math.max(1, .82 / camera.aspect) : 1);
      var cp = Math.cos(cur.pitch);
      camera.position.set(cur.tx + dist * cp * Math.sin(cur.yaw), cur.ty + dist * Math.sin(cur.pitch), cur.tz + dist * cp * Math.cos(cur.yaw));
      camera.lookAt(cur.tx, cur.ty, cur.tz);
      camera.near = Math.max(.05, dist * .02); camera.far = dist * 40;
      var oy = narrow ? -.07 * H : 0;
      if (Math.abs(cur.ox) > .002 || oy) camera.setViewOffset(W, H, -cur.ox * W, oy, W, H); else camera.clearViewOffset();
      camera.updateProjectionMatrix();
      // rig: pose rotation + idle sway + haptics
      var sway = REDUCE ? 0 : 1;
      rig.rotation.set(cur.rx + Math.sin(t * .6) * .03 * sway, cur.ry + Math.sin(t * .45) * .05 * sway, cur.rz);
      var mode = screenState.mode;
      if (mode === "lone" && !REDUCE && cur.e < .1) { if (t - lastBuzz > 2.6) { lastBuzz = t; buzz = 1; } }
      buzz *= Math.exp(-dt * 5);
      band.position.x = buzz > .01 ? Math.sin(t * 90) * .012 * buzz : 0;
      var beat = mode === "exert" && !REDUCE ? 1 + .012 * Math.exp(-((t * 2.4) % 1) * 10) : 1;
      band.scale.setScalar(beat);
      // assembly
      parts.forEach(function (pt) {
        var x = Math.max(0, Math.min(1, cur.e * 1.7 - pt.d)), ep = x * x * (3 - 2 * x);
        var fl = REDUCE ? 0 : Math.sin(t * 1.1 + pt.d * 9) * .04 * ep;
        pt.o.position.set(pt.p0.x + pt.off.x * ep, pt.p0.y + pt.off.y * ep + fl, pt.p0.z + pt.off.z * ep);
        pt.o.rotation.set(pt.r0.x + pt.rot.x * ep, pt.r0.y + pt.rot.y * ep, pt.r0.z + pt.rot.z * ep);
      });
      var ledOn = cur.e < .15 ? (.6 + .4 * Math.sin(t * 14)) : 0;
      M.led.color.setRGB(.15 * ledOn, 1 * ledOn, .5 * ledOn);
      // worker fade
      var wk = cur.wk;
      worker.visible = wk > .01;
      var wantT = wk < .995;
      workerMats.forEach(function (m) { if (m.transparent !== wantT) { m.transparent = wantT; m.needsUpdate = true; } m.opacity = wk; });
      M.shadow.opacity = wk * (1 - cur.crew * .5);
      // streams
      var sf = cur.sf, bl = cur.bl;
      points.visible = sf > .01;
      sMat.opacity = sf * .95;
      if (points.visible) {
        var n = 0, spd = REDUCE ? 0 : .09;
        for (var i = 0; i < STREAMS.length; i++) {
          var pts = curvePts[i], lane = BY + (i - 2.5) * .12;
          for (var j = 0; j < NPER; j++, n++) {
            var u = (sU[n] + t * spd * (1 + (j % 5) * .06)) % 1;
            var idx = Math.floor(u * 200), p = pts[idx];
            var jx = sJ[n * 2] * .06, jy = sJ[n * 2 + 1] * .06;
            // flow position (scaled by sf so it grows out of the band)
            var fu = Math.min(u, sf);
            var fp = pts[Math.floor(fu * 200)];
            var fx = fp.x + jx, fy = fp.y + jy, fz = fp.z + jx;
            // baseline position
            var bx = BX0 + u * (BX1 - BX0), by = lane + Math.sin(u * 18 + i) * .06 + jy * .6, bz = BZ + .02 + jx * .3;
            sPos[n * 3] = fx + (bx - fx) * bl; sPos[n * 3 + 1] = fy + (by - fy) * bl; sPos[n * 3 + 2] = fz + (bz - fz) * bl;
          }
        }
        sGeo.attributes.position.needsUpdate = true;
      }
      base.visible = bl > .01;
      M.corr.opacity = .16 * bl * sf; M.corrEdge.opacity = .9 * bl * sf; M.pop.opacity = .7 * bl * sf;
      // world
      var cr = cur.crew, si = cur.sites, dm = cur.dome;
      world.visible = cr > .01;
      M.map.opacity = cr;
      M.dotC.opacity = M.dotA.opacity = M.dotG.opacity = cr;
      M.haloC.opacity = M.haloA.opacity = M.haloG.opacity = .25 * cr;
      var pr = (t * .7) % 1;
      M.ring.opacity = cr * (1 - pr) * .9;
      rings.forEach(function (r) { r.scale.setScalar(1 + pr * 1.6); });
      M.sites.forEach(function (m) { m.opacity = si; });
      domeG.visible = dm > .01;
      M.domeLine.opacity = .35 * dm; M.domeFill.opacity = .05 * dm; M.domeRing.opacity = .5 * dm;
      M.node.opacity = dm; M.nodeGlow.opacity = dm; M.node.transparent = dm < .99;
      // screen only when it can be seen
      if (dist < 40) drawScreen(now);
    }
    function updateLabels() {
      var vec = new THREE.Vector3();
      labels.forEach(function (l) {
        var v = l.vis(); v = Math.max(0, Math.min(1, v));
        if (v < .02) { if (l.last !== 0) { l.el.style.opacity = 0; l.el.style.visibility = "hidden"; l.last = 0; } return; }
        vec.copy(l.pos()).project(camera);
        if (vec.z > 1 || vec.z < -1) { l.el.style.visibility = "hidden"; l.last = 0; return; }
        var x = (vec.x * .5 + .5) * W, y = (-vec.y * .5 + .5) * H;
        l.el.style.visibility = "visible";
        l.el.style.opacity = v.toFixed(3);
        l.el.style.transform = "translate3d(" + x.toFixed(1) + "px," + y.toFixed(1) + "px,0) translate(" + (l.anchor === "center" ? "-50%" : "8px") + ",-50%)";
        l.last = v;
      });
    }
    var lastNow = performance.now();
    function tick() {
      var now = performance.now();
      var dt = Math.min(.05, (now - lastNow) / 1000); lastNow = now;
      updateChrome();
      applyPose(dt, now);
      renderer.render(scene, camera);
      updateLabels();
      // auto-fallback for phones that can't keep up (skipped with ?static=0)
      if (!checkedPerf && narrow && !/static=0/.test(location.search)) {
        frames.push(dt);
        if (now - startT > 4000) {
          checkedPerf = true;
          var s = frames.slice(30).sort(function (a, b) { return a - b; }), med = s[Math.floor(s.length / 2)] || 0;
          if (med > .055) degrade();
        }
      }
    }
    function degrade() {
      gsap.ticker.remove(tick);
      if (lenis) lenis.destroy();
      ScrollTrigger.getAll().forEach(function (st) { st.kill(); });
      gsap.set(".panel__inner", { clearProps: "all" });
      renderer.dispose();
      goStatic();
    }
    gsap.ticker.add(tick);
    // first frame immediately so there is no fly-in
    applyPose(0, performance.now()); renderer.render(scene, camera); updateLabels();
    requestAnimationFrame(function () { stage.classList.add("is-ready"); });
    window.__sentra = { cur: cur, setMode: setMode };
  }
})();
