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
| `adx_exhaustion` | Profit Chain | ADX reached `adx_level` (45) within `adx_peak_bars` and turned down: `close` takes the profit (after step 1), `both` does both, `tighten` trails the stop behind the last management swing at once |

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

## 21. Volume and trend health (ticket 17)

Videos 22, 23, 27, 29-33 and 67. Volume rules live in `strategy/volume.py`, trend health in
`strategy/health.py`. Nothing is an absolute constant: volume is judged against the mean of the
`lookback` bars before it, a body against the ATR, a range against the mean range before it, so
the rules read the same on any venue, symbol and price level. A venue without volume gives `na`.
A candidate stands on the latest closed bar of the Block's `role` (volume Blocks default to the
LWC, the profile to the MWC).

| Block | Kind | Rule |
|---|---|---|
| `volume_matrix` | Confirmation | price (close vs `bars` ago, beyond `move_atr` ATR) and volume (mean of the last `bars` vs the `bars` before, beyond `margin`): price up on rising volume and price down on falling volume (selling exhausted) pass longs; price up on falling volume and price down on rising volume pass shorts; the other side fails. Flat price or volume, and Box Breakout candidates (quiet volume is compression, video 29): `na` |
| `effort_result` | Confirmation | absorption (volume >= `heavy` x baseline, body <= `small_body_atr` ATR) or vacuum (body >= `big_body_atr` ATR, volume <= `light` x baseline) within `fresh_bars` fails; `anomaly` picks which |
| `volume_climax` | Confirmation | a buying climax (volume >= 3x baseline, range >= 1.8x the mean range, closing up) within `fresh_bars` fails longs; a selling climax fails shorts |
| `low_volume_dip` | Confirmation | one of the `bars` bars before the candidate had volume at a `lookback`-bar low and <= `low` (0.6) x baseline. Meant for reversal setups (`only_setups`); the dip is never an entry itself |
| `volume_node` | Confirmation | the volume profile of the last `window` (200) closed bars over `bins` price bins (each bar's volume spread equally over the bins its range touches); a bin >= `node_factor` x the mean bin is a heavy node, and a node whose centre lies within `clear_atr` ATR beyond the trigger fails the candidate |
| `trend_health` | Context | counts the weaknesses of the selected `metrics` per role bar; with `min_signals` or more the trend's own direction is closed (a weak uptrend disables longs, a weak downtrend shorts), the other side is untouched. Flags `health_up` / `health_down` carry the counts |
| `climax_exit` | Profit Chain | a climax in the trade's direction on the management timeframe closes what remains (after step 1) |
| `health_exit` | Profit Chain | the trade's trend shows `health_min_signals` weaknesses: `tighten` trails the stop behind the last management swing at once, `close` takes the profit (after step 1), `both` does both. Thresholds are the shared `HealthParams` fields |

Trend-health metrics (all per role bar, causal; swings only once confirmed, same-kind swings
collapsed to the more extreme so legs alternate):

* `amplitude`: the last `amp_legs` (3) impulse legs (swing to swing) strictly shrink and the last is
  at most `amp_shrink` (0.7) x the first (10, 6, 2).
* `duration`: the pullback after the last impulse took at least `dur_correction` (1.0) x its
  bars, or the last impulse took at least `dur_slowdown` (2.0) x the one before.
* `body`: price advancing while the mean body-to-range share over `body_bars` is under
  `body_floor` (0.3) and below the share before.
* `close_placement`: price advancing while each of the last `close_bars` closes sits lower in
  its candle than the one before, the last under `close_limit` (0.5).
* `color`: price advancing while opposite-coloured candles are at least `color_max_opposite`
  (0.5) of the last `color_window` (20) bars.
* `channel`: a close beyond the least-squares channel of the previous `channel_window` (50)
  closes, projected one bar, with bands `channel_width` (2) standard deviations out and the
  channel sloping with the trend.

Single-bar metrics (body, close placement, colour, channel) stay flagged for `hold_bars` (3) bars so
signals of different bars can coincide. `effort_result` fails absorption only after a `trend_bars`
(10) move the trade's way (against it, it is accumulation, video 33); the vacuum is direction-blind.
Not built: the 200-bar volume ceiling/floor envelope (video 31), level context for climax and
low-volume dips (pair them with `level_location`), impulse/correction *distance* (only duration),
and a climax exit before the first step (the 2R floor).

**Decisions and limits.** The blueprint gives few numbers; those above are my defaults, all
parameters. The channel is a regression channel, not a drawn trendline channel (ticket 19 adds
trendlines; this metric can then read them). The "curvature" metric (video 23 C) and candle
uniformity (video 22) are not built; the ticket does not list them. `volume_matrix` reads
bullish divergence (falling price, falling volume) as favouring longs, as the blueprint's table
does. `health_exit` and `climax_exit` live in the Profit Chain with the shared `HealthParams`
fields, so the Profit Chain's form is long. All new rows are off in the Template.

## 22. Bollinger, pivots and sessions (ticket 18)

Videos 14, 57 and 58. Bollinger in `strategy/bands.py`, floor pivots in `strategy/pivots.py`,
sessions in `strategy/sessions.py`; `strategy/candles.py` now holds the candle-style Setup
output that `setups.py` and `bands.py` share. All new rows are off in the Template.

| Block | Kind | Rule |
|---|---|---|
| `bb_htf_touch` | Setup | higher-timeframe Dow up: a low at or under the lower band that closes back above it (`touch`), or a close back over the middle line (`cross`) is a long; mirrored for shorts; flat Dow gives nothing |
| `bb_squeeze` | Setup | bandwidth strictly under the `squeeze_pct` quantile of the `window` bars before it within `squeeze_bars` bars, then a close outside the band: trade the break |
| `bb_runway` | Confirmation | the last `bars` closes lie between the 1 SD and 2 SD bands on the trade's side (double Bollinger "Momentum Runway") |
| `pivot_breach` | Confirmation | the close is beyond R1 (longs) or S1 (shorts) of the last closed 4H bar or week; the central P is never a signal |
| `session_filter` | Context | entries only in the chosen sessions (Asia 00-08, London 07-16, New York 12-21 UTC) and never from 21:00 to 00:00 UTC |
| `session_regime` | Context | London and New York trending the same way set a continuation bias until the next London close; a London that failed to trend moves momentum to the 13:30-14:30 UTC window |

Profit Chain additions, both only after the first step (the 2R floor): `runway_exit` closes
what remains once candles that rode the runway in the last `runway_bars` bars close back inside
the 1 SD band (a close beyond 2 SD is not "lost"); `pivot_exit` (`r3`, `r4`, `both`) closes at
R3/S3 or R4/S4 on `pivot_period`, where `both` only tightens the stop (behind the last swing) at
R3 and closes at R4. A management bar is judged against the pivots in force while it traded
(the LWC bar before its close), so the period that closes with the bar never grades its own
candle.

**Pivots are causal by construction.** The H4 and weekly bars come from the shared
`TimeframeViews` resampler, which drops partial ends; at each LWC bar the levels are those of the
latest period closed by then.

**Sessions are UTC and never read a local zone**, so daylight-saving changes in New York or
London move nothing (tested across the four 2024 clock changes). A bar is labelled by its close,
which is also when the next bar opens, so "may I place an order now" is judged by the label's
hour: a bar labelled 21:00 places nothing, one labelled 00:00 may. A session's trend is its net
move over its high-low range (`trend_efficiency`, default 0.5; scale-free) and is judged only
when all its bars are in and its window has ended.

**Decisions and limits.** The blueprint gives no pivot formulas; I use the "traditional" set
(R3 = P + 2 range, R4 = P + 3 range, S mirrored). The three default sessions together cover
00:00-21:00, so the blackout is already implied by them; it stays a switch and takes any window
(wrapping midnight) for sessions chosen otherwise. Regime 2 is judged at the start of the US
window because London's close (16:00) comes after it; on hourly bars, where 13:30 is not a bar
close, London is judged to the last whole bar (13:00). "Aggressive profit-taking at R3" is a stop
tightening in `both` and a close in `r3`; the choice is a parameter. Not built: the weekly pivot
as a *level* for trend filters, and session-based alerts (ticket 22).

## 23. Trendlines and Fibonacci (ticket 19)

Videos 25 and 76-81. Trendlines in `strategy/trendlines.py`, Fibonacci in
`strategy/fibonacci.py`. All new rows are off in the Template.

| Block | Kind | Rule |
|---|---|---|
| `trendline_bounce` | Setup | a bar reaches an active line (within `tol_atr` ATR) and closes on the trend's side: a long on a rising support line, a short on a falling resistance line |
| `trendline_break` | Setup | a close more than `tol_atr` ATR through an active line: a short through support, a long through resistance; a wick that recovers is a sweep |
| `fib_reclaim` | Setup | in an up-leg a bar wicks under the 0.382 retracement and closes back on or above it: a long (mirrored for a down-leg); with `min_confluence` (default 2) the level needs that many other factors, so a lone Fibonacci line makes no candidate |
| `fib_confluence` | Confirmation | a retracement level (0.382, 0.5, 0.618 by default) lies in the setup's range and has at least `min_confluence` other factors on it; `na` until a leg exists |

Profit Chain addition, after the first step only: `fib_target` (`1.0`, `1.272`, `1.618`, `2.0`)
closes what remains when the management bar reaches that extension of the leg projected from the
validated retracement low `C` (`fib_ext_<ratio>`).

**Trendline rules.** A line is *active* once `min_touches` (3) distinct swings sit on it, and
not before the third is confirmed. It is anchored from the *second* swing of the window: the
first swing is the impulse and is never an anchor. Only the last `window` (200) bars take part
and a line expires `window` bars after its anchor. A close beyond a line kills it, and a rebuild
rejects any candidate already broken. Support lines rise through swing lows, resistance lines
fall through swing highs (a falling support line is no uptrend line). Swings are wick extremes
and are used `pivot_bars` bars after their own bar.

**Slope bounds are scale-free.** The source limits angles to 20-60 degrees, which only means
something on a fixed-scale chart. `degrees_to_atr_per_bar` converts them for a reference chart
(`window` bars across, 20 ATR of price up, width twice the height):
`tan(angle) = slope * window / (20 * 2)`, so 20 degrees is 0.073 and 60 degrees is 0.346 ATR
per bar (45 degrees is 0.2). The slope is measured against the ATR at the line's last touch.
The two bounds are parameters (`min_slope`, `max_slope`); anything flatter is a box edge,
anything steeper a blow-off.

**Fibonacci anchors are structural and causal.** A leg runs from the lowest confirmed swing low
since the previous swing high (mirrored for down-legs) to the confirmed swing that ended it; it
exists only from that swing's confirmation (the objective reaction: `pivot_bars` bars with no
new extreme) and only if it is at least `min_impulse_atr` ATR long. One leg lives until a close
beyond its start; a higher high confirmed in its direction moves its end and forgets `C`. All
ratios are measured on `ln(price)`, so they are the same proportions at any price and price scale.
Extensions project the leg from `C`: `C * (B/A)^ratio` for an up-leg.

**Confluence.** The other factors are a horizontal level (the ticket 11 `LevelBook`), the SMA 25
and the SMA 99, each counted separately, within `tol_atr` ATR of the Fibonacci price. The
order-book wall named in the blueprint joins when ticket 21 lands.

**Decisions and limits.** `min_confluence` cannot go below 1: the lone-Fibonacci rule is not a
switch. The impulse swing excluded from anchoring is the first swing inside the rolling window,
so as the window slides a later swing takes that role; a line's window edge is `anchor + window`.
When the impulse extends, `C` is forgotten and `fib_target` is silent until a new retracement
low is confirmed. A leg's start `A` stays at the original swing low. Of the blueprint's three "objective reactions" (a counter-trend
candle, a lower high on a lower timeframe, a break of the 7 SMA), the confirmed swing is the one
built. The "Fib 1.618 without momentum" exhaustion exit is not built (`fib_target` closes at the
level unconditionally). The macro Weekly/Daily Fibonacci floors are available by choosing the
role; they do not gate lower-timeframe triggers, because nothing reads them as a trigger.

## 24. Dominance, ALT/BTC and the screener (ticket 20)

Videos 12, 59, 66, 83 and 84. Market Filter Blocks in `strategy/dominance.py`, the series
plumbing in `strategy/market.py`, the screener in `strategy/screener.py`. Both Blocks are off
in the Template.

**The Market Filter contract.** A Market Filter is a Context Block over the *market series*, not
the symbol's own bars (`MarketFilterBlock`, kind `market_filter`). It returns a `ContextOutput`
with one more field, `available`: where it is False the Block has no data and its check is
`na`, never a pass and never a refusal. `StrategyData.market` carries the series (`MarketData`,
name -> `BarFrame` on a base timeframe); `compile_document` and `backtest_document` take it.
`DocumentRun.incomplete` (and `incomplete_blocks`) says whether any candidate saw such an `na`,
the "incomplete result" of the order-book rule (§9) generalised. The UI shows it.

**Series.** Dominance indices (`BTC.D`, `USDT.D`, `TOTAL2`, `TOTAL3`) come from a TradingView
export (`read_market_series`, hourly or 15-minute like every import) and are read at the
Block's timeframe role like any bars. A pair ratio is the cross pair when it was given
(`SOL/BTC`) and is otherwise derived from the closes of the two exchange pairs on the bars both
have (a ratio's open, high, low and close are all that ratio). A series is *known* at an LWC bar
only if one of its role bars closed by then and no more than `max_stale_bars` role bars ago:
starting late, ending early or a hole all read as unknown. Trend is the Dow state of the closes
(`structure.waves`), the same trend every other Block uses.

| Block | Rule |
|---|---|
| `dominance_regime` | BTC trend x BTC.D trend. **BTC-led** (BTC up, BTC.D up): BTC longs only (no BTC short), no altcoin long. **Altseason** (BTC up or ranging, BTC.D down): altcoin longs; no BTC long unless `altseason_trades_btc`. **Alt flush** (BTC down, BTC.D up): BTC is never shorted; altcoins may be shorted, not bought. Candidates carry the regime as a tag |
| `relative_strength` | a long needs the ALT/BTC trend up, a short the mirror; `second` adds ALT/ETH or ETH/BTC (the Ultimate Long Sieve); a ranging ratio admits neither; BTC itself is outside it |

**Decisions and limits.** Combinations outside the blueprint's table (BTC.D ranging, both
falling) restrict nothing. The block refuses only what the table
names: altcoin longs in BTC-led and Alt flush, BTC shorts in BTC-led and Alt flush, BTC longs in
Altseason (unless asked); the table is silent on altcoin shorts in the bullish regimes, so they
pass. An asset against itself (ALT/ETH on ETH) is no ratio and reads as unknown. ALT/BTC "breaking out of a consolidation on
expanding volume" is read as the ratio's Dow trend turning up, which a breakout of the swing high
does; the volume leg is left to the volume Blocks on the ALT/USDT chart. The Strategy Builder UI
does not yet upload market series, so a UI run with a Market Filter on is honestly incomplete.

**The screener.** `screen` ranks a watchlist from exchange ticker data: 24-hour quote volume
converted to BTC at BTC/USDT's price (at least 1,000 BTC), and performance *valued in BTC*,
`(1 + alt) / (1 + btc) - 1`, positive over 24 hours and 7 days; at most five assets (1 to 5),
ranked by the 7-day figure, then the 24-hour one, then the symbol. Stablecoins, BTC and
non-USDT pairs are skipped (a stablecoin would otherwise "beat" a falling BTC). The 7-day change
comes from daily bars and is fetched only for pairs that already pass the cheaper tests.
`stats_from_exchange` reads a ccxt-style exchange, injected, so every test is offline. The
list is an input to the morning routine, not a signal; it is not yet wired to a CLI command or
the UI.

### 25. Order-book Blocks (ticket 21)

Order-book rules are live-first: they read the walls of ADR 02's Order Book Source (ticket 04)
through `StrategyData.book`, a `BookData` over a recorded or fixture history. Each snapshot is
fed once, in time order, to a `WallTracker` per (symbol, wall parameters), and the Block asks for
the state *as of the candidate's time*: the latest snapshot at or before it, never a later one,
none if it is older than `max_age_seconds` or one-sided. Walls are confirmed (persistent across
`persist` snapshots), sized against the book's own depth (a percentile and a multiple of its
median level), and never spoofs: a wall that vanished or stepped back as price approached is gone
from the state, and a wall confirmed again at a level that spoofed is suspect and left out.

| Block | Rule |
|---|---|
| `wall_trigger` (Execution) | the stop-market trigger moves just beyond the far edge of the *largest* persistent opposing wall within `max_distance_pct` of the setup's trigger (ask wall above a long, bid wall below a short). It aborts the breakout (no order) when volume contracts (the last `volume_bars` average under `contraction_factor` of the bars before) while a wall's near edge is within `approach_pct` of the close |
| `wall_shielded_stop` (Stop) | the nearest persistent wall of the entry's own side strictly between the structural stop and the trigger (bid wall under a long) takes the stop to just behind its far edge; the stop only tightens and stays on the losing side; walls glued to the trigger (`min_gap_pct`) are ignored |
| `wall_targets` (Exit) | a Profit Chain whose steps are pulled in front of the opposing walls that would stop them: for each step, the nearest wall between the previous step and the step's price places the target just in front of its near edge. No step goes below 2R, so a closer wall changes nothing; steps stay increasing; manage, breakeven, trail and exhaustion exits are the Profit Chain's |

**Without a book** (no recording, a gap, a stale snapshot) each Block is its plain counterpart
(`stop_market`, `structural_stop`, `profit_chain`) and the engine journals `book_missing` on every
candidate it evaluated: `DocumentRun.incomplete` is true, `incomplete_blocks` names the Blocks,
`book_missing_candidates` counts the candidates, and `book_gaps` lists, per symbol, the stretches of
the run with no snapshot fresher than the Blocks' `max_age_seconds` (the longest of them). The CLI
prints them (`nnfx strategy backtest --orderbook DIR`, DIR being the recorder's `--root`); the UI
shows the incomplete notice.

**Decisions and limits.** Walls are found with the Block's own parameters, so two order-book
Blocks with different parameters track separately. The Template carries all three disabled; they
replace `stop_market`, `structural_stop` and `profit_chain`, never join them (one Stop and one
Exit Block decide). `wall_targets` extends `ProfitChain` so the recycling record and every
exit option still work. "Heavy" is the wall definition itself (relative to the book), not a second
threshold. The abort is part of `wall_trigger` because an Execution Block can only add orders,
never veto another's; with no venue volume it aborts nothing. A UI run cannot upload recordings
yet, so it is honestly incomplete. Price-scale invariance is not claimed: walls are absolute
prices in the exchange's units.

### 26. Paper mode and alerts (ticket 22)

A paper run is the live harness (ticket 27) with the document engine, not a second runner. Each
cycle fetches the closed 15m bars (`LiveBars`: Nobitex through the UDF feed, the window once and
then only the tail), compiles the document over them (§ Consequences: recompile per bar), and
`LiveHarness.run_cycle` applies the new bars to a persistent `PaperBroker` and journals each step.
Everything lives on disk under `runs/paper/<owner>/<run>/` (`run.json`, `journal.jsonl`,
`broker.json`), so a restarted server resumes every running run. Tests: decisions equal the
backtest's cycle for cycle over the same bars (the `COMPARED` fields of the parity harness), also
when a fresh process runs each bar, and also during a Bale outage.

* **Per user.** Runs belong to their owner (stop is refused for another's run), at most 3 run at
  once and 5 symbols each; symbols are the Nobitex `/USDT` ones (the account is USDT). A run
  starts from a saved strategy version; its document is copied into the run, so later edits do not
  change it. A failing bar source or a failed reconciliation puts only that run in `error` with
  the reason and raises a `halt` alert.
* **Alerts** (`nnfx/alerts.py`) are derived from journaled cycles: a Setup Candidate appears
  (placed or refused, with reasons), a Trigger is placed, filled, cancelled, or expires. Ids are a
  hash of run and cycle content, so replaying a cycle (a crash between journal and bookkeeping)
  adds nothing to the feed. Closes by stop or target are not alerted (not asked for).
* **Channels** are switchable per user: the in-site feed (default on) and Bale (default off; needs
  the server's `NNFX_BALE_TOKEN` and the user's numeric chat id; Telegram comes later via an
  external relay). Bale is the bot API's `sendMessage`, taken from its Telegram-compatible docs,
  not exercised against the live service here: the HTTP client is injected and tested offline.
* **Failures never touch trading.** The feed write is wrapped; Bale delivery runs in a worker
  thread with 3 attempts and doubling delays, and a final failure goes to the user's
  `failures.jsonl`. `submit` returns at once even while a Bale call hangs (tested).
* **Limits.** Order-book Blocks in a paper run read the recorded books when the server has a recordings directory (§28); without one they behave as their plain counterparts and the run's checklists carry `book_missing`. The window is the last 3000 bars (about 31 days), so very long
  lookbacks see less than a full backtest would. A bar source that stays one bar behind is simply
  retried each round. Paper results are not research trials. A run whose bar source fails stays alive for 3
  rounds, then errors (terminal: start a new run); reconciliation and gate failures error at once.
  Queued Bale messages are lost if the process dies (the feed is not); a replayed cycle adds
  nothing anywhere (a `seen` set per user). The Bale chat id is not verified to belong to the
  user, so a handshake (`/start` with a code) is needed before wide use.

### 27. Journal analytics (ticket 23)

Every closed position is one `JournalRow` (`strategy/analytics.py`) with the blueprint's fields:
timestamp, session, weekday, asset, direction, setup type, risk tier, size (units), leverage,
the initial stop, the exit plan's target prices, outcome (win / loss / breakeven on the whole
position's net result), realised R, MAE, slippage, fees (and the spread, kept apart). Backtest
and paper runs build rows the same way from the broker's trades, the journaled cycles and, when at
hand, the bars: the cycle joins a position to its candidate through the fill's order key, so the
setup, tier, leverage, stop and targets are what the engine journaled (`targets` is new in the
candidate's values: the Exit Block's plan priced from the trigger and the stop). `Trade` itself is
unchanged, so the determinism digest is.

- **Session** is the session the entry bar traded in, by the bar's open (the label minus the bar):
  Asia, London or New York in UTC (§22); where two overlap the later-opening one; `off_hours`
  outside all. **Weekday** is the same instant's UTC weekday.
- **MAE** is the deepest drawdown from the entry price, in initial-stop distances, over the bars
  after the entry bar through the exit bar. The entry bar's own range may precede the fill, so it
  is left out (a small understatement). Without bars (a paper run whose window no longer reaches
  the trade, or a source that is down) MAE is `None`, not zero.
- **Statistics** per setup, session, weekday, asset and risk tier: count, wins, win rate,
  expectancy and total R, mean MAE. Weekdays keep calendar order.
- **Review and rule changes.** A review is prompted from 50 trades (the latest multiple of 50 is
  reported, the next one named); changing rules is warned against until 100 forward trades exist.
  A backtest has none (a backtest is not forward), a paper run's trades all count. A losing streak
  up to 7 is called normal. The prompt is stateless: nothing records that the user reviewed, so it
  stays shown from the 50th trade on.
- **API and UI.** `/api/strategy/backtest` returns `journal`, `stats` and `review`;
  `GET /api/paper/journal?id=` returns the same for a user's own paper run. The backtest result
  and the paper tab show the review notes, the five tables and the rows.

Limits: the journal is per position, not per leg (partial closes are summed); a paper run's trades
come from the broker's persisted state, so a run started before this ticket has them but no
journaled `targets`; the leverage is the document's, not an exchange fact.

### 28. Recorded order books reach the paper-run server (ticket 24)

Paper Runs trade only Nobitex `/USDT` pairs (`paper_symbols`), while the deployment's recorder
defaulted to `/IRT` pairs, so no recorded book matched a paper symbol. The recorder's defaults
(deployment compose file and `.env.example`) now also record `BTC/USDT` and `ETH/USDT`; recorder
and reader name a symbol's directory by the same function, so a paper symbol finds its books by
construction, and a test checks that every paper symbol is in the deployment's recorded list.
The server takes the recorder's directory (`nnfx ui --orderbook DIR`, else `NNFX_ORDERBOOK`) and the
deployment mounts the recorder's volume into it read-only. This ticket only gives the server the
directory (`App.orderbook_root`); reading it into a run's decisions follows below (ticket 25).
Without the option nothing changes. Limit: the recorder must be running for books to exist; an existing
deployment has to restart it with the new symbol list (the volume keeps older recordings).

*Reading the books (ticket 25).* The window ends at the cycle's own `now`, so a replay of old
bars reads the books of its own days. A paper run's order-book Blocks read the recordings as of each
cycle. `LiveRecordedOrderBook` remembers its byte offset in each day file and, on `refresh()`,
parses only the lines appended since (a line the recorder is still writing waits for its
newline); days older than two days before now are never read and older snapshots are dropped.
`BookData.refresh()` feeds each wall tracker only the new snapshots, so a cycle's cost follows
what was recorded since the last cycle (the time index, sort and trim still pass over the
two-day window), not the recording's size, and `forget_before` bounds the
timeline's memory (the latest state before the cutoff is kept, so it still answers). The state at
a candidate's time depends only on snapshots up to then, so a paper run decides exactly as the
order-book backtest over the same recording, as far as the two-day window reaches (tested, including a restart on every bar and books
recorded while the run goes). A run whose document has order-book Blocks stores `book_gaps`: the
stretches of the last two days with no snapshot fresher than the Blocks' `max_age`, shown in the
paper tab; `book_missing` is on a candidate only where no fresh two-sided snapshot existed.
Limits: a snapshot that arrives stamped earlier than one already taken in is not fed to a wall
tracker (the recorder stamps with its own monotonic clock); the offsets of day files are kept for
the process's life; walls older than the two-day window are forgotten at the start (a freshly restarted
server rebuilds from the last two days only); a wall tracker built after the first cycle for new
parameters starts from the snapshots then held.

*Stale books (ticket 26).* When a run's document has order-book Blocks and the server has a
recordings directory, each cycle checks every symbol of the run: no snapshot within the Blocks'
largest `max_age_seconds` before the symbol's latest bar means its book is stale. The first stale
cycle raises one `book_stale` alert and the first fresh one after it a `book_back` alert; the
run's `book_stale` list holds who is stale now, so a restart in the middle of an outage does not
alert again (alert ids are also fixed by run, bar and symbol, so a replayed cycle is deduplicated
like any alert). The run is never stopped: its order-book Blocks act as their plain counterparts
and candidates carry `book_missing` (§25), as in a backtest with a gap. A run that starts while the
recorder is down gets `book_stale` at its first cycle. Without a recordings directory nothing is
watched, and a document with no order-book Blocks never raises it. Delivery goes through the
usual notifier, so a Bale failure changes no decision.


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
