# Screening gates

All five gates run before any performance test and consult no performance data
(doc 05 §2). Gates 1 and 2 run automatically across every registered indicator
(`nnfx screen`, `nnfx.research.lookahead.run_gate_1_2`); there is no
per-indicator test to write.

## Gate 1 - no lookahead

Each indicator is recomputed on history truncated at bar *t* and its tail values
are compared with the full-history computation. Any difference fails the gate,
which names the indicator and the first bar at which values diverge. The gate
runs against the exact implementation that ships, never against an indicator's
reputation: repainting is an implementation property.

Families needing extra scrutiny:

- centred or displaced smoothing (centred moving averages, forward-displaced spans)
- zig-zag and pivot logic (a pivot is only known N bars after it forms)
- swing high/low reconstruction
- non-causal DSP filters (zero-phase / filtfilt forms, some published Ehlers variants)

`tests/test_indicators.py::CentredMA` is a deliberately repainting fixture and is
asserted to fail.

## Gate 2 - determinism

Same input, same output: across repeated runs, across a fresh instance, and
across a process restart (a subprocess recomputes digests). Cross-machine:
`nnfx determinism` reproduces the committed reference run in
`tests/golden/reference_run.json`. A mismatch whose environment fingerprint
differs from the reference is reported as **ENVIRONMENT MISMATCH** (run
`uv sync --frozen`), not as a determinism failure.

## Gate 3 - C1 signal frequency

6 to 50 signals per instrument-year; 12 to 35 reported as the target zone.

## Gate 4 - C1/C2 independence

`0.15 <= rho <= 0.60` on pooled `state` series, development segment only. For two
+/-1 series, **rho = 2 x agreement - 1**: rho 0.60 is 80% agreement (C2 is
decoration above it), rho 0.15 is 57.5% agreement (C2 is a near-random filter
below it). Negative rho rejects immediately.

## Gate 5 - parameterisation

Parameters are exposed as a grid, and outputs are price-scale invariant:
multiplying every price by 1000 must leave `signal`/`state`/`gate`/`exit`
unchanged and scale `line`/`value` exactly. Absolute thresholds are re-expressed
in ATR or percentage terms (e.g. the Waddah Attar dead zone is `deadzone_atr x ATR`).
