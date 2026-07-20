"""
LISA — OS Watcher (v2 — dashboard-ready)
=========================================
Same stealth monitoring as before, PLUS:
  - Timeline of last N window switches (default 20) with start/end timestamps
  - Thread-safe snapshot for the dashboard `/api/os_watcher` endpoint
  - Non-Windows fallback (dashboard still runs; monitor just idles)

Public API preserved:
  eye.start_stealth_mode()
  eye.stop_and_report() -> str
  eye.running (bool)
  eye.activity_log (dict — cumulative seconds per window)

New API for dashboard:
  eye.get_status() -> dict
  eye.get_timeline(limit=20) -> list[{title, start, end, duration_sec}]
  eye.current_window (str)
"""

import time
import threading
import sys
from collections import defaultdict, deque
from typing import List, Dict, Any


# ── Cross-platform active window ────────────────────────────────────────
def _win32_active_window() -> str:
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value if buf.value else "Unknown / Desktop"
    except Exception:
        return "Unknown"


def _stub_active_window() -> str:
    # For dev on macOS / Linux — dashboard still works, no real tracking.
    return "Unknown (non-Windows host)"


_ACTIVE_WINDOW_FN = _win32_active_window if sys.platform == "win32" else _stub_active_window


TIMELINE_MAX = 200   # ring buffer of window switches


class OSWatcher:
    def __init__(self):
        self.running               = False
        self.tracking_thread       = None
        self.activity_log          = defaultdict(int)      # cumulative sec per title
        self.current_window        = "—"
        self.window_start_time     = 0.0
        self._timeline: deque      = deque(maxlen=TIMELINE_MAX)
        self._lock                 = threading.Lock()
        self._started_at           = 0.0

    # ── Internals ──────────────────────────────────────────────────────

    def _get_active_window_title(self) -> str:
        try:
            return _ACTIVE_WINDOW_FN()
        except Exception:
            return "Unknown"

    def _monitor_loop(self):
        self.current_window    = self._get_active_window_title()
        self.window_start_time = time.time()

        while self.running:
            new_window = self._get_active_window_title()

            if new_window != self.current_window:
                end_ts     = time.time()
                time_spent = int(end_ts - self.window_start_time)

                if time_spent > 0 and self.current_window and self.current_window != "Unknown":
                    with self._lock:
                        self.activity_log[self.current_window] += time_spent
                        self._timeline.append({
                            "title":        self.current_window,
                            "start":        self.window_start_time,
                            "end":          end_ts,
                            "duration_sec": time_spent,
                        })

                self.current_window    = new_window
                self.window_start_time = end_ts

            time.sleep(2)

    # ── Public — original API ──────────────────────────────────────────

    def start_stealth_mode(self):
        if self.running:
            return
        self.running = True
        self._started_at = time.time()
        with self._lock:
            self.activity_log.clear()
            self._timeline.clear()
        self.tracking_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.tracking_thread.start()
        print("🕵️  [Stealth Watcher] OS Monitoring STARTED. Everything is being logged.")

    def stop_and_report(self) -> str:
        if not self.running:
            return "No active monitoring session found."

        self.running = False
        if self.tracking_thread:
            self.tracking_thread.join(timeout=1)

        end_ts     = time.time()
        time_spent = int(end_ts - self.window_start_time)
        if time_spent > 0 and self.current_window and self.current_window != "Unknown":
            with self._lock:
                self.activity_log[self.current_window] += time_spent
                self._timeline.append({
                    "title":        self.current_window,
                    "start":        self.window_start_time,
                    "end":          end_ts,
                    "duration_sec": time_spent,
                })

        if not self.activity_log:
            return "Koi activity detect nahi hui."

        sorted_log = sorted(self.activity_log.items(), key=lambda x: x[1], reverse=True)
        report_lines = []
        for window, seconds in sorted_log:
            minutes = seconds // 60
            secs    = seconds % 60
            time_str = f"{minutes}m {secs}s" if minutes > 0 else f"{secs}s"
            report_lines.append(f"- **{time_str}**: {window}")
        return "\n".join(report_lines)

    # ── Public — dashboard API (new) ───────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Live snapshot for dashboard header."""
        now = time.time()
        current_dwell = 0
        if self.running:
            current_dwell = int(now - self.window_start_time)
        with self._lock:
            total_windows_seen = len(self.activity_log)
        return {
            "running":            self.running,
            "started_at":         self._started_at,
            "current_window":     self.current_window if self.running else "—",
            "current_dwell_sec":  current_dwell,
            "total_windows_seen": total_windows_seen,
        }

    def get_timeline(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the last N window switches (most recent LAST).
        Live current window (if running) is appended as an open-ended entry."""
        with self._lock:
            tail = list(self._timeline)[-limit:]
        if self.running and self.current_window and self.current_window != "Unknown":
            tail.append({
                "title":        self.current_window,
                "start":        self.window_start_time,
                "end":          None,                             # still active
                "duration_sec": int(time.time() - self.window_start_time),
                "active":       True,
            })
            tail = tail[-limit:]
        return tail


# Global Instance (name preserved for existing imports)
eye = OSWatcher()
