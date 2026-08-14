"""
lisa_os.nodes.understand — Step 1 of the pipeline: mood + intent +
relationship context.

Phase 1: reuses your existing, working detectors instead of rewriting
them (Blueprint Section 5.3 — "reuse before rewrite"):
  - config.prompts.detect_mood()        -> keyword mood pass, free
  - actions.intent_detector.detect_intent() -> regex fast-path + LLM fallback

Relationship context is hardcoded to "manish"/"owner"/L0 for Phase 1 —
real speaker identification is Phase 4/5 work (Relationship Model,
Security Levels), not something to half-build here.
"""
from lisa_os.state import LisaState

from config.prompts import detect_mood
from actions.intent_detector import detect_intent


def understand_node(state: LisaState) -> dict:
    raw = state.get("raw_input", "")

    mood = detect_mood(raw)
    intents = detect_intent(raw)   # list[{"action":..., "params":..., "confidence":...}]

    relationship = {
        "speaker": "manish",
        "relation": "owner",
        "security_level": 0,   # TODO Phase 5: read from core/security.py SecurityManager
    }

    print(f"  [graph] understand_node fired -> mood={mood} intents={[i.get('action') for i in intents]}")

    return {
        "emotion": {"mood": mood},
        "intents": intents,
        "relationship": relationship,
        "mode": state.get("mode", "personal"),
        "language_mode": state.get("language_mode", "hinglish_roman"),
    }
