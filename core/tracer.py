"""
LISA — Internal Trace Logger
=============================
Lightweight, dependency-free tracer for per-turn visibility:
  - Which module did what
  - How long it took
  - How many tokens it cost
  - Which LLM provider responded

Usage:
    from core.tracer import tracer

    tracer.turn_start("meri cutie wifey ji")
    tracer.log("Mood",   "flirty (matched: 'jaan', 'kissi')")
    with tracer.timed("Intent", "local qwen2.5:3b"):
        result = call_intent(...)
    tracer.log("Memory", "Retrieved 2 core + 0 keyword-matched", tokens=180)
    tracer.log("LLM ✓", "cerebras gpt-oss-120b", duration_ms=1400, tokens_in=850, tokens_out=67)
    tracer.turn_end()

ENV:
  LISA_TRACE=1     → enable full trace (default off)
  LISA_TRACE=2     → also print system_prompt length & token counts
"""

import os
import time
import sys
from contextlib import contextmanager
from typing import Optional


# ── Config ──────────────────────────────────────────────────────────────
TRACE_LEVEL = int(os.getenv("LISA_TRACE", "1"))   # 0=off, 1=basic, 2=verbose

# ANSI color codes (gracefully degrade on Windows cmd)
class _C:
    DIM    = "\033[2m"
    CYAN   = "\033[36m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    RED    = "\033[31m"
    MAG    = "\033[35m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

# Disable colors on Windows old terminals
if sys.platform == "win32" and not os.getenv("WT_SESSION"):
    for attr in ["DIM", "CYAN", "GREEN", "YELLOW", "RED", "MAG", "BOLD", "RESET"]:
        setattr(_C, attr, "")


# Color map per module name
_MODULE_COLORS = {
    "Turn":    _C.BOLD + _C.MAG,
    "Mood":    _C.YELLOW,
    "Intent":  _C.CYAN,
    "Memory":  _C.GREEN,
    "RAG":     _C.GREEN,
    "History": _C.DIM,
    "LLM":     _C.CYAN,
    "LLM ✓":   _C.GREEN,
    "LLM ✗":   _C.RED,
    "Action":  _C.YELLOW,
    "WA":      _C.YELLOW,
    "TTS":     _C.MAG,
    "STT":     _C.MAG,
    "Mode":    _C.BOLD,
    "Summary": _C.DIM,
    "Trace":   _C.DIM,
}


class Tracer:
    """Singleton tracer — one per process."""

    def __init__(self):
        self.turn_no = 0
        self._turn_t0 = None
        self._enabled = TRACE_LEVEL > 0

    # ── Public ─────────────────────────────────────────────────────────

    def enable(self, level: int = 1):
        self._enabled = level > 0
        global TRACE_LEVEL
        TRACE_LEVEL = level

    def disable(self):
        self._enabled = False

    def turn_start(self, user_message: str):
        if not self._enabled:
            return
        self.turn_no += 1
        self._turn_t0 = time.perf_counter()
        preview = user_message[:80] + ("…" if len(user_message) > 80 else "")
        print(
            f"\n{_C.BOLD}{_C.MAG}╭─ Turn #{self.turn_no}{_C.RESET} "
            f"{_C.DIM}│{_C.RESET} {preview}"
        )

    def turn_end(self, reply: Optional[str] = None):
        if not self._enabled or self._turn_t0 is None:
            return
        elapsed_ms = (time.perf_counter() - self._turn_t0) * 1000
        suffix = f" → {len(reply)} chars" if reply else ""
        print(
            f"{_C.BOLD}{_C.MAG}╰─ Turn #{self.turn_no} done{_C.RESET} "
            f"{_C.DIM}({elapsed_ms:.0f}ms{suffix}){_C.RESET}\n"
        )
        self._turn_t0 = None

    def log(
        self,
        module: str,
        message: str,
        duration_ms: Optional[float] = None,
        tokens: Optional[int] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
    ):
        """Log a single trace line."""
        if not self._enabled:
            return

        color = _MODULE_COLORS.get(module, _C.DIM)
        tag   = f"{color}[{module}]{_C.RESET}"

        extras = []
        if duration_ms is not None:
            extras.append(f"{duration_ms:.0f}ms")
        if tokens is not None:
            extras.append(f"{tokens} tok")
        if tokens_in is not None or tokens_out is not None:
            ti = tokens_in or 0
            to = tokens_out or 0
            extras.append(f"{ti} in / {to} out tok")

        extras_str = ""
        if extras:
            extras_str = f" {_C.DIM}({' | '.join(extras)}){_C.RESET}"

        print(f"│  {tag} {message}{extras_str}")

    @contextmanager
    def timed(self, module: str, message: str):
        """
        Context manager for auto-timing.

            with tracer.timed("Intent", "local qwen2.5:3b"):
                result = do_work()
        """
        if not self._enabled:
            yield
            return
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - t0) * 1000
            self.log(module, message, duration_ms=elapsed)

    def info(self, msg: str):
        """Plain info line (no module bracket)."""
        if not self._enabled:
            return
        print(f"│  {_C.DIM}{msg}{_C.RESET}")

    def warn(self, msg: str):
        if not self._enabled:
            return
        print(f"│  {_C.YELLOW}⚠ {msg}{_C.RESET}")

    def error(self, msg: str):
        if not self._enabled:
            return
        print(f"│  {_C.RED}✗ {msg}{_C.RESET}")


# ── Singleton instance ──────────────────────────────────────────────────
tracer = Tracer()
