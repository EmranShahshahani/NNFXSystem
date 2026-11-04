# NNFXSystem

Python 3.13, `uv`. Checks before every push: `uv run ruff format`, `uv run ruff check`,
`uv run mypy`, `uv run pytest`, `uv run nnfx determinism`. Design decisions live in
`docs/adr/`; current state in `docs/implementation-status.md`.

## Agent skills

### Issue tracker

Specs and tickets are local markdown files under `.scratch/<feature-slug>/`, committed to the repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles with default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` at the repo root plus `docs/adr/`. See `docs/agents/domain.md`.
