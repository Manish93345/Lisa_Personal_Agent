"""
LISA — Central Settings
========================
SIRF YE FILE CHANGE KARO — kuch aur nahi.

[Phase 0 Changes]
  - Removed dead code: CHAT_MODELS, INTENT_MODELS, CHAT_MODEL, INTENT_MODEL,
    LLM_PROVIDER — ye koi bhi file import nahi karti thi (confirmed via grep).
    Provider routing ab llm_client.py ke CLOUD_CHAT_MODELS se hota hai.
  - MAX_HISTORY_TURNS: 8 → 4 (rolling summary covers older context)
  - MAX_TOKENS: 400 → 280 (Lisa ke best replies 60-100 words hain)
  - RAG_TOP_K: 3 (was already 3, confirmed)
"""

from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.parent
VECTORDB_DIR = BASE_DIR / "data" / "vectordb"
MEMORY_DIR   = BASE_DIR / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ── API Keys ───────────────────────────────────────────────────────────
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY")

# ── Conversation ────────────────────────────────────────────────────────
# MAX_HISTORY_TURNS: raw turns to keep in context before summarizing.
# Rolling summary handles older context — 4 turns is sufficient.
MAX_HISTORY_TURNS = 4       # Was 8, reduced for token saving
MAX_TOKENS        = 280     # Was 400, Lisa ke best replies are 60-100 words

# ── RAG Settings ───────────────────────────────────────────────────────
RAG_TOP_K           = 3
RAG_DISTANCE_CUTOFF = 0.75
EMBEDDING_MODEL     = "gemini-embedding-001"

# ── Identity ───────────────────────────────────────────────────────────
AGENT_NAME = "Lisa"
USER_NAME  = "Manish"

# ── Modes ──────────────────────────────────────────────────────────────
MODE_PERSONAL     = "personal"
MODE_PROFESSIONAL = "professional"
DEFAULT_MODE      = MODE_PERSONAL

# ── Voice Settings ─────────────────────────────────────────────────────
WHISPER_MODEL_SIZE = "medium"
TTS_LANG  = "en"
TTS_RATE  = "+0%"
FFPLAY_PATH = r"C:\ffmpeg\bin\ffplay.exe"

LISA_DESKTOP_INDEX = 2   # Desktop 3 = index 2

# ── WhatsApp Automation ────────────────────────────────────────────────
WHATSAPP_PROFILE_DIR  = str(BASE_DIR / "data" / "whatsapp_profile")
WHATSAPP_URL          = "https://web.whatsapp.com"
WHATSAPP_LOAD_TIMEOUT = 60
WHATSAPP_SIDEBAR_WAIT = 8
WHATSAPP_ACTION_DELAY = (0.5, 1.5)
WHATSAPP_CONFIRM_SEND = True
WHATSAPP_HEADLESS     = False

# ── Web Intelligence ───────────────────────────────────────────────────
DEFAULT_CITY       = "Aurangabad, Bihar"
NEWS_COUNTRY       = "IN"
NEWS_LANG          = "en"
WEB_SEARCH_TIMEOUT = 10