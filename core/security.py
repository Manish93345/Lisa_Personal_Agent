"""
LISA — Security Manager (v2 — dashboard-ready)
===============================================
Same 3-level protocol as before, PLUS:
  - `change_password(old, new)` — in-memory only, resets on restart
  - `get_status()` — for dashboard header (no secrets leaked)
  - Level names / meta returned as structured dict

DESIGN NOTE
-----------
Password change is intentionally memory-only. On process restart, the
`.env` / hardcoded default takes over again. This is the safest option:
  - No file writes (nothing to hijack / no plaintext on disk)
  - No lockout risk if user forgets — a restart brings back the known default
"""

import hashlib
import os


LEVEL_META = {
    0: {"name": "God Mode",     "desc": "Full Access",           "color": "#00ff9d"},
    1: {"name": "Family Mode",  "desc": "Restricted Files",      "color": "#ffb84d"},
    2: {"name": "Lockdown",     "desc": "Max Security",          "color": "#ff3b6b"},
}


class SecurityManager:
    def __init__(self, admin_password: str = "Lisajaanu"):
        self.current_level = 0
        # Case-insensitive
        self._admin_hash = self._hash(admin_password)
        # Track how many times password has been rotated this session
        self._pw_rotations = 0

        self.restricted_folders = [
            r"D:\Private",
            r"D:\LISA_AGENT\Secret_Docs",
        ]

    # ── Hashing ────────────────────────────────────────────────────────
    @staticmethod
    def _hash(pw: str) -> str:
        return hashlib.sha256((pw or "").lower().encode()).hexdigest()

    # ── Original API (unchanged) ───────────────────────────────────────
    def verify_password(self, password: str) -> bool:
        if not password:
            return False
        return self._hash(password) == self._admin_hash

    def set_level(self, target_level: int, password: str = None) -> tuple:
        """Change security protocol level."""
        if target_level == 0:
            if not password or not self.verify_password(password):
                return False, "Access Denied. Incorrect administrative password."

        if target_level not in LEVEL_META:
            return False, f"Unknown level: {target_level}"

        self.current_level = target_level
        meta = LEVEL_META[target_level]
        return True, f"Security protocol updated. Now operating in Level {target_level} ({meta['name']} — {meta['desc']})."

    def is_action_allowed(self, action_name: str) -> bool:
        if self.current_level == 0:
            return True
        if self.current_level == 1:
            blocked = ["system_command", "whatsapp_message"]
            return action_name not in blocked
        if self.current_level == 2:
            return action_name in ["none"]
        return False

    def is_path_allowed(self, file_path: str) -> bool:
        if self.current_level == 0:
            return True
        norm_path = (file_path or "").lower()
        for restricted in self.restricted_folders:
            if restricted.lower() in norm_path:
                return False
        return True

    # ── New API — dashboard ────────────────────────────────────────────
    def change_password(self, old_password: str, new_password: str) -> tuple:
        """
        Rotate the admin password *in-memory only*.

        - old_password must match current
        - new_password must be non-empty, min 4 chars
        - persists ONLY until process restart (by design — see file header)
        """
        if not self.verify_password(old_password):
            return False, "Current password is incorrect."

        new_password = (new_password or "").strip()
        if len(new_password) < 4:
            return False, "New password must be at least 4 characters."

        if self._hash(new_password) == self._admin_hash:
            return False, "New password is same as current."

        self._admin_hash    = self._hash(new_password)
        self._pw_rotations += 1
        return True, "Password updated. Active until process restart."

    def get_status(self) -> dict:
        meta = LEVEL_META.get(self.current_level, {"name": "?", "desc": "?", "color": "#888"})
        return {
            "level":        self.current_level,
            "level_name":   meta["name"],
            "level_desc":   meta["desc"],
            "level_color":  meta["color"],
            "levels":       LEVEL_META,
            "pw_rotations": self._pw_rotations,
            "restricted_folders": self.restricted_folders,
        }


# Global instance (name preserved for existing imports)
auth = SecurityManager(admin_password=os.getenv("LISA_ADMIN_PASSWORD", "Lisajaanu"))
