# Validation records

These files record numerical restart comparisons, solver logs, typed checkpoint
reads and negative checks. `RESULTS.json` lists the configurations and outcomes.

Machine-specific test paths and hostnames have been normalized to
`/validation/runs/...`, `/validation/toolkit` and `validation-host` for portability.
Trailing whitespace in logs is normalized. Numerical results, solver identities
and field/input hashes are unchanged.
The saved `*-native-plan.json` files are provenance records, not runnable case
configurations. Use `selftest.py` to generate new cases and validation records.
