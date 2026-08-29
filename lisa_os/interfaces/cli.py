"""
lisa_os.interfaces.cli — Phase 1 CLI entry point.

Deliberately mirrors your existing main.py almost line-for-line:
same banner, same commands (/quit /mode /memories /remember /reset),
same behavior. The ONE thing that changed: a normal chat message now
goes through `lisa_graph.invoke()` instead of calling `agent.chat()`
directly — Section 14 Phase 1 acceptance criterion: "every turn flows
Understand -> ... -> Respond through the graph; old CLI + voice both
work unchanged."

`main.py` itself is untouched — run this alongside it any time to
compare old vs new behavior on the same input.
"""
import sys
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from lisa_os.graph import lisa_graph
from lisa_os.nodes import get_legacy_agent
from memory.long_term import list_all
from config.settings import AGENT_NAME, USER_NAME


def print_banner():
    print("\n" + "=" * 55)
    print(f"   {AGENT_NAME.upper()} — v3 (LangGraph pipeline) — Phase 1")
    print("=" * 55)
    print(f"   Namaste {USER_NAME}! Main {AGENT_NAME} hoon.")
    print(f"   /quit | /mode | /memories | /remember cat key val | /reset")
    print("=" * 55 + "\n")


def handle_command(cmd: str, agent):
    parts = cmd.strip().split(maxsplit=3)
    c = parts[0].lower()

    if c == "/quit":
        agent.end_session()
        print(f"\n  {AGENT_NAME}: Theek hai, alvida! Take care. \U0001F44B\n")
        return "EXIT"

    elif c == "/mode":
        print(f"  [Mode: {agent.get_mode().upper()} | Mood: {agent.get_mood()}]\n")

    elif c == "/personal":
        agent.mode = "personal"
        print(f"  [{AGENT_NAME} personal mode mein]\n")

    elif c == "/professional":
        agent.mode = "professional"
        print(f"  [{AGENT_NAME} professional mode mein]\n")

    elif c == "/reset":
        agent.reset_conversation()
        print(f"  [Conversation reset]\n")

    elif c == "/memories":
        mems = agent.memory_manager.get_all_active_memories()
        if not mems:
            print("  [Memory DB] Naya database abhi ekdum khali hai ya saari temporary memories expire ho chuki hain.\n")
        else:
            print("  [Active SQLite Memories]")
            for m in mems:
                print(f"  [{m['category'].upper()}] {m['key']} : {m['value']}")
            print()

    elif c == "/remember":
        if len(parts) < 4:
            print("  Usage: /remember category key value\n")
        else:
            agent.save_fact(parts[1], parts[2], parts[3])

    elif c == "/extract":
        agent._extract_and_update_memory(agent.conversation_history)
        print()

    return True


def main():
    print_banner()
    agent = get_legacy_agent()                 # same LisaAgent instance respond_node uses
    thread_id = f"cli-{uuid.uuid4().hex[:8]}"   # one graph "thread" per CLI run
    graph_config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            user_input = input(f"{USER_NAME}: ").strip()
        except (KeyboardInterrupt, EOFError):
            try:
                agent.end_session()
            except KeyboardInterrupt:
                print("\n  [Memory] Extraction skipped — dobara Ctrl+C dabaya.")
            print(f"\n\n  {AGENT_NAME}: Alvida! \U0001F44B\n")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            result = handle_command(user_input, agent)
            if result == "EXIT":
                break
            continue

        result = lisa_graph.invoke({"raw_input": user_input}, config=graph_config)
        reply = result.get("response_text", "...")
        print(f"\n{AGENT_NAME}: {reply}\n")


if __name__ == "__main__":
    main()
