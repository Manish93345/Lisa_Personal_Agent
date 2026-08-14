"""
lisa_os.schemas — shared types used across LisaState and node contracts.

Phase 1: minimal but real. Fields get used more heavily from Phase 2
(Memory Fabric) and Phase 3 (Departments) onward — kept here now so
state.py has something real to import instead of `dict`.

See Blueprint Section 5.2 (State Schema).
"""
from typing import TypedDict, Literal, Optional


class EmotionState(TypedDict, total=False):
    mood: str                 # "sad" | "anxious" | "happy" | "angry" | "flirty" | "neutral"
                               # (values match config/prompts.py MOOD_KEYWORDS — reused, not redefined)
    stress_level: float       # 0.0-1.0, unused until Phase 4 (richer Emotional Reasoning)
    energy: float             # 0.0-1.0, unused until Phase 4


class Intent(TypedDict, total=False):
    action: str                # "none" | "whatsapp_send" | "play_song" | ... (from actions/intent_detector.py)
    params: dict
    confidence: float


class PlanStep(TypedDict, total=False):
    id: str
    department: Literal["planning", "knowledge", "operations"]
    tool: str
    params: dict
    risk: Literal["read", "write", "send", "system"]
    depends_on: list


class Plan(TypedDict, total=False):
    steps: list                # list[PlanStep] — empty in Phase 1 (no Tool Manager yet, Phase 3)
    goal_link: Optional[str]


class TaskResult(TypedDict, total=False):
    task_id: str
    ok: bool
    evidence: dict
    error: Optional[str]
    duration_ms: int


class Reflection(TypedDict, total=False):
    plan_ok: bool
    failures: list
    why: str
    improvement: str


class RelationshipCtx(TypedDict, total=False):
    speaker: str                # "manish" for now — Phase 4 adds real identification
    relation: str                # "owner" | "friend" | "professor" | "parent" | "unknown"
    security_level: int          # 0 | 1 | 2 — Phase 5 wires this to core/security.py properly


class MemoryPacket(TypedDict, total=False):
    relationship_facts: list
    experience_cases: list
    conversation_summary: str
    knowledge_facts: list
    document_chunks: list
    # Phase 1: unused placeholder. Phase 2 (Memory Fabric) builds and
    # budgets this for real (<=600 tokens, priority-ordered — Section 6.1).
