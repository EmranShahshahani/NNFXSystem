# ADR 10 - Strategy Documents and the Block Library

Status: accepted, 2026-11-05. Spec: `.scratch/tcp-strategy-builder/spec.md`.
Code: `nnfx/strategy/`. First ticket: `.scratch/tcp-strategy-builder/issues/05-*.md`.

## Context

Until now a trading system on this platform was code: NNFX is `StrategyEngine`,
and ADR 09 planned two more hand-written engines for Trade City Pro. The
Strategy Builder lets users build and customise strategies themselves, starting
from the Trade City Pro (Arshia Azizpour) blueprint, and later from other
strategies. That calls for strategies that are data, rules that are reusable
parts, and one engine that runs any combination. It also has to keep every
platform guarantee: no lookahead, determinism, the shared harness, the journal,
and honest trial counting.

## Decisions

1. **Documents are data.** A Strategy Document holds:
   - metadata (name, version, parent Template and its version);
   - timeframe roles (HWC, MWC, LWC);
   - a universe;
   - an ordered list of Blocks `{kind, type, enabled, params}`;
   - a Risk section.

   It is never code. The schema is strict: unknown fields, unknown Block types
   and unknown parameters are errors. `validate_document` reports every problem
   at once, each with a path and a Persian message for the UI. A valid document
   has every parameter resolved, with defaults written in.

2. **The fingerprint is the content hash.** It is the SHA-256 of the resolved
   document as canonical JSON (first 16 hex characters). Key order and
   written-out defaults do not change it; any change to a value does. Every
   result and Trial carries it.

3. **Blocks are registry-resolved and typed by kind.** The kinds are Context,
   Setup, Confirmation, Execution, Stop, Exit, Risk and Market Filter. Each
   kind has one contract:
   - Context: per-bar allowed directions and flags.
   - Setup: per-bar Setup Candidates (direction, trigger, invalidation,
     proposed stop, tags).
   - Execution: candidate → stop-market orders.
   - Stop: candidate → initial stop.
   - Exit: candidate (with the data) → an Exit Plan in R.

   Confirmation, Risk and Market Filter get their contracts with their first
   Block (tickets 06-08 and 20). A Block declares:
   - a registry name;
   - a Persian title;
   - the blueprint sources it comes from;
   - a strict parameter model in which every field has a default and a
     description. The registry refuses a Block without these, because the UI
     builds its forms from them.

4. **Blocks reference timeframe roles, not timeframes.** A user re-maps roles
   (for example MWC from 4H to daily) without editing Blocks. Every role is
   resampled from the one LWC base series (ADR 02 amendment, ticket 01). A
   Block reads a higher role only as of the LWC bar's close
   (`StrategyData.positions`).

5. **Blocks are causal, and the gates prove it for every Block.** The gate
   suite iterates the registry, so a new Block is gated the moment it is
   registered. A Block with a timeframe parameter is gated on every role.
   Each Block must pass three checks:
   - **No lookahead:** outputs on truncated history equal the prefix of the
     outputs on full history.
   - **Determinism:** identical outputs from rebuilt inputs, and the same hash
     of every Block's outputs in a separate process.
   - **Price-scale invariance:** prices scale, everything else is unchanged.
     Exits are in R and are scale-free.

   A deliberately planted lookahead is caught (checked when the suite was
   written).

6. **One engine interprets documents.** `DocumentEngine` keeps the pure
   `decide()` contract of ADR 02 and ADR 09 §2 and runs on the shared harness,
   broker, risk manager and journal. Series Blocks are computed once per
   symbol at compile time; causality makes reading them at bar *i* safe. Per
   LWC bar the engine:
   - reads the candidates;
   - checks each candidate against every Context Block, the position limit,
     and whether the instrument can be shorted (a refused short is journaled
     as `cannot_short`, never dropped silently);
   - asks the Stop, Exit and Execution Blocks for orders;
   - emits pending orders sized at the Risk section's risk.

   It journals one evaluation per candidate, with every check's outcome.
   Pending orders, fractional exits and fills are the broker's (ADR 09 §4,
   §5), and nothing is duplicated. This supersedes ADR 09 §2's plan for two
   hand-written TCP engines: the TCP methods become Templates.

7. **Strategy trials are their own family.** Each backtest of a document logs
   a Trial (id = fingerprint + scope) in `research/strategy_trials.jsonl`
   (union-merged like the other logs). It never counts toward NNFX's trial
   total or its deflated Sharpe, and the frozen H2021/H2026 pre-registration
   is untouched. A run whose data reaches its market's holdout is refused,
   whether or not it is logged; the market comes from the instruments. A
   Template's results become evidence only under its own pre-registration
   (spec, Research integration).

8. **R is the whole planned risk of an entry.** A document entry risks its 1R
   in one position. Summaries therefore use `compute_metrics(r_per_entry=1)`,
   while NNFX keeps two positions of 1R per entry.

9. **Order-book rules are live-first.** Order-book Blocks (ticket 21) read the
   Order Book Source (ADR 02 amendment, ticket 04). Where no recorded book
   exists for a period, they report not-applicable and the result is flagged
   as incomplete.

## Consequences

* New strategies are new documents and, at most, new Blocks. The engine,
  harness, broker and UI do not change for them.
* Every Block carries a test burden it cannot skip: the gates. Every Block
  parameter is visible and editable, and no number is hidden in code.
* Blocks are computed vectorised at compile time. Memory grows with bars ×
  Blocks, which is fine for 15m data over years. Live paper mode recompiles
  on each new bar until incremental Blocks are needed.
* The first Blocks (ticket 05) are deliberately basic. The full Candle Setup,
  structure, levels, governors and Profit Chain follow in tickets 06-21.
