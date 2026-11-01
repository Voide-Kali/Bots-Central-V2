/* Aval landing — topbar, scroll reveal, and a neon particle-network hero (Three.js UMD).
   No external calls. Degrades gracefully: no WebGL or reduced motion -> the CSS background stays. */
(function () {
  "use strict";

  // --- topbar shadow on scroll ---
  var topbar = document.getElementById("topbar");
  function onScroll() {
    if (topbar) topbar.classList.toggle("scrolled", window.scrollY > 8);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // --- scroll reveal ---
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var reveals = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
  if (reduceMotion || !("IntersectionObserver" in window)) {
    reveals.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12 });
    reveals.forEach(function (el) { io.observe(el); });
  }

  // --- 3D hero ---
  var canvas = document.getElementById("scene");
  if (!canvas || typeof window.THREE === "undefined") { if (canvas) canvas.style.display = "none"; return; }
  var THREE = window.THREE;

  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch (err) {
    canvas.style.display = "none";
    return;
  }
  renderer.setClearColor(0x000000, 0);

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
  camera.position.z = 15;

  var group = new THREE.Group();
  scene.add(group);

  // Points distributed in a rough sphere shell.
  var COUNT = 320;
  var RADIUS = 9;
  var positions = new Float32Array(COUNT * 3);
  var colors = new Float32Array(COUNT * 3);
  var cyan = new THREE.Color(0x22d3ee);
  var violet = new THREE.Color(0x7b61ff);
  var pts = [];
  for (var i = 0; i < COUNT; i++) {
    var u = Math.random(), v = Math.random();
    var theta = 2 * Math.PI * u, phi = Math.acos(2 * v - 1);
    var r = RADIUS * (0.7 + 0.3 * Math.random());
    var x = r * Math.sin(phi) * Math.cos(theta);
    var y = r * Math.sin(phi) * Math.sin(theta);
    var z = r * Math.cos(phi);
    positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z;
    pts.push([x, y, z]);
    var c = cyan.clone().lerp(violet, (y / RADIUS + 1) / 2);
    colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
  }

  // soft round sprite for the points
  var tex = (function () {
    var c = document.createElement("canvas"); c.width = c.height = 64;
    var g = c.getContext("2d");
    var grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, "rgba(255,255,255,1)");
    grd.addColorStop(0.3, "rgba(255,255,255,0.8)");
    grd.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
    var t = new THREE.CanvasTexture(c); return t;
  })();

  var pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  pGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  var pMat = new THREE.PointsMaterial({
    size: 0.72, map: tex, vertexColors: true, transparent: true, opacity: 0.95,
    depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
  });
  group.add(new THREE.Points(pGeo, pMat));

  // Lines between nearby points (computed once; capped).
  var linePos = [];
  var LINK_DIST = 3.6, MAX_LINKS = 1200;
  for (var a = 0; a < COUNT && linePos.length / 6 < MAX_LINKS; a++) {
    for (var b = a + 1; b < COUNT; b++) {
      var dx = pts[a][0] - pts[b][0], dy = pts[a][1] - pts[b][1], dz = pts[a][2] - pts[b][2];
      if (dx * dx + dy * dy + dz * dz < LINK_DIST * LINK_DIST) {
        linePos.push(pts[a][0], pts[a][1], pts[a][2], pts[b][0], pts[b][1], pts[b][2]);
        if (linePos.length / 6 >= MAX_LINKS) break;
      }
    }
  }
  var lGeo = new THREE.BufferGeometry();
  lGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(linePos), 3));
  var lMat = new THREE.LineBasicMaterial({ color: 0x5aa2ff, transparent: true, opacity: 0.24 });
  group.add(new THREE.LineSegments(lGeo, lMat));

  function resize() {
    var w = canvas.clientWidth || window.innerWidth;
    var h = canvas.clientHeight || window.innerHeight;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    // On a wide (desktop) viewport the text sits on the left, so push the sphere to the right;
    // on a narrow (mobile) viewport keep it centered above the text.
    group.position.x = camera.aspect > 1.1 ? RADIUS * 0.5 : 0;
  }
  window.addEventListener("resize", resize);
  resize();

  // pointer parallax
  var targetX = 0, targetY = 0;
  window.addEventListener("pointermove", function (e) {
    targetX = (e.clientX / window.innerWidth - 0.5) * 0.6;
    targetY = (e.clientY / window.innerHeight - 0.5) * 0.6;
  }, { passive: true });

  group.rotation.set(0.3, 0.2, 0);

  if (reduceMotion) { renderer.render(scene, camera); return; } // static frame, no loop

  var running = true;
  document.addEventListener("visibilitychange", function () { running = !document.hidden; if (running) loop(); });

  function loop() {
    if (!running) return;
    group.rotation.y += 0.0016;
    group.rotation.x += 0.0006;
    camera.position.x += (targetX * 3 - camera.position.x) * 0.04;
    camera.position.y += (-targetY * 3 - camera.position.y) * 0.04;
    camera.lookAt(0, 0, 0);
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }
  loop();
})();
