# Confirmed critique repair

Case `n021w4_h2_wd8`, critique repetition 2, high reasoning effort. The initial 147-record roster was complete and schema-valid but missed Thursday Early Trainee coverage: minimum 1, assigned 0. The [audit](audit.txt) independently identified that exact deficit. The model revision changed one assignment:

```json
{"before":{"nurse_id":"TR_20","day":"Thu","shift":"Off","skill":null},"after":{"nurse_id":"TR_20","day":"Thu","shift":"Early","skill":"Trainee"}}
```

The [initial evaluation](initial-evaluation.json) records one missing coverage unit; the [final evaluation](final-evaluation.json) records zero hard violations and `hard_valid=true`. The evaluator ran after all model calls, and its findings were not supplied to the model. This is one observed successful repair, not a general repair-rate guarantee.

Full [input](instance.json), [initial roster](initial-roster.json) and [final roster](final-roster.json) are included. Replay without API calls:

```sh
uv run python -m rostering evaluate --instance reports/examples/critique_repair/instance.json --roster reports/examples/critique_repair/initial-roster.json
uv run python -m rostering evaluate --instance reports/examples/critique_repair/instance.json --roster reports/examples/critique_repair/final-roster.json
```

The first command exits 2 for an invalid roster; the second exits 0.
