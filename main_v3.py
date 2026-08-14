"""
LISA v3 — Main Entry Point (Text Mode, LangGraph pipeline)

Run this exactly like the old one: `python main_v3.py`
Your existing `main.py` is untouched — run either one, any time, to
compare old vs new on the same input. This just calls into
lisa_os.interfaces.cli, which is the real Phase 1 entry point.
"""
from lisa_os.interfaces.cli import main

if __name__ == "__main__":
    main()
