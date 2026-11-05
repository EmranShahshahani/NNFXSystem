# 08: Pre-Trade Checklist and candidate journal

**What to build:** For every Setup Candidate the user sees the Pre-Trade Checklist: each Context and Confirmation check with pass, fail or not-applicable, its weight, hard-fail flags, the Confluence Score, the resulting Risk Tier and why an order was or was not placed. Stops are labelled justified (setup passed the checklist) or unjustified.

**Blocked by:** 05 (Strategy Document tracer bullet)

**Status:** resolved

- [x] Each candidate's journal record lists every check with outcome and reason
- [x] The UI shows the checklist and the decision path (level test -> volume -> RSI -> trigger -> management) per candidate
- [x] Not-applicable checks (e.g. missing data) are shown as such and never counted as passes
- [x] Justified vs unjustified stop label on every losing trade
- [x] API and UI tests read a candidate's checklist

Spec: `.scratch/tcp-strategy-builder/spec.md`
