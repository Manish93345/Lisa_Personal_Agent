"""
lisa_os.nodes.reflect — Step 6: was the plan right? what failed and why?

Phase 1: intentional no-op — no local-LLM reflection call yet.
See Blueprint Section 5.3 (reflection_node) and Section 11 (Learning Pipeline, Phase 6).
"""
from lisa_os.state import LisaState


def reflection_node(state: LisaState) -> dict:
    # TODO Phase 6: cheap local LLM (qwen/phi4-mini) compares plan vs state["results"].
    return {"reflection": {"plan_ok": True, "failures": [], "why": "", "improvement": ""}}
