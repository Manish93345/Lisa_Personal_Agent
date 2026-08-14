"""
LOSA — Lisa Operating System Architecture (v3)

Phase 1 (active): graph.py, state.py, schemas.py, and nodes/ have real
code. Every turn flows Understand -> Plan -> Personality -> (Execute ->
Verify -> Reflect -> Learn ->) Respond through an actual LangGraph
StateGraph. respond.py wraps your existing core.agent.LisaAgent, so
Lisa's real behavior is unchanged — only how a turn is orchestrated
has changed. See lisa_os/interfaces/cli.py to run it.

Nothing in the old `actions.zip` codebase is deleted. Departments,
Tool Manager, real Memory Fabric, Presence Engine etc. get filled in
phase by phase — see TODO_PHASE0.md / Blueprint Section 14 (Roadmap).
"""
