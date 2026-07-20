"""
LISA — Internal Trace Logger (v2 — dashboard-ready)
====================================================
Same terminal output as before, PLUS:
  - Ring-buffer of last N events (in-memory, thread-safe)
  - Subscriber queues for live streaming (SSE / websocket)
  - JSON-serializable event dicts

Backward-compat: `tracer.log(...)`, `tracer.timed(...)`, `tracer.turn_start(...)`
signatures unchanged — existing call sites keep working.

ENV:
  LISA_TRACE=1     → enable full trace (default on)
  LISA_TRACE=2     → verbose
  LISA_TRACE_BUFFER=500  → ring buffer size (default 500 events)
"""

import os
import time
import sys
import queue
import threading
from collections import deque
from contextlib import contextmanager
from typing import Optional, List, Dict, Any


# ── Config ──────────────────────────────────────────────────────────────
TRACE_LEVEL   = int(os.getenv("LISA_TRACE", "1"))
BUFFER_SIZE   = int(os.getenv("LISA_TRACE_BUFFER", "500"))


class _C:
    DIM    = "\033[2m"
    CYAN   = "\033[36m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    RED    = "\033[31m"
    MAG    = "\033[35m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

if sys.platform == "win32" and not os.getenv("WT_SESSION"):
    for attr in ["DIM", "CYAN", "GREEN", "YELLOW", "RED", "MAG", "BOLD", "RESET"]:
        setattr(_C, attr, "")


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
    """Singleton tracer — one per process. Now also broadcasts to dashboard."""

    def __init__(self):
        self.turn_no    = 0
        self._turn_t0   = None
        self._enabled   = TRACE_LEVEL > 0

        # Dashboard hooks
        self._buffer: deque = deque(maxlen=BUFFER_SIZE)   # ring buffer of events
        self._subscribers: List[queue.Queue] = []          # live listeners (SSE)
        self._lock = threading.Lock()
        self._seq  = 0

    # ── Public API (unchanged signatures) ──────────────────────────────

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
        self._emit({
            "type":    "turn_start",
            "turn_no": self.turn_no,
            "message": preview,
        })

    def turn_end(self, reply: Optional[str] = None):
        if not self._enabled or self._turn_t0 is None:
            return
        elapsed_ms = (time.perf_counter() - self._turn_t0) * 1000
        suffix = f" → {len(reply)} chars" if reply else ""
        print(
            f"{_C.BOLD}{_C.MAG}╰─ Turn #{self.turn_no} done{_C.RESET} "
            f"{_C.DIM}({elapsed_ms:.0f}ms{suffix}){_C.RESET}\n"
        )
        self._emit({
            "type":        "turn_end",
            "turn_no":     self.turn_no,
            "duration_ms": round(elapsed_ms, 1),
            "reply_chars": len(reply) if reply else 0,
        })
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

        self._emit({
            "type":        "log",
            "module":      module,
            "message":     message,
            "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
            "tokens":      tokens,
            "tokens_in":   tokens_in,
            "tokens_out":  tokens_out,
            "turn_no":     self.turn_no,
        })

    @contextmanager
    def timed(self, module: str, message: str):
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
        if not self._enabled:
            return
        print(f"│  {_C.DIM}{msg}{_C.RESET}")
        self._emit({"type": "info", "message": msg, "turn_no": self.turn_no})

    def warn(self, msg: str):
        if not self._enabled:
            return
        print(f"│  {_C.YELLOW}⚠ {msg}{_C.RESET}")
        self._emit({"type": "warn", "message": msg, "turn_no": self.turn_no})

    def error(self, msg: str):
        if not self._enabled:
            return
        print(f"│  {_C.RED}✗ {msg}{_C.RESET}")
        self._emit({"type": "error", "message": msg, "turn_no": self.turn_no})

    # ── Dashboard helpers ──────────────────────────────────────────────

    def _emit(self, event: Dict[str, Any]) -> None:
        """Push event into ring-buffer + fan out to live subscribers."""
        with self._lock:
            self._seq += 1
            event["seq"] = self._seq
            event["ts"]  = time.time()
            self._buffer.append(event)
            # non-blocking fanout — slow subscribers just drop
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass

    def snapshot(self, since_seq: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
        """Return buffered events with seq > since_seq (most recent last)."""
        with self._lock:
            events = [e for e in self._buffer if e.get("seq", 0) > since_seq]
        return events[-limit:]

    def subscribe(self, maxsize: int = 200) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


# ── Singleton instance ──────────────────────────────────────────────────
tracer = Tracer()
