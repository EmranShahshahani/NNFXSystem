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
   - Context: per-bar allowed directions, flags, and candidate tags by
     direction (merged into each candidate, e.g. `counter_trend`, §13).
   - Setup: per-bar Setup Candidates (direction, trigger, invalidation,
     proposed stop, tags).
   - Execution: candidate → stop-market orders.
   - Stop: candidate → initial stop.
   - Exit: candidate (with the data and the stop) → an Exit Plan in R; then,
     on every bar a position is open, position → an optional stop move (§12).

   Confirmation: candidate → pass / fail / n/a with a reason, a weight toward
   the Confluence Score and a hard flag (ticket 08). Market Filter gets its
   contract with its first Block (ticket 20); account-wide risk is the document's Risk section
   (§10), and the Risk kind is reserved for per-candidate sizing Blocks. A Block declares:
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

10. **The risk governor (ticket 06).** Risk is a document section, not a Risk
    Block. It is account-wide, it is not a per-candidate rule, and it is one
    per document. The Risk kind stays reserved for later per-candidate sizing
    Blocks.

    **What the section configures:**
    - sizing: fixed, or tiered by Confluence Score;
    - the Streak Governor;
    - daily and weekly loss limits;
    - the performance governor;
    - equity-milestone sizing;
    - an open-risk cap (a portfolio cap of up to 20%);
    - the Leverage Governor.

    Per-trade risk never exceeds 1%, and every number is a parameter.

    **How it is computed.** Each bar, `update_state` advances a small
    `GovernorState` from the account the broker reports: recent closed
    positions, drawdown from the last equity high, and initial equity. The
    state holds:
    - the sizing base, which follows equity only on ±10% moves;
    - any loss-limit halt, which counts open losses too;
    - the performance cut, which holds until a new equity high.

    It travels in `EngineState` and is journaled every cycle, so a restarted
    paper run governs exactly like an uninterrupted one. This is tested by
    restarting from disk on every bar.

    **What happens to a candidate:**
    - Halts refuse it: five losses (48 h from the latest), the daily limit
      (24 h), and the weekly limit (until Monday).
    - Cuts lower its risk.
    - Risk is never sized on more equity than the account has.
    - Every refusal and cut is journaled per candidate, together with the
      leverage and the margin it implies.
    - Leverage only sets margin, and the document's leverage reaches the
      broker and the risk manager.
    - Resting orders count against the open-risk cap and the exposure caps.

    Until ticket 08's checklist supplies the Confluence Score, tiered sizing
    uses score 0.

11. **The Pre-Trade Checklist (ticket 08).** Every Setup Candidate is
    journaled with every Context check (hard gates, weight 0) and every
    Confirmation check. Each check has its outcome (pass / fail / n/a), its
    weight, its hard flag and a reason.

    **Scoring.** The Confluence Score is the summed weight of passing
    Confirmations, rounded so fractional weights reach their tier in any
    order. It selects the Risk Tier: `tiers[floor(score)]`, capped by the tier
    list.

    **N/a.** N/a, for example missing data or too little history, is never a
    pass. A hard check refuses the candidate only when it fails.

    **Refusals and the decision path.** Every refusal reason is journaled:
    hard checklist failures and the risk refusals (`cannot_short`, position
    limit, halts, open-risk cap). The decision path runs context → each
    Confirmation → risk → stop → order. Every stage after the first refusal
    is marked skipped, while the checklist keeps every outcome.

    **Soft checks.** A soft check that fails lowers the score; it does not
    abort the candidate. The blueprint's "if any branch is False, abort" is
    the hard flag.

    **Stop labels.** A placed setup is *justified* when every applicable check
    passed and its score reaches `checklist.justified_min_score` (default 1,
    "a valid setup with high confluence"). Every position with a losing exit
    is labelled justified, unjustified, or unknown when the journal cannot
    trace it (order key → fill → position). The API returns the latest 500
    candidates with the total count and the labels, and the UI shows them.

12. **The Profit Chain and position management (ticket 07).** The
    `profit_chain` Exit Block is the blueprint's ladder: 35% at 2R, 40% at 5R,
    15% at 10R (20% is the blueprint's other value) and a 10% Runner. Every
    step and the Runner fraction is a parameter; they sum to 1 and R rises.

    **The 2R floor.** No exit rule closes a whole position below 2R. The first
    step and `fixed_r` cannot be set below 2R, and the engine refuses any
    Exit Plan whose steps below 2R add up to the whole position
    (`exit_below_2r`), whatever Block made it.

    **Management.** Exit Blocks gain `manage(position, data, bar)`, which may
    return a stop move. The engine applies a move only when it tightens the
    stop and leaves it on the right side of the close. It sends the move as a
    `ModifyIntent` and journals it as a `stop_move` evaluation (from, to,
    reason). Step fills stay the broker's (ADR 09 §5).

    The Profit Chain manages on the management timeframe
    (`timeframes.management`, the MWC unless set, so 4H by default) and acts
    only on its closes:
    - **Conditional breakeven.** After the first step has filled, the stop
      goes to the entry fill at the first management close where a swing low
      (shorts: high) has been confirmed on a management bar *after* the one
      the entry happened in. That bar's low is mostly the setup itself, so it
      does not count. The move can therefore come well after 2R.
      `breakeven: always` moves the stop to the fill on the bar after the
      first step fills; `off` never moves it. Both modes anchor on the fill,
      the price `at_risk` is measured from.
    - **Runner trail.** Once `trail_after_step` steps have filled, the stop
      trails just behind the latest confirmed swing. The default is all of
      them, so only the Runner trails. The blueprint does not say when the
      trail starts, and between 5R and 10R the 25% still open sits at
      breakeven. Setting 1 or 2 trails the ladder's remainder too, and a
      trail can then stop out a step before it fills.

    A swing at bar *k* has `pivot_bars` strictly higher lows (lower highs) on
    each side. It is readable only from bar *k* + `pivot_bars`. The exit gates
    check `manage()` for lookahead and price scale the way §5 checks every
    other Block.

    **Counter-trend mode.** `always`, or `tagged` for candidates tagged
    `counter_trend`, drops the Runner and closes everything at 2R. With
    `counter_trend_exit: boundary` it closes at the first structural boundary
    instead: the nearest confirmed management swing beyond the trigger at the
    time of the setup, clamped to [2R, `counter_trend_max_r` = 3R], since
    secondary-wave trades target 1:2 or 1:3. A boundary at 1.2R becomes 2R
    (the floor) and one at 6R becomes 3R. "2R or the boundary" is the user's
    choice, not whichever comes first. No Block sets the tag yet; market structure (ticket 09)
    will.

    **Spot recycling.** With `recycle_to_spot`, a whole position closing at
    `recycle_min_r` (5R) or more records its net profit as moved from futures
    to spot, dated at the position's last exit. It does not force a full
    close at 5R–10R (the blueprint's futures contract closing); the ladder
    exits as configured. It is a record, not a cash flow: sizing still uses
    the broker's equity. The run splits the equity curve into trading and
    spot, and the API returns the transfers, the spot balance and the
    trading equity curve.

13. **Market structure and wave cycles (ticket 09).** `structure.dow_states`
    gives each role's Dow state (up / range / down) at every close, from
    swings confirmed `pivot_bars` bars later:
    - Range turns up on a close above the latest swing high while the latest
      swing low is a higher low (video 3). Down is mirrored.
    - Up ends only on a failed peak: the latest swing high is equal to or
      below the one before, and a close breaks the neckline, the lowest low
      between them (video 28). The state goes to range. A lower high plus a
      broken swing low is also a downtrend, so a strict lower high turns
      down on the next bar, while an equal high stays in range. A deep
      pullback through a higher low alone does not end the trend.

    Two Context Blocks read these states:
    - `dow_trend` gates on one role. In range it allows no trade, or both
      directions.
    - `wave_cycles` combines HWC, MWC and LWC (`structure.wave_bias`,
      videos 63, 64, 26):
      - The HWC's trend sets the direction, so an LWC downtrend inside an
        HWC uptrend is never shorted.
      - The HWC is treated as flat only after the LWC and then the MWC turn
        away from its trend (range or opposite), or when its own trend ends.
        An MWC turn with the LWC still in line does not count. The MWC
        coming back restores the bias.
      - A flat HWC follows the MWC's trend (`follow_mwc_when_flat`).
      - With the HWC flat and the MWC ranging, `two_way_box` allows both
        directions.
      - Trades against the HWC's last trend, and box trades, are tagged
        `counter_trend`. The Profit Chain's `counter_trend: tagged` closes
        them at 2R-3R (§12).

    Context Blocks can now tag candidates by direction. The engine merges the
    tags before the checklist, so they are journaled and reach the Exit Block.
    The registry gate's daily HWC never trends on its 40-day fixture, so a
    dedicated test checks `wave_cycles` for lookahead on H4/H1/M15, where
    every rule fires.

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
