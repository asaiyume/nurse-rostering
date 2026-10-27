# Solution A

The feasibility-only CSP solver is implemented in `__main__.py`. See the
[Solution A instructions](../../README.md#solution-a) for single-case execution,
validation, batch runs, time limits and output summaries.

1. Load any ready-made JSON under `converted/`, also used by Solution B; `converted/index.csv` lists all cases.
2. Return the shared roster JSON: one record per nurse-day, including Off.
3. Save runtime, search statistics and proof/optimality information separately.
4. Evaluate the roster with `python -m rostering evaluate`.

Uses the shared input/output contracts and evaluator. The four hard constraint
categories match [the contract](../../docs/input_contract.md); soft penalties
are diagnostic only and are not optimized by Solution A.
