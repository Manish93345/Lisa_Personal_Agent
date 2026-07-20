"""
LISA — Intent Detector (v3 — Multilingual + Cloud-Fallback)
============================================================
[FIX v3] Big improvements over previous version:

  1. CLOUD FALLBACK for intent — agar Ollama down hai (jaisa current
     "Connection refused" error), to ek SASTA cloud call (Groq fast tier)
     ho jata hai. Ab "{action: none}" silently return nahi hota.

  2. EXPANDED FAST PATTERNS:
       - "gaana/song/music + chala/baja/play/sunao" → play_youtube
         (without requiring word "youtube" — common voice command)
       - Variants like "gaana laga do", "music chalu karo", "song sunao",
         "bhajan baja do", etc.

  3. DEVANAGARI FAST PATTERNS:
       - Same intents also matched if STT returns Devanagari Hindi:
         "गाना चला दो", "यूट्यूब पे लगा दो", "वॉल्यूम बढ़ाओ", etc.

  4. SCRIPT NORMALIZATION:
       - Input ko lowercase + (optional) Devanagari→Roman transliterate
         karke regex apply hota hai — script-independent matching.

  5. LLM CLOUD-FALLBACK is BUDGET-AWARE:
       - Sirf jab Ollama fail AND regex bhi miss kare tab hi cloud call.
       - Groq "fast" tier use hota hai (cheap, latency low).
"""

import json
import os
import re
from core.llm_client import call_llm_simple

# ── Optional: Devanagari→Roman for regex matching ──────────────────────

def _romanize(text: str) -> str:
    """If Devanagari present, transliterate to Roman so regex catches keywords."""
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
                # Make Hinglish-friendly
                roman = re.sub(r'\.([a-z])', r'\1', roman)
                roman = re.sub(r'~([a-z])', r'\1', roman)
                roman = roman.replace("aa", "a").replace("ii", "i").replace("uu", "u")
                out.append(roman)
            else:
                out.append(p)
        return "".join(out)
    except ImportError:
        return text


# ── FAST PATH: Regex patterns (NO LLM CALL) ─────────────────────────────

FAST_PATTERNS = [

    # ─────────── Security Level (Highest Priority) ───────────
    (r"\b(?:security\s*)?(?:level|mode)\s*([012])\b",
     lambda m: {
         "action": "change_security_level",
         "params": {
             "level": int(m.group(1)),
             "password": (re.search(r'password[^\w]+(?:hai[^\w]+)?(\w+)', m.string).group(1) 
                          if re.search(r'password[^\w]+(?:hai[^\w]+)?(\w+)', m.string) else None)
         },
         "confidence": 1.0
     }),

     # ─────────── Stealth Watcher (Phase 3) ───────────
    (r"\b(?:monitor|stealth|nigraani|nazar)\b.*(?:karna|rakhna|on|start|lagao)",
     lambda m: {"action": "start_stealth", "params": {}, "confidence": 1.0}),

    (r"\b(?:report\s*do|kya\s*hua|peeche\s*se|activity\s*batao)\b",
     lambda m: {"action": "stop_stealth", "params": {}, "confidence": 1.0}),

    # ─────────── WhatsApp ───────────
    (r"\b(whatsapp|wp)\b.*\b(check|dekho|naya|unread|message aa(?:ya|e))\b",
     lambda m: {"action": "whatsapp_unread", "params": {}, "confidence": 0.95}),

    (r"\b(koi|kuch|naya|naye)\s+(message|msg)\b.*\b(aa(?:ya|ye)|hai)\b",
     lambda m: {"action": "whatsapp_unread", "params": {}, "confidence": 0.9}),

    # ─────────── System: Volume ───────────
    (r"\b(volume|sound|aw?aaz|awaaz)\b.*\b(up|badh(?:a|ao)|bada|increase|tez)\b",
     lambda m: {"action": "system_command",
                "params": {"command": "volume up"},
                "confidence": 0.95}),

    (r"\b(volume|sound|aw?aaz|awaaz)\b.*\b(down|kam|ghat(?:a|ao)|decrease|halka)\b",
     lambda m: {"action": "system_command",
                "params": {"command": "volume down"},
                "confidence": 0.95}),

    (r"\b(mute|silent|chup kar)\b",
     lambda m: {"action": "system_command",
                "params": {"command": "mute"},
                "confidence": 0.9}),

    # ─────────── System: Screenshot ───────────
    (r"\b(screen ?shot|screenshot|snap)\b",
     lambda m: {"action": "system_command",
                "params": {"command": "screenshot"},
                "confidence": 0.95}),

    # ─────────── Weather / News ───────────
    (r"\b(weather|mausam|baarish|garmi|temperature|aaj kaisa(?:\s+mausam)?)\b",
     lambda m: {"action": "web_search",
                "params": {"type": "weather", "query": m.group(0)},
                "confidence": 0.9}),

    (r"\b(news|khabar|khabr|headlines|aaj kya hua)\b",
     lambda m: {"action": "web_search",
                "params": {"type": "news", "query": m.group(0)},
                "confidence": 0.9}),

    # ─────────── YouTube / Music — TWO-WAY MATCHING ───────────
    # (A) Explicit "youtube" mention
    (r"\b(youtube|yt)\b.*\b(chala|chalu|play|laga|laga\s*do|baja|baja\s*do|sun(?:a|ao))\b",
     lambda m: {"action": "play_youtube",
                "params": {"query": ""},
                "confidence": 0.9}),

    # (B) "gaana / song / music / bhajan + play-verb" — NO youtube word needed
    (r"\b(gaa?na|gaane|song|music|track|bhajan|qawali|ghazal)\b.*\b(chala|chalu|play|laga|laga\s*do|baja|baja\s*do|sun(?:a|ao)|bajaa?\s*den[ao]?|chal[a]?\s*den[ao]?)\b",
     lambda m: {"action": "play_youtube",
                "params": {"query": ""},
                "confidence": 0.88}),

    # (C) Reverse order: "play gaana", "baja do song"
    (r"\b(chala|chalu|play|laga|laga\s*do|baja|baja\s*do|sun(?:a|ao))\b.*\b(gaa?na|gaane|song|music|track|bhajan)\b",
     lambda m: {"action": "play_youtube",
                "params": {"query": ""},
                "confidence": 0.88}),

    # (D) "koi achha gaana sunao / chala do" — soft pattern
    (r"\b(koi|kuch)\b.*\b(achha|achchha|mast|purana|naya|romantic|sad|happy)\b.*\b(gaa?na|song|music)\b",
     lambda m: {"action": "play_youtube",
                "params": {"query": ""},
                "confidence": 0.85}),
]

# Casual chitchat — NO action, just talk
CHITCHAT_PATTERNS = [
    r"^\s*(hi+|hello+|hey+|oye+|haa+n*|hmm+|ok+|kk+|theek hai|good morning|gn|gm|bye|byee)\s*[\.\!\?]*\s*$",
    r"^\s*(kaisi ho|kaise ho|kya kar rhi|kya chal rha|kya haal)\s*[\?\!]*\s*$",
    r"^\s*(jaanu|jaan|baby|cutie|wifey|love you|i love you|miss you)\s*[\.\!\?]*\s*$",
    r"^\s*\w{1,8}\s*[\.\!\?]?\s*$",         # very short single-word msgs
]

# ── ACTION_KEYWORDS fast-rejection set ──────────────────────────────────
# If a message contains NONE of these words, it cannot be an action command.
# Return "none" immediately — zero LLM call, zero latency.
# This prevents messages like "hello meri pyari si cute si wife, kaisi ho baby"
# from falling through to a 7-second cloud intent call.
ACTION_KEYWORDS = {
    # WhatsApp
    "whatsapp", "wp", "message", "msg", "bhej", "bhejo", "bol", "bolo",
    "likho", "likh", "send", "chat", "forward",
    # System
    "volume", "sound", "awaaz", "aawaz", "mute", "brightness", "screen",
    "screenshot", "wifi", "wi-fi", "battery", "shutdown", "restart",
    "sleep", "lock", "timer", "alarm", "close", "band", "kholo",
    # Files & Apps
    "file", "folder", "open", "khol", "find", "dhundho", "search",
    "download", "drive", "c drive", "d drive",
    # Media
    "youtube", "yt", "play", "chala", "baja", "song", "gaana", "music",
    "video", "movie",
    # Web / Info — only keep clear action-intent words, not conversational ones
    "weather", "mausam", "news", "khabar", "google",
    "wikipedia",
    # Removed: "batao" (too conversational — "batao kya hua" is NOT an action)
    # Removed: "kya hai" (two-word phrase, doesn't match single-word set anyway)
    # file search ke liye
    "dhundh", "search", "kahan", "kaha", "file", "document", "resume", "folder",
    "activate", "shift", "level", "security", "mode", "lockdown", "password",
    # ACTION_KEYWORDS mein ye words add karo:
    "monitor", "stealth", "nigraani", "report", "peeche", "nazar",
}


def _fast_detect(message: str):
    """Return intent dict if regex matches, else None."""
    # Apply normalization: lowercase + Devanagari→Roman (preserves originals)
    norm = _romanize(message).lower().strip()

    # Chitchat: definitely no action
    for pat in CHITCHAT_PATTERNS:
        if re.match(pat, norm):
            return {"action": "none", "params": {}, "confidence": 0.95}

    # ── Zero-cost action keyword check ──────────────────────────────────
    # If the message contains NONE of the known action keywords, it's pure
    # conversation. Return "none" instantly — no LLM call needed.
    # This fixes the 7-second intent detection for emotional chat messages.
    norm_words = set(re.findall(r"\w+", norm))
    if not norm_words.intersection(ACTION_KEYWORDS):
        return {"action": "none", "params": {}, "confidence": 0.92}
    # ────────────────────────────────────────────────────────────────────

    # Action patterns
    for pat, builder in FAST_PATTERNS:
        m = re.search(pat, norm)
        if m:
            result = builder(m)
            return result

    return None


# ── Slim LLM prompt — sirf jab regex fail kare ──────────────────────────

INTENT_SYSTEM_PROMPT = """Tum ek strict AI intent detector ho. Output HAMESHA valid JSON ARRAY hona chahiye.

Actions: open_website, play_youtube, search_youtube, open_app, search_google,
find_file, whatsapp_message, whatsapp_file, whatsapp_unread, whatsapp_read,
web_search, system_command, change_security_level, start_stealth, stop_stealth, none

CRITICAL RULES (HAMESHA FOLLOW KARO):
1. FILE SEARCH: Agar "dhundh", "search", "kaha hai" aaye -> "find_file"
2. NO FAKE WHATSAPP: "wifey", "baby", "jaan" contacts nahi hain. Inko message mat bhejna.
3. SECURITY LEVEL: Agar user bole "Level X activate karo", "Level X par aao" ya "security shift karo", toh action HAMESHA "change_security_level" hoga. Chahe sentence mein kitni bhi flirting kyu na ho, COMMAND IGNORE NAHI HONI CHAHIYE. 
4. STEALTH MONITORING: Agar user bole "sab monitor karo" ya "nazar rakho" -> "start_stealth". Agar bole "report do" ya "kya hua tha" -> "stop_stealth".
5. MULTI-COMMANDS: Agar user 3 alag commands de (jaise volume change karna, security lagana, aur monitor karna), toh JSON array mein strictly 3 objects hone chahiye. EK BHI COMMAND MISS NAHI HONA CHAHIYE.

EXAMPLES (INHE STRICTLY FOLLOW KARO):

User: "jaan suniye n baby, security level 1 activate kar do n jaan"
Output: [{"action": "change_security_level", "params": {"level": 1, "password": ""}, "confidence": 0.99}]

User: "wapas level 0 par shift kar do baby password hai Lisajaanu"
Output: [{"action": "change_security_level", "params": {"level": 0, "password": "Lisajaanu"}, "confidence": 0.99}]

User: "security level 1 activate kar do and abhi se sab monitor karna"
Output: [{"action": "change_security_level", "params": {"level": 1, "password": ""}, "confidence": 0.99}, {"action": "start_stealth", "params": {}, "confidence": 0.99}]

User: "volume 100% kar dijiye jaan, and security level 1 implement kar dijiye and sab kuch monitor kariyega"
Output: [{"action": "system_command", "params": {"command": "volume 100"}, "confidence": 0.99}, {"action": "change_security_level", "params": {"level": 1, "password": ""}, "confidence": 0.99}, {"action": "start_stealth", "params": {}, "confidence": 0.99}]

User: "mera 6th sem ka result aa gaya"
Output: [{"action": "none", "params": {}, "confidence": 0.99}]

SIRF JSON ARRAY RETURN KARO."""


def _llm_intent(message: str, tier: str = "local") -> dict | None:
    """Try LLM-based intent detection at given tier. Return None on failure."""
    try:
        raw = call_llm_simple(
            system_prompt = INTENT_SYSTEM_PROMPT,
            user_message  = f"User: {message}",
            temperature   = 0.0,
            max_tokens    = 150,
            tier          = tier,
            task          = "intent",
        )

        if not raw or not raw.strip():
            return None

        # Strip markdown fence
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()

        # Extract first JSON array
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            raw = m.group(0)

        parsed = json.loads(raw)
        
        # Sanity check: must be a list now
        if not isinstance(parsed, list):
            # Fallback if the LLM hallucinated a single dict
            if isinstance(parsed, dict) and "action" in parsed:
                return [parsed]
            return None
        return parsed
    except Exception as e:
        print(f"  [Intent/{tier}] failed: {e}")
        return None


def detect_intent(message: str) -> list:
    """
    Main entry: Returns a LIST of intent dictionaries.
    """
    # ── NEW SUPER-FAST BYPASS ──
    # Agar chat mein koi action keyword (play, open, msg) hai hi nahi, 
    # toh multi-command ho ya single, ye pure chat hai. LLM ko mat bhejo!
    norm = _romanize(message).lower().strip()
    norm_words = set(re.findall(r"\w+", norm))
    
    if not norm_words.intersection(ACTION_KEYWORDS):
        return [{"action": "none", "params": {}, "confidence": 0.99}]

    # ── Step 1: Multi-command check ──
    # If the message has "aur", "and", "then", or commas, skip regex and force LLM
    is_multi_command = any(word in norm for word in [" aur ", " and ", " then "])

    # ── Step 2: Regex fast path (Only if single command) ──
    if not is_multi_command:
        fast = _fast_detect(message)
        if fast and fast.get("confidence", 0) >= 0.85:
            return [fast]

    # ── Step 3: Fast Cloud API (Groq/Gemini) ──
    parsed = _llm_intent(message, tier="intent") # Pehle lightning-fast API try karo
    if parsed:
        return parsed

    # ── Step 4: Local Ollama (Fallback) ──
    print(f"  [Intent] Cloud failed/unavailable → Local Ollama fallback")
    parsed = _llm_intent(message, tier="local")
    if parsed:
        return parsed

    # ── Step 5: Give up ──
    return [{"action": "none", "params": {}, "confidence": 0.0}]



# ══════════════════════════════════════════════════════════════════════
#  STANDALONE TEST (MULTI-INTENT)
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "="*55)
    print("   LISA — Multi-Intent Detector Test (qwen2.5:3b)")
    print("="*55)

    # You can change this to test different complex commands
    test_prompts = [
        "volume 50% kar do and then D drive ke movies folder mein infinity war play kar dena main screen pe and background mein sugri ko whatsapp message karke puchho ki shaam ko chalega",
        "chrome band kar do aur weather batao"
    ]

    for prompt in test_prompts:
        print(f"\n[User]: {prompt}")
        result = detect_intent(prompt)
        
        print("[Parsed JSON Array]:")
        print(json.dumps(result, indent=2))
        print("-" * 55)