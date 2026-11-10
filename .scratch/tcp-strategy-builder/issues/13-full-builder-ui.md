# 13: Full builder UI

**What to build:** The Persian, mobile-first Strategy Builder: a Block palette rendered from parameter schemas, enable/disable, parameter editing with defaults, clone from Template, diff against the parent, versions, import/export as a file, and side-by-side comparison of two strategies on the same data.

**Blocked by:** 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] New Blocks appear in the palette with no UI code changes
- [x] Diff view lists every changed parameter and Block against the parent version
- [x] Import rejects invalid files with Persian messages
- [x] Comparison runs both documents on identical data and shows metrics side by side
- [x] HTTP tests for each endpoint; mobile screenshot check has no horizontal scroll

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/diff.py`, `strategy/store.py`, the endpoints in `ui/server.py`, the Strategy tab in `ui/static/index.html`; ADR 10 §17. Notes: forms are drawn from JSON schemas (a test pins that every Block's schema is flat); export is client-side from the validated document; the JSON editor stays as an advanced view; the builder has no undo or unsaved-changes warning yet.
