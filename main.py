"""
LISA — Main Entry Point (Text Mode)
"""

import sys

# Windows terminal encoding fix — emoji aur special chars ke liye
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core.agent       import LisaAgent
from memory.long_term import list_all
from config.settings  import AGENT_NAME, USER_NAME


def print_banner():
    print("\n" + "="*55)
    print(f"   {AGENT_NAME.upper()} — Personal AI Agent")
    print("="*55)
    print(f"   Namaste {USER_NAME}! Main {AGENT_NAME} hoon.")
    print(f"   /quit | /mode | /memories | /remember cat key val | /reset")
    print("="*55 + "\n")


def handle_command(cmd: str, agent: LisaAgent):
    parts = cmd.strip().split(maxsplit=3)
    c     = parts[0].lower()

    if c == "/quit":
        agent.end_session()
        print(f"\n  {AGENT_NAME}: Theek hai, alvida! Take care. 👋\n")
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
        mems = list_all()
        if not mems:
            print("  [Koi memory nahi abhi tak]\n")
        else:
            print("  [Saved Memories]")
            for m in mems:
                print(f"  {m['category']}/{m['key']}: {m['value']}")
            print()

    elif c == "/remember":
        if len(parts) < 4:
            print("  Usage: /remember category key value\n")
        else:
            agent.save_fact(parts[1], parts[2], parts[3])

    elif c == "/extract":
        # Manually trigger memory extraction
        from memory.memory_extractor import extract_and_save
        saved = extract_and_save(agent.conversation_history)
        print(f"  [Extracted {saved} facts from conversation]\n")

    return True


def main():
    print_banner()
    agent = LisaAgent()

    while True:
        try:
            user_input = input(f"{USER_NAME}: ").strip()
        except (KeyboardInterrupt, EOFError):
            agent.end_session()
            print(f"\n\n  {AGENT_NAME}: Alvida! 👋\n")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            result = handle_command(user_input, agent)
            if result == "EXIT":
                break
            continue

        reply = agent.chat(user_input)
        print(f"\n{AGENT_NAME}: {reply}\n")


if __name__ == "__main__":
    main()