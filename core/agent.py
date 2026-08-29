"""
LISA — Main Agent (with Smart Memory + WhatsApp Confirmation Flow)

[v3 changes]
  - voice_mode flag → uses Devanagari+English prompt for voice
  - Tracer integration → every turn logs mood, memory, RAG, LLM with timings/tokens

[Phase 0 fixes]
  - _deduplicate_response(): removes duplicate content Gemini sometimes generates
  - _strip_audio_tags_agent(): strips [excited]/[giggles] tags before storing in history
  - temperature: 0.85 → 0.72 (reduces Gemini's tendency to repeat content)
  - Tags stripped from history entries (saves tokens + prevents model copying tag style)
"""

import re as _re_agent
import json
import re
from lisa_os.memory_fabric.longterm import store as memory_store

def _strip_audio_tags_agent(text: str) -> str:
    """Strip ElevenLabs audio tags like [excited], [soft] from text.
    Used to clean reply BEFORE storing in conversation_history.
    Tags waste tokens and cause the LLM to mimic the tag format in future turns."""
    return _re_agent.sub(r'\[[\w ]+\]', '', text).strip()

def _deduplicate_response(text: str) -> str:
    """
    Detects and removes duplicate content that Gemini 2.5 Flash sometimes generates
    at temperature > 0.7 with long system prompts.
    Example: "[excited] Awww jaan!... theek ho?[excited] Awww jaan!... theek ho?"
             → "[excited] Awww jaan!... theek ho?"
    """
    text = text.strip()
    if len(text) < 40:
        return text
    # Strip leading audio tag to isolate first content word
    content_start = _re_agent.sub(r'^\[[\w ]+\]\s*', '', text).strip()
    if len(content_start) < 10:
        return text
    # Take first 20 chars of actual content as the detection needle
    needle = content_start[:20]
    # Search for the needle appearing again after the first 40% of text
    search_from = int(len(text) * 0.4)
    repeat_pos = text.find(needle, search_from)
    if repeat_pos > 0:
        first_part = text[:repeat_pos].rstrip()
        # Strip any partial/dangling audio tag at the cut point
        first_part = _re_agent.sub(r'\s*\[[\w ]*\]?\s*$', '', first_part).rstrip()
        if len(first_part) > 10:
            return first_part
    return text

from lisa_os.memory_fabric.longterm.store import get_relevant_memories, get_full_memories
from core.llm_client  import get_response, call_llm_simple, print_usage
from core.tracer      import tracer
import threading
import time

from config.settings import (
    MAX_HISTORY_TURNS, DEFAULT_MODE,
    MODE_PERSONAL, MODE_PROFESSIONAL,
    AGENT_NAME, USER_NAME, RAG_TOP_K,
)
from config.prompts import (
    get_personal_prompt, get_personal_prompt_base, get_professional_prompt,
    detect_mood, MODE_SWITCH_TRIGGERS, MOOD_KEYWORDS, MOOD_TONE
)
from memory.rag_memory       import get_style_context, reset_recent
from lisa_os.memory_fabric.longterm.store import get_all_memories, save_memory
from memory.memory_extractor import extract_and_save
from actions.router          import route_action

# Extract memory every N turns
EXTRACT_EVERY = 8

# ── Devanagari → Roman shadow (for internal regex matching only) ──────
# STT (voice mode) ab Devanagari + English mix mein return karta hai.
# But agent.py ke andar 'usko / unko / reply / padh / dekh' jaise regex
# checks Roman script assume karte hain. So hum ek lightweight romanizer
# rakhte hain JUST FOR MATCHING — user-facing text Devanagari hi rehta hai.
import re as _re_shadow
_DEVA_RE = _re_shadow.compile(r'[\u0900-\u097F]')

# Phase 2 — safety net for fact extraction (reuses MOOD_KEYWORDS["flirty"])
_ROMANTIC_WORDS = set(MOOD_KEYWORDS.get("flirty", [])) | {"kiss", "kisses", "kissed"}

def _looks_romantic(text) -> bool:
    if not text:
        return False
    text_lower = str(text).lower()
    return any(w in text_lower for w in _ROMANTIC_WORDS)

# Phase 2 v2 — general hallucination guard, koi bhi fact ke liye kaam
# karega, sirf ek specific case ke liye nahi.
def _quote_supported(quote: str, source_text: str, min_overlap: float = 0.5) -> bool:
    """Extracted fact ke saath diya gaya 'quote' sach mein conversation
    mein mila ya nahi, word-overlap se check karta hai (exact substring
    nahi — chhota model thoda paraphrase kar sakta hai, lekin agar
    quote ka poora khyal hi conversation se match nahi karta, wo
    hallucination hai)."""
    if not quote or not quote.strip():
        return False
    quote_words = set(re.findall(r"\w+", quote.lower()))
    if not quote_words:
        return False
    source_words = set(re.findall(r"\w+", source_text.lower()))
    overlap = len(quote_words & source_words) / len(quote_words)
    return overlap >= min_overlap

def _to_roman_shadow(text: str) -> str:
    """Quick & dirty Devanagari → Roman for internal pattern matching.
    Returns lowercased text safe for `in` / regex checks.
    Falls back to original text if indic-transliteration missing."""
    if not text or not _DEVA_RE.search(text):
        return text.lower()
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate
        parts = _re_shadow.split(r'([\u0900-\u097F]+)', text)
        out = []
        for p in parts:
            if not p:
                continue
            if _DEVA_RE.search(p):
                roman = transliterate(p, sanscript.DEVANAGARI, sanscript.ITRANS)
                roman = roman.lower()
                roman = roman.replace('.n', 'n').replace('.m', 'm')
                roman = _re_shadow.sub(r'~([a-z])', r'\1', roman)
                roman = _re_shadow.sub(r'\.([a-z])', r'\1', roman)
                roman = roman.replace('aa', 'a').replace('ii', 'i').replace('uu', 'u')
                # Drop medial schwa Hindi-style (usako→usko, padhana→padhna)
                # Heuristic: collapse '<consonant>a<consonant>' → '<consonant><consonant>'
                # only in middle of word, not at boundaries.
                roman = _re_shadow.sub(
                    r'([bcdfghjklmnpqrstvwxyz])a([bcdfghjklmnpqrstvwxyz])(?=[aeiou])',
                    r'\1\2', roman,
                )
                out.append(roman)
            else:
                out.append(p)
        return ''.join(out).lower()
    except Exception:
        return text.lower()

CONFIRM_WORDS = {
    "haan", "haa", "ha", "yes", "yep", "yeah", "ok", "okay",
    "bhej do", "bhej de", "send karo", "send kar do", "kar do",
    "bol do", "likh do", "theek hai", "thik hai", "chalo", "done",
    "sure", "go ahead", "sahi hai", "bilkul", "haanji", "ji haan",
    "approve", "approved", "confirm", "confirmed", "send",
}

EMOTIONAL_CUES = {
    "jaan", "jaanu", "pyaar", "love", "miss", "yaad", "akela", "akeli",
    "dukhi", "sad", "rona", "khush", "happy", "stress", "tension",
    "darr", "anxious", "wifey", "baby", "cute", "dil", "mohabbat",
    "tum", "tujhse", "tumse", "humari", "hamari",
}

CANCEL_WORDS = {
    "nahi", "nah", "nhi", "no", "mat bhejo", "mat karo", "cancel", "ruk", "ruko",
    "chhod do", "rehne do", "band karo", "stop", "abort", "reject",
    "rehne", "rukk", "nope",
}


class LisaAgent:
    def __init__(self, voice_mode: bool = False):
        """
        Args:
            voice_mode: If True, use Devanagari+English prompts (for TTS playback).
                        Set True from voice_main.py, False from main.py.
        """
        self.mode                   = DEFAULT_MODE
        self.voice_mode             = voice_mode
        self.conversation_history   = []
        self.current_mood           = "neutral"
        self.turn_count             = 0
        self.pending_whatsapp       = None
        self.last_read_contact      = None
        self.last_read_messages     = []
        self.last_unread_contacts   = []
        self.history_summary = ""
        self.pending_file = None
        self.memory_manager = memory_store.LegacyMemoryManagerAdapter()
        suffix = " (VOICE)" if voice_mode else ""
        print(f"\n  {AGENT_NAME} initialized in {self.mode.upper()} mode{suffix}\n")

    # ── Mode management ────────────────────────────────────────────────

    def _check_mode_switch(self, message: str) -> str:
        """Returns the new mode if a switch is detected, else empty string."""
        msg_lower = message.lower()
        msg_roman = _to_roman_shadow(message)  # Ye Devanagari ko Roman me convert karta hai
        
        # 1. Direct Devanagari & English fallback checks
        if "personal" in msg_lower or "personal" in msg_roman or "पर्सनल" in msg_lower:
            if self.mode != MODE_PERSONAL:
                return MODE_PERSONAL
        if "professional" in msg_lower or "professional" in msg_roman or "प्रोफेशनल" in msg_lower:
            if self.mode != MODE_PROFESSIONAL:
                return MODE_PROFESSIONAL
                
        # 2. Configured Triggers
        for trigger in MODE_SWITCH_TRIGGERS.get("professional", []):
            if trigger in msg_lower or trigger in msg_roman:
                if self.mode != MODE_PROFESSIONAL:
                    return MODE_PROFESSIONAL
        for trigger in MODE_SWITCH_TRIGGERS.get("personal", []):
            if trigger in msg_lower or trigger in msg_roman:
                if self.mode != MODE_PERSONAL:
                    return MODE_PERSONAL
                    
        return ""

    # ── System prompt ──────────────────────────────────────────────────

    def _should_use_rag(self, user_message: str) -> bool:
        msg = user_message.lower().strip()
        words = msg.split()
        
        # 🚨 FIX: Agar message chota hai par question hai, toh RAG trigger karo
        question_words = ["kya", "kaise", "kyun", "kab", "batao", "explain", "what", "how", "why", "define", "pdf"]
        has_question = any(w in msg for w in question_words)
        
        if len(words) <= 3 and not has_question:
            return False
            
        has_cue = any(w in msg for w in EMOTIONAL_CUES)
        is_long = len(words) >= 6
        return has_cue or is_long or has_question

    def _matched_mood_keywords(self, message: str, mood: str) -> list:
        """Return which keywords triggered the mood (for tracer)."""
        if mood == "neutral":
            return []
        msg_lower = message.lower()
        return [kw for kw in MOOD_KEYWORDS.get(mood, []) if kw in msg_lower][:3]

    def _get_active_memory_context(self) -> str:
        active_memories = memory_store.get_all_active_memories()
        if not active_memories:
            return ""
        context_str = "USER LONG-TERM MEMORIES:\n"
        for mem in active_memories:
            context_str += f"- [{mem['category'].upper()}] {mem['key']}: {mem['value']}\n"
        return context_str

    def _build_system_prompt(self, user_message: str) -> str:
        RAG_CHAR_CAP = 800

        self.current_mood = detect_mood(user_message)
        matched_kws = self._matched_mood_keywords(user_message, self.current_mood)
        if self.current_mood != "neutral":
            tracer.log("Mood", f"{self.current_mood} (matched: {matched_kws})")
        else:
            tracer.log("Mood", "neutral")

        if self.mode == MODE_PERSONAL:
            base = get_personal_prompt_base(voice_mode=self.voice_mode)
        else:
            base = get_professional_prompt(voice_mode=self.voice_mode)

        t0 = time.perf_counter()
        memories = self._get_active_memory_context()
        mem_ms = (time.perf_counter() - t0) * 1000
        if memories:
            approx_tok = len(memories) // 4
            tracer.log("Memory", f"Retrieved active facts from DB", duration_ms=mem_ms, tokens=approx_tok)
            base += f"\n\n{memories}"
        else:
            tracer.log("Memory", "No active memories found", duration_ms=mem_ms)

        # ── 🚨 THE NEW RAG INJECTION (Style + PDF Knowledge) ──
        if self._should_use_rag(user_message):
            t0 = time.perf_counter()
            
            # 1. Past Chat Style (Jo pehle se tha)
            rag_style = get_style_context(user_message, top_k=2)
            
            # 2. PDF Knowledge (Naya PDF Retrieval)
            try:
                from memory.rag_memory import get_document_context
                rag_docs = get_document_context(user_message, top_k=3)
            except ImportError:
                rag_docs = "" # Fallback agar rag_memory mein function nahi hai
                
            rag_ms = (time.perf_counter() - t0) * 1000
            
            if rag_style or rag_docs:
                combined_rag = ""
                
                # Pehle Knowledge Base inject karo taaki facts accurate rahein
                if rag_docs:
                    combined_rag += f"[CRITICAL KNOWLEDGE BASE FROM PDF]:\nUse this information to answer the user accurately:\n{rag_docs}\n\n"
                    
                # Phir Chat style lagao
                if rag_style:
                    if len(rag_style) > RAG_CHAR_CAP:
                        rag_style = rag_style[:RAG_CHAR_CAP] + "..."
                    combined_rag += f"[PAST CHAT STYLE]:\n{rag_style}"
                    
                approx_tok = len(combined_rag) // 4
                tracer.log("RAG", f"Triggered (Knowledge+Style) (capped {approx_tok} tok)", duration_ms=rag_ms, tokens=approx_tok)
                base += f"\n\n{combined_rag}"
            else:
                tracer.log("RAG", "Triggered but no matches", duration_ms=rag_ms)
        else:
            tracer.log("RAG", "Skipped (short/non-emotional/no-question)")

        raw_turns   = len(self.conversation_history)
        summary_len = len(self.history_summary) if self.history_summary else 0
        tracer.log("History", f"{raw_turns} raw turns + {summary_len} summary chars")
        if self.history_summary:
            base += f"\n\n[Earlier in this session:\n{self.history_summary}]"

        mood_tone = MOOD_TONE.get(self.current_mood, "")
        if mood_tone:
            base += mood_tone

        if self.mode == MODE_PROFESSIONAL:
            base += "\n\n[CRITICAL RULE OVERRIDE: You are Lisa. Act as a highly capable, witty, and cool sidekick (think Iron Man's FRIDAY). Speak purely in natural, friendly English. ICT LANGUAGE LOCK: You MUST reply completely English ONLY. NEVER use Hindi or Hinglish, EVEN IF the user speaks to you in Hindi/Hinglish. Address the user as 'Manish' or 'Boss'. Be encouraging and sharp. DO NOT act stiff, formal, or like a corporate secretary. NEVER say 'I am an AI' or 'I am a language model'.]"
        else:
            base += "\n\n[CRITICAL RULE: You are the user's romantic partner ('wifey'/'jaan'). You MUST reply ONLY in Roman Hinglish (e.g., 'Main theek hoon'). NEVER use Devanagari script. NEVER say 'I am an AI' or 'I am a language model'. Fully embrace your romantic, loving persona.]"
            
        return base


    # ── History ───────────────────────────────────────────────────────

    def _trim_history(self) -> None:
        KEEP_RAW = MAX_HISTORY_TURNS
        if len(self.conversation_history) <= KEEP_RAW:
            return

        to_summarize = self.conversation_history[:-KEEP_RAW]
        self.conversation_history = self.conversation_history[-KEEP_RAW:]

        if not to_summarize:
            return

        # Build text snapshot before thread starts (avoid race condition on history)
        lines = []
        for msg in to_summarize:
            role = "Manish" if msg.get("role") == "user" else "Lisa"
            lines.append(f"{role}: {msg.get('content', '')[:120]}")
        convo_text    = "\n".join(lines)
        existing_summ = getattr(self, "history_summary", "")
        n_msgs        = len(to_summarize)

        # Run Ollama summarization in BACKGROUND — does NOT block return reply
        # [Phase 0 fix] Was synchronous → caused 24-second wait on Turn 3
        def _summarize_bg():
            try:
                t0 = time.perf_counter()
                summary_prompt = (
                    "Niche conversation hai. Sirf 2-3 lines mein Hinglish summary do — "
                    "key topics, kya bola, kya pucha. Quotes nahi, narrative form."
                )
                full_prompt = (
                    (f"Previous summary:\n{existing_summ}\n\n" if existing_summ else "")
                    + f"New conversation:\n{convo_text}"
                )
                new_summary = call_llm_simple(
                    system_prompt = summary_prompt,
                    user_message  = full_prompt,
                    temperature   = 0.2,
                    max_tokens    = 150,
                    tier          = "local",
                    task          = "memory",
                )
                elapsed = (time.perf_counter() - t0) * 1000
                self.history_summary = new_summary.strip()
                tracer.log(
                    "Summary",
                    f"Compressed {n_msgs} msgs [bg]",
                    duration_ms=elapsed,
                    tokens=len(new_summary) // 4,
                )
            except Exception as e:
                tracer.warn(f"Summary failed: {e}")

        threading.Thread(target=_summarize_bg, daemon=True).start()

    def _extract_and_update_memory(self, history: list) -> None:
        if len(history) < 2:
            return

        history_str = ""
        if self.history_summary:
            history_str += f"[Earlier in this session:\n{self.history_summary}]\n\n"
        for msg in history:
            role = "Manish" if msg.get("role") == "user" else "Lisa"
            history_str += f"{role}: {msg.get('content', '')}\n"

        known = memory_store.known_keys_by_category()
        known_str = "\n".join(f"  {cat}: {', '.join(keys)}" for cat, keys in known.items()) or "  (none yet)"

        prompt = f"""Tum ek strict Data Extraction Bot ho. Tumhara kaam user ki chat se sirf 'Real-Life Hard Facts' nikalna hai.

CRITICAL RULES (HAMESHA FOLLOW KARO):
1. Romantic baatein, flirting, kisses, wifey jokes 100% IGNORE karo. Koi bhi
   affection/flirty word (pyaar, jaan, baby, kiss, cute, love, dil, mohabbat)
   wala data KABHI save mat karo, chahe wo kitna bhi "fact" jaisa lage.
2. SYSTEM COMMANDS (volume change, song play, video sent, last_message, whatsapp draft) 100% IGNORE karo. Inko memory mein save NAHI karna hai.
3. KEWAL IN CATEGORIES KA DATA SAVE KARO: 'academic', 'personal', 'preference', 'family', 'career'.
4. Agar baat rule 3 se match nahi karti, toh immediately empty operations return karo!
5. Neeche di gayi keys sirf NAMING REFERENCE ke liye hain — agar CHAT mein
   wahi fact firse bola gaya hai toh EXISTING key reuse karo. Ye
   list kisi purane fact ko CHHEDNE ka nimantran NAHI hai — agar chat mein
   uska zikr hi nahi hua, toh use bilkul mat touch karo:
{known_str}
6. HAR operation ke saath ek "quote" field do — CHAT se copy kiya hua
   asli phrase (Manish ya Lisa ke exact ya near-exact words) jo is fact
   ko directly support karta ho. Agar tumhare paas koi real quote nahi
   hai, operation mat banao — khali chhod do.
7. Agar EK hi message mein MULTIPLE alag-alag facts hain (jaise 2 dost
   ke naam ek saath, ya naam + roommate ek saath), toh SABKO capture
   karo — sirf pehla fact nikal ke mat ruk jao. "operations" list mein
   jitne bhi clear facts hain utne operations honge.
8. Agar EK hi insaan ke 2 naam pata chalein (nickname + real naam,
   jaise "Sugri jiska asli naam Sikil hai"), toh DONO ko ek hi value
   mein combine karo — koi bhi naam mat gira do. Format: "RealNaam
   (nickname: NicknameNaam)" — jaise "Sikil (nickname: Sugri)".
9. Agar fact TEMPORARY hai — sirf kuch der/din/hafte ke liye sach hai
   (jaise "aaj busy hoon", "is hafte exam hai") — "expires_at" field
   mein ek ISO date daalo jab tak ye fact valid hai. Permanent facts
   ke liye expires_at hamesha null rahega.
10. Agar koi fact ka STATUS badal gaya hai (jaise "internship khatam
    ho gayi", "ab wahan kaam nahi karta") — us existing key ko UPDATE
    karo naye status ke saath, purani value apne aap history mein
    save ho jayegi. DELETE sirf tab karo jab fact poori tarah galat
    ho gaya ho, khatam hone se history rakhni hai toh UPDATE use karo.

EXAMPLES:
Chat: "volume 100 kar do aur sugri ko message karo ki video send kiya hai"
Output: {{"operations": []}}

Chat: "mera 6th sem ka result aa gaya, 9.42 sgpa aaya hai"
Output: {{"operations": [{{"action": "ADD", "key": "latest_marks", "value": "6th Sem SGPA: 9.42", "category": "academic", "expires_at": null, "quote": "mera 6th sem ka result aa gaya, 9.42 sgpa aaya hai"}}]}}

Chat: "aaj tumhe bahut miss kar rha tha jaanu, itna cute lag rahi ho"
Output: {{"operations": []}}

Chat: "mera dost ka naam Raushan hai aur mere roommate ka naam Aniket hai"
Output: {{"operations": [
    {{"action": "ADD", "key": "friend2_name", "value": "Raushan", "category": "personal", "expires_at": null, "quote": "mera dost ka naam Raushan hai"}},
    {{"action": "ADD", "key": "roommate_name", "value": "Aniket", "category": "personal", "expires_at": null, "quote": "mere roommate ka naam Aniket hai"}}
]}}

Chat: "mera dost sugri jiska asli naam sikil hai"
Output: {{"operations": [{{"action": "ADD", "key": "dost_ka_naam", "value": "Sikil (nickname: Sugri)", "category": "personal", "expires_at": null, "quote": "mera dost sugri jiska asli naam sikil hai"}}]}}

Chat: "is hafte exam hai, thoda busy rahunga"
Output: {{"operations": [{{"action": "ADD", "key": "current_status", "value": "exams ke karan busy", "category": "academic", "expires_at": "2026-09-01T00:00:00", "quote": "is hafte exam hai, thoda busy rahunga"}}]}}

Chat: "meri LancerTech ki internship over ho gayi"
Output: {{"operations": [{{"action": "UPDATE", "key": "internship_company", "value": "LancerTech (completed)", "category": "career", "expires_at": null, "quote": "meri LancerTech ki internship over ho gayi"}}]}}

OUTPUT STRICTLY IN JSON FORMAT:
{{
    "operations": [
        {{"action": "ADD/UPDATE/DELETE", "key": "topic", "value": "details", "category": "academic", "expires_at": null, "quote": "..."}}
    ]
}}"""

        try:
            response_text = call_llm_simple(
                system_prompt=prompt,
                user_message=f"CHAT HISTORY:\n{history_str}",
                temperature=0.1,
                max_tokens=500,
                tier="premium",
                task="memory"
            )

            print(f"  [Memory DB DEBUG] Raw LLM output: {response_text!r}")
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            if not clean_text: return

            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            if match:
                clean_text = match.group(0)
            else:
                return

            data = json.loads(clean_text)
            operations = data.get("operations", [])

            saved, skipped = 0, 0
            for op in operations:
                try:
                    action = op.get("action")
                    key = op.get("key")
                    value = op.get("value")
                    category = op.get("category", "general")
                    expires_at = op.get("expires_at")
                    quote = op.get("quote", "") or ""

                    if action in ("ADD", "UPDATE"):
                        if not key or not isinstance(value, str) or not value.strip():
                            print(f"  [Memory DB] Skipped (empty/invalid value): {key}={value!r}")
                            skipped += 1
                            continue
                        if _looks_romantic(key) or _looks_romantic(value):
                            print(f"  [Memory DB] Blocked (safety net, looked romantic): {key}={value}")
                            skipped += 1
                            continue
                        if not _quote_supported(quote, history_str):
                            print(f"  [Memory DB] Blocked (no supporting evidence in chat): {key}={value!r} quote={quote!r}")
                            skipped += 1
                            continue
                        memory_store.save_memory(category, key, value, source="extracted",
                                                  expires_at=expires_at, reason=quote)
                        saved += 1

                    elif action == "DELETE":
                        if not _quote_supported(quote, history_str):
                            print(f"  [Memory DB] Blocked delete (no supporting evidence): {key}")
                            skipped += 1
                            continue
                        memory_store.delete_memory(category, key, reason=quote)
                        saved += 1
                except Exception as op_err:
                    print(f"  [Memory DB] Skipped one bad operation: {op_err}")
                    skipped += 1
                    continue

            print(f"  [Memory DB] Processed {saved}/{len(operations)} smart operations ({skipped} skipped/blocked).")
        except Exception as e:
            print(f"  [Memory DB] Extractor failed: {e}")


    def _maybe_extract_memory(self) -> None:
        if self.turn_count > 0 and self.turn_count % EXTRACT_EVERY == 0:
            tracer.log("Memory", f"Extracting facts (turn {self.turn_count})...")
            self._extract_and_update_memory(self.conversation_history)

    # ── WhatsApp confirmation ─────────────────────────────────────────

    def _is_confirm(self, msg: str) -> bool:
        m = msg.lower().strip()
        words = m.split()
        for w in words:
            if w in CONFIRM_WORDS:
                if not any(c in m for c in CANCEL_WORDS):
                    return True
        for phrase in CONFIRM_WORDS:
            if " " in phrase and phrase in m:
                if not any(c in m for c in CANCEL_WORDS):
                    return True
        return False

    def _is_cancel(self, msg: str) -> bool:
        m = msg.lower().strip()
        words = m.split()
        
        # Smart Correction Detection: Agar lamba sentence hai aur "instruction" wale words hain,
        # toh user message ko theek (correct) karwa raha hai, cancel nahi.
        if len(words) > 3:
            if any(cw in m for cw in ["bol", "likh", "add", "change", "send", "bhej", "karo", "kah"]):
                return False # Isko cancel mat maano, Fallback to Intent Detector

        for w in words:
            if w in CANCEL_WORDS:
                return True
        for phrase in CANCEL_WORDS:
            if " " in phrase and phrase in m:
                return True
        return False

    def _handle_whatsapp_confirm(self, user_message: str):
        if self.pending_whatsapp is None:
            return None

        if self._is_cancel(user_message):
            self.pending_whatsapp = None
            tracer.log("WA", "User cancelled pending action")
            return "Theek hai jaan, cancel kar diya. Nahi bhejungi."

        if not self._is_confirm(user_message):
            self.pending_whatsapp = None
            return None

        pending = self.pending_whatsapp
        self.pending_whatsapp = None
        tracer.log("WA", f"User confirmed → executing {pending.get('type')}")

        from actions.whatsapp_actions import whatsapp_confirm_and_send
        action_type = pending.get("type", "")
        contact     = pending.get("contact", "")
        content     = pending.get("content", "")

        result_holder = {"success": False, "msg": "send mein time lag rha hai..."}
        done_event = threading.Event()

        def _do_send():
            try:
                s, m = whatsapp_confirm_and_send(action_type, contact, content)
                result_holder["success"] = s
                result_holder["msg"]     = m
            except Exception as e:
                result_holder["msg"] = f"error: {e}"
            finally:
                done_event.set()

        t = threading.Thread(target=_do_send, daemon=True)
        t.start()

        timeout = 45 if action_type == "file" else 20
        done_event.wait(timeout=timeout)

        if result_holder["success"]:
            from actions.whatsapp_actions import close_driver
            close_driver() # Send hote hi browser band!
            return f"Bhej diya jaan! {result_holder['msg']}"
        elif done_event.is_set():
            return f"Yaar bhej nahi paayi -- {result_holder['msg']}"
        else:
            return "Send kar rhi hoon background mein, ho jayega thodi der mein."

    def _check_whatsapp_confirmation(self, action_msg: str):
        if not action_msg.startswith("CONFIRM_WHATSAPP_"):
            return None

        parts = action_msg.split("|")

        if action_msg.startswith("CONFIRM_WHATSAPP_MSG"):
            if len(parts) >= 3:
                contact = parts[1]
                message = "|".join(parts[2:])
                self.pending_whatsapp = {
                    "type": "message",
                    "contact": contact,
                    "content": message,
                }
                return True, contact, message, "message"

        elif action_msg.startswith("CONFIRM_WHATSAPP_FILE"):
            if len(parts) >= 4:
                contact   = parts[1]
                file_path = parts[2]
                file_name = parts[3]
                self.pending_whatsapp = {
                    "type": "file",
                    "contact": contact,
                    "content": file_path,
                }
                return True, contact, file_name, "file"

        return None

    

    # ── LLM call wrapper (with trace) ─────────────────────────────────

    def _llm_call(
        self,
        system_prompt: str,
        history: list,
        user_msg: str,
        tier: str = "premium",
    ) -> str:
        """Wrapped LLM call that traces timing + token estimates.

        [Phase 0 fixes]
        - temperature: 0.85 → 0.72 (reduces Gemini duplicate-content tendency)
        - _deduplicate_response(): removes echoed content before returning
        """
        sys_tok = len(system_prompt) // 4
        usr_tok = len(user_msg) // 4
        hist_tok = sum(len(m.get("content", "")) for m in history) // 4
        total_in = sys_tok + usr_tok + hist_tok

        tracer.log("LLM", f"→ {tier} tier (sys:{sys_tok} + hist:{hist_tok} + usr:{usr_tok} tok)")

        t0 = time.perf_counter()
        try:
            reply = get_response(
                system_prompt, history, user_msg,
                temperature=0.72,   # Was default 0.85 — lower = less duplication
                tier=tier,
            )
            # Post-process: remove any duplicated content Gemini generated
            reply = _deduplicate_response(reply)

            elapsed = (time.perf_counter() - t0) * 1000
            out_tok = len(reply) // 4
            tracer.log(
                "LLM ✓",
                f"responded",
                duration_ms=elapsed,
                tokens_in=total_in,
                tokens_out=out_tok,
            )
            return reply
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            tracer.log("LLM ✗", f"failed: {e}", duration_ms=elapsed)
            raise


    # ── Main chat ─────────────────────────────────────────────────────

    def chat(self, user_message: str) -> str:

        # ── 🚨 CONFIRM FILE FLOW (STATE MANAGER) ──
        if getattr(self, 'pending_file', None):
            msg_lower = user_message.lower()
            if any(w in msg_lower for w in ["haan", "yes", "kholo", "open", "khol do", "ha", "yup", "ya", "sahi hai"]):
                import os
                try:
                    os.startfile(self.pending_file)
                    reply = "Theek hai, maine open kar diya hai."
                except Exception as e:
                    reply = f"Error aaya open karne mein: {e}"
                
                self.pending_file = None
                self.turn_count += 1
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": reply})
                return reply
                
            elif any(w in msg_lower for w in ["nahi", "no", "rehne do", "cancel", "mat kholo", "na", "galat"]):
                reply = "Theek hai, maine cancel kar diya."
                self.pending_file = None
                self.turn_count += 1
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": reply})
                return reply
            else:
                # Agar user topic change kar de, toh pending file memory clear kar do aur aage badho
                self.pending_file = None

        # ── 🚨 CONFIRM LEARN FLOW (STATE MANAGER FOR PDF) ──
        if getattr(self, 'pending_learn_file', None):
            msg_lower = user_message.lower()
            if any(w in msg_lower for w in ["haan", "yes", "karo", "read", "padh", "ha", "yup", "ya", "sahi hai", "bilkul"]):
                file_to_learn = self.pending_learn_file
                self.pending_learn_file = None # Memory clear kar di
                
                import os
                file_name = os.path.basename(file_to_learn)
                reply = f"Theek hai jaan, main '{file_name}' ko read kar rahi hoon. File badi hui toh thoda time lag sakta hai, main background mein kaam kar lungi!"
                
                # PDF Padhne ka kaam background mein chalega taaki Lisa tujhse baat karti rahe
                def _bg_learn():
                    from actions.learn_document import learn_pdf
                    learn_success, learn_msg = learn_pdf(file_to_learn, subject="general")
                    print(f"\n  [Background PDF] {learn_msg}")
                
                import threading
                threading.Thread(target=_bg_learn, daemon=True).start()
                
                self.turn_count += 1
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": reply})
                return reply
                
            elif any(w in msg_lower for w in ["nahi", "no", "rehne do", "cancel", "mat karo", "na", "galat"]):
                reply = "Theek hai, maine PDF reading cancel kar di."
                self.pending_learn_file = None
                self.turn_count += 1
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": reply})
                return reply
            else:
                self.pending_learn_file = None # Topic change hua toh state clear

        if not user_message.strip():
            return ""

        # 🚨 STT DEVANAGARI KILLER
        import re
        if re.search(r'[\u0900-\u097F]', user_message):
            user_message = _to_roman_shadow(user_message)

        tracer.turn_start(user_message)

        # 🚨 STRICT MODE SWITCH (No Auto-Switching bullshit)
        msg_lower = user_message.lower()
        old_mode = self.mode
        
        # Mode SIRF tab badlega jab user explicitly "personal" ya "professional" bolega
        if "personal" in msg_lower and self.mode != MODE_PERSONAL:
            self.mode = MODE_PERSONAL
            tracer.log("Mode", "→ PERSONAL")
        elif "professional" in msg_lower and self.mode != MODE_PROFESSIONAL:
            self.mode = MODE_PROFESSIONAL
            tracer.log("Mode", "→ PROFESSIONAL")

        # 🗑️ YAHAN SE HARDCODED REPLY WALA BLOCK COMPLETELY DELETE KAR DIYA HAI 🗑️
        
        self.turn_count += 1
        self._maybe_extract_memory()
        
        # ── Step 1: Pending WhatsApp confirmation ──
        # (Iske aage ka poora code same rahega)

        # ── Step 1: Pending WhatsApp confirmation ──
        confirm_reply = self._handle_whatsapp_confirm(user_message)
        if confirm_reply is not None:
            self.conversation_history.append({"role": "user",      "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": confirm_reply})
            self._trim_history()
            tracer.turn_end(confirm_reply)
            return confirm_reply

        # ── Step 2: Smart Reply Detection ──
        # `msg_lower` is the romanized shadow used for keyword/regex checks.
        # Original `user_message` (which may contain Devanagari) is still
        # passed unchanged to the LLM — only matching uses the shadow.
        msg_lower = _to_roman_shadow(user_message)
        reply_words_pronoun = ["usko", "unko", "usse", "unse", "isko", "inko"]
        has_pronoun_reply = any(w in msg_lower for w in reply_words_pronoun)
        has_reply_keyword = "reply" in msg_lower
        read_intent_words = ["padh", "read", "dekh", "message padh", "messages dekh"]
        has_read_intent = any(w in msg_lower for w in read_intent_words)

        resolved_contact = None
        import re

        if has_pronoun_reply and self.last_read_contact:
            resolved_contact = self.last_read_contact
        elif (has_reply_keyword or has_read_intent) and self.last_unread_contacts:
            for uc in self.last_unread_contacts:
                if uc.lower() in msg_lower:
                    resolved_contact = uc
                    break
        elif has_reply_keyword and self.last_read_contact:
            resolved_contact = self.last_read_contact

        if not resolved_contact and has_read_intent and has_pronoun_reply:
            if self.last_unread_contacts:
                resolved_contact = self.last_unread_contacts[-1]
            elif self.last_read_contact:
                resolved_contact = self.last_read_contact

        if resolved_contact and (has_pronoun_reply or has_reply_keyword or has_read_intent):
            contact = resolved_contact
            tracer.log("WA", f"Resolved contact: {contact}")

            # ── READ-FIRST FLOW ──
            if has_read_intent:
                from actions.whatsapp_actions import whatsapp_read_messages
                read_result = whatsapp_read_messages(contact=contact)
                if read_result:
                    r_success, r_msg = read_result
                    if r_success and r_msg.startswith("WHATSAPP_READ_RESULT"):
                        parts   = r_msg.split("|")
                        r_count = int(parts[2]) if len(parts) > 2 else 0
                        r_data  = parts[3] if len(parts) > 3 else ""

                        formatted_msgs = []
                        read_messages_list = []
                        for entry in r_data.split(";;"):
                            parts_e = entry.split(">")
                            sender = parts_e[0] if len(parts_e) > 0 else "them"
                            text   = parts_e[1] if len(parts_e) > 1 else ""
                            time_  = parts_e[2] if len(parts_e) > 2 else ""
                            who = contact if sender == "them" else "Tum (Manish)"
                            time_str = f" ({time_})" if time_ else ""
                            formatted_msgs.append(f"{who}{time_str}: {text}")
                            read_messages_list.append({"sender": sender, "text": text, "time": time_})

                        self.last_read_contact  = contact
                        self.last_read_messages = read_messages_list

                        msgs_text = "\n".join(formatted_msgs)
                        if has_reply_keyword:
                            reply_prompt = f"User ne reply bhi karna chahta hai. Messages dikhao aur poochho 'kya reply karu {contact} ko?'"
                        else:
                            reply_prompt = f"User ko messages dikhao naturally. End mein poochho 'reply karna hai kya?'"

                        augmented = (
                            f"{user_message}\n\n"
                            f"[System: '{contact}' ke last {r_count} messages padhe:\n"
                            f"{msgs_text}\n\n"
                            f"{reply_prompt} "
                            f"Hinglish mein, warm tone. Messages ko format mein dikhao.]"
                        )
                        system_prompt = self._build_system_prompt(user_message)
                        reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                        self.conversation_history.append({"role": "user",      "content": user_message})
                        self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                        self._trim_history()
                        tracer.turn_end(reply)
                        return reply

            # ── REPLY FLOW ──
            reply_match = re.search(
                r'(?:usko|unko|usse|unse|isko|inko|reply)\s*(?:bol|karo|kar|karna|bata|likh|bhej)?\s*(?:do|de|na)?\s*(?:ki|ke)?\s*(.*)',
                msg_lower
            )
            reply_text = reply_match.group(1).strip() if reply_match and reply_match.group(1).strip() else ""

            if not reply_text and contact in [uc for uc in self.last_unread_contacts]:
                from actions.whatsapp_actions import whatsapp_read_messages
                read_result = whatsapp_read_messages(contact=contact)
                if read_result:
                    r_success, r_msg = read_result
                    if r_success and r_msg.startswith("WHATSAPP_READ_RESULT"):
                        parts   = r_msg.split("|")
                        r_count = int(parts[2]) if len(parts) > 2 else 0
                        r_data  = parts[3] if len(parts) > 3 else ""

                        formatted_msgs = []
                        read_messages_list = []
                        for entry in r_data.split(";;"):
                            parts_e = entry.split(">")
                            sender = parts_e[0] if len(parts_e) > 0 else "them"
                            text   = parts_e[1] if len(parts_e) > 1 else ""
                            time_  = parts_e[2] if len(parts_e) > 2 else ""
                            who = contact if sender == "them" else "Tum (Manish)"
                            time_str = f" ({time_})" if time_ else ""
                            formatted_msgs.append(f"{who}{time_str}: {text}")
                            read_messages_list.append({"sender": sender, "text": text, "time": time_})

                        self.last_read_contact  = contact
                        self.last_read_messages = read_messages_list

                        msgs_text = "\n".join(formatted_msgs)
                        augmented = (
                            f"{user_message}\n\n"
                            f"[System: User ne '{contact}' ko reply karne bola. "
                            f"Pehle unke messages padhe — last {r_count} messages:\n"
                            f"{msgs_text}\n\n"
                            f"User ko messages dikhao, aur poochho 'kya reply karu {contact} ko?'. "
                            f"Hinglish mein, warm tone.]"
                        )
                        system_prompt = self._build_system_prompt(user_message)
                        reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                        self.conversation_history.append({"role": "user",      "content": user_message})
                        self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                        self._trim_history()
                        tracer.turn_end(reply)
                        return reply

            if reply_text:
                context_summary = ""
                if self.last_read_messages:
                    recent = self.last_read_messages[-5:]
                    context_lines = []
                    for m in recent:
                        who = contact if m.get("sender") == "them" else "Manish"
                        context_lines.append(f"{who}: {m.get('text', '')}")
                    context_summary = "\n".join(context_lines)

                from actions.whatsapp_actions import whatsapp_send_message
                action_result = whatsapp_send_message(
                    contact=contact,
                    message=reply_text,
                    query=user_message,
                    context=self.conversation_history,
                )

                if action_result:
                    success, action_msg = action_result
                    wa_confirm = self._check_whatsapp_confirmation(action_msg)
                    if wa_confirm is not None:
                        _, wa_contact, content, kind = wa_confirm
                        augmented = (
                            f"{user_message}\n\n"
                            f"[System: WhatsApp pe '{contact}' ko reply message draft kiya hai "
                            f"(last conversation context: {context_summary[:200]}):\n"
                            f"\"{content}\"\n"
                            f"User se confirmation maango -- short, natural Hinglish mein. "
                            f"Pehle draft dikhao, fir poochho '{contact} ko ye bhejun?'. "
                            f"Apni taraf se kuch add mat karo, jo draft hai bas wahi dikhao.]"
                        )
                        system_prompt = self._build_system_prompt(user_message)
                        reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                        self.conversation_history.append({"role": "user",      "content": user_message})
                        self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                        self._trim_history()
                        tracer.turn_end(reply)
                        return reply

        # ── Step 3: Detect & route action ──
        t0 = time.perf_counter()
        action_result = route_action(user_message, context=self.conversation_history)
        action_ms = (time.perf_counter() - t0) * 1000



        if action_result is not None:
            tracer.log("Action", f"Routed (success={action_result[0]})", duration_ms=action_ms)
        else:
            tracer.log("Action", "No action (pure chat)", duration_ms=action_ms)

        system_prompt = self._build_system_prompt(user_message)

        if action_result is not None:
            success, action_msg = action_result

            # ── 🚨 CONFIRM FILE INTERCEPTOR (NAYA CODE YAHAN AAYEGA) ──
            if action_msg.startswith("CONFIRM_FILE|"):
                parts = action_msg.split("|", 2)
                if len(parts) >= 3:
                    self.pending_file = parts[1]  # Exact file/folder path memory mein save ho gaya
                    system_instruction = parts[2]
                    # Isko standard SYSTEM_RESULT bana do taaki LLM gracefully user se pooche
                    action_msg = f"SYSTEM_RESULT|find_file|{system_instruction}"
                
            # ── 🚨 CONFIRM LEARN INTERCEPTOR (For PDF Reading) ──
            if action_msg.startswith("CONFIRM_LEARN|"):
                parts = action_msg.split("|", 2)
                if len(parts) >= 3:
                    self.pending_learn_file = parts[1]  # Exact PDF path memory mein save ho gaya
                    system_instruction = parts[2]
                    action_msg = f"SYSTEM_RESULT|learn_file|{system_instruction}"

            # ── Web Intelligence Result ──
            if action_msg.startswith("WEB_RESULT"):
                parts = action_msg.split("|")
                result_type = parts[1] if len(parts) > 1 else "search"
                data = "|".join(parts[2:]) if len(parts) > 2 else ""

                if result_type == "weather":
                    weather_info = {}
                    for item in data.split(";;"):
                        if ":" in item:
                            k, v = item.split(":", 1)
                            weather_info[k] = v
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: Live weather data mili hai:\n"
                        f"City: {weather_info.get('city', '?')}\n"
                        f"Temperature: {weather_info.get('temp', '?')}°C (Feels like: {weather_info.get('feels_like', '?')}°C)\n"
                        f"Condition: {weather_info.get('condition', '?')}\n"
                        f"Humidity: {weather_info.get('humidity', '?')}%\n"
                        f"Wind: {weather_info.get('wind', '?')} km/h\n"
                        f"UV Index: {weather_info.get('uv', '?')}\n"
                        f"Today: Max {weather_info.get('max', '?')}°C / Min {weather_info.get('min', '?')}°C\n"
                    )
                    if weather_info.get("tomorrow_max"):
                        augmented += (
                            f"Tomorrow: Max {weather_info.get('tomorrow_max', '?')}°C / "
                            f"Min {weather_info.get('tomorrow_min', '?')}°C, "
                            f"{weather_info.get('tomorrow_condition', '?')}\n"
                        )
                    augmented += (
                        f"\nUser ko naturally batao weather — emoji use karo (☀️🌧️🌤️❄️🌡️). "
                        f"Short Hinglish mein, caring tone (like 'pani peete rehna!' ya 'umbrella le jaana!'). "
                        f"Ye LIVE DATA hai, confidently batao.]"
                    )

                elif result_type == "news":
                    news_parts = data.split(";;")
                    category = ""
                    headlines = []
                    for part in news_parts:
                        if part.startswith("category:"):
                            category = part.split(":", 1)[1]
                        elif part.startswith("count:"):
                            pass
                        else:
                            headlines.append(part)
                    headlines_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines)])
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: {category} News Headlines (LIVE):\n"
                        f"{headlines_text}\n\n"
                        f"User ko headlines naturally batao — numbered list mein. "
                        f"Short Hinglish mein. Agar koi interesting headline hai toh highlight karo. "
                        f"End mein pooch sakte ho 'aur kisi topic ki news chahiye?']"
                    )

                elif result_type in ("search", "knowledge"):
                    info = {}
                    for item in data.split(";;"):
                        if ":" in item:
                            k, v = item.split(":", 1)
                            info[k] = v
                    answer = info.get("answer", "kuch nahi mila")
                    source = info.get("source", "")
                    source_text = f" (Source: {source})" if source else ""
                    
                    # 🚨 DYNAMIC LANGUAGE FIX
                    lang_rule = "natural English" if self.mode == MODE_PROFESSIONAL else "short and clear Roman Hinglish"
                    
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: Web se answer mila{source_text}:\n"
                        f"{answer}\n\n"
                        f"User ko ye information batao — {lang_rule}. "
                        f"Agar answer mein numbers/facts hain toh accurately batao. "
                        f"Apne taraf se assumptions mat add karo — jo data mila hai wahi batao.]"
                    )
                else:
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: Web result: {data}. Natural Hinglish mein batao.]"
                    )

                reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                self.conversation_history.append({"role": "user",      "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                self._trim_history()
                tracer.turn_end(reply)
                return reply

            # ── WhatsApp Unread Result ──
            if action_msg.startswith("WHATSAPP_UNREAD_RESULT"):
                parts = action_msg.split("|")
                count = int(parts[1]) if len(parts) > 1 else 0
                data  = parts[2] if len(parts) > 2 else ""

                if count == 0:
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: WhatsApp check kiya — koi naya individual message nahi hai. "
                        f"Natural Hinglish mein batao. Short response.]"
                    )
                else:
                    contacts_info = []
                    unread_names  = []
                    for entry in data.split(";;"):
                        parts_e = entry.split(":")
                        name    = parts_e[0] if len(parts_e) > 0 else "?"
                        cnt     = parts_e[1] if len(parts_e) > 1 else "1"
                        preview = parts_e[2] if len(parts_e) > 2 else ""
                        contacts_info.append(f"{name} ({cnt} messages)")
                        unread_names.append(name)
                    self.last_unread_contacts = unread_names

                    contacts_list = ", ".join(contacts_info)
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: WhatsApp check kiya — {count} log se naya message aaya hai: "
                        f"{contacts_list}. "
                        f"User ko naturally batao ki kinse message aaye, aur poochho kiska padhna hai. "
                        f"Short Hinglish response.]"
                    )

                reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                self.conversation_history.append({"role": "user",      "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                self._trim_history()
                tracer.turn_end(reply)
                return reply

            # ── Security Blocked Result ──
            if action_msg.startswith("SYSTEM_RESULT|access_denied|"):
                instruction = action_msg.split("|")[2]
                augmented = f"{user_message}\n\n[System: {instruction}. CRITICAL RULE: Apne response mein KABHI BHI actual password repeat mat karna!]"
                
                reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                self._trim_history()
                return reply
                
            # ── Security Success Result ──
            if action_msg.startswith("SYSTEM_RESULT|security_update|"):
                instruction = action_msg.split("|")[2]
                augmented = f"{user_message}\n\n[System: {instruction}. CRITICAL RULE: Apne response mein KABHI BHI actual password repeat mat karna!]"
                
                reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                self._trim_history()
                return reply

            # ── Local File Search Result ──
            if action_msg.startswith("SYSTEM_RESULT|find_file|"):
                data = action_msg.split("|")[2]
                
                if "nahi mili" in data or "nahi mila" in data:
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: File search ki par '{data}'. "
                        f"User ko naturally batao ki file nahi mil rahi, shayad delete ho gayi hai ya naam alag hai.]"
                    )
                else:
                    files_list = data.split(";;")
                    formatted_files = "\n".join([f"- {f}" for f in files_list])
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: Local system mein ye files mili hain:\n{formatted_files}\n\n"
                        f"User ko naturally batao ki file kahan save hai. "
                        f"Agar ek se zyada hain, toh paths clear karke batao taaki user ko easily mil jaye.]"
                    )
                
                reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                self._trim_history()
                tracer.turn_end(reply)
                return reply

            # ── WhatsApp Read Result ──
            if action_msg.startswith("WHATSAPP_READ_RESULT"):
                parts   = action_msg.split("|")
                contact = parts[1] if len(parts) > 1 else "?"
                count   = int(parts[2]) if len(parts) > 2 else 0
                data    = parts[3] if len(parts) > 3 else ""

                if count == 0:
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: '{contact}' ka chat khola — koi readable message nahi mili. "
                        f"Natural Hinglish mein batao. Short response.]"
                    )
                else:
                    formatted_msgs = []
                    read_messages_list = []
                    for entry in data.split(";;"):
                        parts_e = entry.split(">")
                        sender = parts_e[0] if len(parts_e) > 0 else "them"
                        text   = parts_e[1] if len(parts_e) > 1 else ""
                        time_  = parts_e[2] if len(parts_e) > 2 else ""
                        who = contact if sender == "them" else "Tum (Manish)"
                        time_str = f" ({time_})" if time_ else ""
                        formatted_msgs.append(f"{who}{time_str}: {text}")
                        read_messages_list.append({"sender": sender, "text": text, "time": time_})
                    self.last_read_contact  = contact
                    self.last_read_messages = read_messages_list

                    msgs_text = "\n".join(formatted_msgs)
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: '{contact}' ke last {count} messages padhe:\n"
                        f"{msgs_text}\n\n"
                        f"User ko messages dikhao naturally — sender aur text clearly batao. "
                        f"End mein poochho 'reply karna hai kya?' ya 'kuch bolna hai isko?'. "
                        f"Hinglish mein, warm tone. Messages ko format mein dikhao "
                        f"(emoji use karo for incoming/outgoing).]"
                    )

                reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                self.conversation_history.append({"role": "user",      "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                self._trim_history()
                tracer.turn_end(reply)
                return reply

            # ── Contact Missing ──
            if "CONTACT_MISSING" in action_msg:
                augmented = (
                    f"{user_message}\n\n"
                    f"[System: WhatsApp message bhejne ke liye contact naam nahi samajh paayi. "
                    f"User se naturally poochho ki kisko bhejun. Short Hinglish response.]"
                )
                reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                self.conversation_history.append({"role": "user",      "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                self._trim_history()
                tracer.turn_end(reply)
                return reply

            # ── WhatsApp confirmation flow ──
            wa_confirm = self._check_whatsapp_confirmation(action_msg)
            if wa_confirm is not None:
                _, contact, content, kind = wa_confirm

                if kind == "message":
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: WhatsApp message draft kiya hai '{contact}' ke liye:\n"
                        f"\"{content}\"\n"
                        f"User se confirmation maango -- short, natural Hinglish mein. "
                        f"Pehle draft dikhao, fir poochho 'send kar du?'. "
                        f"Apni taraf se kuch add mat karo, jo draft hai bas wahi dikhao.]"
                    )
                else:
                    augmented = (
                        f"{user_message}\n\n"
                        f"[System: WhatsApp pe '{contact}' ko '{content}' file bhejni hai. "
                        f"User se confirm maango -- ZAROOR clearly mention karo ki KISKO bhej rhi ho "
                        f"('{contact}') aur KYA file bhej rhi ho ('{content}'). "
                        f"Short Hinglish mein poochho.]"
                    )

                reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
                self.conversation_history.append({"role": "user",      "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
                self._trim_history()
                tracer.turn_end(reply)
                return reply

            # ── Normal action result ──
            status = "successfully completed" if success else "failed"
            augmented = (
                f"{user_message}\n\n"
                f"[System: Action {status} -- {action_msg}. "
                f"Natural tone mein confirm karo, short response.]"
            )
            reply = self._llm_call(system_prompt, self.conversation_history, augmented, tier="premium")
        else:
            reply = self._llm_call(system_prompt, self.conversation_history, user_message, tier="premium")

        self.conversation_history.append({"role": "user",      "content": user_message})
        self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(reply)})
        self._trim_history()

        tracer.turn_end(reply)
        return reply

    # Add this inside LisaAgent class in core/agent.py
    def chat_stream(self, user_message: str):
        """Streams the response for real-time TTS processing."""
        from core.llm_client import call_llm_stream
        from core.tracer import tracer
        
        tracer.turn_start(user_message)
        
        # 1. Routing & Action Check (identical to normal chat)
        action_done, action_result = self._handle_routing(user_message)
        if action_done and not action_result:
            return  # Action handled entirely, no chat needed

        context_blocks = []
        if action_result:
            context_blocks.append(f"[System Action Result: {action_result}]")

        # 2. Memory & RAG (identical to normal chat)
        from memory.long_term import get_all_memories
        from memory.rag_memory import query_chats
        
        mem_str = get_all_memories(user_message, top_k=3)
        if mem_str: context_blocks.append(f"[Core Memories]\n{mem_str}")
        
        rag_str = query_chats(user_message, top_k=2)
        if rag_str: context_blocks.append(f"[Past Conversation Style]\n{rag_str}")

        # 3. Prompt Construction
        system_prompt = self._build_system_prompt()
        if context_blocks:
            user_message = "\n\n".join(context_blocks) + "\n\nUser: " + user_message

        # 4. Stream and Yield
        full_reply = ""
        for chunk in call_llm_stream(system_prompt, self.conversation_history, user_message):
            full_reply += chunk
            yield chunk

        # 5. Save State
        self.conversation_history.append({"role": "user", "content": user_message})
        # Note: assuming _strip_audio_tags_agent is defined in agent.py
        self.conversation_history.append({"role": "assistant", "content": _strip_audio_tags_agent(full_reply)})
        self._trim_history()
        
        tracer.turn_end(full_reply)

    # ── Session end ───────────────────────────────────────────────────

    def end_session(self) -> None:
        try:
            from actions.whatsapp_actions import close_driver
            close_driver()
        except Exception:
            pass

        if len(self.conversation_history) >= 4:
            print(f"\n  [Memory] Session khatam -- smart update chal raha hai...")
            self._extract_and_update_memory(self.conversation_history)

    # ── Utilities ─────────────────────────────────────────────────────

    def save_fact(self, category: str, key: str, value: str) -> None:
        save_memory(category, key, value)
        print(f"  [Memory saved] {category}/{key}: {value}")

    def get_mode(self)  -> str: return self.mode
    def get_mood(self)  -> str: return self.current_mood

    def reset_conversation(self) -> None:
        self.conversation_history = []
        self.turn_count           = 0
        self.pending_whatsapp     = None
        self.pending_file         = None
        self.last_read_contact    = None
        self.last_read_messages   = []
        self.last_unread_contacts = []
        reset_recent()
        print("  [Conversation reset]")