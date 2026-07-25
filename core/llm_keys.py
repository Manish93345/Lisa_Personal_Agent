"""
LISA — Auto-Rotating LLM Key Manager
Handles Gemini -> Groq -> Next Email loop automatically.
"""
import os
from dotenv import load_dotenv

load_dotenv()

class KeyManager:
    def __init__(self):
        self.accounts = []
        self.current_account_idx = 0
        self.use_groq_fallback = False  # False = Try Gemini, True = Try Groq
        
        # Parse the keys from .env
        raw_keys = os.getenv("ROTATING_LLM_KEYS", "")
        if raw_keys:
            pairs = [p.strip() for p in raw_keys.split(",") if p.strip()]
            for pair in pairs:
                if "|" in pair:
                    gemini, groq = pair.split("|", 1)
                    self.accounts.append({"gemini": gemini.strip(), "groq": groq.strip()})

    def get_current_provider_and_key(self):
        if not self.accounts:
            raise ValueError("No API keys found in ROTATING_LLM_KEYS")
            
        account = self.accounts[self.current_account_idx]
        if self.use_groq_fallback:
            return "groq", account["groq"]
        else:
            return "gemini", account["gemini"]

    def mark_current_exhausted(self):
        """Called when a 429 Rate Limit is hit."""
        if not self.use_groq_fallback:
            # Gemini exhausted -> Switch to Groq on same email
            print(f"  [LLM] Gemini limit hit for Account {self.current_account_idx + 1}. Switching to Groq.")
            self.use_groq_fallback = True
        else:
            # Groq exhausted -> Move to next email account
            print(f"  [LLM] Groq limit hit for Account {self.current_account_idx + 1}. Moving to next Email.")
            self.use_groq_fallback = False
            self.current_account_idx = (self.current_account_idx + 1) % len(self.accounts)

# Global instance
key_manager = KeyManager()