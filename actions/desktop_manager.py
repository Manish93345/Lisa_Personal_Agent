"""
LISA — Virtual Desktop Manager (VirtualDesktopAccessor.dll)
=============================================================
Window ko Desktop 3 pe move karo — screen switch nahi hogi.
Tum Desktop 1 pe rahoge, Lisa Desktop 3 pe kaam karegi.

Setup:
  1. VirtualDesktopAccessor.dll (x64) download karo from:
     https://github.com/Ciantic/VirtualDesktopAccessor/releases
  2. Rakhna: LISA_Agent/actions/VirtualDesktopAccessor.dll
  3. pip install pywin32
  4. 3 desktops banao: Win+Ctrl+D (do baar)
"""

import ctypes
import time
import subprocess
from pathlib import Path

try:
    import win32gui
    import win32process
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("  [Desktop] pip install pywin32 karo")

# DLL path
DLL_PATH        = str(Path(__file__).parent / "VirtualDesktopAccessor.dll")
LISA_DESKTOP    = 2   # Desktop 3 = index 2 (0-indexed)

_dll = None


def _load_dll():
    global _dll
    if _dll is not None:
        return _dll
    if not Path(DLL_PATH).exists():
        print(f"  [Desktop] DLL nahi mili: {DLL_PATH}")
        print("  Download: https://github.com/Ciantic/VirtualDesktopAccessor/releases")
        return None
    try:
        _dll = ctypes.CDLL(DLL_PATH)
        # Function signatures define karo
        _dll.MoveWindowToDesktopNumber.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _dll.MoveWindowToDesktopNumber.restype  = ctypes.c_int
        _dll.GetCurrentDesktopNumber.restype    = ctypes.c_int
        _dll.GetDesktopCount.restype            = ctypes.c_int
        return _dll
    except Exception as e:
        print(f"  [Desktop] DLL load error: {e}")
        return None


def _get_hwnd_for_process(pid: int, timeout: float = 5.0) -> int | None:
    """
    Process ID se uska window handle (HWND) dhundho.
    Window appear hone tak wait karta hai.
    """
    if not WIN32_AVAILABLE:
        return None

    start = time.time()
    while time.time() - start < timeout:
        hwnds = []

        def _callback(hwnd, _):
            try:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid:
                    # Sirf visible, main windows lo
                    if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                        hwnds.append(hwnd)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_callback, None)

        if hwnds:
            # Sabse bada window likely main window hai
            return max(hwnds, key=lambda h: win32gui.GetWindowRect(h)[2])

        time.sleep(0.2)

    return None


def move_to_lisa_desktop(process: subprocess.Popen, wait: float = 2.5) -> bool:
    """
    Process ka main window Lisa ke desktop pe move karo.
    Screen switch nahi hogi — tum Desktop 1 pe rahoge.

    Args:
        process: subprocess.Popen object (launched app)
        wait   : window appear hone ka wait time

    Returns:
        True agar move successful, False otherwise
    """
    dll = _load_dll()
    if dll is None or not WIN32_AVAILABLE:
        return False

    # Desktop count check
    desktop_count = dll.GetDesktopCount()
    if desktop_count <= LISA_DESKTOP:
        print(f"  [Desktop] Sirf {desktop_count} desktops hain!")
        print(f"  Win+Ctrl+D se {LISA_DESKTOP + 1 - desktop_count} aur banao.")
        return False

    # Window appear hone ka wait
    time.sleep(wait)

    # HWND dhundho
    hwnd = _get_hwnd_for_process(process.pid)
    if hwnd is None:
        print(f"  [Desktop] Window nahi mili PID {process.pid} ke liye")
        return False

    # Move to Lisa's desktop (NO SWITCH — ye key point hai)
    result = dll.MoveWindowToDesktopNumber(hwnd, LISA_DESKTOP)
    if result == -1:
        print(f"  [Desktop] Move failed HWND {hwnd}")
        return False

    return True


def launch_on_lisa_desktop(cmd: list, wait: float = 2.5) -> subprocess.Popen | None:
    """
    Command launch karo aur window Lisa ke desktop pe move karo.
    Tum apne desktop pe rahoge — kuch dikhega nahi.

    Args:
        cmd  : command list, e.g. ["chrome", "--new-window", "https://youtube.com"]
        wait : window appear hone ka wait

    Returns:
        subprocess.Popen object ya None
    """
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Background thread mein move karo taaki Lisa block na ho
        import threading
        def _move():
            success = move_to_lisa_desktop(process, wait)
            if success:
                pass  # Silent success
            # Agar fail ho toh window user ke desktop pe rahegi — at least kaam toh hoga

        thread = threading.Thread(target=_move, daemon=True)
        thread.start()

        return process

    except FileNotFoundError as e:
        print(f"  [Desktop] Command nahi mila: {cmd[0]}")
        return None
    except Exception as e:
        print(f"  [Desktop] Launch error: {e}")
        return None


def get_status() -> dict:
    """Desktop manager ka status check karo."""
    dll          = _load_dll()
    dll_ok       = dll is not None
    win32_ok     = WIN32_AVAILABLE
    desktop_count = dll.GetDesktopCount() if dll_ok else 0
    current       = dll.GetCurrentDesktopNumber() if dll_ok else -1

    return {
        "dll_loaded"    : dll_ok,
        "win32_available": win32_ok,
        "desktop_count" : desktop_count,
        "current_desktop": current,
        "lisa_desktop"  : LISA_DESKTOP,
        "ready"         : dll_ok and win32_ok and desktop_count > LISA_DESKTOP
    }


# ── New window detection approach ─────────────────────────────────────

def _get_all_visible_hwnds() -> set[int]:
    """Sabhi visible windows ke HWNDs collect karo."""
    if not WIN32_AVAILABLE:
        return set()

    hwnds = set()

    def _callback(hwnd, _):
        try:
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                hwnds.add(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(_callback, None)
    return hwnds


def open_file_on_lisa_desktop(file_path: str, wait: float = 3.0) -> bool:
    """
    File ko default app mein open karo aur Desktop 3 pe move karo.
    
    Strategy: PID se window nahi milti (cmd/start exit ho jata hai),
    toh pehle se existing windows ka snapshot lo, phir file open karo,
    aur naye windows ko detect karke Desktop 3 pe move karo.

    Args:
        file_path : file ka full path
        wait      : naye window appear hone ka wait (seconds)

    Returns:
        True agar move successful, False otherwise
    """
    import os

    dll = _load_dll()
    if dll is None or not WIN32_AVAILABLE:
        return False

    desktop_count = dll.GetDesktopCount()
    if desktop_count <= LISA_DESKTOP:
        return False

    # Step 1: Snapshot before opening
    before_hwnds = _get_all_visible_hwnds()

    # Step 2: Open file with default app
    try:
        os.startfile(file_path)
    except Exception as e:
        print(f"  [Desktop] File open error: {e}")
        return False

    # Step 3: Wait for new window to appear
    time.sleep(wait)

    # Step 4: Find NEW windows that appeared
    after_hwnds   = _get_all_visible_hwnds()
    new_hwnds     = after_hwnds - before_hwnds

    if not new_hwnds:
        # Retry once with more wait
        time.sleep(2.0)
        after_hwnds = _get_all_visible_hwnds()
        new_hwnds   = after_hwnds - before_hwnds

    if not new_hwnds:
        print(f"  [Desktop] Naya window detect nahi hua")
        return False

    # Step 5: Move ALL new windows to Lisa's desktop
    moved = 0
    for hwnd in new_hwnds:
        try:
            result = dll.MoveWindowToDesktopNumber(hwnd, LISA_DESKTOP)
            if result != -1:
                title = win32gui.GetWindowText(hwnd)
                print(f"  [Desktop] Moved to Desktop {LISA_DESKTOP + 1}: {title}")
                moved += 1
        except Exception:
            pass

    return moved > 0