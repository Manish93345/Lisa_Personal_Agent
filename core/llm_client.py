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
from core.llm_keys import key_manager
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
    "gemini":   "gemini-2.5-flash",        # Chat ke liye
    "groq":     "openai/gpt-oss-120b", # Groq for Chat Fallback AND Intent
    "claude":   "claude-haiku-4-5-20251001",
}

# Local model assignments (Ollama — runs on RTX 3050, zero quota cost)
LOCAL_MODELS = {
    "intent":   "qwen2.5:3b",   # JSON output ke liye best
    "drafting": "gemma3:4b",    # Hinglish tone better
    "memory":   "llama3.2:3b",  # Fast extract
    "default":  "qwen2.5:3b",
}

# Intent detection provider priority (Flash-Lite first — it has 3x more RPM)
INTENT_PROVIDER_PRIORITY = ["groq", "gemini"]

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
    temperature: float = 0.72,
    max_tokens: int = 280,
    tier: str = "premium",
    task: str = "default",
) -> str:
    """Routes to correct model and handles Auto-Rotation of API Keys."""
    
    if tier == "local":
        return _ollama(
            system_prompt, conversation_history, user_message,
            temperature, max_tokens,
            model=LOCAL_MODELS.get(task, LOCAL_MODELS["default"]),
        )

    # Maximum attempts = total keys (Gemini + Groq combined)
    max_attempts = len(key_manager.accounts) * 2
    last_err = None

    for attempt in range(max_attempts):
        provider, current_key = key_manager.get_current_provider_and_key()
        
        # Determine model variant
        if tier == "intent" and provider == "gemini":
            model_type = "gemini_lite"
        else:
            model_type = provider

        try:
            result = _call_cloud(
                model_type, system_prompt, conversation_history,
                user_message, temperature, max_tokens, api_key=current_key
            )
            print(f"  [LLM] ✓ served by {provider.upper()} ({model_type})")
            return result
        except RateLimitError as e:
            print(f"  [LLM] {provider.upper()} rate-limited. Rotating to next key...")
            key_manager.mark_current_exhausted()
            last_err = e
            time.sleep(1)
            continue
        except Exception as e:
            print(f"  [LLM/{provider}] error: {e} — rotating instead of giving up")
            key_manager.mark_current_exhausted()
            last_err = e
            time.sleep(1)
            continue

    print("  [LLM] All cloud providers/keys exhausted — falling back to local Ollama")
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

def _call_cloud(provider, sys_p, hist, user_msg, temp, max_t, api_key):
    if provider == "groq":
        return _groq(sys_p, hist, user_msg, temp, max_t, api_key)
    if provider in ("gemini", "gemini_lite"):
        return _gemini(sys_p, hist, user_msg, temp, max_t, api_key, provider=provider)
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

def _groq(system_prompt, history, user_message, temperature, max_tokens, api_key):
    from groq import Groq, RateLimitError as GroqRL
    if not api_key:
        raise RuntimeError("Groq API key missing from rotation manager")

    model = CLOUD_CHAT_MODELS["groq"]
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

def _gemini(system_prompt, history, user_message, temperature, max_tokens, api_key, provider="gemini"):
    from google import genai
    if not api_key:
        raise RuntimeError("Gemini API key missing from rotation manager")

    model  = CLOUD_CHAT_MODELS.get(provider, CLOUD_CHAT_MODELS["gemini"])
    client = genai.Client(api_key=api_key)

    contents = []
    for msg in history:
        role = "model" if msg.get("role") in ("assistant", "model") else "user"
        contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    _SAFETY_OFF = [
        {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    _gemini_max_tokens = max(512, max_tokens)

    try:
        r = client.models.generate_content(
            model    = model,
            contents = contents,
            config   = {
                "system_instruction": system_prompt,
                "max_output_tokens":  _gemini_max_tokens,
                "temperature":        temperature,
                "thinking_config":    {"thinking_budget": 0},
                "safety_settings":    _SAFETY_OFF,
            },
        )
        reply = (r.text or "").strip()
        if not reply:
            # Gemini ne blank/blocked response diya (safety filter, empty
            # candidate, etc.) — RateLimitError raise karo taaki outer loop
            # Groq pe rotate kare, seedha local pe crash na ho
            raise RateLimitError(
                f"Gemini returned empty response (possible safety block). "
                f"finish_reason={getattr(r.candidates[0], 'finish_reason', '?') if getattr(r, 'candidates', None) else '?'}"
            )
        _track(
            f"gemini:{model}",
            _approx_tokens(system_prompt + user_message),
            _approx_tokens(reply),
        )
        return reply
    except Exception as e:
        err = str(e)
        # 🚨 Added '503' and 'unavailable' so it triggers your rotation cycle instead of breaking to Ollama
        if "429" in err or "503" in err or "unavailable" in err.lower() or "quota" in err.lower() or "resource_exhausted" in err.lower():
            raise RateLimitError(err)
        raise


# ── Cerebras ────────────────────────────────────────────────────────────

# def _cerebras(system_prompt, history, user_message, temperature, max_tokens):
#     from cerebras.cloud.sdk import Cerebras
#     api_key = os.getenv("CEREBRAS_API_KEY")
#     if not api_key:
#         raise RuntimeError("CEREBRAS_API_KEY missing")

#     model = CLOUD_CHAT_MODELS["cerebras"]
#     client = Cerebras(api_key=api_key)

#     messages = [{"role": "system", "content": system_prompt}]
#     for msg in history:
#         role = "assistant" if msg.get("role") == "model" else msg.get("role", "user")
#         messages.append({"role": role, "content": msg.get("content", "")})
#     messages.append({"role": "user", "content": user_message})

#     try:
#         r = client.chat.completions.create(
#             model       = model,
#             messages    = messages,
#             temperature = temperature,
#             max_tokens  = max_tokens,
#         )
#         reply = r.choices[0].message.content.strip()
#         _track(
#             f"cerebras:{model}",
#             _approx_tokens(system_prompt + user_message),
#             _approx_tokens(reply),
#         )
#         return reply
#     except Exception as e:
#         if "429" in str(e) or "rate" in str(e).lower() or "limit" in str(e).lower():
#             raise RateLimitError(str(e))
#         raise


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


def call_llm_stream(system_prompt, history, user_message, temperature=0.72, max_tokens=280):
    """Streams the LLM response token-by-token using the currently active Key."""
    import os
    from google import genai
    from core.llm_keys import key_manager
    
    provider, current_key = key_manager.get_current_provider_and_key()
    
    # Simple fallback check for streaming: if current active is groq, we still force Gemini for stream
    # or handle it gracefully. For now, just grab a Gemini key from the first account.
    if provider == "groq":
        current_key = key_manager.accounts[key_manager.current_account_idx]["gemini"]

    client = genai.Client(api_key=current_key)
    model_name = CLOUD_CHAT_MODELS.get("gemini", "gemini-2.5-flash")

    contents = []
    for msg in history:
        role = "user" if msg.get("role") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    try:
        response = client.models.generate_content_stream(
            model=model_name,
            contents=contents,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text
    except Exception as e:
        print(f"  [LLM Stream Error]: {e}")
        yield "Abhi thoda network issue hai, please try again."