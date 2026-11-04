# 19: Trendlines and Fibonacci

**What to build:** Trendlines that activate on the third touch, anchor from the second swing, fit a 200-bar window and respect slope bounds expressed in ATR per bar (degree limits from the source converted and documented); Fibonacci retracements on confirmed pivots after the impulse has ended, on log scale; Fib levels counted only with two other confluence factors; extension targets (1.0, 1.272, 1.618, 2.0); the 0.382 reclaim fakeout setup.

**Blocked by:** 11 (Levels, touches, boxes and breakout confirmation), 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] Trendlines and Fib anchors are causal and pass the gates
- [ ] Slope bounds are scale-free and documented
- [ ] A lone Fib level never produces a candidate
- [ ] Fixtures per rule; Template updated

Spec: `.scratch/tcp-strategy-builder/spec.md`
