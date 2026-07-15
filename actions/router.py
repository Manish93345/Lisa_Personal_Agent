"""
LISA — Action Router (v4 - Task Chaining Engine)
================================================
[FIX v4]
  - Multi-Intent Support: route_action ab ek list of intents accept
    karta hai aur unhe sequentially execute karta hai.
  - Aggregation: Multiple actions ke results combine karke agent.py
    ko return karta hai.
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
    "play_youtube", "search_youtube",
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
    text = _romanize_inline(user_message).lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    tokens = [t for t in text.split() if t and t not in _STOPWORDS]
    query = " ".join(tokens).strip()

    if not query or len(query) < 3:
        return "latest bollywood songs"
    return query[:80]


# ── Main router (Task Chaining Engine) ───────────────────────────────

def route_action(user_message: str, context=None) -> tuple[bool, str] | None:
    intents = detect_intent(user_message)
    
    # Backward compatibility: agar dict return hua toh list mein wrap karo
    if isinstance(intents, dict):
        intents = [intents]
        
    valid_intents = [
        i for i in intents 
        if i.get("action", "none") != "none" and i.get("confidence", 0.0) >= MIN_CONFIDENCE
    ]
    
    if not valid_intents:
        return None
        
    overall_success = True
    regular_results = []
    special_result = None
    
    # Execute all valid actions sequentially
    for intent in valid_intents:
        action = intent.get("action")
        params = intent.get("params", {})
        action_fn = ACTION_MAP.get(action)
        
        if not action_fn:
            continue
            
        print(f"[Router] Executing chained action: {action}")
        
        try:
            # ── Special param handling ──
            if action in SPECIAL_PARAM_ACTIONS:
                if action == "find_file":
                    success, msg = action_fn(
                        query          = user_message,
                        folder         = params.get("folder", ""),
                        file           = params.get("file", ""),
                        on_main_screen = params.get("main_screen", False),
                    )
                elif action == "whatsapp_message":
                    success, msg = action_fn(
                        contact = params.get("contact", ""),
                        query   = user_message,
                        message = params.get("message", ""),
                        context = context,
                    )
                elif action == "whatsapp_file":
                    success, msg = action_fn(
                        contact = params.get("contact", ""),
                        folder  = params.get("folder", ""),
                        file    = params.get("file", ""),
                        query   = user_message,
                        context = context,
                    )
                elif action == "whatsapp_unread":
                    success, msg = action_fn(query=user_message)
                elif action == "whatsapp_read":
                    success, msg = action_fn(
                        contact = params.get("contact", ""),
                        query   = user_message,
                    )
                elif action == "web_search":
                    success, msg = action_fn(
                        query       = params.get("query", user_message),
                        search_type = params.get("type", "search"),
                        city        = params.get("city", ""),
                    )

                # === FILE SEARCH ACTION ===
                elif action == "find_file":
                    # Intent detector ne jo file ka naam pakda hai
                    file_query = params.get("file", "")
                    if not file_query:
                        return False, "File ka naam nahi bataya."
                        
                    from actions.file_actions import search_local_file
                    return search_local_file(file_query)
                    
                    
                elif action in ("play_youtube", "search_youtube"):
                    q = params.get("query", "").strip()
                    if not q:
                        q = _extract_play_query(user_message)
                    success, msg = action_fn(q)
            else:
                # ── Default single-arg action ──
                query = params.get("query", user_message)
                success, msg = action_fn(query)
                
            if not success:
                overall_success = False
                
            # Separate special agent.py triggers from regular text results
            if msg.startswith("WEB_RESULT") or msg.startswith("WHATSAPP_") or msg.startswith("CONFIRM_"):
                special_result = (success, msg)
            else:
                regular_results.append(msg)
                
        except Exception as e:
            print(f"[Router] Error executing {action}: {e}")
            overall_success = False
            regular_results.append(f"{action} failed")

    # ── Aggregation & Return Logic ──
    # If there is a special flow (WhatsApp confirm/Read/Web), return it so agent.py triggers its specific UI logic.
    if special_result:
        return special_result
        
    # Otherwise, join all standard results into one big context string
    if regular_results:
        combined_msg = " | ".join(regular_results)
        return (overall_success, combined_msg)
        
    return None