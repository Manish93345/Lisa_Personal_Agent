import time
import threading
import ctypes
from collections import defaultdict

class OSWatcher:
    def __init__(self):
        self.running = False
        self.tracking_thread = None
        self.activity_log = defaultdict(int) # Stores { "Window Title" : seconds_spent }
        self.current_window = None
        self.window_start_time = 0

    def _get_active_window_title(self):
        """Windows API se current active window ka naam nikalta hai bina RAM use kiye"""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value if buf.value else "Unknown / Desktop"
        except Exception:
            return "Unknown"

    def _monitor_loop(self):
        """Background mein har 2 second mein check karta hai"""
        self.current_window = self._get_active_window_title()
        self.window_start_time = time.time()

        while self.running:
            new_window = self._get_active_window_title()
            
            if new_window != self.current_window:
                # Calculate time spent on the previous window
                time_spent = int(time.time() - self.window_start_time)
                if time_spent > 0 and self.current_window != "Unknown":
                    self.activity_log[self.current_window] += time_spent
                
                # Update to new window
                self.current_window = new_window
                self.window_start_time = time.time()
                
            time.sleep(2) # 2-second sleep makes it ultra-lightweight

    def start_stealth_mode(self):
        """Monitor start karta hai. Ye stop nahi hoga chahe tray app fail ho jaye."""
        if self.running: return
        self.running = True
        self.activity_log.clear() # Purana data saaf
        self.tracking_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.tracking_thread.start()
        print("🕵️‍♂️ [Stealth Watcher] OS Monitoring STARTED. Everything is being logged.")

    def stop_and_report(self):
        """Monitor stop karke neat report generate karta hai"""
        if not self.running: return "No active monitoring session found."
        
        self.running = False
        if self.tracking_thread:
            self.tracking_thread.join(timeout=1)
            
        # Add the last active window time
        time_spent = int(time.time() - self.window_start_time)
        if time_spent > 0 and self.current_window != "Unknown":
            self.activity_log[self.current_window] += time_spent

        if not self.activity_log:
            return "Koi activity detect nahi hui."

        # Sort log by time spent (highest first)
        sorted_log = sorted(self.activity_log.items(), key=lambda x: x[1], reverse=True)
        
        report_lines = []
        for window, seconds in sorted_log:
            minutes = seconds // 60
            secs = seconds % 60
            time_str = f"{minutes}m {secs}s" if minutes > 0 else f"{secs}s"
            # Window title usually contains "YouTube - Google Chrome" or "resume.pdf - Adobe Reader"
            report_lines.append(f"- **{time_str}**: {window}")

        return "\n".join(report_lines)

# Global Instance
eye = OSWatcher()