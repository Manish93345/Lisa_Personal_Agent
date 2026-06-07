"""
LISA — Speech to Text (Groq Whisper)
=====================================
[FIX v3]
  1. language="hi" force kiya — Whisper ab Gujarati/Urdu script mein
     transcribe nahi karega. Devanagari ya Roman Hindi hi aayega.
  2. Stronger Hinglish prompt — common voice commands include kiye
     (gaana, baja, chala, youtube, whatsapp, etc.) taaki Whisper context samjhe.
  3. Post-process safety net — agar Whisper galti se Gujarati script bhej de
     (ya koi aur Indic script jo Hindi nahi hai), use Devanagari mein
     transliterate kar deta hai indic-transliteration se.
  4. Romanization output mode — set STT_OUTPUT_SCRIPT=roman in .env to get
     Roman Hinglish output (better for regex intent detection).

Requirements:
    pip install indic-transliteration
"""

import os
import re
import wave
import numpy as np
import sounddevice as sd
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
from config.settings import BASE_DIR, GROQ_API_KEY

# ── Recording config ──────────────────────────────────────────────────
SAMPLE_RATE    = 16000
SILENCE_THRESH = 0.015
SILENCE_SECS   = 2.0
TEMP_WAV       = str(BASE_DIR / "temp_audio.wav")

# ── STT config ────────────────────────────────────────────────────────
# "roman" = romanize Devanagari → Roman Hinglish (better for regex intent matching)
# "deva"  = keep Devanagari (looks pretty but breaks regex)
# "auto"  = whatever Whisper returns (NOT recommended — can be Gujarati/Urdu)
STT_OUTPUT_SCRIPT = os.getenv("STT_OUTPUT_SCRIPT", "roman").lower()

# ── Stronger Hinglish prompt — includes common voice-command words ────
# This tells Whisper the EXPECTED vocabulary so it doesn't drift to Gujarati/Urdu.
HINGLISH_PROMPT = (
    "haan yaar main theek hoon, tum kaisi ho. "
    "Lisa jaan suno na, YouTube pe ek purana hindi gaana baja do, "
    "kuch bhi achha sa chala do, music laga do, song play karo. "
    "WhatsApp pe message bhejo, kisi ne message bheja kya, "
    "naya msg check karo, didi ne kya bola, reply karo. "
    "D drive mein file dhundo, folder kholo, resume khol do, "
    "screenshot lo, volume badhao, volume kam karo, mute karo. "
    "weather batao, mausam kaisa hai, news headlines do, "
    "kya khabar hai. Theek hai jaan, ok done, bye Lisa."
)

# Devanagari/Hindi unicode block
_DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]')
# Other Indic scripts that Whisper sometimes hallucinates for Hindi audio
_GUJARATI_RE   = re.compile(r'[\u0A80-\u0AFF]')   # ગુજરાતી
_BENGALI_RE    = re.compile(r'[\u0980-\u09FF]')   # বাংলা
_ARABIC_RE     = re.compile(r'[\u0600-\u06FF]')   # Urdu / Arabic
_TAMIL_RE      = re.compile(r'[\u0B80-\u0BFF]')
_TELUGU_RE     = re.compile(r'[\u0C00-\u0C7F]')

_WRONG_SCRIPT_REGEXES = [
    (_GUJARATI_RE, "gujarati"),
    (_BENGALI_RE,  "bengali"),
    (_ARABIC_RE,   "arabic"),
    (_TAMIL_RE,    "tamil"),
    (_TELUGU_RE,   "telugu"),
]


# ── Audio recording ──────────────────────────────────────────────────

def _record_audio(max_seconds=30):
    print("  [Listening...] Bolo na jaan...")
    chunks, silence_count = [], 0
    chunk_size = int(SAMPLE_RATE * 0.1)
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32') as stream:
        for _ in range(int(max_seconds * 10)):
            chunk, _ = stream.read(chunk_size)
            chunks.append(chunk.copy())
            volume = float(np.sqrt(np.mean(chunk ** 2)))
            silence_count = silence_count + 1 if volume < SILENCE_THRESH else 0
            if silence_count >= int(SILENCE_SECS * 10):
                break
    return np.concatenate(chunks, axis=0).flatten()


def _save_wav(audio):
    audio_int16 = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(TEMP_WAV, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())


# ── Script repair helpers ────────────────────────────────────────────

def _detect_wrong_script(text: str) -> str | None:
    """Return name of wrong script if found, else None."""
    for regex, name in _WRONG_SCRIPT_REGEXES:
        if regex.search(text):
            return name
    return None


def _to_devanagari(text: str, source_script: str) -> str:
    """
    Convert text written in a wrong Indic script (gujarati/bengali/etc)
    INTO Devanagari, because the user actually spoke Hindi.

    indic-transliteration's sanscript handles all major Indic scripts.
    """
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate

        script_map = {
            "gujarati": sanscript.GUJARATI,
            "bengali":  sanscript.BENGALI,
            "tamil":    sanscript.TAMIL,
            "telugu":   sanscript.TELUGU,
        }
        src = script_map.get(source_script)
        if src:
            return transliterate(text, src, sanscript.DEVANAGARI)
    except ImportError:
        pass
    return text


def _devanagari_to_roman(text: str) -> str:
    """Convert Devanagari Hindi → Roman Hinglish using ITRANS scheme."""
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate

        parts = re.split(r'([\u0900-\u097F]+)', text)
        out = []
        for p in parts:
            if not p:
                continue
            if _DEVANAGARI_RE.search(p):
                # Devanagari segment → Roman (HK is most readable, no diacritics)
                roman = transliterate(p, sanscript.DEVANAGARI, sanscript.ITRANS)
                # Clean up ITRANS artifacts → more natural Hinglish
                roman = roman.lower()
                roman = roman.replace(".n", "n").replace(".m", "m")
                roman = re.sub(r'~([a-z])', r'\1', roman)
                roman = re.sub(r'\.([a-z])', r'\1', roman)
                roman = roman.replace("RR", "r").replace("LL", "l")
                roman = roman.replace("aa", "a").replace("ii", "i").replace("uu", "u")
                out.append(roman)
            else:
                out.append(p)
        return "".join(out)
    except ImportError:
        return text


def _normalize_output(text: str) -> str:
    """
    Three-stage clean-up:
      1. Detect & repair wrong Indic script → Devanagari
      2. (Optionally) Convert Devanagari → Roman Hinglish
      3. Strip stray punctuation / collapse whitespace
    """
    if not text:
        return text

    # ── Stage 1: wrong script → Devanagari ──
    wrong = _detect_wrong_script(text)
    if wrong:
        print(f"  [STT] ⚠ Whisper returned {wrong} script — repairing to Devanagari")
        text = _to_devanagari(text, wrong)

    # ── Stage 2: choose final script ──
    if STT_OUTPUT_SCRIPT == "roman" and _DEVANAGARI_RE.search(text):
        text = _devanagari_to_roman(text)

    # ── Stage 3: whitespace ──
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── Main entry ───────────────────────────────────────────────────────

def listen_once(max_seconds=30):
    try:
        audio = _record_audio(max_seconds)
        if len(audio) < SAMPLE_RATE * 0.5:
            return ""
        print("  [STT] Processing...")
        _save_wav(audio)
        if not os.path.exists(TEMP_WAV):
            return ""

        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        with open(TEMP_WAV, "rb") as f:
            # ── KEY FIX: language="hi" forces Hindi recognition ──
            # Without this, Whisper sometimes flips to Gujarati / Urdu / Bengali
            # because Hinglish audio has overlapping phonemes.
            result = client.audio.transcriptions.create(
                file            = f,
                model           = "whisper-large-v3-turbo",
                prompt          = HINGLISH_PROMPT,
                response_format = "text",
                temperature     = 0.0,
                language        = "hi",      # ← critical fix
            )

        raw = result.strip() if isinstance(result, str) else result.text.strip()
        text = _normalize_output(raw)

        if text:
            print(f"  [Heard] {text}")
        return text

    except KeyboardInterrupt:
        return "quit"
    except Exception as e:
        print(f"  [STT] Error: {e}")
        return ""
