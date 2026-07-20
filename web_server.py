"""
LISA — Web UI Server (v3 — dashboard edition)
==============================================
All v2 endpoints preserved. NEW:

Routes
------
GET  /                          → JARVIS-style dashboard (new)
GET  /chat                      → existing wifey chat UI (unchanged)

Dashboard APIs (new)
--------------------
GET  /api/dashboard/status      → aggregated snapshot for header cards
GET  /api/dashboard/trace       → poll trace ring-buffer (?since=<seq>)
GET  /api/dashboard/trace/stream → Server-Sent Events (live trace feed)
GET  /api/os_watcher            → {status, timeline}
POST /api/os_watcher/start      → begin stealth monitoring
POST /api/os_watcher/stop       → stop + return report
GET  /api/security              → security level + meta
POST /api/security/level        → {level:int, password?:str}
POST /api/security/password     → {old_password, new_password}  (in-memory)
"""

import os
import sys
import io
import json
import time
import asyncio
import tempfile
import warnings
from pathlib import Path
from contextlib import asynccontextmanager

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

warnings.filterwarnings("ignore")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()

from core.agent    import LisaAgent
from core.tracer   import tracer
from core.os_watcher import eye
from core.security   import auth
from config.settings import AGENT_NAME, USER_NAME

from core import llm_client as _llm_client
try:
    from voice import elevenlabs_keys as _el_keys
except Exception:
    _el_keys = None

import copy

BASE_DIR      = Path(__file__).parent
STATIC_DIR    = BASE_DIR / "web" / "static"
DASHBOARD_DIR = STATIC_DIR / "dashboard"
UPLOADS_DIR   = STATIC_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

AVATAR_CONFIG_FILE = BASE_DIR / "data" / "avatars.json"
AVATAR_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8765"))


# ── Global singleton agent ────────────────────────────────────────────
_agent: LisaAgent | None = None

def get_agent() -> LisaAgent:
    global _agent
    if _agent is None:
        _agent = LisaAgent(voice_mode=False)
    return _agent

def get_text_agent()  -> LisaAgent: return get_agent()
def get_voice_agent() -> LisaAgent: return get_agent()


# ── Avatar helpers ────────────────────────────────────────────────────
def _load_avatar_config() -> dict:
    if AVATAR_CONFIG_FILE.exists():
        try:
            return json.loads(AVATAR_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"manish": None, "lisa": None}

def _save_avatar_config(cfg: dict) -> None:
    AVATAR_CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ── FastAPI app + lifespan ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "═" * 60)
    print(f"   {AGENT_NAME.upper()} — Web UI server starting")
    print(f"   Dashboard:  http://{WEB_HOST}:{WEB_PORT}/")
    print(f"   Chat UI:    http://{WEB_HOST}:{WEB_PORT}/chat")
    print("═" * 60)

    from concurrent.futures import ThreadPoolExecutor
    print("\n  [Startup] Loading embedding model (first-time only, ~30-40s)...")
    loop = asyncio.get_event_loop()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(pool, lambda: __import__(
                "memory.rag_memory", fromlist=["_get_local_model"]
            )._get_local_model())
        print("  [Startup] Embedding model ready ✓")
    except Exception as e:
        print(f"  [Startup] Embedding model skipped: {e}")
    print(f"  [Startup] Server ready\n")

    yield
    try:
        from actions.whatsapp_actions import close_driver
        close_driver()
    except Exception:
        pass
    print(f"\n  {AGENT_NAME} web server shutting down. Bye!\n")


app = FastAPI(title="Lisa Web UI v3", lifespan=lifespan)

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
    mode: str | None = None
    auto_speak: bool = False

class TTSRequest(BaseModel):
    text: str

class ModeRequest(BaseModel):
    mode: str

class SecurityLevelRequest(BaseModel):
    level: int
    password: str | None = None

class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


# ══════════════════════════════════════════════════════════════════════
#  ROUTES — PAGES
# ══════════════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def dashboard_page():
    idx = DASHBOARD_DIR / "index.html"
    if not idx.exists():
        return HTMLResponse(
            "<h1>Dashboard UI not found</h1>"
            "<p>Expected <code>web/static/dashboard/index.html</code></p>",
            status_code=500,
        )
    return FileResponse(str(idx))


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    idx = STATIC_DIR / "index.html"
    if not idx.exists():
        return HTMLResponse(
            "<h1>Chat UI not found</h1><p>web/static/index.html missing.</p>",
            status_code=500,
        )
    return FileResponse(str(idx))


# ══════════════════════════════════════════════════════════════════════
#  ORIGINAL CHAT / VOICE / TTS ENDPOINTS  (unchanged behaviour)
# ══════════════════════════════════════════════════════════════════════
def _token_snapshot() -> dict:
    try:
        return copy.deepcopy(_llm_client._load_usage())
    except Exception:
        return {"providers": {}}

def _token_delta(before: dict, after: dict) -> dict:
    delta = {"requests": 0, "in": 0, "out": 0, "per_provider": {}}
    b_provs = (before or {}).get("providers", {})
    a_provs = (after  or {}).get("providers", {})
    for prov, a_stats in a_provs.items():
        b_stats = b_provs.get(prov, {"requests": 0, "in": 0, "out": 0})
        d_req = a_stats.get("requests", 0) - b_stats.get("requests", 0)
        d_in  = a_stats.get("in",  0)      - b_stats.get("in",  0)
        d_out = a_stats.get("out", 0)      - b_stats.get("out", 0)
        if d_req or d_in or d_out:
            delta["requests"] += d_req
            delta["in"]       += d_in
            delta["out"]      += d_out
            delta["per_provider"][prov] = {"requests": d_req, "in": d_in, "out": d_out}
    delta["total"] = delta["in"] + delta["out"]
    return delta


_session_voice_chars = {"elevenlabs": 0, "sarvam": 0, "edge": 0, "gtts": 0}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message or not req.message.strip():
        raise HTTPException(400, "Empty message")

    use_voice_mode = (req.mode == "voice") or req.auto_speak
    agent = get_agent()
    agent.voice_mode = use_voice_mode

    from voice.tts import _strip_audio_tags

    tok_before = _token_snapshot()
    loop  = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, agent.chat, req.message)
    tok_after = _token_snapshot()
    tok_delta = _token_delta(tok_before, tok_after)

    tts_text    = reply
    clean_reply = _strip_audio_tags(reply)

    return {
        "reply":         clean_reply,
        "tts_text":      tts_text,
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

        try: os.unlink(tmp_path)
        except Exception: pass

        if not text:
            return {"transcript": "", "reply": "", "skipped": True}

        agent = get_agent()
        agent.voice_mode = True
        loop  = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, agent.chat, text)

        from voice.tts import _strip_audio_tags
        return {
            "transcript":   text,
            "reply":        _strip_audio_tags(reply),
            "tts_text":     reply,
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
    if not req.text or not req.text.strip():
        raise HTTPException(400, "Empty text")

    from voice.tts import (
        _elevenlabs_tts, _sarvam_tts, _edge_tts, _gtts,
        _clean_text, _strip_audio_tags,
        TEMP_WAV, TEMP_MP3, TTS_PROVIDER,
        EDGE_VOICE,
    )
    import voice.tts as tts_mod

    tagged_text = _clean_text(req.text, keep_devanagari=True, keep_audio_tags=True)
    plain_text  = _strip_audio_tags(tagged_text)
    if not plain_text:
        raise HTTPException(400, "Nothing to speak after cleanup")

    original_play = tts_mod._play_file
    tts_mod._play_file = lambda path: None

    el_step     = ("elevenlabs", _elevenlabs_tts, tagged_text, TEMP_MP3, "audio/mpeg")
    sarvam_step = ("sarvam",     _sarvam_tts,    plain_text,  TEMP_WAV, "audio/wav")
    edge_step   = ("edge",       _edge_tts,      plain_text,  TEMP_MP3, "audio/mpeg")
    gtts_step   = ("gtts",       _gtts,          plain_text,  TEMP_MP3, "audio/mpeg")

    current_mode = "personal"
    try:
        current_mode = get_agent().get_mode()
    except Exception:
        pass

    if current_mode == "professional":
        tts_mod.TTS_PROVIDER = "edge"
        tts_mod.EDGE_VOICE = os.getenv("EDGE_VOICE_PROFESSIONAL", "en-US-AnaNeural")
        chain = [edge_step, gtts_step]
    else:
        tts_mod.EDGE_VOICE = os.getenv("EDGE_VOICE", "hi-IN-SwaraNeural")
        chains = {
            "sarvam":     [sarvam_step, edge_step, gtts_step],
            "elevenlabs": [el_step, sarvam_step, edge_step, gtts_step],
            "edge":       [edge_step, gtts_step],
            "gtts":       [gtts_step, edge_step],
        }
        chain = chains.get(TTS_PROVIDER, chains.get("edge", [edge_step, gtts_step]))

    try:
        for label, fn, payload, out_path, mime in chain:
            try:
                if fn(payload):
                    if os.path.exists(out_path):
                        with open(out_path, "rb") as f:
                            audio_bytes = f.read()
                        try:
                            _session_voice_chars[label] = _session_voice_chars.get(label, 0) + len(payload)
                        except Exception:
                            pass
                        return Response(
                            content=audio_bytes,
                            media_type=mime,
                            headers={"X-TTS-Provider": label, "X-TTS-Chars": str(len(payload))},
                        )
            except Exception as e:
                print(f"  [TTS][{label}] {e}")
        last_err = None
        if _el_keys is not None:
            try: last_err = _el_keys.get_last_error()
            except Exception: last_err = None
        raise HTTPException(
            status_code=503,
            detail={
                "error":      "all_tts_providers_failed",
                "last_error": last_err,
                "hint":       "ElevenLabs free-tier blocks VPN/proxy IPs.",
            },
        )
    finally:
        tts_mod._play_file = original_play


# ── Token usage / state / mode / reset / memories / history / avatars ─
@app.get("/api/token_usage")
async def token_usage():
    usage     = _llm_client._load_usage()
    providers = usage.get("providers", {})
    total_in  = sum(p.get("in", 0)       for p in providers.values())
    total_out = sum(p.get("out", 0)      for p in providers.values())
    total_req = sum(p.get("requests", 0) for p in providers.values())

    el_status = None
    if _el_keys is not None:
        try:    el_status = _el_keys.get_status_dict()
        except Exception as e: el_status = {"configured": False, "error": str(e)}

    return {
        "date": usage.get("date"),
        "chat": {"requests": total_req, "in": total_in, "out": total_out,
                 "total": total_in + total_out, "providers": providers},
        "voice": {"session_chars": _session_voice_chars,
                  "total_chars": sum(_session_voice_chars.values()),
                  "elevenlabs": el_status},
    }


@app.post("/api/token_usage/reset")
async def token_usage_reset():
    for k in list(_session_voice_chars.keys()):
        _session_voice_chars[k] = 0
    if _el_keys is not None:
        try: _el_keys.clear_last_error()
        except Exception: pass
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
    get_agent().mode = req.mode
    return {"mode": req.mode, "ok": True}


@app.post("/api/reset")
async def reset():
    get_agent().reset_conversation()
    return {"ok": True}


@app.get("/api/memories")
async def memories():
    mems = get_agent().memory_manager.get_all_active_memories()
    return {"count": len(mems), "memories": mems}


@app.delete("/api/memories")
async def remove_memory(category: str, key: str):
    get_agent().memory_manager.delete_memory(key)
    return {"ok": True}


@app.get("/api/history")
async def history():
    agent = get_text_agent()
    return {"history": agent.conversation_history, "summary": agent.history_summary or ""}


ALLOWED_AVATAR_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_AVATAR_BYTES    = 4 * 1024 * 1024

@app.get("/api/avatar")
async def get_avatars():
    return _load_avatar_config()

@app.post("/api/avatar")
async def upload_avatar(who: str = Form(...), image: UploadFile = File(...)):
    who = (who or "").strip().lower()
    if who not in ("manish", "lisa"):
        raise HTTPException(400, "who must be 'manish' or 'lisa'")
    data = await image.read()
    if not data:
        raise HTTPException(400, "Empty image")
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(413, f"Image > {MAX_AVATAR_BYTES // (1024*1024)} MB")
    ext = Path(image.filename or "").suffix.lower()
    if ext not in ALLOWED_AVATAR_EXTS:
        ext = ".png"
    out_path = UPLOADS_DIR / f"avatar_{who}{ext}"
    for old_ext in ALLOWED_AVATAR_EXTS:
        if old_ext == ext: continue
        old = UPLOADS_DIR / f"avatar_{who}{old_ext}"
        if old.exists():
            try: old.unlink()
            except Exception: pass
    out_path.write_bytes(data)
    url = f"/static/uploads/{out_path.name}?v={int(out_path.stat().st_mtime)}"
    cfg = _load_avatar_config()
    cfg[who] = url
    _save_avatar_config(cfg)
    return {"ok": True, "who": who, "url": url}

@app.delete("/api/avatar")
async def reset_avatar(who: str):
    who = (who or "").strip().lower()
    if who not in ("manish", "lisa"):
        raise HTTPException(400, "who must be 'manish' or 'lisa'")
    for ext in ALLOWED_AVATAR_EXTS:
        f = UPLOADS_DIR / f"avatar_{who}{ext}"
        if f.exists():
            try: f.unlink()
            except Exception: pass
    cfg = _load_avatar_config()
    cfg[who] = None
    _save_avatar_config(cfg)
    return {"ok": True, "who": who}


# ══════════════════════════════════════════════════════════════════════
#  NEW — DASHBOARD APIS
# ══════════════════════════════════════════════════════════════════════
@app.get("/api/dashboard/status")
async def dashboard_status():
    """One-shot aggregated snapshot for header cards."""
    agent = get_agent()
    usage = _llm_client._load_usage()
    providers = usage.get("providers", {})
    total_in  = sum(p.get("in", 0)       for p in providers.values())
    total_out = sum(p.get("out", 0)      for p in providers.values())
    total_req = sum(p.get("requests", 0) for p in providers.values())

    return {
        "agent": {
            "name":         AGENT_NAME,
            "user":         USER_NAME,
            "mode":         agent.get_mode(),
            "mood":         agent.get_mood(),
            "voice_mode":   agent.voice_mode,
            "turn_count":   agent.turn_count,
            "history_size": len(agent.conversation_history),
            "pending_wa":   agent.pending_whatsapp is not None,
        },
        "security":   auth.get_status(),
        "os_watcher": eye.get_status(),
        "tokens": {
            "date":      usage.get("date"),
            "requests":  total_req,
            "in":        total_in,
            "out":       total_out,
            "total":     total_in + total_out,
            "providers": providers,
        },
        "server_time": time.time(),
    }


@app.get("/api/dashboard/trace")
async def dashboard_trace(since: int = 0, limit: int = 200):
    """Polling fallback for the trace feed."""
    return {"events": tracer.snapshot(since_seq=since, limit=limit)}


@app.get("/api/dashboard/trace/stream")
async def dashboard_trace_stream(request: Request, since: int = 0):
    """Server-Sent Events live feed of trace events."""
    q = tracer.subscribe(maxsize=500)

    async def event_gen():
        # First, flush anything already in the buffer newer than `since`
        for ev in tracer.snapshot(since_seq=since, limit=200):
            yield f"data: {json.dumps(ev)}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = q.get_nowait()
                    yield f"data: {json.dumps(ev)}\n\n"
                except Exception:
                    # heartbeat every ~15s so proxies don't close idle streams
                    await asyncio.sleep(0.5)
                    yield ": keep-alive\n\n"
        finally:
            tracer.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── OS Watcher ────────────────────────────────────────────────────────
@app.get("/api/os_watcher")
async def os_watcher_status(limit: int = 20):
    return {
        "status":   eye.get_status(),
        "timeline": eye.get_timeline(limit=limit),
    }

@app.post("/api/os_watcher/start")
async def os_watcher_start():
    eye.start_stealth_mode()
    return {"ok": True, "status": eye.get_status()}

@app.post("/api/os_watcher/stop")
async def os_watcher_stop():
    report = eye.stop_and_report()
    return {"ok": True, "report": report, "status": eye.get_status()}


# ── Security ──────────────────────────────────────────────────────────
@app.get("/api/security")
async def security_status():
    return auth.get_status()

@app.post("/api/security/level")
async def security_set_level(req: SecurityLevelRequest):
    ok, msg = auth.set_level(req.level, password=req.password)
    if not ok:
        raise HTTPException(status_code=403, detail=msg)
    return {"ok": True, "message": msg, "status": auth.get_status()}

@app.post("/api/security/password")
async def security_change_password(req: PasswordChangeRequest):
    ok, msg = auth.change_password(req.old_password, req.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg, "status": auth.get_status()}


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
