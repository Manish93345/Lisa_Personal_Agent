import hashlib
import os

class SecurityManager:
    def __init__(self, admin_password="Lisajaanu"):
        self.current_level = 0  
        # Password ko hash karne se pehle lower() kar diya
        self.admin_hash = hashlib.sha256(admin_password.lower().encode()).hexdigest()
        
        self.restricted_folders = [
            r"D:\Private",
            r"D:\LISA_AGENT\Secret_Docs"
        ]

    def verify_password(self, password: str) -> bool:
        """User input password ko case-insensitive hash karke check karta hai"""
        if not password:
            return False
        return hashlib.sha256(password.lower().encode()).hexdigest() == self.admin_hash

    def set_level(self, target_level: int, password: str = None) -> tuple[bool, str]:
        """Security level change karne ka function."""
        # Agar koi wapas Level 0 (God Mode) aana chahta hai, toh PASSWORD MANDATORY hai
        if target_level == 0:
            if not password or not self.verify_password(password):
                return False, "Access Denied. Incorrect administrative password."
        
        self.current_level = target_level
        
        levels = {
            0: "Level 0 (God Mode - Full Access)", 
            1: "Level 1 (Family Mode - Restricted Files)", 
            2: "Level 2 (Lockdown Mode - Max Security)"
        }
        return True, f"Security protocol updated. Now operating in {levels.get(target_level, 'Unknown')}."

    def is_action_allowed(self, action_name: str) -> bool:
        """Check karta hai ki current level mein ye action (tool) allowed hai ya nahi."""
        # Level 0: Sab kuch allowed hai
        if self.current_level == 0:
            return True
        
        # Level 1: System commands aur WhatsApp blocked hain, baaki (chat, search) allowed hai
        if self.current_level == 1:
            blocked_actions = ["system_command", "whatsapp_message"]
            return action_name not in blocked_actions
            
        # Level 2: Lockdown - Sirf baatcheet (none) allowed hai, sab external actions blocked!
        if self.current_level == 2:
            allowed_actions = ["none"]
            return action_name in allowed_actions
            
        return False

    def is_path_allowed(self, file_path: str) -> bool:
        """File Finder aur Indexer isko use karenge to hide files."""
        if self.current_level == 0:
            return True
            
        norm_path = file_path.lower()
        for restricted in self.restricted_folders:
            if restricted.lower() in norm_path:
                return False  # Restricted folder ki file hide kar do
        return True

# Global instance taaki poora system ek hi security state share kare
auth = SecurityManager(admin_password="Lisajaanu")