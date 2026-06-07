"""
LISA — ElevenLabs API Key Rotation Manager
==========================================
Free tier = 10,000 credits/month per account. Manish ke paas multiple
free accounts hain — ye file un keys ko rotate karta hai so that effective
monthly budget = (num_keys × 10k) chars.

How it works
------------
1. `.env` mein keys comma-separated rakho:
       ELEVENLABS_API_KEYS=key1,key2,key3,...
2. Local JSON file (`data/elevenlabs_usage.json`) mein per-key usage track
   hota hai (chars consumed this month + last reset month).
3. Har TTS request se pehle `get_active_key()` call karta hai:
   - Current key ka usage threshold (default 9500) cross hua? → next key
   - Saare keys exhaust? → None return karega (caller fallback chooses)
4. Successful generation ke baad `record_usage(key, chars)` call.
5. API se 401 / quota error aaye to `mark_key_dead(key)` call → permanent
   skip till month-end reset.

Note: Ye usage local-tracked hai (approximate). Source-of-truth ElevenLabs
ka `/v1/user/subscription` endpoint hai — agar accuracy chahiye to
`refresh_quota_from_api()` periodically call kar sakte ho.
"""

from __future__ import annotations

import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────
_RAW_KEYS = os.getenv("ELEVENLABS_API_KEYS", "").strip()
# Back-compat: bhi support karega agar koi single key set kare
if not _RAW_KEYS:
    _RAW_KEYS = os.getenv("ELEVENLABS_API_KEY", "").strip()

API_KEYS: list[str] = [k.strip() for k in _RAW_KEYS.split(",") if k.strip()]

# Free tier ka actual cap 10000 hai — safety buffer 500 chars
USAGE_THRESHOLD = int(os.getenv("ELEVENLABS_USAGE_THRESHOLD", "9500"))
FREE_TIER_CAP   = int(os.getenv("ELEVENLABS_FREE_CAP",         "10000"))

USAGE_FILE = Path(__file__).parent.parent / "data" / "elevenlabs_usage.json"
USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


# ── Persistence ──────────────────────────────────────────────────────────
def _current_month() -> str:
    """e.g. '2026-05' — used to auto-reset counter when month changes."""
    return datetime.utcnow().strftime("%Y-%m")


def _load_usage() -> dict:
    if not USAGE_FILE.exists():
        return {"month": _current_month(), "keys": {}}
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        # Auto-reset agar naya month aa gaya
        if data.get("month") != _current_month():
            return {"month": _current_month(), "keys": {}}
        return data
    except Exception:
        return {"month": _current_month(), "keys": {}}


def _save_usage(data: dict) -> None:
    try:
        USAGE_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"  [ELKeys] could not save usage: {e}")


def _key_short(key: str) -> str:
    """Mask key for logging — sirf last 6 chars dikhao."""
    return f"...{key[-6:]}" if len(key) > 8 else "(short)"


# ── Public API ───────────────────────────────────────────────────────────
def keys_configured() -> bool:
    """Koi bhi key configured hai ya nahi."""
    return len(API_KEYS) > 0


def get_active_key() -> Optional[str]:
    """
    Pehla available key return karega (usage < threshold AND not dead).
    Koi available nahi to None.
    """
    if not API_KEYS:
        return None

    with _lock:
        data = _load_usage()
        keys_info = data["keys"]

        for k in API_KEYS:
            info = keys_info.get(k, {"used": 0, "dead": False})
            if info.get("dead"):
                continue
            if info.get("used", 0) >= USAGE_THRESHOLD:
                continue
            return k

        return None


def record_usage(key: str, chars: int) -> None:
    """TTS call ke baad ye call karo — chars billed update karega."""
    if not key or chars <= 0:
        return
    with _lock:
        data = _load_usage()
        info = data["keys"].setdefault(key, {"used": 0, "dead": False})
        info["used"] = int(info.get("used", 0)) + int(chars)
        info["last_used"] = int(time.time())
        data["keys"][key] = info
        _save_usage(data)


def mark_key_dead(key: str, reason: str = "") -> None:
    """API ne 401 / quota_exceeded diya — is key ko is month skip karo."""
    if not key:
        return
    with _lock:
        data = _load_usage()
        info = data["keys"].setdefault(key, {"used": 0, "dead": False})
        info["dead"] = True
        info["dead_reason"] = reason
        info["dead_at"] = int(time.time())
        data["keys"][key] = info
        _save_usage(data)
    print(f"  [ELKeys] marked {_key_short(key)} dead ({reason})")


def record_last_error(key: str, kind: str, message: str) -> None:
    """
    Soft error logger — used for things like 'detected_unusual_activity'
    (IP-block) where the key itself is fine but the request was refused.
    Lets the UI surface a clear message without marking the key dead.
    """
    if not key:
        return
    with _lock:
        data = _load_usage()
        data["last_error"] = {
            "key":      _key_short(key),
            "kind":     kind,
            "message":  (message or "")[:300],
            "at":       int(time.time()),
        }
        _save_usage(data)


def get_last_error() -> Optional[dict]:
    """Return the most recent soft error (or None). Used by /api/state."""
    if not USAGE_FILE.exists():
        return None
    try:
        data = _load_usage()
        return data.get("last_error")
    except Exception:
        return None


def clear_last_error() -> None:
    with _lock:
        data = _load_usage()
        if "last_error" in data:
            data.pop("last_error", None)
            _save_usage(data)


def get_status_dict() -> dict:
    """Structured status for the UI (sidebar token / TTS panel)."""
    if not API_KEYS:
        return {"configured": False, "keys": [], "last_error": None}
    data = _load_usage()
    keys = []
    for k in API_KEYS:
        info = data["keys"].get(k, {"used": 0, "dead": False})
        keys.append({
            "key":         _key_short(k),
            "used":        int(info.get("used", 0)),
            "limit":       int(info.get("limit", FREE_TIER_CAP)),
            "dead":        bool(info.get("dead", False)),
            "dead_reason": info.get("dead_reason", ""),
        })
    return {
        "configured": True,
        "month":      data.get("month"),
        "keys":       keys,
        "last_error": data.get("last_error"),
    }


def status_report() -> str:
    """Quick human-readable status for /api/state or debugging."""
    if not API_KEYS:
        return "no ElevenLabs keys configured"
    data = _load_usage()
    parts = [f"month={data['month']}"]
    for k in API_KEYS:
        info = data["keys"].get(k, {"used": 0, "dead": False})
        flag = "DEAD" if info.get("dead") else f"{info.get('used',0)}/{FREE_TIER_CAP}"
        parts.append(f"{_key_short(k)}:{flag}")
    return " | ".join(parts)


def refresh_quota_from_api() -> None:
    """
    Optional: ElevenLabs server se actual remaining quota le ke local
    counter sync karo. Use sparingly — har key per ek API call lagti hai.
    """
    if not API_KEYS:
        return
    try:
        import requests
    except ImportError:
        return

    with _lock:
        data = _load_usage()
        for k in API_KEYS:
            try:
                r = requests.get(
                    "https://api.elevenlabs.io/v1/user/subscription",
                    headers={"xi-api-key": k},
                    timeout=8,
                )
                if r.status_code == 200:
                    j = r.json()
                    used  = int(j.get("character_count", 0))
                    limit = int(j.get("character_limit", FREE_TIER_CAP))
                    info = data["keys"].setdefault(k, {"used": 0, "dead": False})
                    info["used"]   = used
                    info["limit"]  = limit
                    info["dead"]   = used >= limit
                    data["keys"][k] = info
                elif r.status_code in (401, 403):
                    info = data["keys"].setdefault(k, {"used": 0, "dead": False})
                    info["dead"] = True
                    info["dead_reason"] = f"http_{r.status_code}"
                    data["keys"][k] = info
            except Exception as e:
                print(f"  [ELKeys] refresh failed for {_key_short(k)}: {e}")
        _save_usage(data)
