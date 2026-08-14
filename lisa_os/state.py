"""
lisa_os.state — LisaState, the single dict-like object that flows
through every node in the graph.

See Blueprint Section 5.2.
"""
from typing import TypedDict, Literal, Optional
from lisa_os.schemas import (
    EmotionState, Intent, Plan, TaskResult, Reflection, RelationshipCtx, MemoryPacket,
)


class LisaState(TypedDict, total=False):
    # --- input ---
    raw_input: str
    input_modality: Literal["text", "voice"]
    session_id: str
    timestamp: str

    # --- understand ---
    emotion: EmotionState
    intents: list                # list[Intent]
    relationship: RelationshipCtx
    presence_signal: Optional[dict]     # Phase 7 — Presence Engine, unused until then
    mode: Literal["personal", "professional"]
    language_mode: Literal["hinglish_roman", "english", "devanagari_mixed"]

    # --- plan ---
    plan: Optional[Plan]
    personality_verdict: dict    # {"verdict": "approve"|"modify"|"veto", "route": "chat"|"task"|"hybrid"|"refuse"}

    # --- execute / verify ---
    results: list                # list[TaskResult]
    verified: bool

    # --- reflect / learn ---
    reflection: Reflection
    experience_id: Optional[str]

    # --- memory ---
    memory: MemoryPacket

    # --- output ---
    response_text: str
    response_audio_path: Optional[str]
    token_usage: dict
    trace_id: str
