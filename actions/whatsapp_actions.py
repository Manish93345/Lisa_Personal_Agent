"""
LISA — WhatsApp Automation (v2 Fixed)
========================================
Fixes:
  1. BMP error — send_keys se emoji crash hota tha.
     Ab clipboard (pyperclip) se paste hoga — emoji/Hindi sab kaam karega.
  2. Search slow — unnecessary waits kam kiye.
"""

import time
import random
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.options import Options
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, ElementNotInteractableException
)

try:
    import pyperclip
    CLIPBOARD_OK = True
except ImportError:
    CLIPBOARD_OK = False

try:
    from config import settings
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import settings


# ══════════════════════════════════════════════════════════════════════
#  SELECTORS
# ══════════════════════════════════════════════════════════════════════

SEARCH_BOX_SELECTORS = [
    (By.CSS_SELECTOR,  'div[role="searchbox"]'),
    (By.CSS_SELECTOR,  'div[contenteditable="true"][role="searchbox"]'),
    (By.CSS_SELECTOR,  'div[aria-label="Search input textbox"]'),
    (By.XPATH,         '//div[@aria-label="Search input textbox"]'),
    (By.XPATH,         '//div[@role="searchbox"]'),
    (By.CSS_SELECTOR,  'div[data-testid="search-input"]'),
    (By.CSS_SELECTOR,  '[data-testid="chat-list-search"] div[contenteditable="true"]'),
    (By.XPATH,         '//*[@data-testid="chat-list-search"]//div[@contenteditable="true"]'),
    (By.CSS_SELECTOR,  'div[contenteditable="true"][data-tab="3"]'),
    (By.XPATH,         '//div[@contenteditable="true"][@data-tab="3"]'),
    (By.CSS_SELECTOR,  'div[title="Search input textbox"]'),
    (By.XPATH,         '//div[@title="Search input textbox"]'),
    (By.XPATH,         '//div[@contenteditable="true"][contains(@aria-label,"Search")]'),
    (By.CSS_SELECTOR,  'input[type="text"][title*="Search"]'),
    (By.CSS_SELECTOR,  '#side div[contenteditable="true"]'),
    (By.XPATH,         '//div[@id="side"]//div[@contenteditable="true"]'),
]

LOGIN_DETECT_SELECTORS = [
    (By.CSS_SELECTOR, 'div[data-testid="chat-list"]'),
    (By.CSS_SELECTOR, '#side'),
    (By.CSS_SELECTOR, '#pane-side'),
    (By.XPATH,        '//div[@aria-label="Chat list"]'),
]

MSG_BOX_SELECTORS = [
    (By.CSS_SELECTOR,  'div[contenteditable="true"][data-tab="10"]'),
    (By.XPATH,         '//div[@contenteditable="true"][@data-tab="10"]'),
    (By.CSS_SELECTOR,  'div[aria-label="Type a message"]'),
    (By.XPATH,         '//div[@aria-label="Type a message"]'),
    (By.CSS_SELECTOR,  'div[title="Type a message"]'),
    (By.XPATH,         '//div[@role="textbox"][contains(@title,"message")]'),
    (By.XPATH,         '//footer//div[@contenteditable="true"]'),
    (By.XPATH,         '//div[@data-testid="conversation-compose-box-input"]'),
]


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════

def _delay(lo=0.3, hi=0.7):
    time.sleep(random.uniform(lo, hi))


def _find_element(driver, selectors, timeout=6):
    """
    Fast-first approach: pehle 1s mein sabko try karo (fast sweep),
    agar nahi mila toh phir full timeout se retry karo (slow fallback).
    Ye 16 selectors x 6s = 96s wait problem solve karta hai.
    """
    # Fast sweep: 1s per selector
    fast_timeout = min(1, timeout)
    for by, val in selectors:
        try:
            el = WebDriverWait(driver, fast_timeout).until(
                EC.element_to_be_clickable((by, val))
            )
            return el
        except (TimeoutException, NoSuchElementException):
            continue

    # Slow fallback: full timeout, but only top 4 most reliable selectors
    if timeout > 1:
        for by, val in selectors[:4]:
            try:
                el = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((by, val))
                )
                return el
            except (TimeoutException, NoSuchElementException):
                continue
    return None


def _type_via_clipboard(driver, element, text: str):
    """
    THE FIX for BMP error:
    send_keys emoji bhejne ki koshish karta hai byte-by-byte,
    msedgedriver BMP (U+0000 to U+FFFF) se bahar nahi ja sakta.
    Clipboard se paste karo — koi restriction nahi.

    Requires: pip install pyperclip
    """
    if CLIPBOARD_OK:
        pyperclip.copy(text)
        element.send_keys(Keys.CONTROL + "v")
        _delay(0.15, 0.25)
    else:
        # JS execCommand fallback (pyperclip nahi hai toh)
        driver.execute_script(
            "arguments[0].focus();"
            "document.execCommand('insertText', false, arguments[1]);",
            element, text
        )
        _delay(0.15, 0.25)


def _js_find_search_box(driver):
    try:
        return driver.execute_script("""
            let el = document.querySelector('div[role="searchbox"]');
            if (el) return el;
            el = document.querySelector('[aria-label*="Search"][contenteditable="true"]');
            if (el) return el;
            const side = document.querySelector('#side') || document.querySelector('#pane-side');
            if (side) {
                el = side.querySelector('div[contenteditable="true"]');
                if (el) return el;
            }
            el = document.querySelector('div[data-tab="3"]');
            if (el) return el;
            for (const div of document.querySelectorAll('div[contenteditable="true"]')) {
                const label = (div.getAttribute('aria-label') || '').toLowerCase();
                const title = (div.getAttribute('title') || '').toLowerCase();
                if (label.includes('search') || title.includes('search')) return div;
            }
            return null;
        """)
    except Exception as e:
        print(f"  [WhatsApp] JS search box error: {e}")
        return None


def _js_click_contact(driver, name: str):
    name_lower = name.lower()
    try:
        return driver.execute_script(f"""
            const q = "{name_lower}";
            for (const span of document.querySelectorAll('span[title]')) {{
                if (!span.offsetParent) continue;
                if (span.title.toLowerCase().includes(q)) {{
                    let el = span;
                    for (let i = 0; i < 10; i++) {{
                        el = el.parentElement;
                        if (!el) break;
                        const role = el.getAttribute('role');
                        const tab  = el.getAttribute('tabindex');
                        if (role === 'listitem' || role === 'button' || tab === '0' || tab === '-1') {{
                            el.click();
                            return span.title;
                        }}
                    }}
                    span.click();
                    return span.title;
                }}
            }}
            return null;
        """)
    except Exception as e:
        print(f"  [WhatsApp] JS contact click error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
#  MAIN CLASS
# ══════════════════════════════════════════════════════════════════════

class WhatsAppDriver:

    def __init__(self):
        self.driver: webdriver.Edge | None = None

    @staticmethod
    def _kill_stale_edge():
        """
        Profile lock issue fix:
        Agar koi purana Edge process same whatsapp_profile use kar rha hai,
        toh naya Edge start nahi hoga ('session not created: crashed').
        Pehle purane processes kill karo.
        """
        import subprocess
        profile_dir = settings.WHATSAPP_PROFILE_DIR
        lockfile = Path(profile_dir) / "lockfile"

        if not lockfile.exists():
            return  # No lock — safe to start

        # Find Edge processes using our profile via command line args
        try:
            result = subprocess.run(
                ["wmic", "process", "where",
                 "name='msedge.exe'", "get", "ProcessId,CommandLine"],
                capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.strip().split("\n")

            profile_norm = str(Path(profile_dir)).lower().replace("\\", "\\\\")
            pids_to_kill = []

            for line in lines:
                line_lower = line.lower()
                # Check if this Edge process is using our whatsapp_profile
                if "whatsapp_profile" in line_lower or profile_norm in line_lower:
                    # Extract PID (last number on the line)
                    parts = line.strip().split()
                    for part in reversed(parts):
                        if part.isdigit():
                            pids_to_kill.append(int(part))
                            break

            if pids_to_kill:
                print(f"  [WhatsApp] Purane Edge processes kill kar rhi hoon: {pids_to_kill}")
                for pid in pids_to_kill:
                    try:
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                       capture_output=True, timeout=5)
                    except Exception:
                        pass
                time.sleep(1)  # Wait for processes to die

            # Remove stale lockfile if processes were killed
            if pids_to_kill and lockfile.exists():
                try:
                    lockfile.unlink()
                except Exception:
                    pass

        except Exception as e:
            print(f"  [WhatsApp] Stale process cleanup error: {e}")
            # Try to just remove lockfile
            try:
                if lockfile.exists():
                    lockfile.unlink()
            except Exception:
                pass

    def start(self) -> bool:
        if self.driver:
            return True

        print("  [WA] Edge browser start kar raha hoon...")

        from actions.desktop_manager import _get_all_visible_hwnds, _load_dll, LISA_DESKTOP, WIN32_AVAILABLE
        import time
        
        move_to_desktop3 = False
        before_hwnds = set()
        
        if WIN32_AVAILABLE and _load_dll() is not None:
            move_to_desktop3 = True
            before_hwnds = _get_all_visible_hwnds()

        opts = Options()
        opts.add_argument(f"user-data-dir={settings.WHATSAPP_PROFILE_DIR}")
        opts.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        opts.add_experimental_option('useAutomationExtension', False)

        try:
            self.driver = webdriver.Edge(options=opts)
            
            # 🔴 FIX: Pehle URL load karo, connection break nahi hoga
            self.driver.get(settings.WHATSAPP_URL)
            
            # Phir chupke se Desktop 3 pe move karo
            if move_to_desktop3:
                time.sleep(1.0)
                after_hwnds = _get_all_visible_hwnds()
                new_hwnds = after_hwnds - before_hwnds
                
                if new_hwnds:
                    dll = _load_dll()
                    for hwnd in new_hwnds:
                        try:
                            dll.MoveWindowToDesktopNumber(hwnd, LISA_DESKTOP)
                            print(f"  [Desktop] WhatsApp browser secretly moved to Desktop 3 (hwnd: {hwnd})")
                        except Exception:
                            pass
            
            # Wait for chat list
            WebDriverWait(self.driver, settings.WHATSAPP_LOAD_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "pane-side"))
            )
            print("  [WA] WhatsApp is ready on Desktop 3!")
            return True
        except Exception as e:
            print(f"  [WA] Error in start: {e}")
            self.close()
            return False

    def _wait_login(self, timeout=60) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.any_of(*[
                    EC.presence_of_element_located((by, val))
                    for by, val in LOGIN_DETECT_SELECTORS
                ])
            )
            return True
        except TimeoutException:
            return False

    def _get_search_box(self, timeout=5):
        el = _find_element(self.driver, SEARCH_BOX_SELECTORS, timeout=timeout)
        return el or _js_find_search_box(self.driver)

    def _escape_to_main_chat(self):
        """Agar Archived view ya koi aur view khula hai, ESC press karke main chat list pe aao."""
        try:
            # Check if Archived view is open
            archived = self.driver.find_elements(By.XPATH,
                '//header//span[contains(text(),"Archived")]')
            if archived:
                self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                _delay(0.3, 0.5)
                self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                _delay(0.3, 0.5)
                print("  [WhatsApp] Archived se wapas main chat pe aayi")
        except Exception:
            pass

    def _verify_chat_opened(self, timeout=4) -> bool:
        """Verify ki contact ka chat actually khul gaya — message box dikhna chahiye."""
        try:
            for by, val in MSG_BOX_SELECTORS[:3]:  # top 3 reliable selectors
                try:
                    WebDriverWait(self.driver, timeout).until(
                        EC.presence_of_element_located((by, val))
                    )
                    return True
                except TimeoutException:
                    continue
        except Exception:
            pass
        return False

    def search_and_open_contact(self, name: str) -> bool:
        print(f"  [WhatsApp] '{name}' dhundh rhi hoon...")

        # Agar Archived view khula hai toh pehle wapas aao
        self._escape_to_main_chat()

        search_box = self._get_search_box(timeout=3)
        if not search_box:
            print("  [X] Search box nahi mila")
            self._save_debug()
            return False

        try:
            self.driver.execute_script("arguments[0].click();", search_box)
            _delay(0.15, 0.25)
            search_box.send_keys(Keys.CONTROL + "a")
            search_box.send_keys(Keys.DELETE)
            _delay(0.08, 0.12)
            search_box.send_keys(name)
        except ElementNotInteractableException:
            self.driver.execute_script("arguments[0].focus();", search_box)
            search_box.send_keys(name)

        _delay(0.8, 1.0)   # results load hone ka wait

        clicked = self._click_first_result(name)
        if not clicked:
            return False

        # Verify chat actually opened (message box should appear)
        if not self._verify_chat_opened(timeout=3):
            print(f"  [WhatsApp] Chat nahi khula '{name}' ka — retry...")
            # Maybe Archived opened — escape and retry
            self._escape_to_main_chat()
            return False

        return True

    def _click_first_result(self, name: str) -> bool:
        name_lower = name.lower().strip()

        # ── Collect ALL visible span[title] — don't filter by XPath contains ──
        # (XPath contains fails on typos like "Roomate" vs "roommate")
        try:
            all_spans = WebDriverWait(self.driver, 5).until(
                EC.presence_of_all_elements_located(
                    (By.XPATH, '//span[@title]')
                )
            )
        except TimeoutException:
            all_spans = []

        # Filter to visible, short-title spans (contact/group names)
        visible_spans = []
        for span in all_spans:
            try:
                if not span.is_displayed():
                    continue
                title = span.get_attribute('title') or ''
                if len(title) > 60 or len(title) < 1:
                    continue
                visible_spans.append((span, title))
            except Exception:
                continue

        if visible_spans:
            import re
            pattern = re.compile(r'\b' + re.escape(name_lower) + r'\b')

            # Pass 1: exact word boundary match
            for span, title in visible_spans:
                if pattern.search(title.lower()):
                    if self._click_parent_row(span):
                        _delay(0.4, 0.6)
                        print(f"  [✓] Contact mila: '{title}'")
                        return True

            # Pass 2: startswith match
            for span, title in visible_spans:
                if title.lower().startswith(name_lower):
                    if self._click_parent_row(span):
                        _delay(0.4, 0.6)
                        print(f"  [✓] Contact mila (startswith): '{title}'")
                        return True

            # Pass 3: contains match
            for span, title in visible_spans:
                if name_lower in title.lower():
                    if self._click_parent_row(span):
                        _delay(0.4, 0.6)
                        print(f"  [✓] Contact mila (contains): '{title}'")
                        return True

            # Pass 4: FUZZY match — handles typos (e.g. "roommate" vs "Roomate group")
            try:
                from rapidfuzz import fuzz
                best_score = 0
                best_span = None
                best_title = ""

                for span, title in visible_spans:
                    title_lower = title.lower()

                    # CRITICAL: Use different scorers based on length comparison
                    # partial_ratio("roommate","om") = 100% (WRONG! "om" is inside "roommate")
                    # WRatio("roommate","om") = ~36% (CORRECT! length mismatch penalized)
                    if len(title_lower) >= len(name_lower):
                        # Target is longer (e.g. "roomate group 🌿🎉" vs "roommate")
                        # → partial_ratio is ideal here
                        score = fuzz.partial_ratio(name_lower, title_lower)
                    else:
                        # Target is shorter (e.g. "om" vs "roommate")
                        # → WRatio penalizes length mismatch properly
                        score = fuzz.WRatio(name_lower, title_lower)

                    if score > best_score:
                        best_score = score
                        best_span = span
                        best_title = title

                # Accept fuzzy match if score >= 85 (75 was too loose — garbage matches)
                # Better to say "contact nahi mila" than send to WRONG person/group
                if best_score >= 85 and best_span is not None:
                    if self._click_parent_row(best_span):
                        _delay(0.4, 0.6)
                        print(f"  [✓] Contact mila (fuzzy {best_score}%): '{best_title}'")
                        return True
                elif best_score >= 70 and best_span is not None:
                    # Log warning but DON'T auto-accept — too risky
                    print(f"  [⚠] Low confidence match ({best_score}%): '{best_title}' — skipping (threshold 85%)")
            except ImportError:
                pass  # rapidfuzz not available, skip fuzzy

        # Fallback: cell-frame click — BUT filter out Archived/non-chat rows
        SKIP_TEXTS = {'archived', 'communities', 'channels', 'status', 'newsletter',
                      'see more chat history', 'groups in common'}
        for xpath in ['//div[@data-testid="cell-frame-container"]', '//div[@role="listitem"]']:
            try:
                for cell in self.driver.find_elements(By.XPATH, xpath)[:5]:
                    if not cell.is_displayed():
                        continue
                    cell_text = (cell.text or '').lower().strip()
                    if any(skip in cell_text for skip in SKIP_TEXTS):
                        continue
                    # Check if cell has a span with title fuzzy-matching our search
                    spans = cell.find_elements(By.XPATH, './/span[@title]')
                    for s in spans:
                        s_title = (s.get_attribute('title') or '').lower()
                        if name_lower in s_title or s_title.startswith(name_lower[:3]):
                            try:
                                cell.click()
                                _delay(0.3, 0.5)
                                print(f"  [✓] Cell click: {s.get_attribute('title')}")
                                return True
                            except Exception:
                                continue
            except Exception:
                continue

        # JS fallback — last resort
        matched = _js_click_contact(self.driver, name)
        if matched:
            _delay(0.3, 0.5)
            print(f"  [✓] JS se contact mila: '{matched}'")
            return True

        print(f"  [X] '{name}' result nahi mila")
        self._save_debug()
        return False

    def _click_parent_row(self, element) -> bool:
        el = element
        try:
            for _ in range(10):
                role = el.get_attribute("role")
                tab  = el.get_attribute("tabindex")
                if role in ("listitem", "button", "gridcell") or tab in ("0", "-1"):
                    el.click()
                    return True
                parent = self.driver.execute_script(
                    "return arguments[0].parentElement;", el)
                if not parent:
                    break
                el = parent
        except Exception:
            pass
        return False

    def send_message(self, message: str) -> bool:
        msg_box = _find_element(self.driver, MSG_BOX_SELECTORS, timeout=8)
        if not msg_box:
            print("  [X] Message box nahi mila")
            return False

        try:
            self.driver.execute_script("arguments[0].click();", msg_box)
            _delay(0.2, 0.3)

            lines = message.split('\n')
            for i, line in enumerate(lines):
                if line:
                    _type_via_clipboard(self.driver, msg_box, line)
                if i < len(lines) - 1:
                    msg_box.send_keys(Keys.SHIFT + Keys.ENTER)

            _delay(0.2, 0.3)

            if settings.WHATSAPP_CONFIRM_SEND:
                print(f"\n  ┌─ Message preview ─────────────────────────")
                for line in message.split('\n'):
                    print(f"  │  {line}")
                print(f"  └───────────────────────────────────────────")
                confirm = input("  Bhejun? (y/n): ").strip().lower()
                if confirm != 'y':
                    msg_box.send_keys(Keys.ESCAPE)
                    print("  [WhatsApp] Cancel")
                    return False

            msg_box.send_keys(Keys.ENTER)
            _delay(0.3, 0.5)
            print("  [✓] Message bhej diya!")
            return True

        except Exception as e:
            print(f"  [X] Send error: {e}")
            return False

    def send_whatsapp_message(self, contact: str, message: str) -> bool:
        if not self.driver:
            if not self.start():
                return False
        if not self.search_and_open_contact(contact):
            return False
        return self.send_message(message)

    # ══════════════════════════════════════════════════════════════
    #  READ FEATURES — Unread check + Message reading
    # ══════════════════════════════════════════════════════════════

    def get_unread_chats(self) -> list:
        """
        Sidebar scan karke unread individual chats return karo.
        Groups skip — sirf individuals.
        Returns: [{"name": "Sugri", "count": 2, "preview": "bhai kal free hai?"}, ...]
        """
        if not self.driver:
            if not self.start():
                return []

        # Escape any open chat/archived view back to main sidebar
        self._escape_to_main_chat()
        _delay(0.5, 0.8)

        try:
            unread_chats = self.driver.execute_script(r"""
                const results = [];
                // Find all chat rows in sidebar
                const chatRows = document.querySelectorAll(
                    'div[data-testid="cell-frame-container"], div[role="listitem"]'
                );

                for (const row of chatRows) {
                    // Check for unread badge (green circle with number)
                    const badge = row.querySelector(
                        'span[data-testid="icon-unread-count"], ' +
                        'span.aumms1qt, ' +  // common class for unread count
                        'div[data-testid="cell-frame-primary-detail"] span[aria-label*="unread"]'
                    );
                    
                    // Also check for any green-colored badge spans with numbers
                    let unreadCount = 0;
                    if (badge) {
                        const num = parseInt(badge.textContent);
                        unreadCount = isNaN(num) ? 1 : num;
                    } else {
                        // Fallback: look for any small circular badge with number
                        const allSpans = row.querySelectorAll('span');
                        for (const s of allSpans) {
                            const txt = s.textContent.trim();
                            // Small spans with just a number (1-999) = unread count
                            if (/^\d{1,3}$/.test(txt) && s.offsetWidth < 30 && s.offsetWidth > 0) {
                                const style = window.getComputedStyle(s.parentElement || s);
                                const bg = style.backgroundColor;
                                // Green-ish badge detection
                                if (bg && (bg.includes('37, 211') || bg.includes('0, 128') ||
                                    bg.includes('37,211') || bg.includes('rgba(0'))) {
                                    unreadCount = parseInt(txt);
                                    break;
                                }
                                // Also check border-radius (circular = badge)
                                const radius = style.borderRadius;
                                if (radius && (radius.includes('50%') || parseInt(radius) > 10)) {
                                    unreadCount = parseInt(txt);
                                    break;
                                }
                            }
                        }
                    }

                    if (unreadCount === 0) continue;

                    // Get contact name from span[title]
                    const nameSpan = row.querySelector('span[title]');
                    if (!nameSpan) continue;
                    const name = nameSpan.title;

                    // Skip groups — detect by checking for group indicators
                    // Groups show member count like "You, Aniket, +5"
                    // or have group-specific data attributes
                    const groupIcon = row.querySelector(
                        'span[data-icon="default-group"], ' +
                        'span[data-icon="community"], ' +
                        'span[data-icon="newsletter"], ' +
                        'img[alt="Group icon"]'
                    );
                    if (groupIcon) continue;

                    // Another group detection: subtitle has multiple names/commas
                    const subtitle = row.querySelector(
                        'span[data-testid="last-msg-status"]'
                    );
                    const subtitleParent = row.querySelector(
                        'div[data-testid="cell-frame-secondary"]'
                    );
                    if (subtitleParent) {
                        const subText = subtitleParent.textContent || '';
                        // Groups often show "Aniket: message" or "You: message" pattern
                        // with a colon after a short name
                        const colonMatch = subText.match(/^[A-Za-z\s]{2,15}:\s/);
                        if (colonMatch && !subText.startsWith('You:')) {
                            continue; // Likely a group showing "MemberName: msg"
                        }
                    }

                    // Get message preview (last message text)
                    let preview = '';
                    const msgPreview = row.querySelector(
                        'span[data-testid="last-msg-status"] span, ' +
                        'div[data-testid="cell-frame-secondary"] span[title], ' +
                        'div[data-testid="cell-frame-secondary"] span.matched-text'
                    );
                    if (msgPreview) {
                        preview = msgPreview.textContent.trim().substring(0, 60);
                    }

                    results.push({
                        name: name,
                        count: unreadCount,
                        preview: preview
                    });
                }
                return results;
            """)

            if unread_chats:
                print(f"  [WhatsApp] {len(unread_chats)} unread individual chats mili")
            else:
                print("  [WhatsApp] Koi unread nahi")

            return unread_chats or []

        except Exception as e:
            print(f"  [WhatsApp] Unread scan error: {e}")
            self._save_debug()
            return []

    def read_messages(self, contact: str, count: int = 10) -> list:
        """
        Contact ka chat open karke last N messages read karo.
        Returns: [{"sender": "them"/"me", "text": "...", "time": "12:30"}, ...]
        """
        if not self.driver:
            if not self.start():
                return []

        if not self.search_and_open_contact(contact):
            return []

        _delay(1.0, 1.5)  # Chat load hone do

        try:
            messages = self.driver.execute_script(r"""
                const count = arguments[0];
                const results = [];

                // Find all message rows in the chat panel
                const msgRows = document.querySelectorAll(
                    'div.message-in, div.message-out'
                );

                // Get last N messages
                const startIdx = Math.max(0, msgRows.length - count);

                for (let i = startIdx; i < msgRows.length; i++) {
                    const row = msgRows[i];
                    const isIncoming = row.classList.contains('message-in');

                    // Extract message text
                    // Main text spans in WhatsApp messages
                    const textSpan = row.querySelector(
                        'span.selectable-text span, ' +
                        'span[data-testid="msg-text"] span, ' +
                        'div[data-pre-plain-text] span.selectable-text span'
                    );

                    let text = '';
                    if (textSpan) {
                        text = textSpan.textContent.trim();
                    } else {
                        // Fallback: try copyable-text area
                        const copyable = row.querySelector(
                            'div.copyable-text, div[data-pre-plain-text]'
                        );
                        if (copyable) {
                            // Get text but skip timestamp/metadata spans
                            const innerSpan = copyable.querySelector('span.selectable-text');
                            text = innerSpan
                                ? innerSpan.textContent.trim()
                                : copyable.textContent.trim();
                        }
                    }

                    // Skip empty messages (stickers, deleted, etc)
                    if (!text) {
                        // Check if it's a media message
                        const media = row.querySelector(
                            'img[data-testid="media-url-cover"], ' +
                            'span[data-icon="audio-play"], ' +
                            'span[data-icon="media-download"]'
                        );
                        if (media) {
                            text = '[Media]';
                        } else {
                            const sticker = row.querySelector('img[data-testid="sticker"]');
                            if (sticker) text = '[Sticker]';
                            else continue; // Skip completely empty
                        }
                    }

                    // Extract timestamp
                    let time = '';
                    const timeSpan = row.querySelector(
                        'span[data-testid="msg-time"], ' +
                        'div[data-testid="msg-meta"] span, ' +
                        'div.copyable-text[data-pre-plain-text]'
                    );
                    if (timeSpan) {
                        if (timeSpan.getAttribute('data-pre-plain-text')) {
                            // Format: "[12:30 PM, 5/19/2026] Contact: "
                            const pre = timeSpan.getAttribute('data-pre-plain-text');
                            const match = pre.match(/\[(\d{1,2}:\d{2}\s*[AP]?M?)/i);
                            if (match) time = match[1];
                        } else {
                            time = timeSpan.textContent.trim();
                        }
                    }

                    results.push({
                        sender: isIncoming ? 'them' : 'me',
                        text: text.substring(0, 500),  // cap at 500 chars
                        time: time
                    });
                }

                return results;
            """, count)

            print(f"  [WhatsApp] {len(messages or [])} messages padhi '{contact}' se")
            return messages or []

        except Exception as e:
            print(f"  [WhatsApp] Read messages error: {e}")
            self._save_debug()
            return []

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except BaseException:
                # BaseException catches EVERYTHING including KeyboardInterrupt
                # ConnectionRefusedError, WebDriverException, KeyboardInterrupt etc.
                # Browser already dead / user closed it / Ctrl+C — sab handle
                pass
            finally:
                self.driver = None
            print("  [WhatsApp] Browser band ho gaya")

    def _save_debug(self):
        if not self.driver:
            return
        try:
            debug_dir = Path(settings.BASE_DIR) / "data"
            debug_dir.mkdir(parents=True, exist_ok=True)
            self.driver.save_screenshot(str(debug_dir / "wa_debug.png"))
            (debug_dir / "wa_debug.html").write_text(
                self.driver.page_source, encoding="utf-8")
            print("  [WhatsApp] Debug saved → data/wa_debug.png")
            divs = self.driver.execute_script("""
                return Array.from(document.querySelectorAll('div[contenteditable="true"]'))
                    .map(d => ({
                        dataTab: d.getAttribute('data-tab'),
                        role: d.getAttribute('role'),
                        ariaLabel: d.getAttribute('aria-label'),
                        title: d.getAttribute('title'),
                    }));
            """)
            print("  [DEBUG] contenteditable divs:")
            for i, d in enumerate(divs or []):
                print(f"    [{i}] data-tab={d['dataTab']} role={d['role']} "
                      f"aria-label={d['ariaLabel']} title={d['title']}")
        except Exception as e:
            print(f"  Debug save error: {e}")


# ── Singleton ──────────────────────────────────────────────────────────
_wa_driver: WhatsAppDriver | None = None

def get_wa_driver() -> WhatsAppDriver:
    global _wa_driver
    if _wa_driver is None:
        _wa_driver = WhatsAppDriver()
    return _wa_driver


def close_driver():
    """WhatsApp browser band karo — agent.py end_session() se call hota hai."""
    global _wa_driver
    if _wa_driver is not None:
        _wa_driver.close()
        _wa_driver = None


# ══════════════════════════════════════════════════════════════════════
#  PUBLIC API — router.py yahi import karta hai
# ══════════════════════════════════════════════════════════════════════

def whatsapp_send_message(
    contact: str,
    message: str = "",
    query:   str = "",
    context=None,
) -> tuple:
    """
    router.py ka entry point — (bool, str) tuple return karta hai.

    Flow:
      1. wa_send_action.smart_whatsapp_send() se draft karo
      2. CONFIRM_WHATSAPP_MSG return karo (agent.py confirmation maangega)
      3. User confirm kare toh whatsapp_confirm_and_send() chalega
    """
    raw = message or query
    if not raw:
        return (False, "Koi message nahi mila")

    if not contact or not contact.strip():
        return (False, "CONTACT_MISSING|Contact naam nahi mila — kisko bhejun?")

    try:
        from actions.wa_send_action import draft_message, get_contact_info, _guess_relationship, auto_learn_contact

        # Contact info + relationship detect
        info      = get_contact_info(contact)
        full_name = info.get("full_name", contact.title())
        rel       = info.get("relationship", "")
        if not rel or rel == "default":
            rel = _guess_relationship(contact)
            auto_learn_contact(contact, rel, full_name)

        # Draft message via LLM
        drafted = draft_message(full_name, raw, rel)
        print(f"  [WhatsApp] Draft ready for '{full_name}' ({rel})")

        # Return CONFIRM format — agent.py will ask user
        return (True, f"CONFIRM_WHATSAPP_MSG|{contact}|{drafted}")

    except Exception as e:
        print(f"  [!] Draft failed ({e}) — raw intent bhej rhi hoon...")
        # Fallback: return raw message for confirmation
        return (True, f"CONFIRM_WHATSAPP_MSG|{contact}|{raw}")


def whatsapp_send_file(
    contact: str = "",
    folder: str = "",
    file: str = "",
    query: str = "",
    context=None,
) -> tuple:
    """
    WhatsApp pe file bhejne ke liye.
    Pehle file_finder se file dhundhegi, phir confirm karega, phir bhejegi.

    Router.py se call hota hai with: contact, folder, file, query, context
    Returns: (bool, str)
    """
    import os

    if not contact:
        return (False, "Contact naam nahi mila")

    # Step 1: Find the file using file_finder
    from actions.file_finder import smart_find
    success, file_path, msg = smart_find(folder_hint=folder, file_hint=file)

    if not success or not file_path:
        return (False, f"File nahi mili: {msg}")

    if os.path.isdir(file_path):
        return (False, f"Ye toh folder hai, file nahi: {msg}")

    file_name = os.path.basename(file_path)

    # Step 2: Return CONFIRM format — agent.py will ask user
    return (True, f"CONFIRM_WHATSAPP_FILE|{contact}|{file_path}|{file_name}")


def _do_send_file(contact: str, file_path: str) -> tuple:
    """
    Actually send a file on WhatsApp. Called after user confirms.
    Detailed logging at every step to debug failures.
    """
    import os

    wa = get_wa_driver()
    if not wa.driver:
        if not wa.start():
            return (False, "Browser start nahi hua")

    if not wa.search_and_open_contact(contact):
        return (False, f"'{contact}' WhatsApp pe nahi mila")

    driver = wa.driver
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return (False, f"File nahi mili: {abs_path}")

    print(f"  [WhatsApp] File bhej rhi hoon: {os.path.basename(abs_path)}")

    try:
        # ══════════════════════════════════════════════════════════════
        # Step 1: Click "+" attach button to open menu
        # ══════════════════════════════════════════════════════════════
        # IMPORTANT: We MUST open the attach menu first!
        # Without it, the only input[type=file] in DOM is for photos/videos
        # which rejects PDFs with "File type not supported"
        attach_selectors = [
            (By.CSS_SELECTOR, 'span[data-icon="plus"]'),
            (By.CSS_SELECTOR, 'span[data-icon="attach-menu-plus"]'),
            (By.XPATH,        '//button[@aria-label="Attach"]'),
            (By.XPATH,        '//div[@aria-label="Attach"]'),
            (By.CSS_SELECTOR, 'span[data-icon="clip"]'),
            (By.CSS_SELECTOR, 'div[data-testid="attach-btn"]'),
            (By.CSS_SELECTOR, 'button[data-testid="attach-btn"]'),
            (By.CSS_SELECTOR, '[data-testid="clip"]'),
            (By.XPATH,        '//div[@title="Attach"]'),
        ]
        attach_btn = _find_element(driver, attach_selectors, timeout=6)

        # JS fallback
        if not attach_btn:
            try:
                attach_btn = driver.execute_script("""
                    let footer = document.querySelector('footer');
                    if (footer) {
                        let btn = footer.querySelector('button');
                        if (btn) return btn;
                        let icon = footer.querySelector('span[data-icon]');
                        if (icon) return icon.closest('button') || icon;
                    }
                    let plus = document.querySelector('span[data-icon*="plus"]') ||
                               document.querySelector('span[data-icon*="clip"]');
                    if (plus) return plus.closest('button') || plus;
                    return null;
                """)
                if attach_btn:
                    print("  [WhatsApp] Attach button mila (JS)")
            except Exception:
                pass

        if not attach_btn:
            print("  [X] Attach button nahi mila")
            wa._save_debug()
            return (False, "Attachment button nahi mila")

        attach_btn.click()
        print("  [WhatsApp] Attach menu open hua")
        _delay(1.0, 1.5)

        # ══════════════════════════════════════════════════════════════
        # Step 2: Click "Document" in the attach dropdown menu
        # ══════════════════════════════════════════════════════════════
        # The + menu shows: Document, Photos, Camera, Contact, Poll
        # Each option creates its own input[type=file] only when CLICKED.
        # We must click "Document" first, then find its input.
        doc_menu_selectors = [
            (By.XPATH,        '//button[.//span[text()="Document"]]'),
            (By.XPATH,        '//div[.//span[text()="Document"]][@role="button"]'),
            (By.XPATH,        '//li[.//span[text()="Document"]]'),
            (By.XPATH,        '//span[text()="Document"]/ancestor::button'),
            (By.XPATH,        '//span[text()="Document"]'),
            (By.CSS_SELECTOR, '[data-testid="mi-attach-document"]'),
            (By.CSS_SELECTOR, 'span[data-icon="attach-document"]'),
        ]
        doc_btn = _find_element(driver, doc_menu_selectors, timeout=5)

        # JS fallback: find the Document menu item by text
        if not doc_btn:
            try:
                doc_btn = driver.execute_script("""
                    // Search for any element with text "Document"
                    let spans = document.querySelectorAll('span');
                    for (let s of spans) {
                        if (s.textContent.trim() === 'Document') {
                            // Return the clickable parent (button or li)
                            return s.closest('button') || s.closest('li') ||
                                   s.closest('div[role="button"]') || s;
                        }
                    }
                    // Also try "Documents"
                    for (let s of spans) {
                        if (s.textContent.trim() === 'Documents') {
                            return s.closest('button') || s.closest('li') ||
                                   s.closest('div[role="button"]') || s;
                        }
                    }
                    return null;
                """)
                if doc_btn:
                    print("  [WhatsApp] Document menu mila (JS)")
            except Exception:
                pass

        if not doc_btn:
            print("  [X] Document menu item nahi mila")
            wa._save_debug()
            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
            return (False, "Document option nahi mila attach menu mein")

        # Count inputs BEFORE clicking Document
        inputs_before = len(driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]'))

        # Click Document — this will either:
        # a) Create a new input[type=file] for documents, OR
        # b) Open the native file picker dialog
        doc_btn.click()
        print("  [WhatsApp] Document option clicked")
        _delay(1.0, 1.5)

        # ══════════════════════════════════════════════════════════════
        # Step 3: Find the NEW document input (appeared after clicking Document)
        # ══════════════════════════════════════════════════════════════
        all_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        print(f"  [WhatsApp] {len(all_inputs)} file inputs found (was {inputs_before})")

        doc_input = None

        # Strategy A: Find input with accept="*" (document input)
        for inp in all_inputs:
            accept = (inp.get_attribute('accept') or '').strip()
            if accept == '*' or accept == '' or accept == '*/*':
                doc_input = inp
                print(f"  [WhatsApp] Document input mila: accept='{accept}'")
                break

        # Strategy B: Pick any NEW input (wasn't there before)
        if not doc_input and len(all_inputs) > inputs_before:
            doc_input = all_inputs[-1]  # newest = last
            accept = doc_input.get_attribute('accept') or ''
            print(f"  [WhatsApp] New input mila: accept='{accept}'")

        # Strategy C: Use the last input as fallback
        if not doc_input and all_inputs:
            doc_input = all_inputs[-1]
            accept = doc_input.get_attribute('accept') or ''
            print(f"  [WhatsApp] Last input fallback: accept='{accept}'")

        if not doc_input:
            print("  [X] Document file input nahi mila")
            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
            wa._save_debug()
            return (False, "Document file input nahi mila")

        # ══════════════════════════════════════════════════════════════
        # Step 4: Send file path to the document input
        # ══════════════════════════════════════════════════════════════
        doc_input.send_keys(abs_path)
        print(f"  [WhatsApp] File path diya: {os.path.basename(abs_path)}")

        # Close the native file picker dialog (OS-level window, not browser element)
        # IMPORTANT: Do NOT send Keys.ESCAPE to browser — that closes the file
        # PREVIEW dialog (which has the send button we need!)
        # Instead, use OS-level SendKeys to close the native "Open" dialog.
        _delay(0.8, 1.2)
        try:
            import subprocess
            subprocess.run(
                ['powershell', '-Command',
                 '(New-Object -ComObject WScript.Shell).SendKeys("{ESC}")'],
                timeout=3, capture_output=True
            )
        except Exception:
            pass  # File picker stays open but doesn't block anything

        _delay(2.5, 3.5)  # Preview load time

        # ══════════════════════════════════════════════════════════════
        # Step 5: Click send button
        # ══════════════════════════════════════════════════════════════
        fname = os.path.basename(abs_path)

        # Strategy 1 (PRIMARY): JS click — most reliable on current WhatsApp Web
        # CSS selectors break frequently, JS data-icon search is stable
        js_clicked = driver.execute_script("""
            // Try send icons by data-icon attribute
            let icons = ['send-light', 'send'];
            for (let icon of icons) {
                let el = document.querySelector(`span[data-icon="${icon}"]`);
                if (el) {
                    let btn = el.closest('button') || el.closest('div[role="button"]') || el;
                    btn.click();
                    return 'clicked:' + icon;
                }
            }
            // Try aria-label="Send"
            let sendEls = document.querySelectorAll('[aria-label="Send"]');
            for (let el of sendEls) {
                if (el.offsetParent !== null) { el.click(); return 'clicked:aria'; }
            }
            // Try any button with send icon
            let allBtns = document.querySelectorAll('div[role="button"], button');
            for (let btn of allBtns) {
                let icon = btn.querySelector('span[data-icon]');
                if (icon && icon.getAttribute('data-icon').includes('send')) {
                    btn.click(); return 'clicked:icon';
                }
            }
            return null;
        """)
        if js_clicked:
            _delay(1.5, 2.5)
            print(f"  [✓] File bhej di: {fname}")
            return (True, f"{fname} bhej di {contact} ko!")

        # Strategy 2 (FALLBACK): CSS/XPath selectors
        print("  [WhatsApp] JS fail, CSS selector try...")
        send_selectors = [
            (By.CSS_SELECTOR, 'span[data-icon="send-light"]'),
            (By.CSS_SELECTOR, 'span[data-icon="send"]'),
            (By.CSS_SELECTOR, 'div[data-testid="send"]'),
            (By.CSS_SELECTOR, 'div[data-testid="media-send"]'),
            (By.XPATH,        '//div[@aria-label="Send"]'),
            (By.XPATH,        '//button[@aria-label="Send"]'),
        ]
        send_btn = _find_element(driver, send_selectors, timeout=5)
        if send_btn:
            try:
                send_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", send_btn)
            _delay(1.5, 2.5)
            print(f"  [✓] File bhej di: {fname}")
            return (True, f"{fname} bhej di {contact} ko!")

        # Strategy 3: Enter key
        print("  [WhatsApp] JS bhi fail, Enter try...")
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ENTER)
        _delay(1.5, 2.5)
        print(f"  [✓] File bhej di (Enter): {fname}")
        return (True, f"{fname} bhej di {contact} ko!")

    except Exception as e:
        print(f"  [X] File send error: {e}")
        wa._save_debug()
        return (False, f"File send error: {e}")


def whatsapp_confirm_and_send(action_type: str, contact: str, content: str) -> tuple:
    """
    User ne confirm kiya — ab actually send karo.
    agent.py se call hota hai jab user "haan bhej do" bole.

    Args:
        action_type: "message" or "file"
        contact:     contact name
        content:     message text OR file path

    Returns:
        (bool, str)
    """
    if action_type == "message":
        wa = get_wa_driver()
        if not wa.driver:
            if not wa.start():
                return (False, "Browser start nahi hua")

        # Disable double-confirm (we already confirmed in agent.py)
        orig_confirm = settings.WHATSAPP_CONFIRM_SEND
        settings.WHATSAPP_CONFIRM_SEND = False

        try:
            ok = wa.send_whatsapp_message(contact, content)
            return (True, f"{contact} ko message bhej diya!") if ok else (False, "Send fail")
        finally:
            settings.WHATSAPP_CONFIRM_SEND = orig_confirm

    elif action_type == "file":
        return _do_send_file(contact, content)

    return (False, f"Unknown action type: {action_type}")


# ══════════════════════════════════════════════════════════════════════
#  READ API — agent.py / router.py isko import karenge
# ══════════════════════════════════════════════════════════════════════

def whatsapp_check_unread(query="", **kwargs) -> tuple:
    """
    Sidebar scan karke unread individual chats batao.
    Returns: (True, "WHATSAPP_UNREAD_RESULT|...") or (False, "error")
    """
    wa = get_wa_driver()
    if not wa.driver:
        if not wa.start():
            return (False, "Browser start nahi hua")

    unreads = wa.get_unread_chats()

    if not unreads:
        return (True, "WHATSAPP_UNREAD_RESULT|0|Koi naya message nahi hai")

    # Format: "WHATSAPP_UNREAD_RESULT|count|name1:count1:preview1;;name2:count2:preview2"
    entries = []
    for u in unreads:
        name    = u.get("name", "Unknown")
        count   = u.get("count", 1)
        preview = u.get("preview", "").replace("|", "").replace(";", ",")
        entries.append(f"{name}:{count}:{preview}")

    result = f"WHATSAPP_UNREAD_RESULT|{len(unreads)}|{';;'.join(entries)}"
    return (True, result)


def whatsapp_read_messages(contact="", query="", **kwargs) -> tuple:
    """
    Specific contact ke last 10 messages padho.
    Returns: (True, "WHATSAPP_READ_RESULT|contact|msg1;;msg2;;...") or (False, "error")
    """
    if not contact:
        return (False, "Contact naam nahi mila")

    wa = get_wa_driver()
    if not wa.driver:
        if not wa.start():
            return (False, "Browser start nahi hua")

    messages = wa.read_messages(contact, count=10)

    if not messages:
        return (True, f"WHATSAPP_READ_RESULT|{contact}|0|Koi message nahi mili ya chat khaali hai")

    # Format: "WHATSAPP_READ_RESULT|contact|count|sender>text>time;;sender>text>time"
    entries = []
    for m in messages:
        sender = m.get("sender", "them")
        text   = m.get("text", "").replace("|", "").replace(";", ",").replace(">", "-")
        time_  = m.get("time", "")
        entries.append(f"{sender}>{text}>{time_}")

    result = f"WHATSAPP_READ_RESULT|{contact}|{len(messages)}|{';;'.join(entries)}"
    return (True, result)


# ══════════════════════════════════════════════════════════════════════
#  STANDALONE TEST
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("   LISA -- WhatsApp Automation Test (v3)")
    print("=" * 55)

    if not CLIPBOARD_OK:
        print("\n  [!] pyperclip nahi hai — install karo pehle:")
        print("      pip install pyperclip\n")

    wa = WhatsAppDriver()
    if not wa.start():
        input("\n  ENTER to close...")
        exit(1)

    contact = input("\n  Test contact (e.g., 'aniket'): ").strip()
    if not contact:
        wa.close()
        exit(0)

    found = wa.search_and_open_contact(contact)
    if found:
        msg = input("  Message (emoji try kar sakte ho): ").strip()
        if msg:
            wa.send_message(msg)
    else:
        print(f"  [X] Contact nahi mila: '{contact}'")

    input("\n  ENTER to close...")
    wa.close()