"""
LISA — LLM Client (Centralized Multi-Provider + Local Ollama + Auto-Rotation)
==============================================================================
[Phase 0 — Step 1 Changes]
  1. PROVIDER_PRIORITY default changed to gemini-first (gemini, groq, cerebras)
  2. gemini-2.0-flash → gemini-2.5-flash  (2.0-flash was SHUT DOWN June 1 2026)
  3. Added gemini-2.5-flash-lite as dedicated intent detection model (30 RPM)
  4. All model names now centralized in CLOUD_CHAT_MODELS — no more hardcoding
     inside individual provider functions (_groq, _gemini, etc.)
  5. Added tier="intent" → routes to gemini-flash-lite first (higher RPM for
     JSON extraction tasks, Flash-Lite has 30 RPM vs Flash's 10 RPM)
  6. Default max_tokens: 400 → 280 (Lisa's best replies are 60-100 words)
  7. Removed dependency on settings.py model dicts (those were dead code)

FREE TIER LIMITS (post Dec 2025 quota reduction):
  gemini-2.5-flash:      10 RPM / 250 RPD / 250,000 TPM
  gemini-2.5-flash-lite: 30 RPM / 1,000 RPD / 250,000 TPM  ← intent detection
  groq llama-3.3-70b:    30 RPM / 6,000 TPM (much less TPM than Gemini)
  cerebras gpt-oss-120b: Fast but limited quota

USAGE:
  - Personal chat (high quality):      get_response(..., tier="premium")
  - Intent detection (cheap/fast):     get_response(..., tier="intent")
  - Memory extract / summarization:    call_llm_simple(..., tier="local")
"""

import os
import time
import json
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Provider tier preference order ──────────────────────────────────────
# .env mein PROVIDER_PRIORITY="gemini,groq,cerebras" override kar sakte ho
# Default is now gemini-first (was cerebras,groq,gemini before Phase 0)
_PRIORITY_ENV = os.getenv("PROVIDER_PRIORITY", "gemini,groq,cerebras")
PROVIDER_PRIORITY = [p.strip() for p in _PRIORITY_ENV.split(",") if p.strip()]

# ── Model assignments (SINGLE SOURCE OF TRUTH — no hardcoding elsewhere) ──
# Chat models — for conversation quality
CLOUD_CHAT_MODELS = {
    "gemini":      "gemini-2.5-flash",        # Primary — 10 RPM / 250K TPM free
    "gemini_lite": "gemini-2.5-flash-lite",   # Intent only — 30 RPM / 250K TPM free
    "groq":        "llama-3.3-70b-versatile", # Fallback — 30 RPM / 6K TPM
    "cerebras":    "gpt-oss-120b",            # Fallback
    "claude":      "claude-haiku-4-5-20251001",
}

# Local model assignments (Ollama — runs on RTX 3050, zero quota cost)
LOCAL_MODELS = {
    "intent":   "qwen2.5:3b",   # JSON output ke liye best
    "drafting": "gemma3:4b",    # Hinglish tone better
    "memory":   "llama3.2:3b",  # Fast extract
    "default":  "qwen2.5:3b",
}

# Intent detection provider priority (Flash-Lite first — it has 3x more RPM)
INTENT_PROVIDER_PRIORITY = ["gemini_lite", "gemini", "groq", "cerebras"]

# ── Token usage tracking ─────────────────────────────────────────────────
TOKEN_LOG_PATH = Path(__file__).parent.parent / "data" / "token_usage.json"

def _load_usage():
    if not TOKEN_LOG_PATH.exists():
        return {"date": str(date.today()), "providers": {}}
    try:
        d = json.loads(TOKEN_LOG_PATH.read_text())
        if d.get("date") != str(date.today()):
            return {"date": str(date.today()), "providers": {}}
        return d
    except Exception:
        return {"date": str(date.today()), "providers": {}}

def _save_usage(usage):
    try:
        TOKEN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_LOG_PATH.write_text(json.dumps(usage, indent=2))
    except Exception:
        pass

def _track(provider: str, in_tok: int, out_tok: int):
    u = _load_usage()
    p = u["providers"].setdefault(provider, {"requests": 0, "in": 0, "out": 0})
    p["requests"] += 1
    p["in"]       += in_tok
    p["out"]      += out_tok
    _save_usage(u)

def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════

def get_response(
    system_prompt: str,
    conversation_history: list,
    user_message: str,
    temperature: float = 0.85,
    max_tokens: int = 280,          # Changed from 400 → 280 (Phase 0 token reduction)
    tier: str = "premium",          # "premium" | "fast" | "intent" | "local"
    task: str = "default",
) -> str:
    """
    Main response function — routes to correct model based on tier.

    tier="premium": cloud 70B (Gemini 2.5 Flash primary) — for Lisa's chat replies
    tier="fast":    same as premium but tries Groq first (lower latency)
    tier="intent":  Gemini Flash-Lite first (30 RPM free) — for JSON intent extraction
    tier="local":   Ollama only (completely free, no quota) — for memory/summarization
    """
    if tier == "local":
        return _ollama(
            system_prompt, conversation_history, user_message,
            temperature, max_tokens,
            model=LOCAL_MODELS.get(task, LOCAL_MODELS["default"]),
        )

    # Select provider order based on tier
    if tier == "intent":
        priority = INTENT_PROVIDER_PRIORITY
    elif tier == "fast":
        # Fast: try groq first (low latency), then gemini as big fallback
        priority = ["groq"] + [p for p in PROVIDER_PRIORITY if p != "groq"]
    else:
        # premium: use configured PROVIDER_PRIORITY (gemini first by default)
        priority = PROVIDER_PRIORITY

    seen = set()
    last_err = None

    for provider in priority:
        if provider in seen:
            continue
        seen.add(provider)

        try:
            return _call_cloud(
                provider, system_prompt, conversation_history,
                user_message, temperature, max_tokens,
            )
        except RateLimitError as e:
            print(f"  [LLM] {provider} rate-limited → trying next provider")
            last_err = e
            continue
        except Exception as e:
            print(f"  [LLM/{provider}] error: {e}")
            last_err = e
            continue

    # All providers failed → local fallback (user never sees dead silence)
    print("  [LLM] All cloud providers failed — falling back to local Ollama")
    return _ollama(
        system_prompt, conversation_history, user_message,
        temperature, max_tokens, model=LOCAL_MODELS["default"],
    )


def call_llm_simple(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.1,
    max_tokens: int = 250,
    tier: str = "local",        # default LOCAL — single-shot tasks ko cloud na de
    task: str = "default",
) -> str:
    """Single-shot call (intent, memory extract, summarization). Defaults to LOCAL."""
    return get_response(
        system_prompt=system_prompt,
        conversation_history=[],
        user_message=user_message,
        temperature=temperature,
        max_tokens=max_tokens,
        tier=tier,
        task=task,
    )


# ══════════════════════════════════════════════════════════════════════
#  Exceptions
# ══════════════════════════════════════════════════════════════════════

class RateLimitError(Exception):
    pass


# ══════════════════════════════════════════════════════════════════════
#  Cloud dispatcher
# ══════════════════════════════════════════════════════════════════════

def _call_cloud(provider, sys_p, hist, user_msg, temp, max_t):
    if provider == "groq":
        return _groq(sys_p, hist, user_msg, temp, max_t)
    if provider in ("gemini", "gemini_lite"):
        # Both use the same function — model string comes from CLOUD_CHAT_MODELS
        return _gemini(sys_p, hist, user_msg, temp, max_t, provider=provider)
    if provider == "cerebras":
        return _cerebras(sys_p, hist, user_msg, temp, max_t)
    if provider == "claude":
        return _claude(sys_p, hist, user_msg, temp, max_t)
    raise ValueError(f"Unknown provider: {provider}")


# ── Ollama (LOCAL) ──────────────────────────────────────────────────────

def _ollama(system_prompt, history, user_message, temperature, max_tokens, model=None):
    """Local Ollama call — http://localhost:11434"""
    try:
        import requests
        model = model or LOCAL_MODELS["default"]

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            role = "assistant" if msg.get("role") in ("model", "assistant") else "user"
            messages.append({"role": role, "content": msg.get("content", "")})
        messages.append({"role": "user", "content": user_message})

        r = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model":    model,
                "messages": messages,
                "stream":   False,
                "options":  {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_ctx":     4096,
                },
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        reply = data.get("message", {}).get("content", "").strip()
        _track(f"ollama:{model}", _approx_tokens(user_message), _approx_tokens(reply))
        return reply
    except Exception as e:
        print(f"  [LLM/Ollama] {e}")
        return "Yaar local model bhi reply nahi de paa rha. Ollama chal rha hai? `ollama serve` kar."


# ── Groq ─────────────────────────────────────────────────────────────────

def _groq(system_prompt, history, user_message, temperature, max_tokens):
    from groq import Groq, RateLimitError as GroqRL
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing")

    model = CLOUD_CHAT_MODELS["groq"]  # centralized — no hardcoding
    client = Groq(api_key=api_key)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "assistant" if msg.get("role") == "model" else msg.get("role", "user")
        messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    try:
        r = client.chat.completions.create(
            model       = model,
            messages    = messages,
            temperature = temperature,
            max_tokens  = max_tokens,
        )
        reply = r.choices[0].message.content.strip()
        usage = r.usage
        _track(f"groq:{model}", usage.prompt_tokens, usage.completion_tokens)
        return reply
    except GroqRL as e:
        raise RateLimitError(str(e))


# ── Gemini 2.5 Flash / Flash-Lite ──────────────────────────────────────

def _gemini(system_prompt, history, user_message, temperature, max_tokens,
            provider: str = "gemini"):
    """
    Handles both gemini (2.5 Flash) and gemini_lite (2.5 Flash-Lite).
    Model string comes from CLOUD_CHAT_MODELS — no hardcoding here.

    Safety settings set to BLOCK_NONE for all categories — required for
    personal companion AI (romantic/emotional Hinglish content triggers
    Gemini's default filter, causing 8-token truncated responses).
    """
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing")

    model  = CLOUD_CHAT_MODELS.get(provider, CLOUD_CHAT_MODELS["gemini"])
    client = genai.Client(api_key=api_key)

    contents = []
    for msg in history:
        role = "model" if msg.get("role") in ("assistant", "model") else "user"
        contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    # Safety settings: BLOCK_NONE for all categories.
    # Without this, Gemini truncates companion AI responses mid-sentence
    # (observed as 8-token outputs ending with a dangling '[' emotion tag).
    _SAFETY_OFF = [
        {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    # Gemini 2.5 Flash has "thinking" enabled by default. Thinking tokens
    # draw from the same max_output_tokens budget. With max_output_tokens=280,
    # thinking consumes ~260-270 tokens leaving only 10-13 for the actual reply
    # → causes finish_reason=MAX_TOKENS at 11 tokens.
    # Fix: disable thinking (not needed for conversational replies) + give
    # enough output budget. Max actual reply tokens = 280, so 512 is safe.
    _gemini_max_tokens = max(512, max_tokens)  # never below 512 for Gemini

    try:
        r = client.models.generate_content(
            model    = model,
            contents = contents,
            config   = {
                "system_instruction": system_prompt,
                "max_output_tokens":  _gemini_max_tokens,
                "temperature":        temperature,
                "thinking_config":    {"thinking_budget": 0},  # disable thinking overhead
                "safety_settings":    _SAFETY_OFF,
            },
        )

        # Detect safety truncation even after BLOCK_NONE (shouldn't happen but log it)
        try:
            finish = r.candidates[0].finish_reason
            if str(finish) not in ("FinishReason.STOP", "STOP", "1"):
                print(f"  [LLM/Gemini] finish_reason={finish} — response may be incomplete")
        except Exception:
            pass

        reply = r.text.strip()
        _track(
            f"gemini:{model}",
            _approx_tokens(system_prompt + user_message),
            _approx_tokens(reply),
        )
        return reply
    except Exception as e:
        err = str(e)
        if "429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower():
            raise RateLimitError(err)
        if "404" in err or "not found" in err.lower():
            print(f"  [LLM/Gemini] Model '{model}' not found: {err}")
        raise


# ── Cerebras ────────────────────────────────────────────────────────────

def _cerebras(system_prompt, history, user_message, temperature, max_tokens):
    from cerebras.cloud.sdk import Cerebras
    api_key = os.getenv("CEREBRAS_API_KEY")
    if not api_key:
        raise RuntimeError("CEREBRAS_API_KEY missing")

    model = CLOUD_CHAT_MODELS["cerebras"]
    client = Cerebras(api_key=api_key)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = "assistant" if msg.get("role") == "model" else msg.get("role", "user")
        messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    try:
        r = client.chat.completions.create(
            model       = model,
            messages    = messages,
            temperature = temperature,
            max_tokens  = max_tokens,
        )
        reply = r.choices[0].message.content.strip()
        _track(
            f"cerebras:{model}",
            _approx_tokens(system_prompt + user_message),
            _approx_tokens(reply),
        )
        return reply
    except Exception as e:
        if "429" in str(e) or "rate" in str(e).lower() or "limit" in str(e).lower():
            raise RateLimitError(str(e))
        raise


# ── Claude ───────────────────────────────────────────────────────────────

def _claude(system_prompt, history, user_message, temperature, max_tokens):
    import anthropic
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise RuntimeError("CLAUDE_API_KEY missing")

    model = CLOUD_CHAT_MODELS["claude"]
    client = anthropic.Anthropic(api_key=api_key)

    messages = []
    for msg in history:
        role = "assistant" if msg.get("role") in ("model", "assistant") else "user"
        messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    r = client.messages.create(
        model       = model,
        max_tokens  = max_tokens,
        system      = system_prompt,
        messages    = messages,
        temperature = temperature,
    )
    reply = r.content[0].text.strip()
    _track(f"claude:{model}", r.usage.input_tokens, r.usage.output_tokens)
    return reply


# ── Helper: print today's usage ──────────────────────────────────────────

def print_usage():
    u = _load_usage()
    print(f"\n  📊 Token usage ({u['date']}):")
    for prov, stats in u.get("providers", {}).items():
        total = stats["in"] + stats["out"]
        print(f"     {prov:40s} {stats['requests']:4d} req | {total:>7,} tok")
    print()