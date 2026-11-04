# 03: Fractional exit steps

**What to build:** A position can close in steps: a list of (R multiple, fraction) exits plus a remainder rule, with fractions summing to 1 and total initial risk equal to the approved risk. The current tp1/runner pair is expressed as one such list, so NNFX results do not change.

**Blocked by:** 02 (Pending stop-market orders)

**Status:** ready-for-agent

- [ ] A position carries an exit plan of R-multiple steps and fractions that must sum to 1 (validated)
- [ ] Each step closes its fraction of the original size when price reaches its R level
- [ ] Hooks exist for a conditional breakeven move and for a trailing rule on the remainder
- [ ] NNFX's two-leg behaviour is reproduced exactly through the new exit plan (reference run unchanged)

Spec: `.scratch/tcp-strategy-builder/spec.md`
