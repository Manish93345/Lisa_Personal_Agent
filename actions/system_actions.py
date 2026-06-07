"""
LISA — System Actions (with background desktop support)
=========================================================
Browser/app actions Desktop 3 pe hoti hain — screen disturb nahi hoti.
"""

import subprocess
import webbrowser
import os
import urllib.parse
import threading
from pathlib import Path

# Chrome ka path — tumhare PC pe check karo
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _get_chrome() -> str | None:
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None


def _launch_chrome_on_lisa_desktop(url: str) -> tuple[bool, str]:
    """
    Chrome ko Lisa ke desktop pe launch karo — screen disturb nahi hogi.
    """
    from actions.desktop_manager import launch_on_lisa_desktop, get_status

    status = get_status()
    chrome = _get_chrome()

    if not chrome:
        # Chrome nahi mila — default browser use karo (visible hoga)
        webbrowser.open(url)
        return True, "browser mein khola (background setup ke liye Chrome install karo)"

    if not status["ready"]:
        # Desktop manager ready nahi — normal browser
        webbrowser.open(url)
        return True, "browser mein khola!"

    # Chrome new window Lisa ke desktop pe
    process = launch_on_lisa_desktop(
        [chrome, "--new-window", "--start-minimized", url],
        wait=2.5
    )

    if process:
        return True, "background mein khola!"
    else:
        webbrowser.open(url)
        return True, "browser mein khola!"


# ── YouTube ───────────────────────────────────────────────────────────

def play_youtube(query: str) -> tuple[bool, str]:
    """YouTube pe gaana — Chrome Lisa ke desktop pe, screen disturb nahi."""
    encoded = urllib.parse.quote(f"{query} official video")
    url     = f"https://www.youtube.com/results?search_query={encoded}"

    # yt-dlp available ho toh direct video ID se play karo
    try:
        result = subprocess.run(
            ["yt-dlp", f"ytsearch1:{query} official video",
             "--get-id", "--no-playlist", "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            video_id = result.stdout.strip().split('\n')[0]
            url = f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        pass

    success, msg = _launch_chrome_on_lisa_desktop(url)
    return success, f'"{query}" {msg}'


def search_youtube(query: str) -> tuple[bool, str]:
    encoded = urllib.parse.quote(query)
    url     = f"https://www.youtube.com/results?search_query={encoded}"
    success, msg = _launch_chrome_on_lisa_desktop(url)
    return success, f'YouTube pe "{query}" {msg}'


# ── Website ───────────────────────────────────────────────────────────

def open_website(query: str) -> tuple[bool, str]:
    url = query if query.startswith("http") else f"https://{query}"
    success, msg = _launch_chrome_on_lisa_desktop(url)
    name = query.replace("https://","").replace("http://","").replace("www.","").split("/")[0]
    return success, f"{name} {msg}"


# ── Spotify ──────────────────────────────────────────────────────────

def search_spotify(query: str) -> tuple[bool, str]:
    try:
        encoded = urllib.parse.quote(query)
        try:
            os.startfile(f"spotify:search:{encoded}")
            return True, f'Spotify pe "{query}" laga diya!'
        except Exception:
            success, msg = _launch_chrome_on_lisa_desktop(
                f"https://open.spotify.com/search/{encoded}"
            )
            return success, f'Spotify pe "{query}" {msg}'
    except Exception:
        return False, "Spotify nahi khula"


# ── Google search ─────────────────────────────────────────────────────

def search_google(query: str) -> tuple[bool, str]:
    url     = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    success, msg = _launch_chrome_on_lisa_desktop(url)
    return success, f'"{query}" search kar diya {msg}'


# ── App open ──────────────────────────────────────────────────────────

APP_MAP = {
    "vs code": "code", "vscode": "code", "visual studio code": "code",
    "notepad": "notepad", "notepad++": "notepad++",
    "chrome": "chrome", "google chrome": "chrome",
    "firefox": "firefox", "edge": "msedge", "brave": "brave",
    "calculator": "calc", "calc": "calc",
    "paint": "mspaint", "task manager": "taskmgr",
    "file explorer": "explorer", "explorer": "explorer",
    "cmd": "cmd", "terminal": "cmd", "powershell": "powershell",
    "whatsapp": "whatsapp", "telegram": "telegram",
    "discord": "discord", "zoom": "zoom", "vlc": "vlc",
}


def open_app(query: str) -> tuple[bool, str]:
    q   = query.lower().strip()
    cmd = APP_MAP.get(q, q)
    try:
        subprocess.Popen(cmd, shell=True)
        return True, f"{query} khol diya!"
    except Exception:
        return False, f"{query} nahi mila"


# ── Folder open ──────────────────────────────────────────────────────

def open_folder(query: str) -> tuple[bool, str]:
    folder_map = {
        "desktop":   str(Path.home() / "Desktop"),
        "downloads": str(Path.home() / "Downloads"),
        "documents": str(Path.home() / "Documents"),
        "d": "D:\\", "d drive": "D:\\",
        "c": "C:\\", "c drive": "C:\\",
    }
    path = folder_map.get(query.lower().strip(), query)
    try:
        os.startfile(path)
        return True, f"lo khol diya {query}!"
    except Exception:
        return False, f"{query} nahi mila"


# ── File open ─────────────────────────────────────────────────────────

def open_file(query: str) -> tuple[bool, str]:
    try:
        if os.path.exists(query):
            os.startfile(query)
            return True, "file khol di!"
        return False, f"file nahi mili: {query}"
    except Exception:
        return False, "file nahi khuli"


# ── System commands ───────────────────────────────────────────────────

def system_command(query: str) -> tuple[bool, str]:
    q = query.lower().strip()

    # ── Screenshot ────────────────────────────────────────────────────
    if "screenshot" in q:
        try:
            import datetime
            fname   = f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            desktop = str(Path.home() / "Desktop" / fname)
            subprocess.run([
                "powershell", "-command",
                f"Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                f"$b=New-Object System.Drawing.Bitmap("
                f"[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,"
                f"[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); "
                f"$g=[System.Drawing.Graphics]::FromImage($b); "
                f"$g.CopyFromScreen(0,0,0,0,$b.Size); $b.Save('{desktop}')"
            ], shell=True)
            return True, "screenshot le liya!"
        except Exception:
            return False, "screenshot nahi le payi"

    # ── Volume Up ─────────────────────────────────────────────────────
    elif any(x in q for x in ["volume up", "volume badhao", "volume badha",
                               "awaz badhao", "awaz badha"]):
        subprocess.run(["powershell", "-c",
            "$wsh=New-Object -ComObject WScript.Shell;$wsh.SendKeys([char]175)"],
            shell=True)
        return True, "volume badha diya!"

    # ── Volume Down ───────────────────────────────────────────────────
    elif any(x in q for x in ["volume down", "volume kam", "volume ghata",
                               "awaz kam", "awaz ghata"]):
        subprocess.run(["powershell", "-c",
            "$wsh=New-Object -ComObject WScript.Shell;$wsh.SendKeys([char]174)"],
            shell=True)
        return True, "volume ghata diya!"

    # ── Volume Mute ───────────────────────────────────────────────────
    elif "mute" in q or "chup" in q:
        subprocess.run(["powershell", "-c",
            "$wsh=New-Object -ComObject WScript.Shell;$wsh.SendKeys([char]173)"],
            shell=True)
        return True, "mute kar diya!"

    # ── Volume Set (specific percentage) ──────────────────────────────
    elif "volume" in q:
        import re
        match = re.search(r'(\d+)', q)
        if match:
            level = min(100, max(0, int(match.group(1))))

            # Method 1: pycaw (Python Windows Audio API — most reliable)
            try:
                from pycaw.pycaw import AudioUtilities

                speakers = AudioUtilities.GetSpeakers()
                volume = speakers.EndpointVolume
                volume.SetMasterVolumeLevelScalar(level / 100.0, None)
                return True, f"volume {level}% kar diya!"
            except Exception as e:
                print(f"  [Volume] pycaw error: {e}")

            # Method 2: nircmd fallback
            try:
                subprocess.run(
                    ["nircmd", "setsysvolume", str(int(level * 655.35))],
                    capture_output=True, timeout=3
                )
                return True, f"volume {level}% kar diya!"
            except Exception:
                pass

            return False, f"volume set nahi hua — try: 'volume badhao' ya 'volume kam karo'"
        return False, "volume level samajh nahi aayi (e.g., 'volume 50')"

    # ── Brightness ────────────────────────────────────────────────────
    elif any(x in q for x in ["brightness", "roushni", "roshni", "screen light"]):
        import re
        match = re.search(r'(\d+)', q)

        if any(x in q for x in ["kam", "down", "low", "ghata", "dark"]):
            level = 30  # dim
        elif any(x in q for x in ["badha", "up", "high", "zyada", "bright", "max"]):
            level = 90  # bright
        elif match:
            level = min(100, max(0, int(match.group(1))))
        else:
            level = 50  # default medium

        try:
            ps_cmd = (
                f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                f".WmiSetBrightness(1,{level})"
            )
            result = subprocess.run(
                ["powershell", "-c", ps_cmd],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True, f"brightness {level}% kar diya!"
            else:
                return False, f"brightness change nahi hui — laptop nahi hai ya driver issue"
        except Exception as e:
            return False, f"brightness error: {e}"

    # ── WiFi ──────────────────────────────────────────────────────────
    elif any(x in q for x in ["wifi", "wi-fi", "internet", "network"]):
        if any(x in q for x in ["band", "off", "disable", "disconnect", "hatao"]):
            try:
                subprocess.run(
                    ["netsh", "interface", "set", "interface", "Wi-Fi", "disable"],
                    capture_output=True, timeout=5
                )
                return True, "WiFi band kar diya!"
            except Exception:
                return False, "WiFi band nahi hua — admin rights chahiye"
        elif any(x in q for x in ["chalu", "on", "enable", "connect", "lagao", "start"]):
            try:
                subprocess.run(
                    ["netsh", "interface", "set", "interface", "Wi-Fi", "enable"],
                    capture_output=True, timeout=5
                )
                return True, "WiFi chalu kar diya!"
            except Exception:
                return False, "WiFi chalu nahi hua — admin rights chahiye"
        else:
            # WiFi status check
            try:
                result = subprocess.run(
                    ["netsh", "interface", "show", "interface"],
                    capture_output=True, text=True, timeout=5
                )
                if "Connected" in result.stdout:
                    return True, "WiFi connected hai!"
                elif "Disconnected" in result.stdout:
                    return True, "WiFi disconnected hai!"
                else:
                    return True, f"WiFi status: {result.stdout.strip()[:200]}"
            except Exception:
                return False, "WiFi status check nahi hua"

    # ── Battery ───────────────────────────────────────────────────────
    elif any(x in q for x in ["battery", "charge", "charging"]):
        try:
            ps_cmd = (
                "(Get-WmiObject Win32_Battery | Select-Object "
                "EstimatedChargeRemaining, BatteryStatus | ConvertTo-Json)"
            )
            result = subprocess.run(
                ["powershell", "-c", ps_cmd],
                capture_output=True, text=True, timeout=5
            )
            import json
            data = json.loads(result.stdout.strip())
            pct = data.get("EstimatedChargeRemaining", "?")
            status_code = data.get("BatteryStatus", 0)
            # BatteryStatus: 1=discharging, 2=AC/charging, 3-5=various
            charging = "charging" if status_code == 2 else "discharging"
            return True, f"battery {pct}% hai ({charging})"
        except Exception:
            # Fallback: maybe desktop PC (no battery)
            try:
                result = subprocess.run(
                    ["powershell", "-c",
                     "(Get-WmiObject Win32_Battery).EstimatedChargeRemaining"],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    return True, f"battery {result.stdout.strip()}% hai"
                return True, "battery nahi mili — desktop PC hai shayad"
            except Exception:
                return False, "battery status nahi mil rha"

    # ── Timer / Alarm ─────────────────────────────────────────────────
    elif any(x in q for x in ["timer", "alarm", "remind", "yaad"]):
        import re
        match = re.search(r'(\d+)', q)
        if match:
            minutes = int(match.group(1))
            seconds = minutes * 60

            # Start timer in background thread
            def _timer_done():
                # Show Windows notification/toast
                try:
                    subprocess.run([
                        "powershell", "-c",
                        f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                        f"$n = New-Object System.Windows.Forms.NotifyIcon; "
                        f"$n.Icon = [System.Drawing.SystemIcons]::Information; "
                        f"$n.BalloonTipTitle = 'Lisa Timer'; "
                        f"$n.BalloonTipText = '{minutes} minute ka timer complete ho gaya!'; "
                        f"$n.Visible = $true; "
                        f"$n.ShowBalloonTip(10000); "
                        f"Start-Sleep -Seconds 10; "
                        f"$n.Dispose()"
                    ], timeout=20)
                except Exception:
                    pass
                # Also play system beep
                try:
                    import winsound
                    for _ in range(3):
                        winsound.Beep(1000, 500)
                        import time; time.sleep(0.3)
                except Exception:
                    pass

            timer = threading.Timer(seconds, _timer_done)
            timer.daemon = True
            timer.start()
            return True, f"{minutes} minute ka timer laga diya! Jab complete hoga toh bata dungi."
        return False, "kitne minute ka timer? (e.g., 'timer 5 minute')"

    # ── Close / Kill App ──────────────────────────────────────────────
    elif any(x in q for x in ["close", "band karo", "band kar do", "kill",
                               "hatao", "chhod do"]):
        # Extract app name
        app_keywords = ["close", "band karo", "band kar do", "kill",
                        "hatao", "chhod do", "karo", "kar do"]
        app_name = q
        for kw in app_keywords:
            app_name = app_name.replace(kw, "")
        app_name = app_name.strip()

        if not app_name:
            return False, "kaunsa app band karna hai?"

        # Map common names to process names
        PROCESS_MAP = {
            "chrome": "chrome.exe", "google chrome": "chrome.exe",
            "edge": "msedge.exe", "microsoft edge": "msedge.exe",
            "firefox": "firefox.exe",
            "notepad": "notepad.exe", "notepad++": "notepad++.exe",
            "vs code": "Code.exe", "vscode": "Code.exe",
            "vlc": "vlc.exe",
            "discord": "Discord.exe",
            "telegram": "Telegram.exe",
            "word": "WINWORD.EXE", "excel": "EXCEL.EXE",
            "powerpoint": "POWERPNT.EXE",
            "calculator": "Calculator.exe", "calc": "Calculator.exe",
            "paint": "mspaint.exe",
            "spotify": "Spotify.exe",
            "zoom": "Zoom.exe",
            "task manager": "Taskmgr.exe",
        }

        proc = PROCESS_MAP.get(app_name, f"{app_name}.exe")
        try:
            result = subprocess.run(
                ["taskkill", "/IM", proc, "/F"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True, f"{app_name} band kar diya!"
            else:
                return False, f"{app_name} nahi mila ya band nahi hua"
        except Exception:
            return False, f"{app_name} band nahi hua"

    # ── Lock Screen ───────────────────────────────────────────────────
    elif any(x in q for x in ["lock", "screen lock", "tala", "lock karo"]):
        try:
            subprocess.run(
                ["rundll32.exe", "user32.dll,LockWorkStation"],
                timeout=3
            )
            return True, "screen lock kar diya!"
        except Exception:
            return False, "lock nahi hua"

    # ── Shutdown / Restart / Sleep ────────────────────────────────────
    elif any(x in q for x in ["shutdown", "band karo computer", "shut down"]):
        try:
            subprocess.run(["shutdown", "/s", "/t", "30"], timeout=3)
            return True, "30 second mein shutdown ho jayega! Cancel: shutdown /a"
        except Exception:
            return False, "shutdown nahi hua"

    elif any(x in q for x in ["restart", "reboot"]):
        try:
            subprocess.run(["shutdown", "/r", "/t", "30"], timeout=3)
            return True, "30 second mein restart hoga! Cancel: shutdown /a"
        except Exception:
            return False, "restart nahi hua"

    elif any(x in q for x in ["sleep", "hibernate", "neend"]):
        try:
            subprocess.run(
                ["powershell", "-c", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"],
                timeout=3
            )
            return True, "sleep mode mein jaa rha hai!"
        except Exception:
            return False, "sleep nahi hua"

    return False, f"ye command samajh nahi aayi: {query}"


# ── Smart File Finder + Open ─────────────────────────────────────────

def smart_find_and_open(query: str, folder: str = "", file: str = "", on_main_screen: bool = False) -> tuple[bool, str]:
    """
    Smart fuzzy file/folder finder — dhundhega aur Desktop 3 pe kholega.
    Agar user explicitly bole "main screen pe" toh main desktop pe kholega.

    Args:
        query          : original user message (fallback)
        folder         : folder hint from intent detector
        file           : file hint from intent detector
        on_main_screen : True = main desktop, False = Desktop 3 (default)

    Returns:
        (success, message)
    """
    from actions.file_finder import smart_find

    success, path, message = smart_find(folder_hint=folder, file_hint=file)

    if not success or not path:
        return False, message

    # ── Open on main screen (user explicitly asked) ──────────────────
    if on_main_screen:
        try:
            os.startfile(path)
            return True, f"{message}, khol diya tumhare screen pe!"
        except Exception as e:
            return False, f"file khulne mein error: {e}"

    # ── Open on Desktop 3 (default — background mein) ────────────────
    from actions.desktop_manager import get_status, open_file_on_lisa_desktop

    status = get_status()
    if not status["ready"]:
        # Desktop 3 nahi hai — fallback to main screen
        os.startfile(path)
        return True, f"{message}, khol diya! (Desktop 3 ready nahi tha)"

    # Window-snapshot approach: works for BOTH files and folders
    # (PID-based approach fails for explorer.exe because it reuses instances)
    import threading

    def _open_in_background():
        moved = open_file_on_lisa_desktop(path, wait=3.0)
        if not moved:
            print(f"  [Desktop] Desktop 3 pe move nahi hua, main screen pe khula hoga")

    thread = threading.Thread(target=_open_in_background, daemon=True)
    thread.start()

    item_type = "folder" if os.path.isdir(path) else os.path.basename(path)
    return True, f"{message}, background mein khol rhi hoon!"