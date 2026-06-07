"""
LISA — Voice Mode Entry Point

[v2 changes]
  - Passes voice_mode=True to LisaAgent → uses Devanagari+English prompt
  - Tracer is auto-enabled (set LISA_TRACE=0 in .env to silence)
"""

from core.agent      import LisaAgent
from voice.stt       import listen_once
from voice.tts       import speak
from config.settings import AGENT_NAME, USER_NAME


def main():
    print("\n" + "="*55)
    print(f"   {AGENT_NAME.upper()} — Voice Mode")
    print("="*55)
    print("   Bolo — main sun rhi hoon!")
    print("   Band karne ke liye bolo: 'bye lisa'")
    print("="*55 + "\n")

    # ← voice_mode=True flips the agent to Devanagari+English prompt
    agent    = LisaAgent(voice_mode=True)
    greeting = f"हाँ {USER_NAME}, मैं सुन रही हूँ! बोलो ना।"
    print(f"{AGENT_NAME}: {greeting}\n")
    speak(greeting)

    while True:
        try:
            user_text = listen_once(max_seconds=30)
            if not user_text:
                continue
            if user_text == "quit":
                break

            exit_words = ["bye lisa", "alvida", "band karo", "quit", "exit"]
            if any(x in user_text.lower() for x in exit_words):
                agent.end_session()
                farewell = "ठीक है, अलविदा! Take care."
                print(f"\n{AGENT_NAME}: {farewell}\n")
                speak(farewell)
                break

            print(f"{USER_NAME}: {user_text}")
            reply = agent.chat(user_text)
            print(f"{AGENT_NAME}: {reply}\n")
            speak(reply)

        except KeyboardInterrupt:
            agent.end_session()
            print(f"\n\n  Alvida!\n")
            break


if __name__ == "__main__":
    main()
