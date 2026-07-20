/* ============================================================
   LISA — JARVIS Orb (Three.js)
   Reactive 3D sphere with vertex-displaced wireframe + inner core.
   Exposes:
     window.LisaOrb.setState('idle'|'listening'|'thinking'|'speaking'|'alert')
     window.LisaOrb.pulse(intensity=1)   // one-shot bump (e.g. new trace event)
     window.LisaOrb.setLevel(v)          // 0..1 audio level (mic amplitude)
   ============================================================ */

(function () {
  const canvas = document.getElementById('orbCanvas');
  if (!canvas || typeof THREE === 'undefined') {
    console.warn('[Orb] Three.js or canvas missing — falling back to CSS orb.');
    window.LisaOrb = {
      setState: () => {}, pulse: () => {}, setLevel: () => {},
    };
    return;
  }

  // ── Scene / renderer ─────────────────────────────────────────
  const scene    = new THREE.Scene();
  const camera   = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0, 4.2);

  const renderer = new THREE.WebGLRenderer({
    canvas, alpha: true, antialias: true, powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  function resize() {
    const w = canvas.clientWidth  || canvas.parentElement.clientWidth;
    const h = canvas.clientHeight || canvas.parentElement.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas.parentElement);
  resize();

  // ── Lights ────────────────────────────────────────────────────
  scene.add(new THREE.AmbientLight(0x223366, 0.6));
  const key = new THREE.PointLight(0x00e5ff, 2.4, 20);
  key.position.set(3, 2, 4);
  scene.add(key);
  const rim = new THREE.PointLight(0xff2fb0, 1.4, 20);
  rim.position.set(-3, -2, 3);
  scene.add(rim);

  // ── Inner glowing core ────────────────────────────────────────
  const coreGeo = new THREE.IcosahedronGeometry(0.85, 4);
  const corePositions = coreGeo.attributes.position.clone();
  const coreMat = new THREE.MeshStandardMaterial({
    color: 0x00e5ff,
    emissive: 0x00a8cc,
    emissiveIntensity: 0.9,
    roughness: 0.35,
    metalness: 0.6,
    transparent: true,
    opacity: 0.85,
  });
  const core = new THREE.Mesh(coreGeo, coreMat);
  scene.add(core);

  // ── Outer wireframe shell ─────────────────────────────────────
  const shellGeo = new THREE.IcosahedronGeometry(1.35, 3);
  const shellMat = new THREE.MeshBasicMaterial({
    color: 0x00e5ff,
    wireframe: true,
    transparent: true,
    opacity: 0.55,
  });
  const shell = new THREE.Mesh(shellGeo, shellMat);
  scene.add(shell);

  // ── Particle halo (points around orb) ─────────────────────────
  const haloCount = 220;
  const haloPos = new Float32Array(haloCount * 3);
  const haloBaseR = new Float32Array(haloCount);
  for (let i = 0; i < haloCount; i++) {
    const r    = 1.75 + Math.random() * 0.9;
    const th   = Math.random() * Math.PI * 2;
    const ph   = Math.acos(2 * Math.random() - 1);
    haloBaseR[i]     = r;
    haloPos[3*i]     = r * Math.sin(ph) * Math.cos(th);
    haloPos[3*i + 1] = r * Math.sin(ph) * Math.sin(th);
    haloPos[3*i + 2] = r * Math.cos(ph);
  }
  const haloGeo = new THREE.BufferGeometry();
  haloGeo.setAttribute('position', new THREE.BufferAttribute(haloPos, 3));
  const haloMat = new THREE.PointsMaterial({
    color: 0x7cf7ff,
    size: 0.035,
    transparent: true,
    opacity: 0.8,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const halo = new THREE.Points(haloGeo, haloMat);
  scene.add(halo);

  // ── State palette ─────────────────────────────────────────────
  const STATE_STYLES = {
    idle:      { core: 0x00e5ff, shell: 0x00e5ff, halo: 0x7cf7ff, speed: 0.4, amp: 0.06, emit: 0.7 },
    listening: { core: 0xff2fb0, shell: 0xff2fb0, halo: 0xffb0e2, speed: 1.2, amp: 0.18, emit: 1.5 },
    thinking:  { core: 0xffb84d, shell: 0xffb84d, halo: 0xffe0a8, speed: 0.9, amp: 0.10, emit: 1.1 },
    speaking:  { core: 0x00ff9d, shell: 0x00ff9d, halo: 0xbfffde, speed: 1.6, amp: 0.22, emit: 1.6 },
    alert:     { core: 0xff3b6b, shell: 0xff3b6b, halo: 0xffa1b8, speed: 2.0, amp: 0.14, emit: 1.8 },
  };

  let state = 'idle';
  let target = { ...STATE_STYLES.idle };
  let current = { ...STATE_STYLES.idle };
  let pulseBoost = 0;   // decays each frame
  let micLevel   = 0;   // 0..1, decays each frame

  function lerp(a, b, t) { return a + (b - a) * t; }
  function lerpColor(cur, tgt, t) {
    const c1 = new THREE.Color(cur), c2 = new THREE.Color(tgt);
    c1.lerp(c2, t);
    return c1.getHex();
  }

  // ── Public API ────────────────────────────────────────────────
  window.LisaOrb = {
    setState(name) {
      if (!STATE_STYLES[name]) return;
      state  = name;
      target = { ...STATE_STYLES[name] };
      const lbl = document.getElementById('orbLabel');
      if (lbl) lbl.textContent = name.toUpperCase();
    },
    pulse(intensity = 1) {
      pulseBoost = Math.min(1.2, pulseBoost + 0.35 * intensity);
    },
    setLevel(v) {
      micLevel = Math.max(0, Math.min(1, v));
    },
  };

  // ── Animation loop ────────────────────────────────────────────
  const clock = new THREE.Clock();

  function animate() {
    requestAnimationFrame(animate);
    const t  = clock.getElapsedTime();
    const dt = clock.getDelta();

    // Smoothly interpolate state colors / params
    current.speed = lerp(current.speed, target.speed, 0.05);
    current.amp   = lerp(current.amp,   target.amp,   0.05);
    current.emit  = lerp(current.emit,  target.emit,  0.05);
    current.core  = lerpColor(current.core,  target.core,  0.06);
    current.shell = lerpColor(current.shell, target.shell, 0.06);
    current.halo  = lerpColor(current.halo,  target.halo,  0.06);

    coreMat.color.setHex(current.core);
    coreMat.emissive.setHex(current.core);
    coreMat.emissiveIntensity = current.emit + pulseBoost * 0.8;
    shellMat.color.setHex(current.shell);
    haloMat.color.setHex(current.halo);

    // Rotation
    const rotSpeed = current.speed * 0.35;
    core.rotation.y  += dt * rotSpeed;
    core.rotation.x  += dt * rotSpeed * 0.6;
    shell.rotation.y -= dt * rotSpeed * 0.7;
    shell.rotation.z += dt * rotSpeed * 0.3;
    halo.rotation.y  += dt * 0.08;
    halo.rotation.x  += dt * 0.05;

    // Vertex displacement — organic breathing / audio-reactive
    const amp   = current.amp + pulseBoost * 0.15 + micLevel * 0.35;
    const freq  = 1.4 + current.speed * 0.6;
    const posAttr = core.geometry.attributes.position;
    for (let i = 0; i < posAttr.count; i++) {
      const bx = corePositions.getX(i);
      const by = corePositions.getY(i);
      const bz = corePositions.getZ(i);
      const n  = Math.sin(bx * freq + t * 1.6)
               + Math.sin(by * freq + t * 1.2)
               + Math.sin(bz * freq + t * 0.9);
      const disp = 1 + amp * n * 0.18;
      posAttr.setXYZ(i, bx * disp, by * disp, bz * disp);
    }
    posAttr.needsUpdate = true;
    core.geometry.computeVertexNormals();

    // Halo breathing
    const haloScale = 1 + Math.sin(t * 0.9) * 0.02 + pulseBoost * 0.05 + micLevel * 0.12;
    halo.scale.setScalar(haloScale);

    // Decay pulse + mic level
    pulseBoost = Math.max(0, pulseBoost - dt * 1.4);
    micLevel   = Math.max(0, micLevel   - dt * 1.2);

    renderer.render(scene, camera);
  }
  animate();
})();
