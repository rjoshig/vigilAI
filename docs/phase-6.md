# Phase 6 — Hardening and in-house fit

**Status:** ⬜ **not started**. **Goal:** production readiness on the internal network and adaptation
of the parsers to the real file layouts, which are only available in-house. Effort ~2
weeks. Depends on Phases 3–5.

## Scope · ⬜ not started

**Privacy and security** (`llm-privacy.md`, `design.md` "Security and PII") · ⬜ not started
- [ ] Masking: the masked-column list populated from the real DIRT layout; a PII regex
      tripwire on every assembled prompt (fail closed, logged as a finding on the run).
- [ ] `audit_log` complete: every report view, download, review decision, requirement edit,
      rerun reason.
- [ ] Log review: ids and counts only; `LLM_LOG_PROMPTS` forced false outside dev.
- [ ] Upload hardening: size limits, content-type checks, macros ignored, path safety on
      the volume.
- [ ] TLS at the reverse proxy; encrypted volumes — with the in-house platform team.

**Retention** · ⬜ not started
- [ ] Nightly purge task: runs past `expires_at` + files + rules/findings/stats;
      aggregated usage kept; `scripts/purge.py --dry-run`.
- [ ] Decision on a shorter window for DIRT files (open question).

**In-house fit** · ⬜ not started
- [ ] Adapt `parsers/` implementations to the real OSL template, config style, and each
      report layout, on a machine that never pushes real files. Keep the Protocols; add a
      synthetic fixture that mirrors each real layout's *shape*.
- [ ] Point the adapter at the in-house model / gateway; enable guided JSON decoding if
      the serving stack supports it; re-run the golden set and record accuracy.
- [ ] Seed `attribute_aliases` from the data dictionary if one exists.

**Scale** · ⬜ not started
- [ ] Load test at ~80 concurrent users and a queue of real-sized runs; tune worker
      replicas × `LLM_MAX_CONCURRENCY`; confirm the 5–15 min per-run estimate.
- [ ] Per-order-number queue cap verified.

## Acceptance criteria · ⬜ not started

1. [ ] A real OSL / config / report set runs end to end in-house with the pipeline unchanged
   except parser implementations and prompt examples.
2. [ ] Golden-set accuracy on the in-house model recorded in `docs/benchmarks/`.
3. [ ] Security / compliance sign-off on retention and PII handling recorded as an ADR.
4. [ ] Load test results recorded; the deployment checklist in `deployment.md` all ticked.
