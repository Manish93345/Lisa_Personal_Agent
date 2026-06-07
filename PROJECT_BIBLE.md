# LISA Agent — Complete Project Documentation
## Project Bible / Context File for AI Assistants
**Last Updated**: 2026-05-22

---

## 1. PROJECT OVERVIEW

**LISA** (Personal AI Agent) is a Hinglish-speaking AI companion built for a single user (Manish). She acts as a personal assistant that can:
- Have natural conversations in Hinglish (Hindi + English in Roman script)
- Control system functions (volume, brightness, WiFi, battery, timer, etc.)
- Send WhatsApp messages and files via browser automation
- Find and open files/folders using fuzzy matching
- Open websites, play YouTube, search Google/Spotify
- Remember facts about the user across sessions
- Detect emotional state and adjust tone accordingly

**Tech Stack**: Python 3.12+, Selenium (Edge), SQLite, ChromaDB, Multi-LLM (Groq/Gemini/Cerebras/Claude)  
**Platform**: Windows 10/11 only  
**Virtual Environment**: `lisajaanu/` (Python venv)

---

## 2. FOLDER STRUCTURE

```
LISA_Agent/
│
├── main.py                  # TEXT mode entry point (terminal REPL)
├── voice_main.py            # VOICE mode entry point (mic → STT → LLM → TTS)
├── .env                     # API keys + LLM_PROVIDER (ONLY file to change providers)
├── requirements.txt         # pip dependencies
│
├── config/                  # ── CONFIGURATION ──
│   ├── settings.py          # Central settings — paths, API keys, model names, timeouts
│   └── prompts.py           # Lisa's personality, mood detection, tone adjustments
│
├── core/                    # ── BRAIN ──
│   ├── agent.py             # Main agent class (LisaAgent) — orchestrates everything
│   └── llm_client.py        # CENTRALIZED LLM client — ALL LLM calls go through here
│
├── actions/                 # ── ACTIONS (what Lisa can DO) ──
│   ├── intent_detector.py   # Detects user intent via LLM (→ action type + params)
│   ├── router.py            # Routes detected intents to correct action functions
│   ├── system_actions.py    # System controls (volume, brightness, WiFi, apps, etc.)
│   ├── file_finder.py       # Fuzzy file/folder search across drives
│   ├── desktop_manager.py   # Virtual desktop management (Desktop 3)
│   ├── whatsapp_actions.py  # WhatsApp Web automation (Selenium + Edge)
│   ├── wa_send_action.py    # WhatsApp message drafting (tone-aware) + contacts
│   ├── web_actions.py       # Web Intelligence (weather, news, search, knowledge)
│   └── VirtualDesktopAccessor.dll  # Native DLL for virtual desktop switching
│
├── memory/                  # ── MEMORY ──
│   ├── long_term.py         # SQLite-based persistent memory (facts, incidents, sessions)
│   ├── memory_extractor.py  # Auto-extracts facts from conversation via LLM
│   └── rag_memory.py        # RAG — retrieves past conversation style for consistency
│
├── voice/                   # ── VOICE ──
│   ├── stt.py               # Speech-to-Text (Groq Whisper)
│   ├── tts.py               # Text-to-Speech (gTTS / edge-tts)
│   └── kokoro_models/       # Local TTS model files
│
├── data/                    # ── PERSISTENT DATA ──
│   ├── contacts.json        # WhatsApp contacts + relationship types
│   ├── memory/              # SQLite database (lisa_memory.db)
│   ├── vectordb/            # ChromaDB embeddings for RAG
│   └── whatsapp_profile/    # Edge browser profile for WhatsApp Web
│
├── training/                # ── RAG TRAINING ──
│   ├── clean_chats.py       # Clean raw chat exports
│   ├── embedder.py          # Generate embeddings from cleaned chats
│   └── data/                # Raw/cleaned chat data files
│
├── docs/plans/              # ── DOCUMENTATION ──
│   ├── 004_next_steps_roadmap.md
│   └── 005_whatsapp_file_send.md
│
├── Desktop_Switch_repo/     # External: virtual desktop switching utility
└── lisajaanu/               # Python virtual environment (DO NOT modify)
```

---

## 3. ARCHITECTURE — HOW IT ALL WORKS

### 3.1 Message Flow (Text Mode)

```
User types message
      │
      ▼
  main.py  ──→  LisaAgent.chat(user_input)
                      │
                      ├── 1. Mood Detection (prompts.py)
                      │      └── keyword-based: sad/happy/anxious/angry/flirty/neutral
                      │
                      ├── 2. Intent Detection (intent_detector.py)
                      │      └── LLM call → returns {action, params, confidence}
                      │
                      ├── 3. Action Routing (router.py)
                      │      └── Maps action → function, passes params
                      │      └── Returns (bool, result_string) or None
                      │
                      ├── 4. If action found → execute + tell user result
                      │   If no action → go to step 5
                      │
                      ├── 5. Build System Prompt
                      │      ├── Personality base (personal/professional mode)
                      │      ├── Mood-specific tone adjustments
                      │      ├── Long-term memories (SQLite)
                      │      └── RAG style context (past conversations)
                      │
                      ├── 6. LLM Chat Response (llm_client.py)
                      │      └── get_response(system_prompt, history, user_msg)
                      │
                      └── 7. Memory Extraction (every 8 turns)
                             └── Auto-saves facts from conversation
```

### 3.2 WhatsApp Flow (Confirmation Required)

```
User: "aniket ko message bhejo ki kal milte hain"
      │
      ▼
  Intent: whatsapp_message → {contact: "aniket", message: "kal milte hain"}
      │
      ▼
  wa_send_action.py → drafts message with correct tone (friend/elder/etc.)
      │
      ▼
  agent.py → shows draft → asks "confirm karo"
      │
      ▼
  User: "haan bhej do"
      │
      ▼
  whatsapp_actions.py → opens Edge → finds contact → sends message
```

### 3.3 WhatsApp File Flow

```
User: "downloads mein admit card hai, sugri ko bhej do"
      │
      ▼
  Intent: whatsapp_file → {contact: "sugri", folder: "downloads", file: "admit card"}
      │
      ▼
  file_finder.py → fuzzy search → finds "sikil_admit_card.pdf"
      │
      ▼
  agent.py → confirms file + contact with user
      │
      ▼
  whatsapp_actions.py → opens Edge → finds contact → attaches file → sends
```

---

## 4. KEY DESIGN DECISIONS

### 4.1 Centralized LLM System
- **ALL LLM calls** go through `core/llm_client.py`
- Two public functions:
  - `get_response(system_prompt, history, user_msg, temperature, max_tokens)` — chat with history
  - `call_llm_simple(system_prompt, user_msg, temperature, max_tokens)` — single-shot (intent, memory, drafting)
- Provider switching: **ONLY change `.env`** — `LLM_PROVIDER=groq|gemini|cerebras|claude`
- NO provider logic exists in any other file

### 4.2 Safety-First WhatsApp
- **85% fuzzy match threshold** for contact names (better to fail than send to wrong person)
- **Mandatory user confirmation** before every message/file send
- Confirmation prompt explicitly states contact name + content
- Saved contact names prioritized over generic words ("dost", "friend")

### 4.3 Singleton WhatsApp Driver
- `whatsapp_actions.py` uses a singleton `WhatsAppDriver`
- Dedicated Edge profile (`data/whatsapp_profile/`) — doesn't disturb user's main browser
- QR scan needed once, then session persists

### 4.4 Intent Detector
- LLM-based (not regex) — handles natural Hinglish with filler words
- Returns: `{"action": "...", "params": {...}, "confidence": 0.95}`
- **FILLER WORDS RULE**: ignores "jaanu", "baby", "suno", "please" etc. — focuses on action keywords
- 16 action types currently supported

### 4.5 Memory Architecture
```
SHORT TERM:  conversation_history (in-memory list, max 8 turns)
MEDIUM TERM: RAG embeddings (ChromaDB) — past conversation style matching
LONG TERM:   SQLite database — facts, incidents, session summaries
```

---

## 5. SUPPORTED ACTIONS (Intent Types)

| Action | Description | Example |
|--------|-------------|---------|
| `open_website` | Open any website | "youtube khol do" |
| `play_youtube` | Play video/song on YouTube | "Arijit ka gaana chala do" |
| `search_youtube` | Search YouTube | "YouTube pe react course search karo" |
| `search_spotify` | Open Spotify search | "Spotify pe Dil Dooba chala do" |
| `open_app` | Open desktop application | "calculator khol do" |
| `search_google` | Google search | "Google pe Python tutorial search karo" |
| `open_folder` | Open specific folder | "D drive khol do" |
| `open_file` | Open specific file | "resume.pdf khol do" |
| `find_file` | Fuzzy search for file/folder | "Free Fire folder mein divya ki photo dhundho" |
| `whatsapp_message` | Send WhatsApp message | "aniket ko bolo kal milte hain" |
| `whatsapp_file` | Send file via WhatsApp | "downloads mein admit card sugri ko bhej do" |
| `whatsapp_unread` | Check for unread messages | "koi naya message aaya?" |
| `whatsapp_read` | Read specific contact's messages | "sugri ne kya bola?" |
| `web_search` | Weather, news, search, knowledge | "aaj weather kaisa hai?", "koi news bata do" |
| `system_command` | System controls | "volume 70 karo", "battery kitni hai" |
| `none` | Just conversation | "kaisi ho tum" |

### System Commands (sub-actions)
| Command | Keywords | Method |
|---------|----------|--------|
| Screenshot | "screenshot" | PowerShell screen capture |
| Volume Up/Down | "volume badhao/kam" | WScript.Shell SendKeys |
| Volume Set % | "volume 70" | pycaw (Windows Audio API) |
| Mute | "mute" | WScript.Shell SendKeys |
| Brightness | "brightness 50", "roshni kam" | WMI PowerShell |
| WiFi On/Off | "WiFi band/chalu karo" | netsh interface |
| Battery | "battery kitni hai" | WMI Win32_Battery |
| Timer | "5 minute ka timer" | threading.Timer + beep |
| Close App | "chrome band karo" | taskkill |
| Lock Screen | "screen lock karo" | rundll32 LockWorkStation |
| Shutdown | "shutdown karo" | shutdown /s /t 30 |
| Restart | "restart karo" | shutdown /r /t 30 |
| Sleep | "sleep mode" | powrprof.dll |

---

## 6. FILE-BY-FILE REFERENCE

### `main.py` — Text Mode Entry Point
- Terminal REPL loop: `User → agent.chat() → print response`
- Handles slash commands: `/quit`, `/mode`, `/memories`, `/remember`, `/reset`, `/extract`

### `voice_main.py` — Voice Mode Entry Point
- Mic recording → Groq Whisper STT → LisaAgent.chat() → gTTS/edge-tts → speaker

### `config/settings.py` — Central Settings
- ALL paths, API keys, model names, timeouts, delays
- `.env` values loaded here via `python-dotenv`
- **Change API keys/provider HERE or in .env — nowhere else**

### `config/prompts.py` — Personality Engine
- Lisa's base personality prompt (personal + professional modes)
- Keyword-based mood detection → tone adjustment strings
- Mode switch triggers (personal ↔ professional)

### `core/agent.py` — LisaAgent Class
- **The brain** — orchestrates everything
- Maintains: conversation history, mood state, pending WhatsApp confirmations
- Smart reply: `last_read_contact` + `last_read_messages` for "usko reply karo" resolution
- **Unread context tracking**: `last_unread_contacts` stores names from unread scan → resolves "didi ko reply karo" by matching name against recent unread contacts
- Flow: mood detect → smart reply detect (pronoun + unread context) → intent detect → route action → LLM response → memory extract
- WhatsApp confirmation flow: pending_whatsapp dict → user confirms → execute
- WhatsApp read results: formats messages for display, stores context for replies
- **CONTACT_MISSING handling**: when intent detector returns empty contact, asks user "kisko bhejun?" instead of matching random contact

### `core/llm_client.py` — Centralized LLM Client
- **SINGLE SOURCE OF TRUTH for all LLM calls**
- Supports: Groq (llama-3.3-70b), Gemini (2.0-flash), Cerebras (llama3.1-8b), Claude (haiku-4-5)
- All other files import `get_response()` or `call_llm_simple()` from here

### `actions/intent_detector.py` — Intent Detection
- Massive system prompt with 40+ examples for all action types
- Disambiguation rules (find_file vs play_youtube, close app vs open app)
- Filler words rule for casual Hinglish
- Contact name extraction rules for WhatsApp
- **Reply disambiguation**: explicit rules for "didi ko reply karo" (contact="didi") vs "usko reply karo" (contact="", resolved by agent.py)

### `actions/router.py` — Action Router
- Maps intent action strings → Python functions
- Special parameter handling for find_file, whatsapp_message, whatsapp_file, whatsapp_unread, whatsapp_read
- Minimum confidence threshold: 75%

### `actions/system_actions.py` — System Controls
- All system-level actions (volume, brightness, WiFi, battery, etc.)
- Also handles: website open, YouTube play, app open, folder open, file find
- Uses pycaw for precise volume control, PowerShell for system queries

### `actions/file_finder.py` — Fuzzy File Search
- Scans common directories (Desktop, Downloads, Documents, D:/)
- Nested folder chain support: "study/sem 6/software engineering"
- Uses `rapidfuzz` for fuzzy string matching (configurable thresholds)

### `actions/whatsapp_actions.py` — WhatsApp Automation (largest file)
- Selenium WebDriver with dedicated Edge profile
- Singleton pattern — one browser instance reused
- Contact search with 85% fuzzy match threshold
- Message sending: type → confirm → send
- File sending: click '+' → Document → OS file picker → send
- **Unread check**: sidebar scan for green badge, filter groups out (individuals only)
- **Message reading**: open chat → extract last 10 messages with sender direction
- Native dialog handling via PowerShell (OS-level ESC for file picker)
- **Empty contact guard**: rejects blank/empty contact with `CONTACT_MISSING` signal → prevents sending to wrong person

### `actions/wa_send_action.py` — WhatsApp Message Drafting
- Tone-aware message drafting based on relationship type
- Contact lookup from `data/contacts.json`
- Auto-learns new contacts with relationship guessing
- Tone types: friend, elder_family, family, senior, colleague, default
- **Empty name guard**: `get_contact_info("")` returns default instead of matching first contact (Python `"" in "name"` = True bug fix)

### `voice/stt.py` — Speech-to-Text (Groq Whisper)
- Forces `language="hi"` to prevent Whisper drifting to Gujarati/Urdu
- Strong Hinglish prompt biases vocabulary toward voice-command words
- 3-stage normalize: wrong-script repair → final script choice → whitespace
- `STT_OUTPUT_SCRIPT` env var controls final output:
  - `"deva"` (default since 2026-05-24) → Devanagari + English mixed (matches TTS)
  - `"roman"` → transliterates Devanagari to Roman (legacy)

### `voice/tts.py` — Text-to-Speech (Sarvam Bulbul V3 + edge-tts + gTTS fallback)
- Provider chain: Sarvam → edge-tts → gTTS (auto-fallback)
- Default voice: `shreya` (warm, expressive, romantic)
- Pace: 0.95 (slightly slowed for intimate companion tone)
- Strips emojis, keeps Devanagari (TTS handles mixed script natively)

### `memory/long_term.py` — SQLite Persistent Memory
- Tables: `memories` (category/key/value) + `sessions` (summaries)
- Categories: personal, academic, incident, preference, goal, health
- Auto-dedup on (category, key) — updates if exists
- Session summaries: keeps last 20

### `memory/memory_extractor.py` — Auto Memory Extraction
- Runs every 8 conversation turns
- LLM extracts facts from conversation → saves to SQLite
- Uses `call_llm_simple()` from centralized client

### `memory/rag_memory.py` — RAG Style Memory
- ChromaDB vector database with Gemini embeddings
- Retrieves past conversation snippets matching current topic
- Helps Lisa maintain consistent speaking style
- Lazy Gemini client init — won't crash if API key missing

---

## 7. HOW TO ADD A NEW FEATURE

### 7.1 Adding a New System Command

**Example**: Adding a "dark mode toggle"

1. **`actions/system_actions.py`** — Add handler in `system_command()`:
```python
# Add this elif block in the system_command() function chain
elif any(x in q for x in ["dark mode", "night mode", "andhera"]):
    try:
        subprocess.run(["powershell", "-c", "...your command..."], timeout=5)
        return True, "dark mode on kar diya!"
    except Exception:
        return False, "dark mode nahi hua"
```

2. **`actions/intent_detector.py`** — Add examples in the SYSTEM COMMANDS section:
```
"dark mode on karo" -> {"action": "system_command", "params": {"query": "dark mode on"}, "confidence": 0.95}
"night mode laga do" -> {"action": "system_command", "params": {"query": "dark mode on"}, "confidence": 0.95}
```

That's it! No other files need changes for system commands.

### 7.2 Adding a New Action Type (e.g., whatsapp_read)

1. **`actions/intent_detector.py`**:
   - Add action type in the "Action types" list
   - Add example mappings
   
2. **`actions/your_new_module.py`** (or add to existing):
   - Create the action function: `def your_action(params) -> tuple[bool, str]`
   - Must return `(True, "success msg")` or `(False, "error msg")`

3. **`actions/router.py`**:
   - Import the function
   - Add to `ACTION_MAP`: `"your_action": your_function`
   - If special params needed, add to `SPECIAL_PARAM_ACTIONS` set

4. **If confirmation flow needed** (like WhatsApp):
   - Handle in `core/agent.py` in the `chat()` method
   - Set `self.pending_whatsapp` or a similar dict

### 7.3 Adding a New LLM Provider

**ONLY modify** `core/llm_client.py`:

1. Add a new `_newprovider()` function following the existing pattern
2. Add the `elif PROVIDER == "newprovider":` case in `_call_provider()`
3. Add model name to `config/settings.py` CHAT_MODELS and INTENT_MODELS dicts
4. Add API key to `.env` and `config/settings.py`

**NO other files need changes.**

---

## 8. CODING CONVENTIONS

### 8.1 Return Format for Actions
ALL action functions MUST return: `tuple[bool, str]`
```python
def my_action(query: str) -> tuple[bool, str]:
    return True, "kaam ho gaya!"    # success
    return False, "nahi hua yaar"   # failure
```

### 8.2 Language Style
- Code comments: Hinglish or English (whatever is clearer)
- Print logs: `[ModuleName] message` format (e.g., `[WhatsApp] Searching...`)
- User-facing strings: Hinglish (Roman script, NEVER Devanagari)

### 8.3 LLM Calls
- **ALWAYS** use `core/llm_client.py` functions
- NEVER create provider-specific clients in other files
- For chat with history: `get_response(system_prompt, history, user_msg)`
- For single-shot: `call_llm_simple(system_prompt, user_msg, temperature, max_tokens)`

### 8.4 Error Handling
- Actions: catch exceptions, return `(False, "error message")`
- LLM calls: return fallback string on error, don't crash
- WhatsApp: catch `BaseException` (not just `Exception`) for Ctrl+C handling

### 8.5 Config Changes
- Provider switching: `.env` → `LLM_PROVIDER=xxx` + API key
- Behavioral settings: `config/settings.py`
- Personality changes: `config/prompts.py`
- Contact info: `data/contacts.json`

---

## 9. DEPENDENCIES

```
# Core
python-dotenv       # .env file loading
chromadb            # Vector database for RAG
google-genai        # Gemini API (embeddings + optional chat)
groq                # Groq API (Llama models)
selenium            # Browser automation
webdriver-manager   # Auto-download Edge WebDriver

# Audio/Volume
pycaw               # Windows audio control (volume set)
sounddevice         # Microphone recording
gTTS                # Text-to-speech
pygame              # Audio playback

# Utilities
rapidfuzz           # Fuzzy string matching
pyperclip           # Clipboard operations
pyautogui           # GUI automation helpers
pywin32             # Windows API access
```

---

## 10. ENVIRONMENT SETUP

```bash
# 1. Create venv
python -m venv lisajaanu
lisajaanu\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure .env
LLM_PROVIDER=groq          # or gemini, cerebras, claude
GROQ_API_KEY=gsk_xxx       # if using groq
GEMINI_API_KEY=AIza_xxx    # always needed (for RAG embeddings)

# 4. Run
python main.py             # text mode
python voice_main.py       # voice mode
```

---

## 11. CURRENT STATUS (May 2026)

| Feature | Status |
|---------|--------|
| Web Intelligence (Weather) | ✅ Working (wttr.in, Aurangabad Bihar default) |
| Web Intelligence (News) | ✅ Working (Google News RSS, category support) |
| Web Intelligence (Search) | ✅ Working (DuckDuckGo + LLM fallback) |
| Web Intelligence (Knowledge) | ✅ Working (LLM-powered explanations) |
|---------|--------|
| Natural Hinglish Conversation | ✅ Working |
| Multi-LLM (Groq/Gemini/Cerebras/Claude) | ✅ Working |
| Centralized Provider Switching (.env only) | ✅ Working |
| Mood Detection + Tone Adjustment | ✅ Working |
| Long-term Memory (SQLite) | ✅ Working |
| RAG Style Memory (ChromaDB) | ✅ Working |
| Auto Memory Extraction | ✅ Working |
| File Finder (fuzzy search) | ✅ Working |
| WhatsApp Messaging (confirm flow) | ✅ Working |
| WhatsApp File Send | ✅ Working |
| WhatsApp Read Unread | ✅ Working |
| WhatsApp Read Messages | ✅ Working |
| WhatsApp Smart Reply (tone-aware) | ✅ Working |
| WhatsApp Reply Context Resolution | ✅ Working (unread scan + pronoun + explicit name) |
| Contact Safety Guards | ✅ Working (empty name guard + CONTACT_MISSING flow) |
| System Controls (volume, brightness, etc.) | ✅ Working |
| Volume Set Exact % (pycaw) | ✅ Working |
| Battery/WiFi/Timer/Lock/Shutdown | ✅ Working |
| Close App (taskkill) | ✅ Working |
| Voice Mode (STT + TTS) | ✅ Working (separate entry) |
| Desktop 3 (background operations) | ⚠️ Partial (~70%) |

---

## 12. ROADMAP (Next Features)

1. ~~**WhatsApp Read & Reply**~~ — ✅ DONE (read unreads, read messages, smart reply)
2. ~~**Reply Interpretation Fix**~~ — ✅ DONE (unread context, empty guard, CONTACT_MISSING)
3. ~~**Web Intelligence**~~ — ✅ DONE (weather, news, search, knowledge)
4. **Voice + Text Unified Mode** — single entry point for both
5. **Smart Context & Task Chaining** — "ye file aniket ko bhi bhej do"
6. **Desktop 3 Reliability** — improve background window management
7. **Tiered LLM** — local model for simple tasks + cloud for complex
8. **Phone Integration** — call handling via ADB (future)

---

## 13. IMPORTANT NOTES FOR AI ASSISTANTS

> **DO NOT** create new LLM provider logic in any file other than `core/llm_client.py`
> 
> **DO NOT** use Devanagari script in any user-facing string — always Roman Hinglish
> 
> **DO NOT** skip the confirmation flow for WhatsApp actions — safety critical
> 
> **ALL action functions** must return `tuple[bool, str]` — `(success, message)`
> 
> **Test changes** by running: `python -c "from core.agent import LisaAgent; print('OK')"` before deploying
> 
> **WhatsApp UI** changes frequently — the automation code uses multi-strategy fallbacks (JS → CSS → keyboard) for resilience
> 
> **RAG embeddings** always use Gemini regardless of LLM_PROVIDER — this is intentional (only Gemini supports the embedding model)
