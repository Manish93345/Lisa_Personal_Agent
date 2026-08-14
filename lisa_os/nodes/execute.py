"""
lisa_os.nodes.execute — Step 4 of the pipeline: run plan steps via
Tool Manager.

Phase 1: intentional no-op. There is no Tool Manager and no
Departments yet (Phase 3). Real task execution for now still happens
*inside* the legacy LisaAgent.chat() call in respond.py — this node
exists so the graph shape (execute -> verify -> reflect -> learn ->
respond) is already correct and doesn't need rewiring later; only the
body of this function changes in Phase 3.

See Blueprint Section 5.3 (executor_node) and Section 7 (Tool Manager).
"""
from lisa_os.state import LisaState


def executor_node(state: LisaState) -> dict:
    # TODO Phase 3: for step in topo_sort(state["plan"]["steps"]):
    #                   tool_manager.acl_check(...) -> interrupt() if risk>=send -> tool_manager.call(...)
    return {"results": []}
