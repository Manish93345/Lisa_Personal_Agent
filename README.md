# LOSA v3 — Phase 0 Skeleton

Drop this `lisa_os/` folder into the root of your existing project, right next
to your current folders (`core/`, `actions/`, `memory/`, `voice/`, `training/`,
`config/`, etc.). Nothing existing is touched or overwritten.

```
your-project/
├── core/              <- unchanged, still runs
├── actions/           <- unchanged, still runs
├── memory/            <- unchanged, still runs
├── voice/
├── training/
├── config/
├── lisa_os/           <- NEW, from this zip. Empty structure only.
├── TODO_PHASE0.md      <- NEW, from this zip. Do this before Phase 1.
└── ...
```

## What's in here

- `lisa_os/` — the full v3 module layout from Blueprint Section 5.4. Every
  folder has an `__init__.py` with a one-line docstring saying what goes there
  and which phase fills it in. No logic yet — that's intentional.
- `lisa_os/identity/identity.yaml` — a placeholder shape for the Identity
  Layer. Real content gets filled in during Phase 1.
- `TODO_PHASE0.md` — the concrete Phase 0 checklist, including three real
  security items found in your current codebase (see Section A — do these
  first, before anything else).

## What to do next

1. Work through `TODO_PHASE0.md`, Section A first.
2. Once Phase 0's acceptance criteria are met, Phase 1 starts writing real
   code into `graph.py`, `state.py`, `schemas.py`, and `nodes/` — see
   `LOSA_v3_Blueprint.docx`, Section 5 and Section 14 (Roadmap).
3. Old code in `core/`, `actions/`, `memory/`, `voice/` stays exactly where it
   is and keeps running. It gets wrapped and migrated in per the Refactor Map
   (Blueprint Section 13) — one department, one phase at a time.
