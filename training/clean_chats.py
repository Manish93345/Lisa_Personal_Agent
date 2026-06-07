"""
LISA Chat Data Cleaner — Format A (Labeled Only)
=================================================
Supports files where every turn has explicit labels like:
    You said: [message]
    Lisa: [reply]

Usage:
    python clean_chats.py

Reads from  : data/raw/
Writes to   : data/cleaned/
"""

import re
import json
from pathlib import Path
from docx import Document


# ── Folder paths (relative to this script) ────────────────────────────
RAW_DIR     = Path("training/data/raw")
CLEANED_DIR = Path("training/data/cleaned")


# ── Label patterns ─────────────────────────────────────────────────────
INLINE_YOU  = re.compile(r'^(you said|you|manish)\s*:\s*(.+)$', re.IGNORECASE)
INLINE_LISA = re.compile(r'^(chatgpt said|chatgpt|lisa)\s*:\s*(.+)$', re.IGNORECASE)
LABEL_YOU   = re.compile(r'^(you said|you|manish)\s*:?\s*$', re.IGNORECASE)
LABEL_LISA  = re.compile(r'^(chatgpt said|chatgpt|lisa)\s*:?\s*$', re.IGNORECASE)


# ── Text cleaner ───────────────────────────────────────────────────────
def clean_text(text: str) -> str:
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── Main parser ────────────────────────────────────────────────────────
def parse_docx(docx_path: Path) -> list[dict]:
    doc     = Document(str(docx_path))
    turns   = []
    speaker = None
    lines   = []

    def flush():
        if speaker and lines:
            text = clean_text(' '.join(lines))
            if text:
                turns.append({"speaker": speaker, "text": text})

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        m_you  = INLINE_YOU.match(text)
        m_lisa = INLINE_LISA.match(text)

        if m_you:
            flush(); speaker = "manish"; lines = [m_you.group(2).strip()]
        elif m_lisa:
            flush(); speaker = "lisa";   lines = [m_lisa.group(2).strip()]
        elif LABEL_YOU.match(text):
            flush(); speaker = "manish"; lines = []
        elif LABEL_LISA.match(text):
            flush(); speaker = "lisa";   lines = []
        elif speaker:
            lines.append(text)

    flush()
    return turns


# ── Process all files ──────────────────────────────────────────────────
def process_all():
    CLEANED_DIR.mkdir(parents=True, exist_ok=True)

    docx_files = list(RAW_DIR.glob("*.docx"))

    if not docx_files:
        print(f"\n  No .docx files found in {RAW_DIR}/")
        print("  Put your raw docx files there and run again.\n")
        return

    print(f"\n  Found {len(docx_files)} file(s) in {RAW_DIR}/\n")

    all_turns = []

    for docx_path in docx_files:
        turns    = parse_docx(docx_path)
        manish_n = sum(1 for t in turns if t["speaker"] == "manish")
        lisa_n   = sum(1 for t in turns if t["speaker"] == "lisa")

        print(f"  {docx_path.name}")
        print(f"  Turns: {len(turns)}  (Manish: {manish_n}, Lisa: {lisa_n})")
        for t in turns[:2]:
            print(f"  [{t['speaker'].upper():8}] {t['text'][:80]}")
        print()

        out_path = CLEANED_DIR / f"cleaned_{docx_path.stem}.json"
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(turns, f, ensure_ascii=False, indent=2)

        all_turns.extend(turns)

    combined_path = CLEANED_DIR / "combined_cleaned.json"
    with open(combined_path, 'w', encoding='utf-8') as f:
        json.dump(all_turns, f, ensure_ascii=False, indent=2)

    print(f"  Combined file saved: {combined_path}")
    print(f"  Total turns across all files: {len(all_turns)}\n")


if __name__ == "__main__":
    process_all()