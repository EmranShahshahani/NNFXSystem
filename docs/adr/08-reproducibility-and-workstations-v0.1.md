# ADR 08 — Reproducibility and multi-workstation working

**Status:** Accepted, 2026-08-31.
**Context:** Development happens across more than one machine, synced by git.
**Companions:** `02` (principle P3, determinism), `03` (§5.2 trial counting, §3 holdout), `06` (the spec).

---

## Decision

Git is the sync mechanism. Code, config, tickets, ADRs and **research state** are
version-controlled. Market data and run outputs are not.

The reason this needs an ADR rather than a `.gitignore` comment is that two of
the project's core guarantees — determinism (P3) and an accurate trial count
(§5.2) — are *silently* broken by naive multi-machine working, in the direction
that flatters the result.

---

## 1. Data is not in version control

Twenty years of H1 bars across 28 pairs is gigabytes. It is ignored, and a
second workstation re-fetches.

**But re-fetching is not automatically identical.** A vendor can revise history;
an exchange can serve slightly different candles. So each fetch writes a
**manifest** — symbol, date range, row count, and a content checksum — and the
manifest *is* committed. A second workstation verifies its download against the
manifest and reports a mismatch rather than proceeding.

Without this, two machines can hold different history under the same name and
produce different backtests from identical code, which presents as a
non-deterministic engine and wastes a week.

## 2. Research state is in version control, and is append-only

`03` requires a counted trial budget, a log of every validation-segment pass,
and a holdout that is touched exactly once. If that state is machine-local, each
workstation keeps its own partial view, and the Deflated Sharpe Ratio in `03`
§5.3 is then computed against an undercount.

**This failure is invisible and optimistic.** An undercounted trial budget makes
the DSR *more* favourable, so nothing in the output looks wrong. Of everything
in this project, it is the mistake most likely to produce a confident, funded,
worthless system.

Three decisions follow.

**2a. No counter file.** The trial count is **derived** by counting distinct
trial ids in `research/trials.jsonl`. A stored number is a single value two
machines can each overwrite; a derived count cannot be clobbered.

**2b. Append-only JSONL, union-merged.** Each line carries a unique trial id, a
workstation id and an environment fingerprint. `.gitattributes` sets
`merge=union` on these logs, so two machines' entries concatenate rather than
conflict. Union merge is safe *only* because of 2a — dedupe by id and the count
is right regardless of how the merge resolved.

**2c. Frozen thresholds are the exception.** `research/thresholds.frozen.json`
is marked `-merge`. A conflict there means someone is moving a goalpost, and it
should stop and be looked at rather than resolved automatically.

## 3. The environment is pinned, and recorded

`02` P3 and the acceptance criteria in `06` require a backtest run twice to
produce byte-identical output. Across two workstations that holds only if the
environment matches: a NumPy point release can change a floating-point
reduction and move a stop by a tick.

- `.python-version` and `pyproject.toml` bound the toolchain; `uv.lock` pins it
  exactly and is committed.
- Every journal entry and trial line carries an **environment fingerprint**:
  Python version plus resolved dependency versions.
- A determinism failure whose fingerprint differs from the reference run is
  reported as an *environment mismatch*, not as an engine bug. These are
  different problems and confusing them costs days.

## 4. Compute is not symmetric across workstations

The selection pipeline (`06`, ticket 25) sweeps thousands of configurations
across decades of daily bars. Steps 1–4 of the build run on any laptop — they
are small fixtures and unit tests. Step 5 wants a substantially bigger machine.

Consequences:

- The pipeline is **checkpointed and resumable**, so a run can move between
  machines without restarting or double-counting.
- Laptops are editors. One machine — likely the same box that later runs the
  daily live cycle — is the compute host.
- Git makes this free: the compute host is another clone.

---

## Consequences

**Accepted:** a second workstation is not useful until it has re-fetched
history, which is slow. Union-merged logs can hold duplicate ids after an
awkward merge, requiring a reconcile pass.

**Rejected:** file-sync tools (Dropbox, Syncthing) for the repo. They resolve
concurrent edits by picking a winner, silently. For the research logs
specifically, a lost append is a corrupted trial count, which is the exact
failure this ADR exists to prevent.

**Rejected:** committing the bar cache via git-lfs. It solves the size problem
but not the revision problem, and the manifest solves both more cheaply.
