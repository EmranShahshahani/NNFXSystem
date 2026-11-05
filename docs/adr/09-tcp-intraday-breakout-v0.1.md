# ADR 09 - Trade City Pro hypotheses: intraday bars, a second engine, pending orders

Status: accepted, 2026-11-01. Pre-registration: `research/tcp_prereg.frozen.json`.
Evidence: `docs/research/ستاپ های تلگرام ترید سیتی پرو.md`, rule ledger `research/tcp_rules.yaml`.

## Context

The NNFX platform (ADRs 01-08) is daily-bar only, enters at the next open with
market orders, and manages two legs (TP1 + runner). The Trade City Pro (TCP)
methods to be tested need hourly bars, stop-entry orders that may never fill,
up to three partial exits, tiered risk and daily loss limits. The NNFX engine
must not change behaviour while this is added.

## Decisions

1. **Two hypotheses, frozen before data.** H2021 (education-era two-trigger
   system) and H2026 (current trigger-breakout method) are separate
   hypotheses with their own budgets (20 and 32 trials) plus a shared
   risk-layer budget (8). Total 60. The budget is enforced from
   `research/trials.jsonl` by stage prefix (`H2021/...`, `H2026/...`,
   `risk_layer/...`) via `nnfx.research.prereg`. Anything added after a result
   is seen is a new hypothesis with a new file.
2. **Second engine, same contract.** `Tcp2021Engine` and `Tcp2026Engine` sit
   beside `StrategyEngine` and expose the same pure
   `decide(history, open_positions, account_state, config, state)`. The
   harness loop, journal, broker and risk manager are shared. NNFX outputs
   must stay byte-identical (the committed reference run is the check).
3. **Sub-daily bars.** H1 is the base bar, labelled by close in UTC. 4H and
   1D for higher-timeframe context are resampled from H1 in the data layer,
   never fetched separately, so all timeframes agree. The daily session close
   for crypto stays 00:00 UTC.
4. **Pending orders.** New intents: `PendingOrderIntent` (stop or limit,
   expiry in bars, optional OCO group) and `CancelIntent`. Fills: stop orders
   fill at max(trigger, open) for longs (gaps at the open); within a bar, if a
   stop-loss and a target are both touched, the stop is assumed first.
   *Amendment (Strategy Builder ticket 02).* Built: stop-market orders only
   (`PendingOrderIntent`, `CancelIntent`); limit orders are deferred until a
   Block needs one. Naming follows the glossary: the order rests at the
   **Trigger** = level + direction x buffer. Further rules fixed here:
   (a) entries trigger on last price, stops keep `stop_trigger_price`;
   (b) stop and target are absolute, so a gap fill beyond the Trigger takes
   more than the approved risk; R is still measured against the approved
   (planned) risk, which charges the gap to the strategy as a real loss;
   (c) in one bar, orders that gapped through at the open fill before
   orders reached intrabar, and within each group the earlier-placed order
   fills first (a bar cannot tell which intrabar level came first);
   (d) a close strictly beyond the invalidation price, or `expires_after_bars`
   rested bars, cancels at that bar's close, after the fill attempt;
   (e) resting orders count against the risk manager's exposure caps and the
   Strategy Document open-risk cap (done in ticket 06).
5. **Legs generalise to fractions.** A position is a list of exit fractions
   (e.g. 0.30 at 2R with breakeven, 0.40 at 5R, 0.10 runner, remainder at the
   runner rule). Fractions must sum to 1; total initial risk equals the
   approved risk. The existing tp1/runner pair is the special case
   [0.5 at TP1, 0.5 runner].
   *Amendment (Strategy Builder ticket 03).* Built as `ExitPlan`: steps of
   (R multiple, fraction of the **original** size, optional `stop_to_r`) plus
   a Runner fraction; they must sum to 1, R levels must increase, and
   `stop_to_r` must sit below its step's R. Rules fixed here:
   (a) R is the planned stop distance, measured from the planned entry: the
   Trigger for a pending order (so steps, like its absolute stop, do not move
   on a gap fill), the fill for a market order;
   (b) the open fills every step it gapped through, at the open, in order;
   intrabar steps fill in order at their price, with the stop checked first;
   (c) when a filled step tightens the stop and the same bar reaches the new
   stop, the rest is stopped there (conservative);
   (d) step sizes round down to the instrument's `size_step`; the last step
   or the stop takes what is left. NNFX's single target keeps closing its
   exact fraction, because its frozen results depend on it;
   (e) a target change that would pass the next step is refused;
   (f) hooks: `stop_to_r` is the unconditional stop move; conditional
   breakeven and trailing the Runner are engine rules sent as `ModifyIntent`
   after reading `PositionView.steps_filled`.
   NNFX legs map onto plans: tp1 = one full step, combined = 0.5 step +
   0.5 Runner, runner/single = empty plan; the hedged pair stays two
   positions. All six NNFX leg shapes reproduce byte-identical backtests.
6. *Superseded for Strategy Documents by ADR 10 §10 (ticket 06):* tiers,
   governors and loss limits live in the document's risk governor, not the
   risk manager; the daily limit halts for 24 h from the breach (the
   blueprint's wording) rather than resetting at 00:00 UTC. The risk manager
   keeps its portfolio caps, which now include resting orders.
   **Risk manager extensions.** Tiered risk from flags, a shared open-risk
   budget that releases positions at breakeven, max open positions, a daily
   loss limit reset at 00:00 UTC, and cooldowns. Every rejection is journaled
   with its reason.
7. **Screening gates redefined for these engines.** Gates 1, 2 and 5 are
   unchanged. Gate 3 uses the pre-registered trades-per-month band for the
   whole universe instead of 6-50 signals per instrument-year. Gate 4 checks
   filter-vs-trigger agreement (volume, RSI, Dow) with the same 0.15-0.60
   band on development data only.
8. **Holdout honesty.** The crypto holdout (2025-2026) overlaps the posts the
   H2026 rules were read from; its verdict must state this. Forward paper
   trading from the freeze date is H2026's real holdout. H2021's rules predate
   2022, so its 2022-2026 results are genuinely out of sample.
9. **Call replay is an audit, not a trial.** Replaying the 941 published calls
   follows `research/tcp_callreplay.frozen.json`; calls from 2025 onward stay
   sealed until the holdout is touched.

## Consequences

* New code is additive: a second engine family, new intents, a generalised
  leg model and risk-manager options, all off for NNFX configs.
* The 15 frozen verdict criteria apply unchanged. Criterion 10 (costs x1.5)
  is expected to be the hardest for stop entries with tight stops.
* Discretionary TCP rules (ledger type `discretionary`) are not coded.
