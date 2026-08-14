"""
lisa_os.nodes.plan — Step 2/3 of the pipeline: task decomposition.

Phase 1: intentional stub. There is no Planner LLM call and no
Experience Store yet (that's Phase 2 for memory, Phase 6 for the
learning loop that actually retrieves past cases). Right now this
node just carries the detected intents forward as a trivial "plan"
so the shape of state.plan is already correct for later phases to
fill in for real, without another state-schema migration.

See Blueprint Section 5.3 (planner_node) and Section 14 (Phase 2, 6).
"""
from lisa_os.state import LisaState


def planner_node(state: LisaState) -> dict:
    intents = state.get("intents", [])
    steps = []  # TODO Phase 3: real PlanStep objects once Tool Manager + Departments exist

    return {
        "plan": {"steps": steps, "goal_link": None},
    }
