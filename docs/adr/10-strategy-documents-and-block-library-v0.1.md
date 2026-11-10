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
   - Context: per-bar allowed directions, flags, candidate tags by
     direction (merged into each candidate, e.g. `counter_trend`, §13) and,
     optionally, bars where resting orders are cancelled (§14).
   - Setup: per-bar Setup Candidates (direction, trigger, invalidation,
     proposed stop, tags).
   - Execution: candidate → stop-market orders.
   - Stop: candidate → initial stop.
   - Exit: candidate (with the data and the stop) → an Exit Plan in R; then,
     on every bar a position is open, position → an optional stop move or
     profit-taking close (§12, §14).

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

    **Counter-trend mode.** `always`, or `tagged` (the default) for
    candidates tagged `counter_trend`, drops the Runner and closes everything at 2R. With
    `counter_trend_exit: boundary` it closes at the first structural boundary
    instead: the nearest confirmed management swing beyond the trigger at the
    time of the setup, clamped to [2R, `counter_trend_max_r` = 3R], since
    secondary-wave trades target 1:2 or 1:3. A boundary at 1.2R becomes 2R
    (the floor) and one at 6R becomes 3R. "2R or the boundary" is the user's
    choice, not whichever comes first. `wave_cycles` sets the tag (§13).

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
    - "Turns down" means on a later close below the latest swing low,
      usually the very next one.

    Two Context Blocks read these states:
    - `dow_trend` gates on one role. In range it allows no trade, or both
      directions.
    - `wave_cycles` combines HWC, MWC and LWC (`structure.wave_bias`,
      videos 63, 64, 26):
      - The HWC's trend sets the direction, so an LWC downtrend inside an
        HWC uptrend is never shorted.
      - The HWC is treated as flat only when the MWC turns away from its
        trend (range or opposite) while the LWC already has (the same bar
        counts), or when its own trend ends. An MWC that turns first does
        not count, even if the LWC follows later. The MWC coming back
        restores the bias. "Flat" is this effective bias: the HWC's own Dow
        state may still read up, and the box can then open.
      - A flat HWC follows the MWC's trend (`follow_mwc_when_flat`).
      - With the HWC flat and the MWC ranging, `two_way_box` allows both
        directions.
      - Trades against the HWC's last trend, and box trades, are tagged
        `counter_trend`. The Profit Chain's default `counter_trend: tagged`
        closes them at 2R-3R (§12). `fixed_r` ignores the tag.
      - The box only allows both directions. The entries still come from
        the document's Setup Blocks. Stop-buy and stop-sell triggers at
        the box extremes need boxes, which come in ticket 11.

    Context Blocks can now tag candidates by direction. The engine merges the
    tags before the checklist, so they are journaled and reach the Exit Block.
    A tag is merged even when the Context that sets it refuses the
    candidate.

    The registry gate's daily HWC never trends on its 40-day fixture. A
    dedicated test therefore checks `wave_cycles` for lookahead on H4/H1/M15,
    where every rule fires. A harness run on the same three timeframes checks
    each candidate's journaled decision and tags against the rules. Hand-built
    harness fixtures cover the box, the range refusal and the failed peak;
    the pure functions are unit-tested rule by rule.

14. **The 3-SMA system and the full Candle Setup (ticket 10).** Each rule is
    its own switchable Block. The numbers the blueprint does not give are
    parameters, marked as such in each Block's docstring.

    Context Blocks:
    - `choppy_regime` (the entanglement filter): chop starts when the three
      SMAs have crossed each other `min_crosses` times in `lookback` bars
      while the middle one has hardly moved (`flat_atr`), and lasts until
      separation resumes: the SMAs ordered one way with every gap at least
      `separation_atr` ATR. While it lasts it refuses every candidate and
      cancels the resting orders (a `cancel_orders` journal event per
      symbol, `context_disabled_orders` on each broker cancel).
    - `sma_baseline_filter`: no longs below the 99 SMA, no shorts above it.
    - `overextension_guard`: no trade in the direction of a stretch beyond
      `max_atr` ATR from the 99 SMA; it lifts as price returns or the SMA
      catches up.
    - `sma_slope_gate`: a flattening SMA 7 stops new entries (the slope must
      exceed `min_slope_atr`; exactly flat never qualifies).

    The Candle Setup now requires the SMA 7 to slope with the trade
    (`sma_slope`, on by default; the other geometry rules stand). Its other
    conditions are Confirmation Blocks you attach (the UI sample attaches
    them): `second_wave`, `rsi_momentum`, `volume_expansion`, and
    `volume_continuation` (the setup candle quieter than the impulse before
    it), plus `sma_crossover`. A key-level location comes with levels
    (ticket 11). Two blueprint details are parameters of existing Blocks:
    `volume_expansion.max_factor` caps the setup candle's volume so a climax
    is not taken for a surge ("moderate, not exhaustion"), and
    `rsi_momentum.verge` accepts an RSI that is within that many points of
    its level ("on the verge of 70"). Both are off by default, so the
    default checks stay as strict as before.

    **Second Wave.** `structure.waves` numbers the legs of a Dow trend from
    confirmed swings. A trend starts in wave 1; a leg ends with a confirmed
    swing in the trend's direction, and the pullback after it ends with the
    next confirmed counter-swing, which starts the next wave. `second_wave`
    passes when the trend runs the trade's way and its wave number is within
    `min_wave`..`max_wave` (2..any). It is a hard check by default, and
    with no trend or one against the trade it fails.

    **Cancelled orders free their room.** When a Context cancels the
    resting orders of a symbol, those orders no longer count toward the
    position limit or the open-risk cap in the same cycle.

    **Crossovers confirm, never enter.** `sma_crossover` is only a
    Confirmation (the faster SMA on the trade's side of the slower one).
    No Setup Block reads crossovers, and a golden cross with no Candle Setup
    places nothing.

    **SMA 25 flattening takes profit.** The Profit Chain's optional
    `sma_flatten_exit` closes what remains once the first step has filled
    and the SMA on the management timeframe no longer slopes with the trade
    (`sma_flat_atr`). Exit Blocks may now return a close as well as a stop
    move (`CloseMove`); the engine ignores one before the first step, so the
    2R floor stands.

15. **Levels, touches, boxes and breakout confirmation (ticket 11).**
    `strategy/levels.py` is causal and scale-free: swings confirm
    `pivot_bars` later, distances are in ATR.

    **Levels.** A swing joins the nearest level within `tolerance_atr` ATR or
    starts one. A level is a single price, the median of its touches' body
    prices (a swing high is its body top, a swing low its body bottom), never
    a zone. A touch weighs 0.5 per `half_life` bars of age, so recent tests
    count more. A level touched as both resistance and support has flipped
    polarity. `level_location` (Confirmation) passes when such a level lies
    in the setup candle, widened by the tolerance; it is the key-level
    location the Candle Setup was waiting for.

    **Boxes.** A top edge touched `min_touches` times (3) and a bottom edge
    `min_bottom_touches` times (2) within `lookback` bars, between
    `min_height_atr` and `max_height_atr` ATR apart, at least `min_bars` old,
    with no close beyond an edge by more than the tolerance since the first
    touch. It is detected again whenever a swing is confirmed.

    **Box Breakout** (`box_breakout`). A breakout is the first close beyond
    an edge by more than the tolerance. A candidate stands on that bar and on
    each later one, up to `window` bars, while every close since stays beyond
    the edge; a close back inside ends it. A wick that pierces the edge and
    falls back is a sweep and makes none. Trigger: the bar's extreme in the
    breakout direction. Invalidation: the broken edge. Stop: the opposite
    edge. The candidate carries facts for the Confirmation Blocks (`meta`:
    the level, the breakout bar, the box start, the edge's touches).

    **A breakout belongs to the timeframe of its level.** Levels and boxes are
    computed on the bars of the Block's `timeframe` role, and a candidate
    appears only on the LWC bar where a bar of that role closes. A 15m close
    beyond a 4H level is nothing until the 4H bar closes beyond it. All
    counts are in that timeframe's bars.

    **Confirmations, each its own Block.** `breakout_body_close`: the whole
    body (or, if switched, the close) beyond the level. `breakout_range`:
    the breakout candle's range at least 1.5x the previous 6 bars' average.
    `consecutive_closes`: the closes beyond the level since the breakout reach
    N, 8 on 15m, 4 on 4H, 2 on daily (no default for other timeframes: it is
    not applicable until `bars` is set). `box_volume_dryup`: the box's second
    half quieter than its first. `touch_count`: the touch rule. One touch is
    a breakout on the first attempt and is refused. Two need another factor:
    the `confluence_timeframe` trend running the trade's way, or an
    absorption wick on the breakout candle. Three or four are the best
    window. All hard by default except the volume one. A touch is a
    confirmed swing whose body price lies within the tolerance of the level;
    a test that makes no swing is not counted. With the default
    `min_touches` of 3 an upward break has at least three touches, so the
    tiers apply to boxes built with fewer. A downward break reports the
    bottom edge's touches, whose default minimum is 2, so it can land on
    the second-touch tier and need the extra factor.

    **The two-way box** (`box_extremes`, one instance per side). While price
    is inside a detected box it stands every `refresh_bars` bars with the
    trigger at one edge and the stop at the other. Paired with `wave_cycles`
    (`two_way_box`), the Execution Block's `oco` (one fill cancels its twin),
    and `max_positions_per_symbol` 2, it is the blueprint's pair of
    stop-buy and stop-sell triggers at the box extremes; trades are tagged
    `counter_trend`, so the Profit Chain takes 2R-3R. The stop is the whole
    box, not a tight one. With one position or order already open, a refresh
    places only the side that registers first (the position limit counts
    both), and `expiry_bars` counts LWC bars while `refresh_bars` counts the
    box timeframe's, so size them together. The volume and RSI conditions of
    the blueprint's binary scenario are Confirmation Blocks attached to the
    document, not part of the box Blocks.

    **One order per breakout.** A breakout candidate stands for `window`
    bars, so the engine remembers each breakout it has placed an order for
    (`placed_breakouts` in the engine state, the symbol, Block and breakout
    bar, journaled and bounded to 500). Later candidates of the same breakout
    are refused (`already_placed`) even if the trade has closed. `window`
    must be at least the longest `consecutive_closes` count, or that check
    can never pass.

    **Where recency and polarity count.** `box_breakout` finds its edges
    from unweighted swing clusters. The recency weights and the polarity flip
    feed `level_location`, the key-level location check, and are there for
    Blocks that need a level book.

16. **Templates (ticket 12).** A Template is a validated, frozen
    `StrategyDocument` plus the source of each Block: the blueprint video
    numbers and a note, for every Block and for the Risk section
    (`strategy/templates.py`). Nothing edits one in place; `clone` returns a
    plain dict whose metadata names the Template and its version, which the
    user changes and validates like any document. Listed and cloned through the
    CLI (`nnfx strategy templates|clone`), the API (`/api/strategy/templates`,
    `/api/strategy/clone`) and the Strategy tab.

    **TCP Azizpour.** HWC `D1` (weekly is a one-line change), MWC `H4`, LWC
    `M15`, management `H4`. On: `wave_cycles`, `three_sma_alignment`,
    `choppy_regime`, `sma_baseline_filter`, the Candle Setup and the Box
    Breakout, the candle confirmations (`second_wave` as a score, not a
    refusal, since the blueprint says "ideally"; `rsi_momentum`;
    `volume_continuation`), the box confirmations (touch count, body close,
    1.5x range, consecutive closes, volume dry-up), the stop-market trigger,
    the structural stop, the Profit Chain 35/40/15/10, tiered risk and the
    governors. Off but present: `box_extremes`, `dow_trend`,
    `overextension_guard`, `sma_slope_gate`, `volume_expansion`,
    `sma_crossover`, `level_location`, `fixed_r`. Where the blueprint gives two
    values the Template takes the series-summary one: 15% at 10R (20% is `f3`),
    tiers 0.25-1.0% (the 0.5% base is `risk.sizing = "fixed"`). A test pins that
    every registered Block is in the Template, so each later Block ticket adds
    its Block here.

    **Scoped Confirmations.** Two setups share one document, so every
    Confirmation has `only_setups` (empty: all). A check scoped to other
    setups is left out of a candidate's checklist, not shown as not
    applicable. The Template scopes the candle checks to `candle_setup` and
    the box checks to `box_breakout`.

    **Research.** A Template's backtest is a Strategy Trial in
    `strategy_trials.jsonl`, a hypothesis family apart from NNFX's. No
    pre-registration file changes (a test hashes them), and its results are
    exploration until the family has its own pre-registration (spec).

    **Known limits.** The Template has no market universe (the user picks
    datasets). The weekly HWC and the order-book Blocks are not in it yet. A
    one-touch box needs the cloner to lower `box_breakout.min_touches`; as
    shipped, the Template needs three touches before the touch-count rule can
    even refuse a first touch.

17. **The builder, versions, diff and comparison (ticket 13).** The builder
    draws every form from a JSON schema, so a new Block shows up in the
    palette and gets a form with no UI code: `/api/strategy/blocks` serves each
    Block's parameter schema, `/api/strategy/schema` serves the Risk and
    Checklist sections and the timeframe roles. A test pins that every
    registered Block's schema is flat (boolean, integer, number, string, enum,
    list) so the generic renderer can draw it.

    **Storage.** `strategy/store.py` keeps one file per saved version,
    `<owner>/<name>/v0001.json`; owner and name are hashed into directory
    names, so no user text becomes a path. The version number is the store's,
    never the client's. A save identical to the latest version adds none.
    Caps: 100 strategies per user and 200 versions per strategy. Strategies are
    private to their user (the account name; `local` without accounts).

    **Diff.** `strategy/diff.py` compares two resolved documents: Blocks by
    (kind, type) as added, removed, switched on or off, a changed parameter,
    or reordered; the timeframe roles, universe, Risk and Checklist field by
    field. The name, version, parent and description are not compared. The
    default base is the document's parent: a Template, or one of the user's
    own strategies when the document is a duplicate. The base can also be the
    last saved version, another saved strategy, a Template or any document.

    **Import and export.** Export downloads the validated, resolved document as
    a JSON file. Import (`/api/strategy/import`) reads text, never trusting it:
    empty files, broken JSON, non-objects and invalid documents come back as
    Persian issues, every problem at once, and nothing is saved until the user
    saves.

    **Comparison.** `/api/strategy/compare` runs two documents on the same
    bars with the same costs and returns their metrics side by side plus the
    diff. The two documents must share the LWC. Both runs are Strategy Trials
    (stage `strategy/compare`), so a comparison is exploration, not research.

    **UI.** A Stop or Exit Block decides alone, so switching one on switches
    the others of its kind off. Forms keep their open state across redraws.
    The JSON editor remains as an advanced view that is always the same
    document. Known limits: the builder has no undo and does not warn before
    opening, importing or loading over unsaved edits; some Risk-section
    descriptions are still in English; a parent name that equals a Template
    slug is read as the Template; a strategy that fails to read is left out
    of the list rather than hiding the others (saving a new version repairs
    it); and each comparison logs two Strategy Trials, which count as tried
    variants for that family.

### 18. The remaining setups and the chase guard (ticket 14)

`strategy/setups.py` holds eight Blocks, all in the Template **disabled** (a clone
switches on what it trades). The candle setups read the LWC bars; the structural ones
read the timeframe role their parameters name. Each emits a trigger, an invalidation
and a proposed stop; every number is a parameter.

| Block | Fires when | Trigger / stop |
|---|---|---|
| `engulfing` (38) | the body covers the previous candle's whole range (wicks too), after a leg the other way of at least `min_prior_move_atr` whose pushes were fading (recent bodies at most `weakness_ratio` x earlier; optionally volume too) | high / low of the engulfing bar (mirrored) |
| `giant_indecision` (26) | range (and volume, where the venue has it) above all of the last 10 bars, small body, one long wick, after a move into it, with the higher timeframe already weak | beyond the *opposite* side of the candle; stop at the wick tip |
| `absorption_wick` (68) | the low pierces the lowest low of the last `lookback` bars and the body closes back above it (mirrored at resistance) | above the candle's high; stop at its low |
| `layered_setup` (69, "LA") | an impulse, then a box whose latest confirmed swing low is above its first, and whose pushes up take fewer bars than the pullbacks | above the ceiling; stop under the inner higher low; invalidation the box bottom. One instance per side |
| `dow_continuation` (62) | in a Dow trend, the first close beyond the last confirmed swing | break bar's extreme; invalidation the broken swing; stop the previous swing |
| `binary_scenario` (87) | a box is confirmed: the long arms the top, the short the bottom, once per box (or every `refresh_bars`) | `stop_market` with `oco` cancels the loser |
| `momentum_continuation` (66) | RSI beyond 70 (30) on every listed timeframe, then a micro-setup (pullback to the 7 SMA, or a bar taking out the prior bar's extreme) | the bar's extreme |
| `chase_guard` (64, Context) | a bar whose range is over `multiple` x the mean of the previous `lookback` | refuses new candidates in the bar's direction for `cooldown_bars`; resting orders are kept |

Decisions and known limits:

* **Binary scenario.** The pair is two Setup Blocks (one per side) sharing the Execution
  Block's `oco` (ticket 02). The video's volume and RSI>70 / <30 readings belong to the
  *breakout moment*, which a pre-placed order cannot see, so they are Confirmation Blocks
  (`only_setups: ["binary_scenario"]`) that judge the candidate when it is armed.
* **Giant indecision.** "Higher-timeframe weakness" is read as the higher timeframe's last
  close being above (for a long) its short SMA: the old trend has lost it. It is an
  interpretation; the parameters let a clone change it or switch it off.
* **Absorption wick.** Support is the rolling low of the previous bars; whether it is a
  *key* level is the existing `level_location` confirmation's job.
* **Chase guard** is disabled in the Template: the box-breakout's own range rule asks for
  a big candle, and blocking by default would suppress valid breakouts. Whoever wants the
  blueprint's "never chase" switches it on and picks the multiple.
* **Momentum continuation** defaults to the SMA pullback; `prior_high` takes every bar that
  breaks the previous bar's extreme while momentum lasts, which is noisy. Roles are the
  three timeframe roles, so "15m, 1H and 4H" is expressed as the roles a document maps.
  The "15m consolidation breakout" micro-setup is the existing `box_breakout`.
* **Not built in:** the Template's binary pair carries no volume/RSI confirmations (a clone
  attaches them), `dow_continuation` does not check that the way is clear of higher-timeframe
  barriers, and the engulfing weakness is the fading-body test (volume contraction optional;
  boundary rejections and divergence are not read).
* The LA's "faster pushes" are counted in bars between confirmed swings, so they appear
  `pivot_bars` late; every output is causal and tested to be.

## 19. The oscillator methods (ticket 15)

Oscillators warn and filter; they never trigger (videos 44, 53). The registry enforces it:
a Block class flagged `oscillator = True` cannot be a Setup or Execution Block
(`register` raises), and the catalogue reports the flag. All nine are Confirmation Blocks in
`strategy/oscillators.py`, off in the Template, and read the oscillator of one timeframe
role (`role`) at the role bar the candidate stands on.

| Block | Method | Passes when |
|---|---|---|
| `osc_momentum` | 1, OB/OS as momentum | beyond the zone in the trade's favour (optionally just entered) |
| `osc_inflection` | 2, 50/0 line | on the trade's side of the line (`offset` moves it; optional fresh cross) |
| `osc_signal_cross` | 3, signal line | cross of a half-period synthetic SMA in the extreme zone or through the midline; mid-zone crosses ignored |
| `osc_level_break` | 4, levels on the oscillator | closed beyond its latest confirmed swing level within `fresh_bars` |
| `rsi_bb_reentry` | 5, BB on RSI | RSI back over its Bollinger middle after an impulse out of the band (`impulse`) or a dip into the other band (`dip`) |
| `osc_recalibrated` | 6, cycle length | momentum with RSI period = mean swing-to-swing distance of the current Dow regime |
| `osc_mf` | 7, multiplier factor | momentum with the LWC RSI period = base x (higher minutes / LWC minutes) |
| `osc_divergence` | 8, divergences | regular/hidden divergence between the last two confirmed swings, one oscillator pivot in the extreme zone |
| `rsi_cascade` | RSI ladder | a role just entered the zone while the lower roles are still in it |

Decisions and limits:

* Bounded oscillators (RSI) use fixed zones (70/30). Unbounded ones (CCI, ROC) use
  `extreme_fraction` (0.8) of the rolling 200-bar extremes of the bars *before* the tested one,
  so a new extreme can still break the zone; the 0.8 is my reading of "the highest and lowest
  swing extremes over 200 candles", exposed as a parameter.
* The recalibrated period resets at a Dow state change of the role (the "regime shift
  governor"); with fewer than two cycles in the regime the base period stands.
* The MF RSI needs `base x MF` LWC bars first (224 for 4H on 15m), so it is not applicable
  earlier.
* The exit side lives in `profit_chain` (one Exit Block per document): `rsi_exhaustion_exit`
  closes what remains, after the first step, when RSI pierced its upper (shorts: lower)
  Bollinger band within `rsi_reject_bars` management bars and has turned back inside;
  `hold_while_rsi_role` is the cascade's hold side: while that role's RSI is still beyond
  70/30 the SMA-flatten and RSI-exhaustion closes wait. Both are off by default. The
  exhaustion exit does not also ask that price be at resistance.
* The cascade's `sequential` option (lower roles still in the zone) is off by default: a
  missed 15m entry may already have pulled back when the 4H closes above 70. The cascade
  and the hold use the three roles (a daily rung is reachable by mapping a role to it); the
  hold is one role, not the whole 1H/4H/daily chain.
* The extreme-zone rule for divergences is strict (`< 30`, `> 70`), and the oscillator is
  read at the price pivots' bars. `rsi_bb_reentry` needs a cross from at or below the
  middle line; the established trend is the context's job.
* **Not built in:** trendlines and chart patterns on the oscillator (only horizontal levels),
  the apex timing principle, scaling MACD and SMA by MF (RSI only; MACD is ticket 16), and
  a price-at-resistance condition on the RSI exhaustion exit.

## 20. MACD, ROC and ADX/DMI (ticket 16)

Videos 54-56. The rules live in `strategy/momentum.py` (series helpers, three Blocks, the
exit-side signals) and `library` (the Execution Block and the Profit Chain options).

| Block / option | Kind | Rule |
|---|---|---|
| `macd_cross` | Confirmation (oscillator) | the MACD line crossed its signal line in the trade's favour within `cross_bars`; a cross whose \|MACD\| is under `zero_band` (0.1) of the prior 200-bar maximum \|MACD\| is chop and ignored, and the newest cross outside the band decides |
| `roc_ceiling` | Context (oscillator) | no longs while the ROC (default 4H, period 14) is at `extreme_fraction` (0.95) of its prior 200-bar high; `mirror` closes shorts at the floor. Unknown history forbids nothing |
| `roc_box_breakout` | Confirmation (oscillator) | ROC beyond the high-low range of its previous `box_bars` (20) within `fresh_bars` |
| `adx_order_type` | Execution | DI separated (\|+DI - -DI\| >= 10) with ADX above its value `slope_bars` ago: the usual stop-market order. DI tangled (< 5): a market entry at the next open, only once the last LWC close is beyond the candidate's invalidation, otherwise no order (the engine journals `no_order`). Between the two: `between` (stop by default) |
| `macd_decel_exit` | Profit Chain | histogram on the trade's side shrinking `macd_decel_bars` in a row while a close set a new `macd_extreme_bars` high in that window; closes what remains (after step 1) |
| `roc_ceiling_exit` | Profit Chain | ROC at its ceiling (shorts: floor) closes what remains (after step 1) |
| `adx_exhaustion` | Profit Chain | ADX reached `adx_level` (45) within `adx_peak_bars` and turned down: `close` takes the profit (after step 1), `tighten` trails the stop behind the last management swing at once |

Engine: an `OrderSpec` may now be `market`; the engine turns it into an `OpenIntent` whose stop
distance runs from the confirming close to the stop. The reference run is unchanged.

**Decisions and limits.** The blueprint gives no ROC period, MACD band or DI thresholds; the
numbers above are parameters with my reading as default. The ROC ceiling is 0.95 of the prior
extreme because "hits or exceeds" is a hand-drawn line, not a new high (1.0 means only new highs).
The ROC "box" is the rolling range of the previous bars, not a drawn consolidation. "Tangled DI
requires a body close" is built as a market entry on a close beyond the invalidation level, which
for a Box Breakout candidate is the broken edge; the resting-order cancellation rules do not apply
to it. MF scaling of MACD and SMA periods is not built (only RSI scales); the Template keeps all of
this off.

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
