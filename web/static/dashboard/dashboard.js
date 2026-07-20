/* ============================================================
   LISA — Core Dashboard wiring
   - Boots orb, header status, trace SSE feed
   - Mic (record → /api/voice → transcript+reply → auto-play TTS)
   - OS Watcher timeline (polling every 2s)
   - Security level + password rotation
   - Memory bank + Token usage
   ============================================================ */

(() => {
  "use strict";

  // ── Tiny helpers ────────────────────────────────────────────
  const $  = (id) => document.getElementById(id);
  const el = (tag, cls, txt) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt !== undefined) n.textContent = txt;
    return n;
  };
  const fmtTime = (ts) => {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour12: false });
  };
  const fmtDur = (sec) => {
    if (sec == null) return "—";
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60), s = sec % 60;
    return `${m}m ${s}s`;
  };
  const escapeHtml = (s) =>
    (s ?? "").toString()
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");

  async function apiJSON(url, opts = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); msg = j.detail || j.message || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  }

  // ── Header status ───────────────────────────────────────────
  async function refreshStatus() {
    try {
      const s = await apiJSON("/api/dashboard/status");

      // Mode
      const mode = s.agent.mode || "—";
      $("modeValue").textContent = mode.toUpperCase();
      $("modeValue").className   = "chip-value " + mode;

      // Mood
      const mood = s.agent.mood || "neutral";
      $("moodValue").textContent = mood.toUpperCase();
      $("moodValue").className   = "chip-value " + mood;

      // Security
      const sec = s.security;
      $("secLevelValue").textContent = `L${sec.level} · ${sec.level_name.toUpperCase()}`;
      $("secLevelValue").className   = "chip-value l" + sec.level;
      $("secInfo").textContent =
        `Current: Level ${sec.level} — ${sec.level_name} (${sec.level_desc}) · rotations: ${sec.pw_rotations}`;
      document.querySelectorAll(".sec-btn").forEach(b => {
        b.classList.toggle("active", parseInt(b.dataset.level, 10) === sec.level);
      });

      // OS Watcher
      const w = s.os_watcher;
      $("watchValue").textContent = w.running ? "ON" : "OFF";
      $("watchValue").className   = "chip-value " + (w.running ? "on" : "off");

      // Turns / tokens
      $("turnValue").textContent  = s.agent.turn_count ?? 0;
      $("tokenValue").textContent = (s.tokens.total ?? 0).toLocaleString();

      // Orb state — driven by mood + voice activity
      if (!window.__micActive) {
        if (mode === "professional")     window.LisaOrb.setState("thinking");
        else if (mood === "flirty")      window.LisaOrb.setState("listening");
        else if (mood === "angry" || mood === "sad") window.LisaOrb.setState("alert");
        else                             window.LisaOrb.setState("idle");
      }
    } catch (e) {
      console.warn("[status]", e.message);
    }
  }

  // ── Trace feed (SSE with polling fallback) ──────────────────
  const traceList  = $("traceList");
  let   tracePaused = false;
  let   traceSince  = 0;
  const TRACE_MAX_DOM = 300;

  function renderTraceEvent(ev) {
    if (tracePaused) return;
    if (ev.seq <= traceSince) return;
    traceSince = ev.seq;

    let mod = ev.module || (ev.type === "turn_start" ? "Turn"
                           : ev.type === "turn_end"   ? "Turn"
                           : ev.type === "error"      ? "error"
                           : ev.type === "warn"       ? "warn"
                           : "info");
    let msg;
    if      (ev.type === "turn_start") msg = `▶ Turn #${ev.turn_no} · "${ev.message}"`;
    else if (ev.type === "turn_end")   msg = `✓ Turn #${ev.turn_no} done · ${ev.reply_chars} chars`;
    else                                msg = ev.message || "";

    const line = el("div", "trace-line tl-" + mod.replace(/\s/g, ""));
    line.appendChild(el("span", "ts",  fmtTime(ev.ts)));
    line.appendChild(el("span", "mod", "[" + mod + "]"));
    line.appendChild(el("span", "msg", msg));
    const extras = [];
    if (ev.duration_ms != null) extras.push(ev.duration_ms + "ms");
    if (ev.tokens != null)      extras.push(ev.tokens + " tok");
    if (ev.tokens_in != null || ev.tokens_out != null)
      extras.push(`${ev.tokens_in || 0} in / ${ev.tokens_out || 0} out`);
    line.appendChild(el("span", "meta", extras.join(" · ")));

    traceList.appendChild(line);
    while (traceList.children.length > TRACE_MAX_DOM) {
      traceList.removeChild(traceList.firstChild);
    }
    traceList.scrollTop = traceList.scrollHeight;

    // Nudge the orb on every event (subtle life sign)
    window.LisaOrb.pulse(0.6);
  }

  let sseRef = null;
  function connectTraceStream() {
    try {
      if (sseRef) sseRef.close();
      sseRef = new EventSource(`/api/dashboard/trace/stream?since=${traceSince}`);
      $("traceStreamTag").textContent = "SSE •";
      $("traceStreamTag").classList.remove("off");

      sseRef.onmessage = (e) => {
        if (!e.data) return;
        try { renderTraceEvent(JSON.parse(e.data)); } catch (_) {}
      };
      sseRef.onerror = () => {
        $("traceStreamTag").textContent = "POLL •";
        $("traceStreamTag").classList.add("off");
        try { sseRef.close(); } catch (_) {}
        sseRef = null;
        // fall back to polling
        pollTraceLoop();
      };
    } catch (e) {
      pollTraceLoop();
    }
  }

  async function pollTraceLoop() {
    try {
      const j = await apiJSON(`/api/dashboard/trace?since=${traceSince}&limit=100`);
      (j.events || []).forEach(renderTraceEvent);
    } catch (_) {}
    setTimeout(pollTraceLoop, 1500);
  }

  $("traceClearBtn").onclick = () => { traceList.innerHTML = ""; };
  $("tracePauseBtn").onclick = () => {
    tracePaused = !tracePaused;
    $("tracePauseBtn").textContent = tracePaused ? "RESUME" : "PAUSE";
  };

  // ── OS Watcher ──────────────────────────────────────────────
  async function refreshWatcher() {
    try {
      const j = await apiJSON("/api/os_watcher?limit=20");
      const st = j.status;
      $("watchNow").textContent   = st.current_window || "—";
      $("watchDwell").textContent = fmtDur(st.current_dwell_sec);
      $("watchCount").textContent = st.total_windows_seen ?? 0;

      const tl = $("watchTimeline");
      tl.innerHTML = "";
      (j.timeline || []).slice().reverse().forEach(item => {
        const row = el("div", "tl-item" + (item.active ? " active" : ""));
        row.appendChild(el("span", "t", fmtTime(item.start)));
        row.appendChild(el("span", "w", item.title || "—"));
        row.appendChild(el("span", "d", fmtDur(item.duration_sec)));
        tl.appendChild(row);
      });
      if (!j.timeline || j.timeline.length === 0) {
        tl.appendChild(el("div", "mem-empty",
          st.running ? "Waiting for window switches…"
                     : "Monitor is off. Click START above."));
      }
    } catch (e) {
      console.warn("[watcher]", e.message);
    }
  }

  $("watchStartBtn").onclick = async () => {
    try {
      await apiJSON("/api/os_watcher/start", { method: "POST" });
      setTicker("OS Watcher engaged. Silent monitoring active.");
      refreshWatcher(); refreshStatus();
    } catch (e) { setTicker("Watcher start failed: " + e.message, "err"); }
  };
  $("watchStopBtn").onclick = async () => {
    try {
      const j = await apiJSON("/api/os_watcher/stop", { method: "POST" });
      setTicker("OS Watcher stopped. Report generated.");
      refreshWatcher(); refreshStatus();
      pushTranscript("sys", "OS Watcher report:\n" + (j.report || "—"));
    } catch (e) { setTicker("Watcher stop failed: " + e.message, "err"); }
  };

  // ── Security ────────────────────────────────────────────────
  document.querySelectorAll(".sec-btn").forEach(btn => {
    btn.onclick = async () => {
      const level = parseInt(btn.dataset.level, 10);
      let password = null;
      if (level === 0) {
        password = prompt("Level 0 (God Mode) requires the admin password:");
        if (password == null) return;
      }
      try {
        const j = await apiJSON("/api/security/level", {
          method: "POST",
          body:   JSON.stringify({ level, password }),
        });
        setTicker(j.message || "Level updated.");
        refreshStatus();
      } catch (e) {
        setTicker("Security change denied: " + e.message, "err");
      }
    };
  });

  $("pwChangeBtn").onclick = async () => {
    const oldPw = $("pwOld").value;
    const newPw = $("pwNew").value;
    const msg   = $("pwMsg");
    msg.className = "pw-msg";
    msg.textContent = "";
    if (!oldPw || !newPw) {
      msg.textContent = "Both fields required.";
      msg.classList.add("err");
      return;
    }
    try {
      const j = await apiJSON("/api/security/password", {
        method: "POST",
        body:   JSON.stringify({ old_password: oldPw, new_password: newPw }),
      });
      msg.textContent = j.message;
      msg.classList.add("ok");
      $("pwOld").value = "";
      $("pwNew").value = "";
      refreshStatus();
    } catch (e) {
      msg.textContent = e.message;
      msg.classList.add("err");
    }
  };

  // ── Memory bank ─────────────────────────────────────────────
  async function refreshMemories() {
    try {
      const j = await apiJSON("/api/memories");
      const box = $("memList");
      box.innerHTML = "";
      if (!j.memories || j.memories.length === 0) {
        box.appendChild(el("div", "mem-empty", "No long-term memories yet."));
        return;
      }
      j.memories.forEach(m => {
        const row = el("div", "mem-item");
        row.appendChild(el("span", "k", m.key));
        row.appendChild(el("span", "v", m.value));
        row.appendChild(el("span", "c", m.category || ""));
        box.appendChild(row);
      });
    } catch (e) { console.warn("[mem]", e.message); }
  }
  $("memRefreshBtn").onclick = refreshMemories;

  // ── Tokens ──────────────────────────────────────────────────
  async function refreshTokens() {
    try {
      const j    = await apiJSON("/api/token_usage");
      const grid = $("tokenGrid");
      grid.innerHTML = "";
      const cells = [
        ["REQS",   j.chat.requests],
        ["IN",     j.chat.in],
        ["OUT",    j.chat.out],
        ["TOTAL",  j.chat.total],
      ];
      cells.forEach(([k, v]) => {
        const c = el("div", "cell");
        c.appendChild(el("div", "k", k));
        c.appendChild(el("div", "v", (v ?? 0).toLocaleString()));
        grid.appendChild(c);
      });
      // Voice chars
      const vc = j.voice.session_chars || {};
      const parts = Object.entries(vc).map(([k, v]) => `${k}: ${v}`);
      $("voiceChars").textContent = "VOICE (this session) — " + (parts.join(" · ") || "0");
    } catch (e) { console.warn("[tokens]", e.message); }
  }
  $("resetVoiceBtn").onclick = async () => {
    try { await apiJSON("/api/token_usage/reset", { method: "POST" }); refreshTokens(); }
    catch (e) { setTicker(e.message, "err"); }
  };

  // ── Mode / reset ────────────────────────────────────────────
  $("modeToggleBtn").onclick = async () => {
    try {
      const s = await apiJSON("/api/state");
      const next = s.mode === "personal" ? "professional" : "personal";
      await apiJSON("/api/mode", { method: "POST", body: JSON.stringify({ mode: next }) });
      setTicker(`Mode → ${next.toUpperCase()}`);
      refreshStatus();
    } catch (e) { setTicker(e.message, "err"); }
  };
  $("resetChatBtn").onclick = async () => {
    if (!confirm("Reset conversation history? This clears in-memory turns.")) return;
    try { await apiJSON("/api/reset", { method: "POST" }); setTicker("Chat history cleared.");
          refreshStatus(); }
    catch (e) { setTicker(e.message, "err"); }
  };

  // ── Transcript / TTS ────────────────────────────────────────
  const transcriptBox = $("transcriptBox");
  const ttsAudio      = $("ttsAudio");

  function pushTranscript(kind, text) {
    // kinds: "user" | "lisa" | "sys"
    const hint = transcriptBox.querySelector(".tx-hint");
    if (hint) hint.remove();
    const div = el("div", "tx-line tx-" + kind);
    div.textContent = text;
    transcriptBox.appendChild(div);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
    while (transcriptBox.children.length > 40) {
      transcriptBox.removeChild(transcriptBox.firstChild);
    }
  }

  async function playTTS(text) {
    if (!text || !text.trim()) return;
    try {
      const res = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ text }),
      });
      if (!res.ok) throw new Error("TTS failed (" + res.status + ")");
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      ttsAudio.src = url;
      ttsAudio.onplay  = () => window.LisaOrb.setState("speaking");
      ttsAudio.onended = () => {
        window.__micActive = false;
        refreshStatus();
        URL.revokeObjectURL(url);
      };
      await ttsAudio.play();
    } catch (e) {
      pushTranscript("sys", "TTS error: " + e.message);
      window.__micActive = false;
    }
  }

  // ── Quick-type send (matches chat page behaviour) ───────────
  async function sendTypedMessage(text) {
    if (!text.trim()) return;
    const autoSpeak = $("autoSpeak").checked;
    pushTranscript("user", text);
    window.LisaOrb.setState("thinking");
    window.__micActive = true;

    try {
      const j = await apiJSON("/api/chat", {
        method: "POST",
        body:   JSON.stringify({ message: text, auto_speak: autoSpeak }),
      });
      pushTranscript("lisa", j.reply || "…");
      refreshStatus();
      if (autoSpeak && j.tts_text) {
        await playTTS(j.tts_text);
      } else {
        window.__micActive = false;
      }
    } catch (e) {
      pushTranscript("sys", "chat error: " + e.message);
      window.__micActive = false;
    }
  }

  $("quickSend").onclick = () => {
    const v = $("quickInput").value;
    $("quickInput").value = "";
    sendTypedMessage(v);
  };
  $("quickInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("quickSend").click();
  });

  // ── Mic (record → /api/voice → chat reply + TTS) ────────────
  const micBtn   = $("micBtn");
  const micLabel = $("micLabel");
  let mediaRecorder = null;
  let recChunks     = [];
  let audioCtx      = null;
  let analyser      = null;
  let levelRAF      = null;

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Audio-level meter → feeds orb.setLevel
      try {
        audioCtx  = new (window.AudioContext || window.webkitAudioContext)();
        const src = audioCtx.createMediaStreamSource(stream);
        analyser  = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        src.connect(analyser);
        const buf = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          if (!analyser) return;
          analyser.getByteTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = (buf[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / buf.length);
          window.LisaOrb.setLevel(Math.min(1, rms * 3));
          levelRAF = requestAnimationFrame(tick);
        };
        tick();
      } catch (_) {}

      mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      recChunks = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data.size) recChunks.push(e.data); };
      mediaRecorder.onstop = async () => {
        cancelAnimationFrame(levelRAF); levelRAF = null;
        try { analyser = null; audioCtx && audioCtx.close(); audioCtx = null; } catch (_) {}
        stream.getTracks().forEach(t => t.stop());
        await handleRecordedBlob(new Blob(recChunks, { type: "audio/webm" }));
      };
      mediaRecorder.start();

      micBtn.classList.add("recording");
      micLabel.textContent = "RECORDING · TAP TO STOP";
      window.LisaOrb.setState("listening");
      window.__micActive = true;
    } catch (e) {
      pushTranscript("sys", "Mic error: " + e.message);
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    micBtn.classList.remove("recording");
    micBtn.classList.add("processing");
    micLabel.textContent = "TRANSCRIBING…";
    window.LisaOrb.setState("thinking");
  }

  async function handleRecordedBlob(blob) {
    try {
      const fd = new FormData();
      fd.append("audio", blob, "clip.webm");
      const res = await fetch("/api/voice", { method: "POST", body: fd });
      if (!res.ok) throw new Error("STT failed (" + res.status + ")");
      const j = await res.json();

      if (j.skipped || !j.transcript) {
        pushTranscript("sys", "…nothing heard.");
      } else {
        pushTranscript("user", j.transcript);
      }
      if (j.reply) {
        pushTranscript("lisa", j.reply);
        // AUTO-PLAY TTS — same as chat page voice flow
        await playTTS(j.tts_text || j.reply);
      } else {
        window.__micActive = false;
      }
      refreshStatus();
    } catch (e) {
      pushTranscript("sys", "voice error: " + e.message);
      window.__micActive = false;
    } finally {
      micBtn.classList.remove("processing");
      micLabel.textContent = "TAP TO SPEAK";
    }
  }

  micBtn.onclick = () => {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      stopRecording();
    } else {
      startRecording();
    }
  };

  // ── Ticker + clock ──────────────────────────────────────────
  function setTicker(msg, tone) {
    const t = $("ticker");
    t.textContent = msg;
    t.style.color = tone === "err" ? "var(--red)" : "";
  }
  function tickClock() {
    const d = new Date();
    $("clock").textContent = d.toLocaleTimeString([], { hour12: false });
  }
  setInterval(tickClock, 1000); tickClock();

  // ── Boot ────────────────────────────────────────────────────
  refreshStatus();
  refreshWatcher();
  refreshMemories();
  refreshTokens();
  connectTraceStream();

  setInterval(refreshStatus,   3000);
  setInterval(refreshWatcher,  2000);
  setInterval(refreshTokens,   5000);
  setInterval(refreshMemories, 10000);

  setTicker("SYSTEM ONLINE · L.I.S.A. core awake · awaiting operator…");
})();
