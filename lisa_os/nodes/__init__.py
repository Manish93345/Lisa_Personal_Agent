"""
LOSA v3 — Nodes package.

Phase 1: understand, plan, personality, execute, verify, reflect,
learn, respond — see Blueprint Section 5.3 for each node's contract.
Only respond.py does real work in Phase 1 (wraps the legacy agent);
the rest are typed, honest no-ops that later phases fill in, one at
a time, without changing the graph shape again.
"""
from lisa_os.nodes.understand import understand_node
from lisa_os.nodes.plan import planner_node
from lisa_os.nodes.personality import personality_node
from lisa_os.nodes.execute import executor_node
from lisa_os.nodes.verify import verifier_node
from lisa_os.nodes.reflect import reflection_node
from lisa_os.nodes.learn import learning_node
from lisa_os.nodes.respond import responder_node, get_legacy_agent

__all__ = [
    "understand_node", "planner_node", "personality_node", "executor_node",
    "verifier_node", "reflection_node", "learning_node", "responder_node",
    "get_legacy_agent",
]
