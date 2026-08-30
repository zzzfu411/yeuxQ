# Research Trial Registry

`research_trials.jsonl` is the canonical append-only local ledger. Each event
contains the SHA-256 of the previous event and is verified before another event
can be appended.

The `guard-v1-20260716/` directory retains the exact packet, resolved execution
configuration, preregistration payload, and append receipt for sequence 1. The
tracked copies pin the local evidence in the project history once committed;
they are not an external trusted timestamp or a digital signature.

Current boundary:

- `guard-v1-20260716` is research-only and has no result event.
- Its test window starts on `2026-07-17`; `2026-07-15` and `2026-07-16` are embargoed.
- The bound cache prefix lacks promotion-safe import lineage and source QA.
- No strategy execution, paper approval, micro-live approval, or broker action
  is authorized by this registry.

Verify the complete chain with:

```powershell
.\.venv\Scripts\python.exe examples\run_trial_registry.py verify `
  --registry evidence\trial_registry\research_trials.jsonl
```
