"""
lisa_os.graph — the supervisor graph. This wiring has been sanity-
tested against LangGraph 1.2.10 (current as of Aug 2026) before being
handed to you — both the conditional-routing shape and the
interrupt()/Command(resume=...) pattern (tested separately, will be
used for real starting Phase 3's confirmation flow).

See Blueprint Section 5.1.
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from lisa_os.state import LisaState
from lisa_os.nodes import (
    understand_node, planner_node, personality_node, executor_node,
    verifier_node, reflection_node, learning_node, responder_node,
)


def route_decision(state: LisaState) -> str:
    return state.get("personality_verdict", {}).get("route", "chat")


def build_graph():
    builder = StateGraph(LisaState)

    builder.add_node("understand", understand_node)
    builder.add_node("plan", planner_node)
    builder.add_node("personality", personality_node)
    builder.add_node("execute", executor_node)
    builder.add_node("verify", verifier_node)
    builder.add_node("reflect", reflection_node)
    builder.add_node("learn", learning_node)
    builder.add_node("respond", responder_node)

    builder.add_edge(START, "understand")
    builder.add_edge("understand", "plan")
    builder.add_edge("plan", "personality")
    builder.add_conditional_edges("personality", route_decision, {
        "chat": "respond",
        "task": "execute",
        "hybrid": "execute",
        "refuse": "respond",
    })
    builder.add_edge("execute", "verify")
    builder.add_edge("verify", "reflect")
    builder.add_edge("reflect", "learn")
    builder.add_edge("learn", "respond")
    builder.add_edge("respond", END)

    return builder


def compile_graph(db_path: str = "data/lisa_checkpoints.sqlite"):
    """
    Uses SqliteSaver so conversation/turn state survives a restart —
    this is what gives Lisa "resume from where we left off" for free
    (Blueprint Section 13.1 / 09_REFACTOR_MAP known-issue fix), even
    though the *memory fabric* itself isn't real until Phase 2.

    Needs the `langgraph-checkpoint-sqlite` package (separate from
    core `langgraph`) — see requirements.txt additions.
    """
    import sqlite3
    from pathlib import Path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return build_graph().compile(checkpointer=checkpointer)


# Module-level singleton — import this from interfaces/*.py
lisa_graph = compile_graph()
