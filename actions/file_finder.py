"""
LISA — Smart File Finder (Fuzzy Matching)
============================================
Natural language se file/folder dhundhta hai.
"free fire" → D:\\Free_fire
"divya image" → D:\\Free_fire\\divya_screenshot.png

Usage:
    from actions.file_finder import smart_find
    success, path, message = smart_find(folder_hint="free fire", file_hint="divya")
"""

import os
import re
import ctypes
from ctypes import wintypes
from pathlib import Path
from rapidfuzz import fuzz, process

# ── Resolve Windows known folders (handles OneDrive redirection) ──────

def _get_known_folder(folder_name: str) -> str:
    """Get actual path for known Windows folders, handling OneDrive redirection."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        )
        # Registry names for known folders
        reg_map = {
            "Desktop":   "Desktop",
            "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
            "Documents": "Personal",
            "Pictures":  "My Pictures",
        }
        reg_name = reg_map.get(folder_name)
        if reg_name:
            val, _ = winreg.QueryValueEx(key, reg_name)
            # Expand environment variables like %USERPROFILE%
            expanded = os.path.expandvars(val)
            if os.path.isdir(expanded):
                return expanded
    except Exception:
        pass

    # Fallback to standard path
    fallback = str(Path.home() / folder_name)
    if os.path.isdir(fallback):
        return fallback

    # OneDrive fallback
    onedrive = str(Path.home() / "OneDrive" / folder_name)
    if os.path.isdir(onedrive):
        return onedrive

    return fallback


# Resolve once at import
_DESKTOP   = _get_known_folder("Desktop")
_DOWNLOADS = _get_known_folder("Downloads")
_DOCUMENTS = _get_known_folder("Documents")
_PICTURES  = _get_known_folder("Pictures")

# ── Search roots ──────────────────────────────────────────────────────

SEARCH_ROOTS = [
    "D:\\",
    _DESKTOP,
    _DOWNLOADS,
    _DOCUMENTS,
    _PICTURES,
]

# Common aliases -> map to actual root
ROOT_ALIASES = {
    "d":           "D:\\",
    "d drive":     "D:\\",
    "desktop":     _DESKTOP,
    "downloads":   _DOWNLOADS,
    "documents":   _DOCUMENTS,
    "pictures":    _PICTURES,
    "photos":      _PICTURES,
    "screenshots": _PICTURES,
}

# Skip these folders during scanning
SKIP_FOLDERS = {
    "__pycache__", ".git", ".venv", "node_modules", ".idea",
    "venv", "env", ".vs", ".vscode", "$RECYCLE.BIN",
    "System Volume Information", ".Trash-1000",
}

# Thresholds
FOLDER_MATCH_THRESHOLD = 60
FILE_MATCH_THRESHOLD   = 55


# ── Helpers ───────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Normalize name for comparison -- lowercase, underscores->spaces, strip ext."""
    name = name.lower().strip()
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r'\s+', ' ', name)
    return name


def _normalize_file(name: str) -> str:
    """Normalize file name — remove extension too."""
    stem = Path(name).stem
    return _normalize(stem)


def _should_skip(name: str) -> bool:
    """Skip hidden/system folders."""
    return name in SKIP_FOLDERS or name.startswith(".")


# ── Folder Scanner ────────────────────────────────────────────────────

def _scan_folders(root: str, max_depth: int = 2) -> list[tuple[str, str]]:
    """
    Scan folders up to max_depth levels.
    Returns: [(normalized_name, full_path), ...]
    """
    results = []

    def _recurse(current_path: str, depth: int):
        if depth > max_depth:
            return
        try:
            with os.scandir(current_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if _should_skip(entry.name):
                            continue
                        norm = _normalize(entry.name)
                        results.append((norm, entry.path))
                        if depth < max_depth:
                            _recurse(entry.path, depth + 1)
        except (PermissionError, OSError):
            pass

    _recurse(root, 0)
    return results


def _scan_files(folder: str, max_depth: int = 1) -> list[tuple[str, str]]:
    """
    Scan files inside a folder (up to max_depth sub-levels).
    Returns: [(normalized_stem, full_path), ...]
    """
    results = []

    def _recurse(current_path: str, depth: int):
        if depth > max_depth:
            return
        try:
            with os.scandir(current_path) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        norm = _normalize_file(entry.name)
                        results.append((norm, entry.path))
                    elif entry.is_dir(follow_symlinks=False):
                        if not _should_skip(entry.name) and depth < max_depth:
                            _recurse(entry.path, depth + 1)
        except (PermissionError, OSError):
            pass

    _recurse(folder, 0)
    return results


# ── Core Search Functions ─────────────────────────────────────────────

def find_folder(folder_hint: str, search_root: str = None) -> tuple[str | None, int]:
    """
    Fuzzy match folder name across search roots.

    Args:
        folder_hint : user ka natural language folder name ("free fire")
        search_root : specific root to search (None = search all)

    Returns:
        (matched_path, score) or (None, 0)
    """
    hint_norm = _normalize(folder_hint)

    # Check if hint is a root alias (exact match)
    alias_match = ROOT_ALIASES.get(hint_norm)
    if alias_match and os.path.isdir(alias_match):
        return alias_match, 100

    # Check partial alias match -- but skip very short aliases to avoid false positives
    # e.g., "desktop" should NOT match "d" (which points to D:\)
    for alias_key, alias_path in ROOT_ALIASES.items():
        if len(alias_key) < 3:
            continue  # skip single-char aliases like "d"
        if hint_norm in alias_key or alias_key in hint_norm:
            if os.path.isdir(alias_path):
                return alias_path, 95

    # Determine which roots to scan
    roots = [search_root] if search_root else SEARCH_ROOTS

    # Collect all folders from all roots
    all_folders: list[tuple[str, str]] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        all_folders.extend(_scan_folders(root, max_depth=2))

    if not all_folders:
        return None, 0

    names = [f[0] for f in all_folders]

    # Get top candidates (not just best one) — so we can rank by depth
    candidates = process.extract(
        hint_norm,
        names,
        scorer=fuzz.WRatio,
        score_cutoff=FOLDER_MATCH_THRESHOLD,
        limit=5
    )

    if not candidates:
        return None, 0

    # Among top candidates, prefer:
    # 1. Higher fuzzy score
    # 2. Shallower path (fewer separators = closer to root)
    # 3. Name length closer to hint length (avoid partial matches on short names)
    best_path  = None
    best_score = 0
    best_rank  = float('inf')

    for matched_name, score, idx in candidates:
        path   = all_folders[idx][1]
        depth  = path.count(os.sep)
        # Penalize very short names that match via subset
        # e.g., "security" matching "cyber security" at 100%
        len_diff = abs(len(matched_name) - len(hint_norm))
        rank = depth + (len_diff * 0.1)  # depth matters more

        if score > best_score or (score == best_score and rank < best_rank):
            best_path  = path
            best_score = score
            best_rank  = rank

    if best_path is None:
        return None, 0

    print(f"  [FileFinder] Folder match: '{folder_hint}' -> '{Path(best_path).name}' (score: {best_score})")
    return best_path, int(best_score)


def find_folder_chain(chain: list[str]) -> tuple[str | None, int]:
    """
    Resolve a chain of folder names step by step.
    ['study', 'sem 6', 'software engineering']
    → D:\Study → D:\Study\Sem 6 → D:\Study\Sem 6\Software Engineering

    Args:
        chain: list of folder names to resolve in sequence

    Returns:
        (resolved_path, avg_score) or (None, 0)
    """
    if not chain:
        return None, 0

    # Step 1: Resolve first folder from SEARCH_ROOTS
    current_path, score = find_folder(chain[0])
    if current_path is None:
        return None, 0

    total_score = score

    # Step 2: Resolve remaining folders inside previous result
    for i, subfolder_hint in enumerate(chain[1:], 1):
        hint_norm = _normalize(subfolder_hint)

        # Scan only immediate children of current folder
        subfolders = []
        try:
            with os.scandir(current_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False) and not _should_skip(entry.name):
                        subfolders.append((_normalize(entry.name), entry.path))
        except (PermissionError, OSError):
            return None, 0

        if not subfolders:
            print(f"  [FileFinder] Chain step {i}: '{subfolder_hint}' — no subfolders in {Path(current_path).name}")
            return None, 0

        names = [f[0] for f in subfolders]
        result = process.extractOne(
            hint_norm,
            names,
            scorer=fuzz.WRatio,
            score_cutoff=FOLDER_MATCH_THRESHOLD
        )

        if result is None:
            print(f"  [FileFinder] Chain step {i}: '{subfolder_hint}' — no match in {Path(current_path).name}")
            return None, 0

        matched_name, sub_score, idx = result
        current_path = subfolders[idx][1]
        total_score += sub_score
        print(f"  [FileFinder] Chain step {i}: '{subfolder_hint}' -> '{Path(current_path).name}' (score: {sub_score})")

    avg_score = total_score / len(chain)
    return current_path, int(avg_score)


def find_file(file_hint: str, folder_path: str = None) -> tuple[str | None, int]:
    """
    Fuzzy match file name.

    Args:
        file_hint   : user ka natural language file name ("divya", "resume pdf")
        folder_path : specific folder to search (None = search all roots)

    Returns:
        (matched_path, score) or (None, 0)
    """
    hint_norm = _normalize(file_hint)
    # Remove common suffixes like "photo", "image", "file", "pdf" etc. for better matching
    hint_clean = re.sub(
        r'\b(photo|image|file|pdf|doc|video|pic|picture|screenshot|ss)\b',
        '', hint_norm
    ).strip()
    # Use cleaned version if it's not empty, else fallback to original
    if hint_clean:
        hint_norm = hint_clean

    # Determine scan targets
    if folder_path:
        scan_targets = [folder_path]
    else:
        scan_targets = SEARCH_ROOTS

    # Collect all files
    # Depth logic:
    #   - With folder resolved via chain: depth=2 (already narrowed)
    #   - With single folder: depth=2
    #   - No folder (global search): depth=3
    all_files: list[tuple[str, str]] = []
    for target in scan_targets:
        if not os.path.isdir(target):
            continue
        depth = 3 if not folder_path else 2
        all_files.extend(_scan_files(target, max_depth=depth))

    if not all_files:
        return None, 0

    names = [f[0] for f in all_files]

    # Fuzzy match
    result = process.extractOne(
        hint_norm,
        names,
        scorer=fuzz.token_set_ratio,
        score_cutoff=FILE_MATCH_THRESHOLD
    )

    if result is None:
        return None, 0

    matched_name, score, idx = result
    matched_path = all_files[idx][1]

    print(f"  [FileFinder] File match: '{file_hint}' -> '{Path(matched_path).name}' (score: {score})")
    return matched_path, int(score)


# ── Main Entry Point ──────────────────────────────────────────────────

def smart_find(
    folder_hint: str = "",
    file_hint: str = ""
) -> tuple[bool, str, str]:
    """
    Main smart file finder — resolves folder + file using fuzzy matching.

    Args:
        folder_hint : "free fire", "downloads", "d drive", etc.
        file_hint   : "divya", "resume pdf", etc.

    Returns:
        (success, resolved_path, message)
    """
    folder_hint = (folder_hint or "").strip()
    file_hint   = (file_hint or "").strip()

    if not folder_hint and not file_hint:
        return False, "", "kya dhundhna hai bata do -- folder ya file?"

    # ── Step 1: Resolve folder ────────────────────────────────────────
    resolved_folder = None

    if folder_hint:
        # Check if folder_hint is a chain (contains /)
        if "/" in folder_hint:
            chain = [part.strip() for part in folder_hint.split("/") if part.strip()]
            if len(chain) > 1:
                resolved_folder, folder_score = find_folder_chain(chain)
            else:
                resolved_folder, folder_score = find_folder(chain[0])
        else:
            resolved_folder, folder_score = find_folder(folder_hint)

        if resolved_folder is None:
            return False, "", f"'{folder_hint}' naam ka koi folder nahi mila"

    # ── Step 2: Resolve file ──────────────────────────────────────────
    if file_hint:
        resolved_file, file_score = find_file(file_hint, resolved_folder)
        if resolved_file is None:
            if resolved_folder:
                folder_name = Path(resolved_folder).name
                return False, "", f"'{file_hint}' naam ki koi file nahi mili {folder_name} mein"
            else:
                return False, "", f"'{file_hint}' naam ki koi file nahi mili"

        file_name   = Path(resolved_file).name
        folder_name = Path(resolved_file).parent.name
        return True, resolved_file, f"mil gayi! {file_name}, {folder_name} folder mein"

    # ── Only folder requested ─────────────────────────────────────────
    if resolved_folder:
        folder_name = Path(resolved_folder).name
        return True, resolved_folder, f"mil gaya! {folder_name} folder"

    return False, "", "kuch samajh nahi aaya -- folder ya file naam batao"


# ── Standalone test ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*55)
    print("   LISA -- Smart File Finder Test")
    print("="*55 + "\n")

    test_cases = [
        # (folder_hint, file_hint)
        ("free fire",       ""),
        ("movies",          ""),
        ("cyber security",  ""),
        ("resume",          ""),
        ("screenshot laptop", ""),
        ("downloads",       ""),
        ("desktop",         ""),
    ]

    # Nested chain tests
    chain_tests = [
        # (folder_chain, file_hint)
        ("study/sem 6/software engineering",  "pyq"),
        ("study/sem 6",                       ""),
    ]

    print("\n  ── Nested Chain Tests ──")
    for folder, file in chain_tests:
        label = f"chain='{folder}'"
        if file:
            label += f", file='{file}'"
        success, path, msg = smart_find(folder_hint=folder, file_hint=file)
        status = "[OK]" if success else "[X]"
        print(f"  {status} {label}")
        print(f"     -> {msg}")
        if path:
            print(f"     -> {path}")
        print()

    print("  ── Single Folder Tests ──")

    for folder, file in test_cases:
        label = f"folder='{folder}'"
        if file:
            label += f", file='{file}'"

        success, path, msg = smart_find(folder_hint=folder, file_hint=file)
        status = "[OK]" if success else "[X]"
        print(f"  {status} {label}")
        print(f"     -> {msg}")
        if path:
            print(f"     -> {path}")
        print()
