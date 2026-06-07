/* ═════════════════════════════════════════════════════════════════════
   LISA Web UI — frontend logic  (v2 — May 2026)

   Fixes shipped:
     • Problem #2 — When auto-speak is ON, send `auto_speak:true` flag so
       the server routes the message through the VOICE agent (Devanagari +
       English), making Sarvam Bulbul read it naturally instead of robot.
     • Problem #3 — Typing indicator hides defensively after every reply
       (success / error / network fail). showTyping() also checks busy
       state so it can never get "stuck on" between renders.
     • Problem #5 — Recording bar uses `.hidden = false` only inside
       startRecording(), and is ALWAYS forced off in stopRecording() and
       on every page-load (defensive boot).
     • Problem #7 — Click on Lisa's or Manish's avatar to upload a custom
       photo. Persists on server via /api/avatar, mirrors in localStorage
       for instant reload, applied to sidebar AND every chat bubble.
     • Send button now glows when there's text in the input.
   ════════════════════════════════════════════════════════════════════ */

const API = "";   // same origin

// ── DOM refs ────────────────────────────────────────────────────────
const $messages    = document.getElementById("messages");
const $input       = document.getElementById("input");
const $btnSend     = document.getElementById("btnSend");
const $btnMic      = document.getElementById("btnMic");
const $btnReset    = document.getElementById("btnReset");
const $btnMemories = document.getElementById("btnMemories");
const $btnHelp     = document.getElementById("btnHelp");
const $btnTrace    = document.getElementById("btnTrace");
const $btnCloseTrace = document.getElementById("btnCloseTrace");
const $btnAutoSpeak  = document.getElementById("btnAutoSpeak");
const $autoSpeakIcon = document.getElementById("autoSpeakIcon");
const $typing      = document.getElementById("typing");
const $moodCard    = document.getElementById("moodCard");
const $moodEmoji   = document.getElementById("moodEmoji");
const $moodText    = document.getElementById("moodText");
const $statTurns   = document.getElementById("statTurns");
const $statHistory = document.getElementById("statHistory");
const $statMemories= document.getElementById("statMemories");
const $statusDot   = document.getElementById("statusDot");
const $subtitle    = document.getElementById("subtitle");
const $recIndicator= document.getElementById("recIndicator");
const $recTimer    = document.getElementById("recTimer");
const $btnStopRec  = document.getElementById("btnStopRec");
const $waBanner    = document.getElementById("waBanner");
const $tracePane   = document.getElementById("tracePane");
const $traceContent= document.getElementById("traceContent");
const $traceTitle  = document.getElementById("traceTitle");
const $toasts      = document.getElementById("toasts");
const $app         = document.querySelector(".app");

// Avatar refs (Problem #7)
const $lisaAvatarSide   = document.getElementById("lisaAvatarSide");
const $manishAvatarSide = document.getElementById("manishAvatarSide");
const $lisaAvatarImg    = document.getElementById("lisaAvatarImg");
const $lisaAvatarEmoji  = document.getElementById("lisaAvatarEmoji");
const $manishAvatarImg  = document.getElementById("manishAvatarImg");
const $manishAvatarEmoji= document.getElementById("manishAvatarEmoji");
const $avatarFileLisa   = document.getElementById("avatarFileLisa");
const $avatarFileManish = document.getElementById("avatarFileManish");


// ── State ────────────────────────────────────────────────────────────
const state = {
  mode: "personal",
  mood: "neutral",
  turn_count: 0,
  history_size: 0,
  autoSpeak: true,
  recording: false,
  mediaRecorder: null,
  chunks: [],
  recStart: 0,
  recTimer: null,
  lastTrace: [],
  traceTab: "trace",
  busy: false,
  avatars: { lisa: null, manish: null },   // custom photo URLs
};

const MOOD_EMOJI = {
  neutral: "🌸",
  happy:   "😊",
  sad:     "🥺",
  anxious: "😰",
  angry:   "😤",
  flirty:  "🥰",
};

const MOOD_SUBTITLES = {
  neutral: "Bolo na, kya haal hai?",
  happy:   "Aaj khushi ka mood lag rha hai! ✨",
  sad:     "Main yahaan hoon, batao kya hua…",
  anxious: "Saans lo, sab theek ho jayega.",
  angry:   "Chill kar, baat karo mujhse.",
  flirty:  "Awww, baby 💕",
};


// ════════════════════════════════════════════════════════════════════
//  TOAST helpers
// ════════════════════════════════════════════════════════════════════
function toast(text, kind = "info", ttl = 3000) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = text;
  $toasts.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateX(40px)";
    el.style.transition = "all 0.3s";
    setTimeout(() => el.remove(), 300);
  }, ttl);
}


// ════════════════════════════════════════════════════════════════════
//  AVATAR helpers (Problem #7)
// ════════════════════════════════════════════════════════════════════
function applyAvatars() {
  // Sidebar — Lisa
  if (state.avatars.lisa) {
    $lisaAvatarImg.src = state.avatars.lisa;
    $lisaAvatarImg.hidden = false;
    $lisaAvatarEmoji.style.display = "none";
  } else {
    $lisaAvatarImg.hidden = true;
    $lisaAvatarEmoji.style.display = "";
  }
  // Sidebar — Manish
  if (state.avatars.manish) {
    $manishAvatarImg.src = state.avatars.manish;
    $manishAvatarImg.hidden = false;
    $manishAvatarEmoji.style.display = "none";
  } else {
    $manishAvatarImg.hidden = true;
    $manishAvatarEmoji.style.display = "";
  }

  // All existing chat bubbles
  document.querySelectorAll(".msg-lisa .msg-avatar").forEach(el => {
    renderBubbleAvatar(el, "lisa");
  });
  document.querySelectorAll(".msg-manish .msg-avatar").forEach(el => {
    renderBubbleAvatar(el, "manish");
  });
}

function renderBubbleAvatar(el, who) {
  const url = state.avatars[who];
  if (url) {
    el.innerHTML = `<img src="${url}" alt="${who}" />`;
  } else {
    const emoji = who === "lisa" ? "💜" : "🧑";
    el.innerHTML = `<span class="msg-avatar-emoji">${emoji}</span>`;
  }
}

async function fetchAvatars() {
  try {
    const r = await fetch(API + "/api/avatar");
    if (!r.ok) return;
    const j = await r.json();
    state.avatars.lisa   = j.lisa   || null;
    state.avatars.manish = j.manish || null;
    // Mirror locally so reloads feel instant
    localStorage.setItem("lisa_avatars", JSON.stringify(state.avatars));
    applyAvatars();
  } catch (e) {
    // Fallback to localStorage if server unreachable
    try {
      const cached = JSON.parse(localStorage.getItem("lisa_avatars") || "{}");
      state.avatars.lisa   = cached.lisa   || null;
      state.avatars.manish = cached.manish || null;
      applyAvatars();
    } catch {}
  }
}

async function uploadAvatar(who, file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    toast("Sirf image file daalo jaan 🖼️", "error");
    return;
  }
  if (file.size > 4 * 1024 * 1024) {
    toast("Image bahut bada hai — 4 MB se kam ho", "error");
    return;
  }

  const fd = new FormData();
  fd.append("who", who);
  fd.append("image", file);

  try {
    const r = await fetch(API + "/api/avatar", { method: "POST", body: fd });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    state.avatars[who] = j.url;
    localStorage.setItem("lisa_avatars", JSON.stringify(state.avatars));
    applyAvatars();
    toast(
      who === "lisa" ? "Lisa ka naya look lag gaya 💜" : "Tumhari photo set ho gayi ✨",
      "success",
    );
  } catch (e) {
    toast("Upload fail: " + e.message, "error");
  }
}


// ════════════════════════════════════════════════════════════════════
//  RENDERING
// ════════════════════════════════════════════════════════════════════
function timeNow() {
  const d = new Date();
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function addMessage(who, text, time = null) {
  const msg = document.createElement("div");
  msg.className = `msg msg-${who}`;
  msg.innerHTML = `
    <div class="msg-avatar"></div>
    <div class="msg-bubble">
      <div class="msg-text"></div>
      <div class="msg-time">${time || timeNow()}</div>
    </div>
  `;
  renderBubbleAvatar(msg.querySelector(".msg-avatar"), who);
  msg.querySelector(".msg-text").textContent = text;
  $messages.appendChild(msg);
  $messages.scrollTop = $messages.scrollHeight;
  return msg;
}

// ── Typing indicator (Problem #3) ────────────────────────────────────
function showTyping() {
  $typing.hidden = false;
  $typing.removeAttribute("aria-hidden");
  $statusDot.classList.add("thinking");
  $messages.scrollTop = $messages.scrollHeight;
}
function hideTyping() {
  $typing.hidden = true;
  $typing.setAttribute("aria-hidden", "true");
  $statusDot.classList.remove("thinking");
}

// Defensive: ensure typing is hidden on boot (Problem #3)
hideTyping();

function updateStateUI(s) {
  if (s.mode) {
    state.mode = s.mode;
    document.querySelectorAll(".mode-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.mode === s.mode);
    });
  }
  if (s.mood) {
    state.mood = s.mood;
    $moodEmoji.textContent = MOOD_EMOJI[s.mood] || "🌸";
    $moodText.textContent = s.mood;
    $subtitle.textContent = MOOD_SUBTITLES[s.mood] || MOOD_SUBTITLES.neutral;
  }
  if (typeof s.turn_count === "number") {
    state.turn_count = s.turn_count;
    $statTurns.textContent = s.turn_count;
  }
  if (typeof s.history_size === "number") {
    state.history_size = s.history_size;
    $statHistory.textContent = s.history_size;
  }
  if (typeof s.pending_wa !== "undefined") {
    $waBanner.hidden = !s.pending_wa;
  }
}

async function refreshMemoryCount() {
  try {
    const r = await fetch(API + "/api/memories");
    const j = await r.json();
    $statMemories.textContent = j.count;
  } catch { /* ignore */ }
}

async function refreshState() {
  try {
    const r = await fetch(API + "/api/state");
    const j = await r.json();
    updateStateUI(j);
  } catch (e) {
    console.warn("state poll failed:", e);
  }
}


// ════════════════════════════════════════════════════════════════════
//  CHAT (text)
// ════════════════════════════════════════════════════════════════════
async function sendMessage(text, fromVoice = false) {
  if (state.busy) return;
  text = (text || "").trim();
  if (!text) return;

  state.busy = true;
  $btnSend.disabled = true;

  addMessage("manish", text);
  $input.value = "";
  autoResize();
  updateSendButton();
  showTyping();

  try {
    const r = await fetch(API + "/api/chat", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        message:    text,
        mode:       fromVoice ? "voice" : "text",
        // Problem #2 — when TTS will play, force Devanagari-friendly agent
        auto_speak: state.autoSpeak && !fromVoice,
      }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();

    hideTyping();
    const lisaMsg = addMessage("lisa", j.reply);
    // Per-message token chip (Problem #4)
    if (lisaMsg && j.tokens && (j.tokens.total || j.tokens.requests)) {
      attachTokenChip(lisaMsg, j.tokens);
    }
    if (j.tokens) onTokensFromChat(j.tokens, j.tokens_today);
    updateStateUI(j);

    if (state.autoSpeak && j.tts_text) {
      speakText(j.tts_text);
    } else if (state.autoSpeak && j.reply) {
      speakText(j.reply);
    }
  } catch (e) {
    hideTyping();   // defensive — never leave typing stuck
    toast("Lisa offline ho gayi 😔: " + e.message, "error");
    console.error(e);
  } finally {
    hideTyping();   // double-safety
    state.busy = false;
    $btnSend.disabled = false;
    $input.focus();
  }
}


// ════════════════════════════════════════════════════════════════════
//  VOICE INPUT (mic → blob → /api/voice)
// ════════════════════════════════════════════════════════════════════
async function startRecording() {
  if (state.recording) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeOptions = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    let mimeType = "";
    for (const m of mimeOptions) {
      if (MediaRecorder.isTypeSupported(m)) { mimeType = m; break; }
    }
    state.mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    state.chunks = [];

    state.mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) state.chunks.push(e.data);
    };
    state.mediaRecorder.onstop = onRecordingStopped;

    state.mediaRecorder.start();
    state.recording = true;
    state.recStart = Date.now();
    $btnMic.classList.add("recording");
    $recIndicator.hidden = false;          // SHOW only while recording
    $recIndicator.removeAttribute("aria-hidden");

    state.recTimer = setInterval(() => {
      const s = Math.floor((Date.now() - state.recStart) / 1000);
      $recTimer.textContent = s + "s";
      if (s >= 30) stopRecording();   // auto-stop at 30s
    }, 250);
  } catch (e) {
    toast("Mic access denied — browser permission do.", "error");
    console.error(e);
  }
}

function stopRecording() {
  // Problem #5 — always force the indicator hidden, even if we're not
  // actually recording (defensive — catches stale UI states).
  state.recording = false;
  $btnMic.classList.remove("recording");
  $recIndicator.hidden = true;
  $recIndicator.setAttribute("aria-hidden", "true");
  if (state.recTimer) { clearInterval(state.recTimer); state.recTimer = null; }
  try { if (state.mediaRecorder) state.mediaRecorder.stop(); } catch {}
  if (state.mediaRecorder && state.mediaRecorder.stream) {
    state.mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
}

// Defensive: ensure recording bar hidden on boot (Problem #5)
$recIndicator.hidden = true;

async function onRecordingStopped() {
  const blob = new Blob(state.chunks, { type: state.mediaRecorder.mimeType || "audio/webm" });
  if (blob.size < 1000) {
    toast("Audio bahut chhota tha — phir try karo.", "info");
    return;
  }

  state.busy = true;
  showTyping();

  try {
    const fd = new FormData();
    fd.append("audio", blob, "voice.webm");

    const r = await fetch(API + "/api/voice", { method: "POST", body: fd });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();

    hideTyping();

    if (j.skipped) {
      toast("Kuch suna nahi — phir bolo.", "info");
      return;
    }

    if (j.transcript) addMessage("manish", j.transcript);
    if (j.reply)      addMessage("lisa", j.reply);
    updateStateUI(j);

    if (j.tts_text) speakText(j.tts_text);
    else if (j.reply) speakText(j.reply);
  } catch (e) {
    hideTyping();
    toast("Voice processing fail: " + e.message, "error");
    console.error(e);
  } finally {
    hideTyping();
    state.busy = false;
  }
}


// ════════════════════════════════════════════════════════════════════
//  TTS (text → /api/tts → audio)
// ════════════════════════════════════════════════════════════════════
let currentAudio = null;
async function speakText(text) {
  if (!text || !state.autoSpeak) return;
  try {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    const r = await fetch(API + "/api/tts", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ text }),
    });
    if (!r.ok) return;
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    currentAudio = new Audio(url);
    currentAudio.play().catch(e => console.warn("autoplay blocked:", e));
    currentAudio.onended = () => URL.revokeObjectURL(url);
  } catch (e) {
    console.warn("TTS failed:", e);
  }
}


// ════════════════════════════════════════════════════════════════════
//  MEMORY / TRACE PANEL
// ════════════════════════════════════════════════════════════════════
function openTrace(tab = "trace") {
  $tracePane.hidden = false;
  $app.classList.add("trace-open");
  switchTraceTab(tab);
}
function closeTrace() {
  $tracePane.hidden = true;
  $app.classList.remove("trace-open");
}
function switchTraceTab(tab) {
  state.traceTab = tab;
  document.querySelectorAll(".trace-tab").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  $traceTitle.textContent = ({
    trace: "📜 Trace",
    memories: "🧠 Memories",
    history: "💬 History",
  })[tab];

  if (tab === "memories")     renderMemories();
  else if (tab === "history") renderHistory();
  else                        renderTrace();
}

function renderTrace() {
  if (!state.lastTrace.length) {
    $traceContent.innerHTML = `<div class="trace-empty">
      Live tracer wiring nahi hai (yet). Lisa ka backend tracer terminal
      mein chal raha hai. Future feature: WebSocket /ws/trace stream.
    </div>`;
    return;
  }
  $traceContent.innerHTML = state.lastTrace.map(e => `
    <div class="trace-entry">
      <div class="trace-tag">${escapeHtml(e.tag)}</div>
      <div>${escapeHtml(e.msg)}</div>
    </div>
  `).join("");
}

async function renderMemories() {
  $traceContent.innerHTML = `<div class="trace-empty">Loading…</div>`;
  try {
    const r = await fetch(API + "/api/memories");
    const j = await r.json();
    if (!j.memories.length) {
      $traceContent.innerHTML = `<div class="trace-empty">
        Abhi tak Lisa ne kuch save nahi kiya. Baat karo, voh kheech legi 💡
      </div>`;
      return;
    }
    $traceContent.innerHTML = j.memories.map(m => `
      <div class="memory-card">
        <div class="memory-cat">${escapeHtml(m.category || "")}</div>
        <div class="memory-key">${escapeHtml(m.key || "")}</div>
        <div class="memory-val">${escapeHtml(m.value || "")}</div>
      </div>
    `).join("");
  } catch (e) {
    $traceContent.innerHTML = `<div class="trace-empty">Failed: ${escapeHtml(e.message)}</div>`;
  }
}

async function renderHistory() {
  $traceContent.innerHTML = `<div class="trace-empty">Loading…</div>`;
  try {
    const r = await fetch(API + "/api/history");
    const j = await r.json();
    let html = "";
    if (j.summary) {
      html += `<div class="memory-card">
        <div class="memory-cat">Earlier summary</div>
        <div class="memory-val">${escapeHtml(j.summary)}</div>
      </div>`;
    }
    if (!j.history.length && !j.summary) {
      $traceContent.innerHTML = `<div class="trace-empty">No history yet.</div>`;
      return;
    }
    html += j.history.map(m => `
      <div class="memory-card" style="border-left-color:${m.role==='user'?'#ffb478':'#c084fc'}">
        <div class="memory-cat">${m.role === "user" ? "Manish" : "Lisa"}</div>
        <div class="memory-val">${escapeHtml(m.content || "")}</div>
      </div>
    `).join("");
    $traceContent.innerHTML = html;
  } catch (e) {
    $traceContent.innerHTML = `<div class="trace-empty">Failed: ${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}


// ════════════════════════════════════════════════════════════════════
//  MODE / RESET
// ════════════════════════════════════════════════════════════════════
async function setMode(mode) {
  try {
    const r = await fetch(API + "/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    if (!r.ok) throw new Error("mode switch failed");
    updateStateUI({ mode });
    toast(mode === "personal" ? "Personal mode on 💖" : "Professional mode on 💼", "success");
  } catch (e) {
    toast(e.message, "error");
  }
}

async function resetChat() {
  if (!confirm("Saari chat history reset kar du? Long-term memories bachi rahengi.")) return;
  try {
    await fetch(API + "/api/reset", { method: "POST" });
    $messages.innerHTML = "";
    addMessage("lisa", "Theek hai jaan, fresh start! Bolo kya haal hai?");
    refreshState();
    toast("Reset ho gaya 🔄", "success");
  } catch (e) {
    toast(e.message, "error");
  }
}


// ════════════════════════════════════════════════════════════════════
//  EVENT WIRING
// ════════════════════════════════════════════════════════════════════
function autoResize() {
  $input.style.height = "auto";
  $input.style.height = Math.min($input.scrollHeight, 180) + "px";
}

function updateSendButton() {
  if ($input.value.trim().length > 0) {
    $btnSend.classList.add("has-text");
  } else {
    $btnSend.classList.remove("has-text");
  }
}

$input.addEventListener("input", () => { autoResize(); updateSendButton(); });
$input.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage($input.value);
  }
});

$btnSend.addEventListener("click", () => sendMessage($input.value));

$btnMic.addEventListener("click", () => {
  if (state.recording) stopRecording();
  else                 startRecording();
});
$btnStopRec.addEventListener("click", stopRecording);

document.querySelectorAll(".mode-btn").forEach(b => {
  b.addEventListener("click", () => setMode(b.dataset.mode));
});

$btnReset.addEventListener("click", resetChat);
$btnMemories.addEventListener("click", () => openTrace("memories"));
$btnTrace.addEventListener("click", () => {
  if ($tracePane.hidden) openTrace(state.traceTab);
  else closeTrace();
});
$btnCloseTrace.addEventListener("click", closeTrace);

document.querySelectorAll(".trace-tab").forEach(b => {
  b.addEventListener("click", () => switchTraceTab(b.dataset.tab));
});

$btnAutoSpeak.addEventListener("click", () => {
  state.autoSpeak = !state.autoSpeak;
  $btnAutoSpeak.classList.toggle("active", state.autoSpeak);
  $autoSpeakIcon.textContent = state.autoSpeak ? "🔊" : "🔇";
  toast(state.autoSpeak ? "Voice on 🔊" : "Voice muted 🔇", "info", 1500);
});
$btnAutoSpeak.classList.add("active");

$btnHelp.addEventListener("click", () => {
  addMessage("lisa", [
    "Tips:",
    "• Type karo ya 🎙️ button dabake bolo",
    "• 'aaj ka weather' / 'koi news bata' — web queries",
    "• 'sugri ko bolo kal milte hain' — WhatsApp",
    "• 'volume 50 karo' / 'screenshot lo' — system",
    "• 'usko reply karo …' — context-aware reply",
    "• Mode toggle se professional/personal switch",
    "• Sidebar mein avatars pe click karke apni / Lisa ki photo set karo 📸",
  ].join("\n"));
});

// ── Avatar click → file picker (Problem #7) ──────────────────────────
$lisaAvatarSide.addEventListener("click", () => $avatarFileLisa.click());
$manishAvatarSide.addEventListener("click", () => $avatarFileManish.click());

$avatarFileLisa.addEventListener("change", e => {
  const f = e.target.files && e.target.files[0];
  if (f) uploadAvatar("lisa", f);
  e.target.value = "";   // allow re-uploading same file
});
$avatarFileManish.addEventListener("change", e => {
  const f = e.target.files && e.target.files[0];
  if (f) uploadAvatar("manish", f);
  e.target.value = "";
});

// Keyboard shortcut: Spacebar (held) for push-to-talk when input not focused
document.addEventListener("keydown", e => {
  if (e.code === "Space" && document.activeElement !== $input && !state.recording) {
    e.preventDefault();
    startRecording();
  }
});
document.addEventListener("keyup", e => {
  if (e.code === "Space" && state.recording) {
    e.preventDefault();
    stopRecording();
  }
});


// ════════════════════════════════════════════════════════════════════
//  TOKEN PANEL (Problem #4)
//  - Sidebar detailed breakdown (LLM today + voice this session + EL keys)
//  - Header live badge
//  - Per-message chip showing this turn's token cost
// ════════════════════════════════════════════════════════════════════
const $tokTotal       = document.getElementById("tokTotal");
const $tokIn          = document.getElementById("tokIn");
const $tokOut         = document.getElementById("tokOut");
const $tokReq         = document.getElementById("tokReq");
const $tokLastMsg     = document.getElementById("tokLastMsg");
const $tokProviders   = document.getElementById("tokProviders");
const $voiceChars     = document.getElementById("voiceChars");
const $voiceProviders = document.getElementById("voiceProviders");
const $elBlock        = document.getElementById("elBlock");
const $elKeys         = document.getElementById("elKeys");
const $elError        = document.getElementById("elError");
const $tokenBadge     = document.getElementById("tokenBadge");
const $tokenBadgeVal  = document.getElementById("tokenBadgeValue");
const $tokenBadgeDelta = document.getElementById("tokenBadgeDelta");
const $btnTokenRefresh = document.getElementById("btnTokenRefresh");

function fmtNum(n) {
  if (n == null) return "0";
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k";
  return String(n);
}

function attachTokenChip(msgEl, tokens) {
  if (!msgEl || !tokens) return;
  const bubble = msgEl.querySelector(".msg-bubble");
  if (!bubble) return;
  const total = (tokens.in || 0) + (tokens.out || 0);
  if (!total && !tokens.requests) return;
  const chip = document.createElement("div");
  chip.className = "token-chip";
  const provBits = Object.keys(tokens.per_provider || {}).map(p => {
    const short = p.split(":")[0];   // e.g. "cerebras"
    return short;
  }).join(" + ") || "local";
  chip.innerHTML = `
    <span class="token-chip-icon">⚡</span>
    <span>${fmtNum(total)} tok</span>
    <span class="token-chip-sub">${fmtNum(tokens.in || 0)} in · ${fmtNum(tokens.out || 0)} out · ${provBits}</span>
  `;
  bubble.appendChild(chip);
}

function onTokensFromChat(delta, today) {
  // Update "last msg" line
  if (delta && (delta.total || delta.requests)) {
    $tokLastMsg.textContent = `${fmtNum(delta.total)} (${delta.requests} req)`;
  }
  // Update aggregate from today snapshot if provided
  if (today && today.providers) {
    renderTokenTotals(today);
  } else {
    refreshTokenPanel();
  }
}

function renderTokenTotals(today) {
  const provs = today.providers || {};
  let tIn = 0, tOut = 0, tReq = 0;
  Object.values(provs).forEach(p => {
    tIn  += p["in"]      || 0;
    tOut += p["out"]     || 0;
    tReq += p["requests"] || 0;
  });
  $tokTotal.textContent = fmtNum(tIn + tOut);
  $tokIn.textContent    = fmtNum(tIn);
  $tokOut.textContent   = fmtNum(tOut);
  $tokReq.textContent   = String(tReq);
  $tokenBadgeVal.textContent = fmtNum(tIn + tOut);

  // Per-provider breakdown bars
  $tokProviders.innerHTML = "";
  const sorted = Object.entries(provs).sort((a, b) =>
    (b[1].in + b[1].out) - (a[1].in + a[1].out)
  );
  const maxTotal = sorted.length ? (sorted[0][1].in + sorted[0][1].out) : 1;
  sorted.forEach(([prov, st]) => {
    const tot = (st.in || 0) + (st.out || 0);
    if (!tot) return;
    const pct = Math.max(4, Math.round((tot / maxTotal) * 100));
    const row = document.createElement("div");
    row.className = "prov-row";
    row.innerHTML = `
      <div class="prov-label">
        <span class="prov-name">${prov}</span>
        <span class="prov-val">${fmtNum(tot)}</span>
      </div>
      <div class="prov-bar"><div class="prov-bar-fill" style="width:${pct}%"></div></div>
    `;
    $tokProviders.appendChild(row);
  });
}

function renderVoicePanel(voice) {
  if (!voice) return;
  $voiceChars.textContent = fmtNum(voice.total_chars || 0);
  $voiceProviders.innerHTML = "";
  Object.entries(voice.session_chars || {}).forEach(([prov, chars]) => {
    if (!chars) return;
    const row = document.createElement("div");
    row.className = "prov-row";
    row.innerHTML = `
      <div class="prov-label">
        <span class="prov-name">${prov}</span>
        <span class="prov-val">${fmtNum(chars)} chars</span>
      </div>
    `;
    $voiceProviders.appendChild(row);
  });

  // ElevenLabs keys + last error
  const el = voice.elevenlabs;
  if (el && el.configured) {
    $elBlock.hidden = false;
    $elKeys.innerHTML = "";
    (el.keys || []).forEach(k => {
      const pct = Math.min(100, Math.round((k.used / Math.max(1, k.limit)) * 100));
      const dead = k.dead;
      const div = document.createElement("div");
      div.className = "el-key-row" + (dead ? " dead" : "");
      div.innerHTML = `
        <div class="el-key-head">
          <span class="el-key-id">${k.key}</span>
          <span class="el-key-usage">${dead ? "DEAD" : (fmtNum(k.used) + " / " + fmtNum(k.limit))}</span>
        </div>
        ${dead ? `<div class="el-key-reason">${k.dead_reason || ""}</div>` :
                 `<div class="prov-bar"><div class="prov-bar-fill" style="width:${pct}%"></div></div>`}
      `;
      $elKeys.appendChild(div);
    });
    if (el.last_error) {
      $elError.hidden = false;
      const isIPBlock = (el.last_error.kind === "ip_block");
      $elError.innerHTML = isIPBlock
        ? `⚠️ <strong>ElevenLabs IP-block</strong> — free tier blocks VPN/datacenter IPs.
           Mobile hotspot try karo, ya plan upgrade.<br/>
           <small>${el.last_error.message}</small>`
        : `⚠️ ${el.last_error.message || el.last_error.kind}`;
    } else {
      $elError.hidden = true;
    }
  } else {
    $elBlock.hidden = true;
  }
}

async function refreshTokenPanel() {
  try {
    const r = await fetch(API + "/api/token_usage");
    if (!r.ok) return;
    const j = await r.json();
    if (j.chat)  renderTokenTotals({ providers: j.chat.providers });
    if (j.voice) renderVoicePanel(j.voice);
  } catch (e) { /* silent */ }
}

if ($btnTokenRefresh) {
  $btnTokenRefresh.addEventListener("click", () => {
    $btnTokenRefresh.classList.add("spin");
    refreshTokenPanel().finally(() =>
      setTimeout(() => $btnTokenRefresh.classList.remove("spin"), 400)
    );
  });
}
if ($tokenBadge) {
  $tokenBadge.addEventListener("click", () => {
    const panel = document.querySelector(".token-panel");
    if (panel) {
      panel.scrollIntoView({ behavior: "smooth", block: "center" });
      panel.classList.add("pulse");
      setTimeout(() => panel.classList.remove("pulse"), 1200);
    }
  });
}


// ════════════════════════════════════════════════════════════════════
//  INIT
// ════════════════════════════════════════════════════════════════════
fetchAvatars();
refreshState();
refreshMemoryCount();
refreshTokenPanel();
setInterval(refreshState, 10000);
setInterval(refreshMemoryCount, 30000);
setInterval(refreshTokenPanel, 15000);
$input.focus();
updateSendButton();