# 19: Trendlines and Fibonacci

**What to build:** Trendlines that activate on the third touch, anchor from the second swing, fit a 200-bar window and respect slope bounds expressed in ATR per bar (degree limits from the source converted and documented); Fibonacci retracements on confirmed pivots after the impulse has ended, on log scale; Fib levels counted only with two other confluence factors; extension targets (1.0, 1.272, 1.618, 2.0); the 0.382 reclaim fakeout setup.

**Blocked by:** 11 (Levels, touches, boxes and breakout confirmation), 12 (TCP Azizpour Template (core))

**Status:** resolved

- [x] Trendlines and Fib anchors are causal and pass the gates
- [x] Slope bounds are scale-free and documented
- [x] A lone Fib level never produces a candidate
- [x] Fixtures per rule; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`

## Resolution

`strategy/trendlines.py` (`trendline_bounce`, `trendline_break`; third-touch activation, second-swing anchor, 200-bar window, slope bounds in ATR per bar with `degrees_to_atr_per_bar`), `strategy/fibonacci.py` (`fib_reclaim`, `fib_confluence`; log-scale legs on confirmed swings, retracements, extensions, confluence with a level / SMA 25 / SMA 99), `profit_chain` option `fib_target` (1.0 / 1.272 / 1.618 / 2.0), Template rows (disabled), ADR 10 §23. Notes: 20-60 degrees map to 0.073-0.346 ATR per bar on a documented reference chart; the order-book wall factor waits for ticket 21; of the three "reaction" confirmations only the confirmed swing is built; the "Fib 1.618 without momentum" exhaustion exit is not.
