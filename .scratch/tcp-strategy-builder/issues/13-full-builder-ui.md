# 13: Full builder UI

**What to build:** The Persian, mobile-first Strategy Builder: a Block palette rendered from parameter schemas, enable/disable, parameter editing with defaults, clone from Template, diff against the parent, versions, import/export as a file, and side-by-side comparison of two strategies on the same data.

**Blocked by:** 12 (TCP Azizpour Template (core))

**Status:** ready-for-agent

- [ ] New Blocks appear in the palette with no UI code changes
- [ ] Diff view lists every changed parameter and Block against the parent version
- [ ] Import rejects invalid files with Persian messages
- [ ] Comparison runs both documents on identical data and shows metrics side by side
- [ ] HTTP tests for each endpoint; mobile screenshot check has no horizontal scroll

Spec: `.scratch/tcp-strategy-builder/spec.md`
