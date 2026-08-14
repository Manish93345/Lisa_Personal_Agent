"""
lisa_os.nodes.verify — Step 5: evidence-based success check.

Phase 1: intentional no-op (nothing real to verify yet — see execute.py).
See Blueprint Section 5.3 (verifier_node).
"""
from lisa_os.state import LisaState


def verifier_node(state: LisaState) -> dict:
    # TODO Phase 3: check state["results"] evidence, retry failures once.
    return {"verified": True}
