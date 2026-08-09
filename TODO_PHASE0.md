# TODO — Phase 0 (Freeze & Clean)

Generated from `what_happened.md` + a direct read of the current `actions.zip`
codebase. Do the items in **Section A** before writing any new code — they're
real, sitting-in-plaintext security issues, not hypothetical ones.

---

## A. Rotate secrets — DO THIS FIRST

- [ ] **Picovoice account** — the email + password in `what_happened.md` (line 14)
      is plaintext. Log in, change the password, then delete that line from the
      file (replace with "see password manager" or just remove it).
- [ ] **`.env` API keys** (`GROQ_API_KEY`, `SARVAM_API_KEY`, `ELEVENLABS_API_KEY`,
      `ROTATING_LLM_KEYS`) — regenerate all of these from each provider's dashboard
      and revoke the old ones. `.env` is already gitignored, which is good, but
      these exact keys have now passed through a third-party AI chat (this one),
      so treat them as exposed and rotate as a precaution.
- [ ] **`core/security.py`** — remove the hardcoded default
      `admin_password: str = "Lisajaanu"`. Require it to come from
      `.env` (`LISA_ADMIN_PASSWORD`), with no hardcoded fallback. This is also
      tracked properly in Phase 5 (Autonomy) as part of formalizing security
      levels, but the hardcoded literal should come out of the source file now,
      independent of the bigger refactor.

## B. Freeze the current state

- [ ] Make a full backup copy of the current project folder (a plain zip
      somewhere safe is enough), OR `git init` + first commit — either way you
      want one clean "v1, before refactor" snapshot to roll back to.
- [ ] If you `git init`: do it **after** Section A, so the very first commit is
      already clean and nothing sensitive ever enters history.
- [ ] Smoke-test: confirm current Lisa v1 still runs end-to-end (a normal chat
      turn + one WhatsApp action + one memory recall) so you have a known-good
      baseline to compare against once the refactor starts touching things.

## C. `lisa_os/` skeleton

- [ ] Extract the `lisa_os/` skeleton (provided) into the project root, next to
      the existing code. It's structure only — no logic — so this is zero-risk
      and can be done today even though it's technically "Phase 1" scope.

## D. Old backlog → mapped onto the new roadmap (nothing lost, nothing duplicated)

| From `what_happened.md` | Where it lives now |
|---|---|
| File finder should search whole folders / return all matches | Phase 3 — `departments/knowledge/files/` |
| Lisa should continue conversation from where it left off | Phase 1 — LangGraph `sqlite_checkpointer` gives this for free (Blueprint 13.1) |
| Password hardcoded, single password for all security levels | Section A above (now) + Phase 5 formalizes L0/L1/L2 properly |
| Blocked actions editable from system tray / admin dashboard | Phase 9 — Dashboard 2.0 |
| chat6 needs embedding | Phase 0/1 housekeeping — run the existing `training/` pipeline on it before Phase 4 (Personality) needs the full corpus |
| Bug-experience tracker (past failures → vector DB → confidence → fewer repeated failures) | Phase 6 — Learning Engine, "bug lane" (Blueprint Section 11 / 06_LEARNING_PIPELINE §3) |
| Priority 1 — Smart Document/PDF Reader (PyMuPDF + PaddleOCR fallback) | Phase 3 — `departments/knowledge/documents/`, extends `pdf_processor.py` |
| Priority 2 — 2 AM rule / hibernate authority | Phase 5 — Autonomy Engine L4, gated by `grants.yaml` (this is exactly why L4 exists) |
| Priority 3 — Creator Mode (`create_project` action) | Phase 3 — `departments/planning/coding/` |
| Priority 4 — Background email manager | Phase 3 — `departments/operations/email/` |
| Priority 5 — Behavioral pattern tracking (sleep, mood, coding hours) | Phase 6 — weekly pattern job, `pattern:*` facts in Long-term memory |
| Priority 6 — Screen & vision awareness | Superseded / absorbed by Phase 7 — Presence & Context Awareness Engine (camera is now spec'd properly, not "on hold") |

Nothing on the old list is dropped — it's all accounted for in a specific phase
of `LOSA_v3_Blueprint.docx`. If something here feels out of order once you're
actually building, that's a normal refactor judgment call, not a mistake.

---

**Acceptance for Phase 0:** Section A fully done, one clean backup/commit exists,
v1 still runs unchanged, `lisa_os/` skeleton exists alongside it. Nothing about
Lisa's actual behavior has changed yet — that starts in Phase 1.
