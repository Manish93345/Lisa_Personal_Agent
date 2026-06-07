"""
LISA — Action Router (v3)
===========================
[FIX v3]
  - play_youtube ke liye query EMPTY hone par user_message se
    smart extraction hota hai (e.g., "koi purana hindi gaana baja do"
    → query="purana hindi gaana")
  - Devanagari input bhi handle hota hai (transliterate before extract)
"""

import re

from actions.intent_detector import detect_intent
from actions.system_actions  import (
    open_website, search_youtube, play_youtube,
    search_spotify, open_app, search_google,
    open_folder, open_file, system_command,
    smart_find_and_open,
)
from actions.whatsapp_actions import (
    whatsapp_send_message, whatsapp_send_file,
    whatsapp_check_unread, whatsapp_read_messages,
)
from actions.web_actions import web_search

MIN_CONFIDENCE = 0.75

ACTION_MAP = {
    "open_website"      : open_website,
    "play_youtube"      : play_youtube,
    "search_youtube"    : search_youtube,
    "search_spotify"    : search_spotify,
    "open_app"          : open_app,
    "search_google"     : search_google,
    "open_folder"       : open_folder,
    "open_file"         : open_file,
    "find_file"         : smart_find_and_open,
    "whatsapp_message"  : whatsapp_send_message,
    "whatsapp_file"     : whatsapp_send_file,
    "whatsapp_unread"   : whatsapp_check_unread,
    "whatsapp_read"     : whatsapp_read_messages,
    "web_search"        : web_search,
    "system_command"    : system_command,
}

SPECIAL_PARAM_ACTIONS = {
    "find_file", "whatsapp_message", "whatsapp_file",
    "whatsapp_unread", "whatsapp_read", "web_search",
    "play_youtube", "search_youtube",     # ← naye: query smart-extract karte hain
}


# ── Smart query extractor for YouTube ────────────────────────────────

def _romanize_inline(text: str) -> str:
    """Devanagari → Roman for query extraction."""
    if not re.search(r'[\u0900-\u097F]', text):
        return text
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate
        parts = re.split(r'([\u0900-\u097F]+)', text)
        out = []
        for p in parts:
            if not p:
                continue
            if re.search(r'[\u0900-\u097F]', p):
                roman = transliterate(p, sanscript.DEVANAGARI, sanscript.ITRANS).lower()
                roman = re.sub(r'\.([a-z])', r'\1', roman)
                roman = re.sub(r'~([a-z])', r'\1', roman)
                roman = roman.replace("aa", "a").replace("ii", "i").replace("uu", "u")
                out.append(roman)
            else:
                out.append(p)
        return "".join(out)
    except ImportError:
        return text


_STOPWORDS = {
    "koi", "kuch", "ek", "bhi", "aur", "to", "toh", "na", "pe", "pr", "par",
    "mein", "me", "ko", "se", "ka", "ki", "ke", "ya", "do", "de", "den",
    "dena", "denaa", "lo", "le", "kar", "karo", "karna", "yaar", "jaan",
    "please", "suno", "sunao", "lisa", "abhi", "thoda", "ek",
    "chala", "chalu", "laga", "play", "baja", "bajaao", "bajao", "chalao",
    "youtube", "yt", "spotify",
}


def _extract_play_query(user_message: str) -> str:
    """
    Extract the actual song/genre hint from a play command.

    "koi purana hindi gaana baja do" → "purana hindi gaana"
    "YouTube pe shreya ghoshal ka song chala do" → "shreya ghoshal song"
    "kuch romantic music sunao" → "romantic music"
    Empty / ambiguous → "latest bollywood songs"
    """
    text = _romanize_inline(user_message).lower()
    # Remove punctuation
    text = re.sub(r'[^\w\s]', ' ', text)
    tokens = [t for t in text.split() if t and t not in _STOPWORDS]
    # Keep only nouns/adjectives (everything except stopwords)
    query = " ".join(tokens).strip()

    if not query or len(query) < 3:
        return "latest bollywood songs"
    # Cap length
    return query[:80]


# ── Main router ──────────────────────────────────────────────────────

def route_action(user_message: str, context=None) -> tuple[bool, str] | None:
    intent     = detect_intent(user_message)
    action     = intent.get("action", "none")
    params     = intent.get("params", {})
    confidence = intent.get("confidence", 0.0)

    if action == "none" or confidence < MIN_CONFIDENCE:
        return None

    action_fn = ACTION_MAP.get(action)
    if not action_fn:
        return None

    # ── Special param handling ─────────────────────────────────────
    if action in SPECIAL_PARAM_ACTIONS:
        try:
            if action == "find_file":
                return action_fn(
                    query          = user_message,
                    folder         = params.get("folder", ""),
                    file           = params.get("file", ""),
                    on_main_screen = params.get("main_screen", False),
                )

            elif action == "whatsapp_message":
                return action_fn(
                    contact = params.get("contact", ""),
                    query   = user_message,
                    message = params.get("message", ""),
                    context = context,
                )

            elif action == "whatsapp_file":
                return action_fn(
                    contact = params.get("contact", ""),
                    folder  = params.get("folder", ""),
                    file    = params.get("file", ""),
                    query   = user_message,
                    context = context,
                )

            elif action == "whatsapp_unread":
                return action_fn(query=user_message)

            elif action == "whatsapp_read":
                return action_fn(
                    contact = params.get("contact", ""),
                    query   = user_message,
                )

            elif action == "web_search":
                return action_fn(
                    query       = params.get("query", user_message),
                    search_type = params.get("type", "search"),
                    city        = params.get("city", ""),
                )

            elif action in ("play_youtube", "search_youtube"):
                # ← NEW: smart query extraction if intent gave empty/missing
                q = params.get("query", "").strip()
                if not q:
                    q = _extract_play_query(user_message)
                print(f"  [YT] resolved query: '{q}'")
                return action_fn(q)

        except Exception as e:
            print(f"[Router] Error: {e}")
            return False, "action complete nahi hua"

    # ── Default single-arg action ──
    query = params.get("query", user_message)
    try:
        return action_fn(query)
    except Exception as e:
        print(f"[Router] Error: {e}")
        return False, "action complete nahi hua"
