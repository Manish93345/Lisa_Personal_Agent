"""
lisa_os.nodes.personality — Step 3 of the pipeline: approve/modify/veto
+ decide the route (chat | task | hybrid | refuse).

Phase 1: no deterministic hard-rules and no tone-shaping LLM call yet
(that's Phase 4 — Personality Engine, driven by identity.yaml hard
rules + the style corpus). What IS real here: the route decision,
based on whether intent detection found an actual action or not.

Today, "task" and "hybrid" still end up back at the legacy responder
(Section 13.1 — LisaAgent.chat() already does its own action dispatch
internally), because Departments + Tool Manager don't exist until
Phase 3. Once they do, only executor_node changes — this file's job
(deciding chat vs task) doesn't need to change again.

See Blueprint Section 5.3 (personality_node) and Section 8 (Autonomy —
veto power lives here from Phase 5 onward).
"""
from lisa_os.state import LisaState


def personality_node(state: LisaState) -> dict:
    intents = state.get("intents", [])
    has_real_action = any(i.get("action", "none") != "none" for i in intents)

    # TODO Phase 4: deterministic hard-rules from identity.yaml run here FIRST,
    # and can force verdict="veto" regardless of route (e.g. health/safety).
    # TODO Phase 5: Autonomy Engine can force verdict="refuse" here too.

    route = "task" if has_real_action else "chat"

    print(f"  [graph] personality_node fired -> route={route}")

    return {
        "personality_verdict": {"verdict": "approve", "route": route, "reason": None},
    }
