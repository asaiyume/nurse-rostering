# Solution A

Place the classical solver here; it is not implemented yet.

1. Load a ready-made JSON from `converted/n005w4/`, also used by Solution B.
2. Return the shared roster JSON: one record per nurse-day, including Off.
3. Save runtime, search statistics and proof/optimality information separately.
4. Evaluate the roster with `python -m rostering evaluate`.

Use `rostering.contracts`, `rostering.inrc2`, `rostering.evaluate` and `rostering.io` as the shared interface. Match the agreed constraints and objective in [the contract](../../docs/input_contract.md).
