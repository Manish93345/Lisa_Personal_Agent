"""
lisa_os.nodes.learn — Step 7: write an experience case.

Phase 1: intentional no-op — Experience Store doesn't exist until
Phase 2 (schema) / Phase 6 (real reflect+learn loop with confidence
decay). See Blueprint Section 6.3 and Section 11.
"""
from lisa_os.state import LisaState


def learning_node(state: LisaState) -> dict:
    # TODO Phase 6: embed {situation, plan_used, outcome, lesson} -> ChromaDB "lisa_experience".
    return {"experience_id": None}
