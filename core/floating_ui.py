import tkinter as tk
import threading
import queue
import time

class FloatingDot:
    def __init__(self):
        self.root = tk.Tk()
        
        # 1. Frameless aur Always on Top
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # 2. Transparent Background Magic (Windows specific)
        self.bg_color = 'black'
        self.root.configure(bg=self.bg_color)
        self.root.attributes('-transparentcolor', self.bg_color)
        
        # 3. Size and Initial Position (Top Right corner)
        self.size = 24
        screen_width = self.root.winfo_screenwidth()
        x = screen_width - self.size - 50
        y = 50
        self.root.geometry(f"{self.size}x{self.size}+{x}+{y}")
        
        # 4. Draw the Glowing Orb
        self.canvas = tk.Canvas(self.root, width=self.size, height=self.size, 
                                bg=self.bg_color, highlightthickness=0)
        self.canvas.pack()
        
        padding = 2
        self.dot = self.canvas.create_oval(
            padding, padding, 
            self.size - padding, self.size - padding,
            fill="#00ff9d", outline="#7cf7ff", width=1.5
        )
        
        # 5. Drag and Drop Setup
        self._offset_x = 0
        self._offset_y = 0
        self.canvas.bind("<Button-1>", self.click_window)
        self.canvas.bind("<B1-Motion>", self.drag_window)
        
        # 6. Thread-Safe State Queue
        self.cmd_queue = queue.Queue()
        self.update_loop()

    def click_window(self, event):
        """Jab user dot par click kare"""
        self._offset_x = event.x
        self._offset_y = event.y

    def drag_window(self, event):
        """Jab user dot ko drag kare"""
        x = self.root.winfo_pointerx() - self._offset_x
        y = self.root.winfo_pointery() - self._offset_y
        self.root.geometry(f"+{x}+{y}")

    def set_state(self, state):
        """FastAPI ya Wake-word thread se call karne ke liye safe function"""
        self.cmd_queue.put(state)

    def update_loop(self):
        """Background mein check karta hai ki koi naya color aaya hai kya"""
        try:
            while True:
                state = self.cmd_queue.get_nowait()
                self._apply_state(state)
        except queue.Empty:
            pass
        # Har 100ms mein wapas check karo
        self.root.after(100, self.update_loop)

    def _apply_state(self, state):
        # Humari Color Scheme
        colors = {
            "idle": "#00ff9d",        # Green (Ready)
            "listening": "#ff2fb0",   # Magenta (Hearing you)
            "processing": "#ffb84d",  # Amber (Thinking)
            "speaking": "#00e5ff"     # Blue (Replying)
        }
        color = colors.get(state, "#00ff9d")
        self.canvas.itemconfig(self.dot, fill=color)

    def run(self):
        self.root.mainloop()

# --- Global Access Functions ---
_dot_thread = None
_dot_instance = None

def _run_ui():
    global _dot_instance
    _dot_instance = FloatingDot()
    _dot_instance.run()

def start_floating_dot():
    """Server start hote hi isko call karenge"""
    global _dot_thread
    if _dot_thread is None:
        _dot_thread = threading.Thread(target=_run_ui, daemon=True)
        _dot_thread.start()
        # Tkinter load hone ke liye chhota sa wait
        time.sleep(1)

def set_dot_state(state: str):
    """'idle', 'listening', 'processing', 'speaking' pass karo"""
    global _dot_instance
    if _dot_instance:
        _dot_instance.set_state(state)

# Testing ke liye agar is file ko direct run karo
if __name__ == "__main__":
    start_floating_dot()
    print("Floating UI Started. Drag it around!")
    
    # Test colors loop
    states = ["idle", "listening", "processing", "speaking"]
    idx = 0
    while True:
        time.sleep(2)
        idx = (idx + 1) % len(states)
        print(f"Switching state to: {states[idx]}")
        set_dot_state(states[idx])