"""
LISA — Web UI Server (v2)
==========================

Browser-based UI that wraps the SAME LisaAgent instance used by main.py
and voice_main.py — so memory, RAG, history, mood, WhatsApp confirmation
flow all work identically.

Run:
    python web_server.py

Then open:  http://127.0.0.1:8765

[v2 changes — May 2026]
  - /api/chat now accepts `auto_speak` flag. When True, even a typed message
    is routed through the VOICE agent so Lisa replies in Devanagari+English
    (Sarvam TTS friendly). Pure text-only chats stay on the Roman agent.
  - NEW: /api/avatar POST — upload custom avatar photo (Manish or Lisa).
  - NEW: /api/avatar GET  — return current avatar choices (persisted on disk).
  - Static /uploads route exposes saved avatars to the browser.

Endpoints
---------
GET  /                          → serves the single-page UI
POST /api/chat       {message, mode, auto_speak} → LisaAgent.chat() → reply
POST /api/voice      <audio>    → Whisper STT → chat → reply
POST /api/tts        {text}     → audio/wav (Sarvam → edge → gTTS chain)
GET  /api/state                 → {mode, mood, turn_count, history_summary}
POST /api/mode       {mode}     → switch personal ↔ professional
POST /api/reset                 → reset conversation history
GET  /api/memories              → list saved long-term facts
GET  /api/history               → current conversation_history (last N turns)
POST /api/wa_confirm {reply}    → answer pending WhatsApp draft (haan/nahi)
POST /api/avatar     <image>    → upload avatar (form: who=manish|lisa)
GET  /api/avatar                → {manish: url|null, lisa: url|null}
"""

import os
import sys
import io
import json
import tempfile
import asyncio
import warnings
from pathlib import Path
from contextlib import asynccontextmanager

# Windows console encoding fix (matches main.py)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

warnings.filterwarnings("ignore")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()

from core.agent import LisaAgent
from memory.long_term import list_all
from config.settings import AGENT_NAME, USER_NAME

# Token tracking + ElevenLabs key status
from core import llm_client as _llm_client
try:
    from voice import elevenlabs_keys as _el_keys
except Exception:
    _el_keys = None

import copy

BASE_DIR    = Path(__file__).parent
STATIC_DIR  = BASE_DIR / "web" / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_CONFIG_FILE = BASE_DIR / "data" / "avatars.json"
AVATAR_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8765"))


# ── Global singleton agent (single instance — shared history, mood, WA state) ──
# [Phase 0 Step 4 fix] Previously two separate agents (_text_agent, _voice_agent)
# caused conversation history to split between typed and voice turns.
# Now one agent handles everything. voice_mode is set per-request before chat().
_agent: LisaAgent | None = None


def get_agent() -> LisaAgent:
    global _agent
    if _agent is None:
        _agent = LisaAgent(voice_mode=False)
    return _agent


# Keep backward-compatible aliases (used by existing code paths below)
def get_text_agent() -> LisaAgent:
    return get_agent()

def get_voice_agent() -> LisaAgent:
    return get_agent()


# ── Avatar persistence helpers ────────────────────────────────────────
def _load_avatar_config() -> dict:
    if AVATAR_CONFIG_FILE.exists():
        try:
            return json.loads(AVATAR_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"manish": None, "lisa": None}


def _save_avatar_config(cfg: dict) -> None:
    AVATAR_CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── FastAPI app ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "═" * 60)
    print(f"   {AGENT_NAME.upper()} — Web UI server starting")
    print(f"   Open in browser: http://{WEB_HOST}:{WEB_PORT}")
    print("═" * 60 + "\n")

    # Preload sentence-transformers model in background thread at startup.
    # Without this, the FIRST RAG call loads the model (44-69 seconds of silence).
    # With this, model loads during startup while the banner is showing.
    def _preload_embedder():
        try:
            from memory.rag_memory import _get_local_model
            _get_local_model()
            print("  [RAG] Local embedding model ready.\n")
        except Exception as e:
            print(f"  [RAG] Preload skipped: {e}\n")

    import threading
    threading.Thread(target=_preload_embedder, daemon=True).start()

    yield
    try:
        from actions.whatsapp_actions import close_driver
        close_driver()
    except Exception:
        pass
    print(f"\n  {AGENT_NAME} web server shutting down. Bye!\n")


app = FastAPI(title="Lisa Web UI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Request models ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    mode: str | None = None       # "text" (default) or "voice"
    auto_speak: bool = False      # If True → route through voice agent
                                  #          for Devanagari-friendly TTS


class TTSRequest(BaseModel):
    text: str


class ModeRequest(BaseModel):
    mode: str                     # "personal" or "professional"


# ── Routes ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            "<h1>UI not found</h1><p>web/static/index.html missing.</p>",
            status_code=500,
        )
    return FileResponse(str(index_path))


def _token_snapshot() -> dict:
    """Deep-copy current token_usage.json content (in-memory)."""
    try:
        return copy.deepcopy(_llm_client._load_usage())
    except Exception:
        return {"providers": {}}


def _token_delta(before: dict, after: dict) -> dict:
    """Compute per-provider delta (requests / in / out) between snapshots."""
    delta = {"requests": 0, "in": 0, "out": 0, "per_provider": {}}
    b_provs = (before or {}).get("providers", {})
    a_provs = (after  or {}).get("providers", {})
    for prov, a_stats in a_provs.items():
        b_stats = b_provs.get(prov, {"requests": 0, "in": 0, "out": 0})
        d_req = a_stats.get("requests", 0) - b_stats.get("requests", 0)
        d_in  = a_stats.get("in", 0)       - b_stats.get("in", 0)
        d_out = a_stats.get("out", 0)      - b_stats.get("out", 0)
        if d_req or d_in or d_out:
            delta["requests"] += d_req
            delta["in"]       += d_in
            delta["out"]      += d_out
            delta["per_provider"][prov] = {"requests": d_req, "in": d_in, "out": d_out}
    delta["total"] = delta["in"] + delta["out"]
    return delta


# Live counter for voice/TTS characters billed this session
_session_voice_chars = {"elevenlabs": 0, "sarvam": 0, "edge": 0, "gtts": 0}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    Text chat. Routing decision:
      - mode == "voice"  → voice agent (mic flow)
      - auto_speak True  → voice agent (so TTS reads Devanagari naturally)
      - else             → text agent (pure typing, no TTS)
    """
    if not req.message or not req.message.strip():
        raise HTTPException(400, "Empty message")

    use_voice_mode = (req.mode == "voice") or req.auto_speak
    agent = get_agent()
    agent.voice_mode = use_voice_mode   # set BEFORE chat() — affects system prompt

    # Import tag stripper (already available from tts module)
    from voice.tts import _strip_audio_tags

    # 🔥 Capture token usage delta around the chat() call
    tok_before = _token_snapshot()

    loop  = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, agent.chat, req.message)

    tok_after = _token_snapshot()
    tok_delta = _token_delta(tok_before, tok_after)

    # reply may still contain audio tags (for ElevenLabs TTS)
    tts_text   = reply                   # tagged version → TTS uses this
    clean_reply = _strip_audio_tags(reply)  # clean version → UI displays this

    return {
        "reply":         clean_reply,    # displayed in chat bubble (no tags)
        "tts_text":      tts_text,       # sent to /api/tts (has tags for ElevenLabs)
        "mode":          agent.get_mode(),
        "mood":          agent.get_mood(),
        "turn_count":    agent.turn_count,
        "pending_wa":    agent.pending_whatsapp is not None,
        "history_size":  len(agent.conversation_history),
        "agent_used":    "voice" if use_voice_mode else "text",
        "tokens":        tok_delta,
        "tokens_today":  tok_after,
    }


@app.post("/api/voice")
async def voice(audio: UploadFile = File(...)):
    """
    Voice chat — accepts a recorded audio blob from the browser mic,
    runs Groq Whisper STT, then routes through the voice-mode agent.
    """
    try:
        data = await audio.read()
        if not data:
            raise HTTPException(400, "Empty audio")

        suffix = ".webm" if "webm" in (audio.content_type or "") else ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            tmp_path = f.name

        from groq import Groq
        from config.settings import GROQ_API_KEY
        client = Groq(api_key=GROQ_API_KEY)

        HINGLISH_PROMPT = (
            "haan yaar main theek hoon, tum kaisi ho. "
            "Lisa jaan suno na, YouTube pe ek purana hindi gaana baja do. "
            "WhatsApp pe message bhejo. weather kaisa hai, news batao."
        )

        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file            = f,
                model           = "whisper-large-v3-turbo",
                prompt          = HINGLISH_PROMPT,
                response_format = "text",
                temperature     = 0.0,
                language        = "hi",
            )

        raw = result.strip() if isinstance(result, str) else result.text.strip()

        from voice.stt import _normalize_output
        text = _normalize_output(raw)

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        if not text:
            return {"transcript": "", "reply": "", "skipped": True}

        agent = get_agent()
        agent.voice_mode = True    # voice endpoint always uses voice prompt
        loop  = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, agent.chat, text)

        from voice.tts import _strip_audio_tags
        tts_text    = reply
        clean_reply = _strip_audio_tags(reply)

        return {
            "transcript":   text,
            "reply":        clean_reply,
            "tts_text":     tts_text,
            "mode":         agent.get_mode(),
            "mood":         agent.get_mood(),
            "turn_count":   agent.turn_count,
            "pending_wa":   agent.pending_whatsapp is not None,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"voice processing failed: {e}")


@app.post("/api/tts")
async def tts(req: TTSRequest):
    """
    Generate TTS audio for the given text.

    Provider chain (matches voice/tts.py speak()):
        ElevenLabs (audio tags) → Sarvam → Edge → gTTS

    Returns the audio bytes plus an `X-TTS-Provider` header so the UI
    can show which provider actually answered.
    """
    if not req.text or not req.text.strip():
        raise HTTPException(400, "Empty text")

    from voice.tts import (
        _elevenlabs_tts, _sarvam_tts, _edge_tts, _gtts,
        _clean_text, _strip_audio_tags,
        TEMP_WAV, TEMP_MP3, TTS_PROVIDER,
    )
    import voice.tts as tts_mod

    # ElevenLabs gets the tagged text; everyone else gets it stripped.
    tagged_text = _clean_text(req.text, keep_devanagari=True, keep_audio_tags=True)
    plain_text  = _strip_audio_tags(tagged_text)
    if not plain_text:
        raise HTTPException(400, "Nothing to speak after cleanup")

    # Suppress the local pygame playback — we only want the file bytes
    original_play = tts_mod._play_file
    tts_mod._play_file = lambda path: None

    # Chain definition: (label, fn, payload, file_path, mime)
    el_step    = ("elevenlabs", _elevenlabs_tts, tagged_text, TEMP_MP3, "audio/mpeg")
    sarvam_step = ("sarvam",    _sarvam_tts,    plain_text,  TEMP_WAV, "audio/wav")
    edge_step  = ("edge",       _edge_tts,      plain_text,  TEMP_MP3, "audio/mpeg")
    gtts_step  = ("gtts",       _gtts,          plain_text,  TEMP_MP3, "audio/mpeg")

    chains = {
        "elevenlabs": [el_step, sarvam_step, edge_step, gtts_step],
        "sarvam":     [sarvam_step, el_step, edge_step, gtts_step],
        "edge":       [edge_step, sarvam_step, gtts_step],
        "gtts":       [gtts_step, edge_step],
    }
    chain = chains.get(TTS_PROVIDER, chains["elevenlabs"])

    try:
        for label, fn, payload, out_path, mime in chain:
            try:
                if fn(payload):
                    if os.path.exists(out_path):
                        with open(out_path, "rb") as f:
                            audio_bytes = f.read()
                        # Track session-level voice char usage
                        try:
                            _session_voice_chars[label] = (
                                _session_voice_chars.get(label, 0) + len(payload)
                            )
                        except Exception:
                            pass
                        return Response(
                            content=audio_bytes,
                            media_type=mime,
                            headers={
                                "X-TTS-Provider": label,
                                "X-TTS-Chars":    str(len(payload)),
                            },
                        )
            except Exception as e:
                print(f"  [TTS][{label}] {e}")
        # All failed — surface a structured error (helps UI show IP-block msg)
        last_err = None
        if _el_keys is not None:
            try:
                last_err = _el_keys.get_last_error()
            except Exception:
                last_err = None
        raise HTTPException(
            status_code=503,
            detail={
                "error":      "all_tts_providers_failed",
                "last_error": last_err,
                "hint":       "ElevenLabs free-tier blocks VPN/proxy IPs. "
                              "Try mobile hotspot or upgrade your plan.",
            },
        )
    finally:
        tts_mod._play_file = original_play


# ════════════════════════════════════════════════════════════════════════
#  TOKEN USAGE  (Problem #4 — sidebar detailed + header live badge)
# ════════════════════════════════════════════════════════════════════════

@app.get("/api/token_usage")
async def token_usage():
    """
    Return today's LLM token usage (per provider) + this-session voice TTS
    character usage + ElevenLabs key status for the sidebar panel.
    """
    usage = _llm_client._load_usage()
    providers = usage.get("providers", {})
    total_in  = sum(p.get("in", 0)  for p in providers.values())
    total_out = sum(p.get("out", 0) for p in providers.values())
    total_req = sum(p.get("requests", 0) for p in providers.values())

    el_status = None
    if _el_keys is not None:
        try:
            el_status = _el_keys.get_status_dict()
        except Exception as e:
            el_status = {"configured": False, "error": str(e)}

    return {
        "date":      usage.get("date"),
        "chat": {
            "requests":  total_req,
            "in":        total_in,
            "out":       total_out,
            "total":     total_in + total_out,
            "providers": providers,
        },
        "voice": {
            "session_chars": _session_voice_chars,
            "total_chars":   sum(_session_voice_chars.values()),
            "elevenlabs":    el_status,
        },
    }


@app.post("/api/token_usage/reset")
async def token_usage_reset():
    """Reset the session voice counter (does NOT reset persistent LLM totals)."""
    for k in list(_session_voice_chars.keys()):
        _session_voice_chars[k] = 0
    if _el_keys is not None:
        try:
            _el_keys.clear_last_error()
        except Exception:
            pass
    return {"ok": True}


@app.get("/api/state")
async def state():
    agent = get_agent()
    return {
        "mode":            agent.get_mode(),
        "mood":            agent.get_mood(),
        "turn_count":      agent.turn_count,
        "history_size":    len(agent.conversation_history),
        "history_summary": agent.history_summary or "",
        "pending_wa":      agent.pending_whatsapp,
        "voice_mode":      agent.voice_mode,
        "agent_name":      AGENT_NAME,
        "user_name":       USER_NAME,
    }


@app.post("/api/mode")
async def set_mode(req: ModeRequest):
    if req.mode not in ("personal", "professional"):
        raise HTTPException(400, "mode must be 'personal' or 'professional'")
    for ag in (_text_agent, _voice_agent):
        if ag is not None:
            ag.mode = req.mode
    return {"mode": req.mode, "ok": True}


@app.post("/api/reset")
async def reset():
    for ag in (_text_agent, _voice_agent):
        if ag is not None:
            ag.reset_conversation()
    return {"ok": True}


@app.get("/api/memories")
async def memories():
    mems = list_all()
    return {"count": len(mems), "memories": mems}


@app.get("/api/history")
async def history():
    agent = get_text_agent()
    return {
        "history": agent.conversation_history,
        "summary": agent.history_summary or "",
    }


# ════════════════════════════════════════════════════════════════════════
#  AVATAR upload / get  (Problem #7 — change Manish + Lisa photos)
# ════════════════════════════════════════════════════════════════════════
ALLOWED_AVATAR_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_AVATAR_BYTES    = 4 * 1024 * 1024   # 4 MB ka cap


@app.get("/api/avatar")
async def get_avatars():
    """Return persisted avatar URLs (or null if default emoji)."""
    cfg = _load_avatar_config()
    return cfg


@app.post("/api/avatar")
async def upload_avatar(
    who:   str       = Form(...),                   # "manish" | "lisa"
    image: UploadFile = File(...),
):
    """Upload an avatar image; replaces the existing one for that side."""
    who = (who or "").strip().lower()
    if who not in ("manish", "lisa"):
        raise HTTPException(400, "who must be 'manish' or 'lisa'")

    data = await image.read()
    if not data:
        raise HTTPException(400, "Empty image")
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(413, f"Image > {MAX_AVATAR_BYTES // (1024*1024)} MB")

    # Pick extension from filename, default to .png
    ext = Path(image.filename or "").suffix.lower()
    if ext not in ALLOWED_AVATAR_EXTS:
        ext = ".png"

    # Stable filename per person → overwrite each upload (no cache buildup)
    out_path = UPLOADS_DIR / f"avatar_{who}{ext}"

    # Clean older variants (different ext) so /static/uploads doesn't bloat
    for old_ext in ALLOWED_AVATAR_EXTS:
        if old_ext == ext:
            continue
        old = UPLOADS_DIR / f"avatar_{who}{old_ext}"
        if old.exists():
            try: old.unlink()
            except Exception: pass

    out_path.write_bytes(data)

    # Cache-bust via mtime
    url = f"/static/uploads/{out_path.name}?v={int(out_path.stat().st_mtime)}"

    cfg = _load_avatar_config()
    cfg[who] = url
    _save_avatar_config(cfg)

    return {"ok": True, "who": who, "url": url}


@app.delete("/api/avatar")
async def reset_avatar(who: str):
    """Reset an avatar back to emoji default."""
    who = (who or "").strip().lower()
    if who not in ("manish", "lisa"):
        raise HTTPException(400, "who must be 'manish' or 'lisa'")

    # Remove all files for that side
    for ext in ALLOWED_AVATAR_EXTS:
        f = UPLOADS_DIR / f"avatar_{who}{ext}"
        if f.exists():
            try: f.unlink()
            except Exception: pass

    cfg = _load_avatar_config()
    cfg[who] = None
    _save_avatar_config(cfg)
    return {"ok": True, "who": who}


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web_server:app",
        host=WEB_HOST,
        port=WEB_PORT,
        reload=False,
        log_level="info",
    )