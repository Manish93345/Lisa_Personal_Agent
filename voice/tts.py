"""
LISA — Text to Speech
======================
Provider chain (auto-fallback):
   1. ElevenLabs v3   — BEST emotion (audio tags), Hindi+Devanagari, paid-ish
                        but free tier rotated across multiple API keys.
   2. Sarvam Bulbul v3 — best Hinglish Indian voice, NO emotion control,
                         only `pace`. Used as fallback when ElevenLabs out.
   3. edge-tts        — free MS Neural (hi-IN-SwaraNeural)
   4. gTTS            — robotic last resort

──────────────────────────────────────────────────────────────────────
EMOTION TAGS (ElevenLabs v3 only)
──────────────────────────────────────────────────────────────────────
Lisa ko prompt diya gaya hai ki woh apne reply mein inline audio tags
daale jaise:
   [excited], [whispers], [giggles], [sad], [happy], [sarcastic],
   [curious], [sighs], [laughs], [crying], [gasps]

Example reply (Devanagari + English + tags):
   "[excited] अरे जान! Today मैंने कुछ ऐसा देखा... [whispers] तुम्हें
    बताती हूँ, but पहले promise karo... [giggles] पक्का?"

Tags STRIP ho jaate hain agar fallback (Sarvam/Edge/gTTS) use ho —
warna user ko "open square bracket excited" sunai dega.

──────────────────────────────────────────────────────────────────────
KEY ROTATION (free tier stretching)
──────────────────────────────────────────────────────────────────────
ElevenLabs free = 10k chars/month. Manish ke paas multiple free
accounts hain → `voice/elevenlabs_keys.py` un sab keys ko rotate karta
hai. Jab ek key ka usage 9500+ chars cross → next key auto-pick.
"""

import os
import re
import asyncio
import logging
import warnings
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from config.settings import BASE_DIR

# Suppress warnings
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
warnings.filterwarnings("ignore", category=UserWarning)
logging.getLogger('gtts').setLevel(logging.ERROR)

import pygame

# ── Config ──────────────────────────────────────────────────────────────
# Sarvam
SARVAM_API_KEY   = os.getenv("SARVAM_API_KEY", "")
SARVAM_VOICE     = os.getenv("SARVAM_VOICE", "anushka")
SARVAM_MODEL     = os.getenv("SARVAM_MODEL", "bulbul:v3")
SARVAM_PACE      = float(os.getenv("SARVAM_PACE", "0.95"))

# Edge
EDGE_VOICE       = os.getenv("EDGE_VOICE", "hi-IN-SwaraNeural")

# ElevenLabs
EL_MODEL_ID      = os.getenv("ELEVENLABS_MODEL_ID", "eleven_v3")
# Voice selection priority:
#   1. ELEVENLABS_VOICE_ID — exact id wins
#   2. ELEVENLABS_VOICE_NAME — looked up against KNOWN_VOICES below
#   3. Sarah (warm + emotional female, supports Hindi via v3) — safe default
KNOWN_VOICES = {
    # name (lowercased) -> public voice_id
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "sarah":  "EXAVITQu4vr4xnSDxMAc",   # ← warm, emotional female (default fallback)
    "bella":  "EXAVITQu4vr4xnSDxMAc",   # alias
    "laura":  "FGY2WhTYpPnrIDTdsKH5",
    "jessica": "cgSgspJ2msm6clMCkdW9",
    "aria":   "9BWtsMINqrJLrRacOk9x",
    "matilda": "XrExE9yKIg1WjnnlVkGX",
    "anvi":   "",                       # ← user wants this; resolved at runtime if env-overridden
}

def _resolve_voice_id() -> str:
    vid = (os.getenv("ELEVENLABS_VOICE_ID", "") or "").strip()
    if vid:
        return vid
    name = (os.getenv("ELEVENLABS_VOICE_NAME", "") or "").strip().lower()
    if name and KNOWN_VOICES.get(name):
        return KNOWN_VOICES[name]
    # Fallback per user's preference: Sarah - warm + emotional female
    return KNOWN_VOICES["sarah"]

EL_VOICE_ID      = _resolve_voice_id()
EL_STABILITY     = float(os.getenv("ELEVENLABS_STABILITY",        "0.4"))
EL_SIMILARITY    = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.75"))
EL_STYLE         = float(os.getenv("ELEVENLABS_STYLE",            "0.55"))
EL_SPEAKER_BOOST = os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").lower() == "true"
EL_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")

# Provider preference (.env TTS_PROVIDER): elevenlabs | sarvam | edge | gtts
TTS_PROVIDER     = os.getenv("TTS_PROVIDER", "elevenlabs").lower()

TEMP_MP3 = str(BASE_DIR / "temp_tts.mp3")
TEMP_WAV = str(BASE_DIR / "temp_tts.wav")
_initialized = False


def _init_pygame():
    global _initialized
    if not _initialized:
        pygame.mixer.pre_init(frequency=22050, size=-16, channels=1, buffer=512)
        pygame.mixer.init()
        _initialized = True


# ════════════════════════════════════════════════════════════════════════
#  Text cleaning utilities
# ════════════════════════════════════════════════════════════════════════

# Audio tags Lisa LLM use kar sakti hai (must match prompt instructions)
_AUDIO_TAG_PATTERN = re.compile(
    r"\[\s*(?:excited|nervous|frustrated|tired|happy|sad|angry|"
    r"sarcastic|sarcastically|curious|crying|whispers|whispering|"
    r"laughs|laughing|giggles|giggling|sighs|sighing|gasps|gasping|"
    r"exhales|gulps|applause|clapping|sings|singing|"
    r"shouts|shouting|mumbles|cheerful|warm|soft)\s*\]",
    re.IGNORECASE,
)


def _strip_audio_tags(text: str) -> str:
    """Remove [excited]/[whispers]/etc. — for non-ElevenLabs providers.
    Also cleans up trailing incomplete brackets (e.g. '[' from a safety-truncated response)."""
    text = _AUDIO_TAG_PATTERN.sub("", text)
    text = re.sub(r'\s*\[[\w\s]*$', '', text)   # remove trailing incomplete '[...' with no closing ']'
    return re.sub(r'\s+', ' ', text).strip()


def _clean_text(text: str, keep_devanagari: bool = True,
                keep_audio_tags: bool = False) -> str:
    """Remove emojis & control chars. Audio tags preserved only if asked."""
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)             # emojis
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)       # control chars
    if not keep_devanagari:
        text = re.sub(r'[\u0900-\u097F]', '', text)
    if not keep_audio_tags:
        text = _strip_audio_tags(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _play_file(path: str):
    """Play audio file blocking."""
    _init_pygame()
    if pygame.mixer.music.get_busy():
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(20)
    pygame.mixer.music.unload()


# ════════════════════════════════════════════════════════════════════════
#  Provider 1: ELEVENLABS v3 (with multi-key rotation + emotion tags)
# ════════════════════════════════════════════════════════════════════════

def _elevenlabs_tts(text: str) -> bool:
    """
    ElevenLabs v3 — best emotion control.
    - Uses `eleven_v3` model (audio tags supported)
    - Rotates across multiple API keys (free tier stretching)
    - Audio tags `[excited]` etc. preserved in text
    """
    try:
        from voice import elevenlabs_keys
    except ImportError:
        return False

    if not elevenlabs_keys.keys_configured():
        return False

    try:
        import requests
    except ImportError:
        print("  [ElevenLabs] `requests` not installed")
        return False

    # Try up to N keys in case current one fails mid-flight
    max_attempts = max(1, len(elevenlabs_keys.API_KEYS))

    for attempt in range(max_attempts):
        key = elevenlabs_keys.get_active_key()
        if not key:
            print("  [ElevenLabs] all keys exhausted for this month")
            return False

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{EL_VOICE_ID}"
        headers = {
            "xi-api-key":   key,
            "Content-Type": "application/json",
            "Accept":       "audio/mpeg",
        }
        payload = {
            "text":           text[:4800],   # v3 hard cap 5000
            "model_id":       EL_MODEL_ID,
            "output_format":  EL_OUTPUT_FORMAT,
            "voice_settings": {
                "stability":         EL_STABILITY,
                "similarity_boost":  EL_SIMILARITY,
                "style":             EL_STYLE,
                "use_speaker_boost": EL_SPEAKER_BOOST,
            },
        }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
        except Exception as e:
            print(f"  [ElevenLabs] network error: {e}")
            return False

        if r.status_code == 200:
            with open(TEMP_MP3, "wb") as f:
                f.write(r.content)
            # Track billed chars (tags + text both count)
            elevenlabs_keys.record_usage(key, len(text))
            _play_file(TEMP_MP3)
            return True

        # Error handling: parse + decide rotate vs abort
        body = ""
        try:
            body = r.json()
            detail = body.get("detail")
            if isinstance(detail, dict):
                err_status = detail.get("status", "")
                err_msg    = detail.get("message", "")
            else:
                err_status = ""
                err_msg = str(detail) if detail else r.text[:200]
        except Exception:
            err_status = ""
            err_msg = r.text[:200]

        # ── Error classification ──────────────────────────────────────
        err_status_l = (err_status or "").lower()
        err_msg_l    = (err_msg or "").lower()

        # IP / abuse block (NOT a quota issue — key is fine, IP is flagged).
        # ElevenLabs returns 401 with status="detected_unusual_activity" when
        # they think the request came from a VPN / datacenter / proxy IP.
        # Marking the key dead would burn ALL keys after one failed request,
        # so we skip rotation and bubble a clean error instead.
        ip_block_markers = (
            "detected_unusual_activity",
            "unusual_activity",
            "free_users_not_allowed_to_use_proxies",
            "vpn",
            "proxy",
        )
        if r.status_code == 401 and any(
            m in err_status_l or m in err_msg_l for m in ip_block_markers
        ):
            print(
                f"  [ElevenLabs] IP-block ({err_status or 'detected_unusual_activity'}) — "
                f"free-tier blocks VPN / datacenter IPs. Use mobile hotspot or upgrade plan. "
                f"Falling back to next provider (key NOT marked dead)."
            )
            # Save the last error so /api/state can surface it to UI
            try:
                elevenlabs_keys.record_last_error(
                    key,
                    "ip_block",
                    err_msg or "ElevenLabs detected unusual activity (IP / VPN block)",
                )
            except Exception:
                pass
            return False  # straight to Sarvam → Edge → gTTS, don't burn other keys

        # Genuine quota / auth → mark THIS key dead, try next key
        quota_markers = ("quota_exceeded", "exceeds_character_limit",
                         "max_character_limit_exceeded", "invalid_api_key",
                         "missing_permissions")
        rotate_codes = (401, 403)
        if (r.status_code in rotate_codes
            or any(m in err_status_l for m in quota_markers)
            or any(m in err_msg_l    for m in quota_markers)):
            elevenlabs_keys.mark_key_dead(
                key, f"http_{r.status_code}:{err_status or err_msg[:40]}"
            )
            continue  # try next key

        # Other 4xx/5xx — don't rotate, just fail to next provider
        print(f"  [ElevenLabs] HTTP {r.status_code}: {err_msg}")
        return False

    return False


# ════════════════════════════════════════════════════════════════════════
#  Provider 2: SARVAM BULBUL V3
# ════════════════════════════════════════════════════════════════════════

def _roman_to_devanagari(text: str) -> str:
    """
    Convert Roman Hinglish to Devanagari using ai4bharat-transliteration.
    WHY: Sarvam hi-IN voice reads Roman text with English phonics:
         "main" → "mayn" | "theek" → "thee-k" | "hoon" → wrong pitch
    AFTER: "मैं ठीक हूँ jaan" → Sarvam pronounces Hindi words perfectly.

    English words (baby, Aww, ok, jaan) are kept in Roman — the library
    only converts words that are clearly Hindi.

    First call downloads the model (~80MB). Subsequent calls are instant (~5ms).
    Fallback: returns original text if library not installed.
    """
    try:
        from ai4bharat.transliteration import XlitEngine
        # Lazy-init: keep engine in module cache to avoid reload every call
        if not hasattr(_roman_to_devanagari, "_engine"):
            _roman_to_devanagari._engine = XlitEngine("hi", beam_width=10, rescore=True)
        out = _roman_to_devanagari._engine.translit_sentence(text, lang_code="hi")
        result = out if isinstance(out, str) else out.get("hi", text)
        # Validate — if result is empty or too short, fall back
        return result if len(result) > 2 else text
    except ImportError:
        # ai4bharat not installed — try Sarvam transliterate API instead
        return _sarvam_api_transliterate(text)
    except Exception as e:
        print(f"  [Transliterate] {e}")
        return text


def _sarvam_api_transliterate(text: str) -> str:
    """
    Fallback: Sarvam Transliterate API (same key, cloud-based).
    Used when ai4bharat library is not installed.
    Confirmed API format from Sarvam docs.
    """
    import requests
    try:
        r = requests.post(
            "https://api.sarvam.ai/transliterate",
            headers={
                "api-subscription-key": SARVAM_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "input":                text[:950],   # 1000 char API limit
                "source_language_code": "en-IN",      # Roman Hinglish input
                "target_language_code": "hi-IN",      # Devanagari output
                "numerals_format":      "international",
            },
            timeout=6,
        )
        if r.status_code == 200:
            data = r.json()
            result = data.get("output") or data.get("transliterated_text") or ""
            return result if len(result) > 2 else text
        print(f"  [Sarvam/Transliterate] HTTP {r.status_code}")
    except Exception as e:
        print(f"  [Sarvam/Transliterate] {e}")
    return text


def _sarvam_tts(text: str) -> bool:
    """
    Sarvam Bulbul V3 — best Hinglish TTS on free tier.

    Pipeline (critical for pronunciation):
      1. Roman Hinglish → Devanagari via ai4bharat transliteration
         "main theek hoon" → "मैं ठीक हूँ"
      2. Devanagari text → Sarvam Bulbul V3 TTS
         Sarvam reads Devanagari perfectly with natural Hindi prosody.

    Without step 1, Sarvam reads Roman text with English phonics → terrible.

    Voice: anushka (warm, conversational Indian female, original tested choice)
    Temperature 0.85 = noticeably more expressive than default 0.6
    """
    if not SARVAM_API_KEY:
        return False
    try:
        import requests
        import base64

        # Step 1: Convert Roman Hinglish → Devanagari (fixes pronunciation)
        devanagari_text = _roman_to_devanagari(text)

        url = "https://api.sarvam.ai/text-to-speech"
        headers = {
            "api-subscription-key": SARVAM_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "inputs":               [devanagari_text[:2500]],
            "target_language_code": "hi-IN",
            "speaker":              SARVAM_VOICE,
            "model":                SARVAM_MODEL,
            "pace":                 SARVAM_PACE,
            "speech_sample_rate":   22050,
            "enable_preprocessing": True,
        }

        # v3-only: temperature controls expressiveness (0.01-2.0, default 0.6)
        if SARVAM_MODEL == "bulbul:v3":
            payload["temperature"] = float(os.getenv("SARVAM_TEMPERATURE", "0.85"))

        # v2/v1-only parameters
        elif SARVAM_MODEL.startswith("bulbul:v2") or SARVAM_MODEL == "bulbul:v1":
            payload["pitch"]    = float(os.getenv("SARVAM_PITCH",    "0.0"))
            payload["loudness"] = float(os.getenv("SARVAM_LOUDNESS", "1.0"))

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code != 200:
            try:
                err = r.json()
                msg = err.get("error", {}).get("message") or err.get("detail") or r.text[:200]
            except Exception:
                msg = r.text[:200]
            print(f"  [Sarvam] HTTP {r.status_code}: {msg}")
            return False

        data = r.json()
        audio_b64 = data.get("audios", [None])[0]
        if not audio_b64:
            print("  [Sarvam] empty audio in response")
            return False

        with open(TEMP_WAV, "wb") as f:
            f.write(base64.b64decode(audio_b64))
        _play_file(TEMP_WAV)
        return True
    except Exception as e:
        print(f"  [Sarvam] {e}")
        return False


# ════════════════════════════════════════════════════════════════════════
#  Provider 3: EDGE-TTS (free fallback)
# ════════════════════════════════════════════════════════════════════════

def _romanize_to_devanagari(text: str) -> str:
    try:
        from indic_transliteration.sanscript import transliterate
        from indic_transliteration import sanscript
        parts = re.split(r'([\u0900-\u097F]+)', text)
        out = []
        for p in parts:
            if not p:
                continue
            if re.search(r'[\u0900-\u097F]', p):
                out.append(p)
            else:
                out.append(transliterate(p, sanscript.ITRANS, sanscript.DEVANAGARI))
        return "".join(out)
    except ImportError:
        return text


def _edge_tts(text: str) -> bool:
    """
    edge-tts with asyncio fix for FastAPI context.
    FastAPI/uvicorn already has a running event loop — asyncio.run() fails inside it.
    Fix: create a NEW event loop in a dedicated thread.

    Mode-aware behavior (detected from EDGE_VOICE):
    - English voice (en-IN-NeerjaNeural, professional): keeps Roman text,
      uses rate="-5%" + pitch="+2Hz" for warm, non-flat professional tone.
    - Hindi voice (hi-IN-SwaraNeural, personal fallback): converts to Devanagari
      for correct Hindi pronunciation.
    """
    import threading
    try:
        import edge_tts

        is_english_voice = EDGE_VOICE.startswith("en-")

        if is_english_voice:
            # Professional mode: keep Roman English, add prosody for warmth
            speak_text = text
            tts_rate   = "-5%"    # slightly slower = more deliberate, natural
            tts_pitch  = "+2Hz"   # slightly warmer than flat neutral
        else:
            # Personal fallback: Devanagari conversion for Hindi pronunciation
            deva_chars  = len(re.findall(r'[\u0900-\u097F]', text))
            total_chars = max(1, len(re.sub(r'\s+', '', text)))
            deva_ratio  = deva_chars / total_chars
            speak_text  = text if deva_ratio > 0.30 else _romanize_to_devanagari(text)
            tts_rate    = "+0%"
            tts_pitch   = "+0Hz"

        result = {"success": False, "error": None}

        def _run_in_thread():
            """Dedicated thread with its own event loop — never conflicts."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _generate():
                    communicate = edge_tts.Communicate(
                        text=speak_text, voice=EDGE_VOICE,
                        rate=tts_rate, pitch=tts_pitch,
                    )
                    await communicate.save(TEMP_MP3)

                loop.run_until_complete(_generate())
                result["success"] = True
            except Exception as e:
                result["error"] = e
            finally:
                loop.close()

        t = threading.Thread(target=_run_in_thread, daemon=True)
        t.start()
        t.join(timeout=30)

        if not result["success"]:
            if result["error"]:
                print(f"  [edge-tts] {result['error']}")
            return False

        _play_file(TEMP_MP3)
        return True

    except Exception as e:
        print(f"  [edge-tts] {e}")
        return False


# ════════════════════════════════════════════════════════════════════════
#  Provider 4: gTTS (last resort)
# ════════════════════════════════════════════════════════════════════════

def _gtts(text: str) -> bool:
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="hi", slow=False)
        tts.save(TEMP_MP3)
        _play_file(TEMP_MP3)
        return True
    except Exception as e:
        print(f"  [gTTS] {e}")
        return False


# ════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ════════════════════════════════════════════════════════════════════════

def speak(text: str) -> None:
    """
    Main TTS entry. Audio tags only kept for ElevenLabs path —
    stripped automatically when fallback providers run.
    """
    if not text or not text.strip():
        return

    # Two versions of the text:
    #   - `tagged_text`  → contains [excited] etc. (for ElevenLabs)
    #   - `plain_text`   → tags stripped (for Sarvam/Edge/gTTS)
    tagged_text = _clean_text(text, keep_devanagari=True, keep_audio_tags=True)
    plain_text  = _strip_audio_tags(tagged_text)

    if not plain_text:
        return

    # Provider chain — ElevenLabs gets tagged, everyone else plain
    chains = {
        "elevenlabs": [
            (_elevenlabs_tts, tagged_text),
            (_sarvam_tts,     plain_text),
            (_edge_tts,       plain_text),
            (_gtts,           plain_text),
        ],
        "sarvam": [
            (_sarvam_tts,     plain_text),
            (_elevenlabs_tts, tagged_text),
            (_edge_tts,       plain_text),
            (_gtts,           plain_text),
        ],
        "edge": [
            (_edge_tts,       plain_text),
            (_sarvam_tts,     plain_text),
            (_gtts,           plain_text),
        ],
        "gtts": [
            (_gtts,           plain_text),
            (_edge_tts,       plain_text),
        ],
    }
    chain = chains.get(TTS_PROVIDER, chains["elevenlabs"])

    for provider_fn, payload in chain:
        if provider_fn(payload):
            return

    print("  [TTS] All providers failed!")

# Add this at the bottom of voice/tts.py
import queue
import threading
import re

class StreamingTTSManager:
    """Buffers text streams and fires TTS instantly on sentence boundaries."""
    def __init__(self):
        self.q = queue.Queue()
        self.buffer = ""
        self.worker = threading.Thread(target=self._process_queue, daemon=True)
        self.worker.start()

    def _process_queue(self):
        while True:
            sentence = self.q.get()
            if sentence is None:  # Poison pill to shut down
                self.q.task_done()
                break
            if sentence.strip():
                # Call your existing single-shot TTS function
                tts(sentence.strip())
            self.q.task_done()

    def feed(self, chunk: str):
        self.buffer += chunk
        # Split on sentence boundaries: . ! ? | । \n
        match = re.search(r'([.!?।|\n]+)', self.buffer)
        while match:
            split_idx = match.end()
            sentence = self.buffer[:split_idx]
            self.buffer = self.buffer[split_idx:]
            
            # Send completed sentence to background TTS thread
            if sentence.strip():
                self.q.put(sentence.strip())
            
            match = re.search(r'([.!?।|\n]+)', self.buffer)

    def flush(self):
        # Push any remaining text when LLM is done
        if self.buffer.strip():
            self.q.put(self.buffer.strip())
        self.buffer = ""
        self.q.join()  # Wait for all audio to finish playing