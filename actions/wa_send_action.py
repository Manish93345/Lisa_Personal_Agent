"""
LISA — Smart WhatsApp Send Action (v2)
========================================
Changes:
  - smart_whatsapp_send ab (bool, str) tuple return karta hai
    agent.py ko yahi chahiye tha
  - Auto-learn: naye contacts automatically contacts.json mein save
  - Relationship guess: naam se detect (papa/bhai/etc)
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import settings

CONTACTS_FILE = BASE_DIR / "data" / "contacts.json"


# ══════════════════════════════════════════════════════════════════════
#  CONTACTS
# ══════════════════════════════════════════════════════════════════════

def _load_contacts() -> dict:
    if CONTACTS_FILE.exists():
        with open(CONTACTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("contacts", {})
    return {}


def get_contact_info(name: str) -> dict:
    contacts = _load_contacts()
    name_lower = name.lower().strip()
    if not name_lower:
        return {"full_name": "", "relationship": "default"}
    if name_lower in contacts:
        return contacts[name_lower]
    for key, info in contacts.items():
        if name_lower in key or key in name_lower:
            return info
    return {"full_name": name.title(), "relationship": "default"}


def _guess_relationship(name: str) -> str:
    """Naam se relationship guess karo."""
    n = name.lower()
    elder  = {"papa", "dad", "pita", "mummy", "mom", "maa", "mama", "chacha",
               "chachi", "nana", "nani", "dada", "dadi", "uncle", "aunty",
               "mausi", "mausa", "taau", "taai"}
    family = {"bhai", "brother", "behen", "sister", "didi", "bhaiya", "sis"}
    if any(k in n for k in elder):
        return "elder_family"
    if any(k in n for k in family):
        return "family"
    return "friend"


def auto_learn_contact(name: str, relationship: str, full_name: str = "") -> None:
    """Naya contact contacts.json mein save karo — dobara poochhna nahi padega."""
    try:
        if CONTACTS_FILE.exists():
            with open(CONTACTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"contacts": {}}

        key = name.lower().strip()
        if key not in data.get("contacts", {}):
            data.setdefault("contacts", {})[key] = {
                "full_name"    : full_name or name.title(),
                "relationship" : relationship,
                "auto_learned" : True,
            }
            CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  [Contacts] '{name}' auto-save ({relationship})")
    except Exception as e:
        print(f"  [Contacts] Save error: {e}")


# ══════════════════════════════════════════════════════════════════════
#  TONE PROMPTS
# ══════════════════════════════════════════════════════════════════════

TONE_PROMPTS = {
    "friend": """
Tu LISA hai — Manish ki AI assistant.
Ek dost ki taraf se WhatsApp message likhna hai.
TONE & STYLE (CRITICAL RULE):
- Ekdum casual, desi, doston wali Indian Hinglish use karo (e.g., 'bhai', 'yaar', 'kya haal').
- KOI FORMAL WORDS NAHI (NO 'ji', NO 'kripya', NO 'namaste', NO 'pranam', NO 'shri').
- Ekdum natural, short aur direct baat karo (max 1 ya 2 line).
- Example style: "Hello sugri, game mein online aayega kya abhi?"
- Sirf message ka text return karo, koi extra quotes ("") ya text nahi.
""",
    "elder_family": """
Tu LISA hai — Manish ki AI assistant.
Ek bete ki taraf se Papa/Mama ya kisi bade ko message likhna hai.
Tone: respectful warm Hindi. "Aap" use karo, "tum" nahi.
2-3 lines. Formal nahi but respectful zaroor.
Example: "Papa, namaste 🙏 Kal ghar aa sakta hoon kya? Kuch baat karni thi."
""",
    "family": """
Tu LISA hai — Manish ki AI assistant.
Family member (Bhai/Behen) ko message likhna hai.
Tone: warm, casual Hindi/Hinglish. Close family feel.
2-3 lines max.
""",
    "senior": """
Tu LISA hai — Manish ki AI assistant.
Ek senior/professor/sir ko professional message likhna hai.
Tone: formal respectful English ya Hindi. "Sir/Ma'am" use karo.
Short aur to-the-point.
""",
    "colleague": """
Tu LISA hai — Manish ki AI assistant.
College/office colleague ko message likhna hai.
Tone: semi-formal friendly Hinglish. 2-3 lines.
""",
    "default": """
Tu LISA hai — Manish ki AI assistant.
WhatsApp message likhna hai. Tone: neutral polite Hinglish.
Chhota aur clear rakho.
""",
}


# ══════════════════════════════════════════════════════════════════════
#  LLM DRAFTER
# ══════════════════════════════════════════════════════════════════════

def draft_message(contact_name: str, intent: str, relationship: str) -> str:
    """Central LLM client se message draft karo — provider logic wahan hai."""
    from core.llm_client import call_llm_simple

    tone_prompt = TONE_PROMPTS.get(relationship, TONE_PROMPTS["default"])
    user_prompt = (
        f"Contact: {contact_name}\n"
        f"Ye convey karna hai: {intent}\n\n"
        f"Sirf WhatsApp message text likho — koi explanation nahi, koi quotes nahi."
    )

    return call_llm_simple(
        system_prompt=tone_prompt,
        user_message=user_prompt,
        temperature=0.7,
        max_tokens=200,
    )


# ══════════════════════════════════════════════════════════════════════
#  MAIN FUNCTION
# ══════════════════════════════════════════════════════════════════════

def smart_whatsapp_send(
    contact: str,
    intent: str,
    wa_driver=None,
    relationship: str = "",
) -> tuple:
    """
    NON-INTERACTIVE: Sirf draft karta hai — confirmation caller handle karta hai.

    Returns tuple (bool, str):
      (True,  drafted_message_text)
      (False, "error reason")
    """

    # ── Contact info ──────────────────────────────────────────────────
    info      = get_contact_info(contact)
    full_name = info.get("full_name", contact.title())

    rel = (relationship
           or (info.get("relationship") if info.get("relationship") != "default" else "")
           or _guess_relationship(contact))

    # Auto-learn naye contacts
    if not info or info.get("relationship", "default") == "default":
        auto_learn_contact(contact, rel, full_name)

    # ── Draft ─────────────────────────────────────────────────────────
    try:
        drafted = draft_message(full_name, intent, rel)
    except Exception as e:
        return (False, f"Draft error: {e}")

    return (True, drafted)


# ══════════════════════════════════════════════════════════════════════
#  INTENT PARSER
# ══════════════════════════════════════════════════════════════════════

def parse_whatsapp_intent(user_text: str) -> dict | None:
    import re
    text_lower = user_text.lower()
    patterns = [
        r'(\w+)\s+ko\s+(?:message|msg|whatsapp)\s+(?:kar|karo|bhejo|bhej|dena|do)\s+(?:ki|ke liye|na ki)?\s*(.*)',
        r'(?:message|msg)\s+(?:kar|karo|bhejo)\s+(\w+)\s+ko\s+(?:ki|ke liye)?\s*(.*)',
        r'(\w+)\s+ko\s+(?:bolo|bol)\s+(.*)',
        r'(\w+)\s+ko\s+(?:likh|likho|type kar)\s+(.*)',
    ]
    skip = {"ek", "yeh", "wo", "woh", "mujhe", "mera", "meri", "apne", "aap"}
    for pattern in patterns:
        m = re.search(pattern, text_lower)
        if m:
            contact = m.group(1).strip()
            intent  = m.group(2).strip() if m.group(2) else ""
            if contact not in skip:
                return {"contact": contact, "intent": intent or user_text}
    return None


# ══════════════════════════════════════════════════════════════════════
#  STANDALONE TEST
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "="*55)
    print("   LISA — Smart WhatsApp Send (v2)")
    print("="*55)

    user_input = input("\n  Kya kehna hai Lisa se: ").strip()
    parsed = parse_whatsapp_intent(user_input)

    if parsed:
        print(f"  Contact: {parsed['contact']} | Intent: {parsed['intent']}")
        ok, msg = smart_whatsapp_send(parsed["contact"], parsed["intent"])
        print(f"\n  Result: {'✓' if ok else '✗'} — {msg}")
    else:
        contact = input("  Contact naam: ").strip()
        intent  = input("  Kya kehna hai: ").strip()
        ok, msg = smart_whatsapp_send(contact, intent)
        print(f"\n  Result: {'✓' if ok else '✗'} — {msg}")