"""
lisa_os.nodes.respond — Step 8 (final): produce the reply.

Phase 1: THIS is the node doing real work. Every route (chat/task/
hybrid/refuse) currently lands here and calls the existing, battle-
tested LisaAgent.chat() — exactly the "Phase A: wrap existing
LisaAgent.chat() as a single legacy respond node" pattern from
Blueprint Section 13.2 / Section 14 (Phase 1 acceptance: "Lisa
responds via the new graph, even if dumb").

Known, intentional Phase-1 duplication: LisaAgent.chat() re-detects
mood/intent internally and keeps its own conversation_history — it
doesn't yet know about the mood/intents the new understand_node
already computed, or about LangGraph's checkpointer. That overlap is
fine for now and goes away piece by piece from Phase 2 onward, as
real logic moves INTO the graph nodes and this wrapper call shrinks
until it's gone. Don't try to "clean this up" early — it's the
planned shape, not an oversight.

A single LisaAgent instance is created once at import time (module-
level singleton), matching how main.py does `agent = LisaAgent()`
once per process — this preserves the existing session/mood/
conversation-history behavior unchanged.
"""
from lisa_os.state import LisaState
from core.agent import LisaAgent

_legacy_agent = LisaAgent(voice_mode=False)


def responder_node(state: LisaState) -> dict:
    verdict = state.get("personality_verdict", {})

    if verdict.get("verdict") == "veto":
        # Not reachable yet in Phase 1 (personality_node never vetoes
        # until Phase 4), kept here so the shape is right.
        return {"response_text": verdict.get("reason") or "Nahi, abhi nahi."}

    reply = _legacy_agent.chat(state.get("raw_input", ""))
    return {"response_text": reply}


def get_legacy_agent() -> LisaAgent:
    """Exposed for interfaces/cli.py — needed for /mode, /memories,
    /remember etc. commands that talk to the agent directly and
    aren't part of the turn pipeline."""
    return _legacy_agent
