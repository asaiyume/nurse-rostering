# Nurse Rostering

CS4263: compare **Solution A (classical CSP)** and **Solution B (LLM)** on the same INRC2 inputs, roster format and evaluator. Both solutions are implemented independently.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from this directory:

```sh
uv sync --locked
```

Python 3.13 and dependencies are managed by uv. Only live LLM runs need a key:

```sh
export SOCLAAS_API_KEY="your-api-key"
```

Provider/model settings are in `config/llm.json`; `.env` files are not loaded automatically.

## Layout

- `rostering/`: shared conversion, contracts, evaluation and JSON utilities.
- `rostering/classical/`: Solution A, a feasibility-only CSP solver.
- `rostering/llm/`: Solution B, safeguards and batch runner.
- `schemas/`, `converted/`, `inrc2/`: shared formats and inputs.
- `config/`, `prompts/`: LLM settings and experiment plans.
- `scripts/`, `tests/`, `reports/`: reporting, offline checks and recorded results.

## Shared input and evaluation

Both solutions can load the ready-made JSON files in [`converted/`](converted/README.md): all 690 combinations across 23 scenarios. [`converted/index.csv`](converted/index.csv) lists the files; the batch plans already use them directly.

```sh
uv run python -m rostering evaluate --instance converted/n005w4/h0_wd1.json --roster outputs/ROSTER.json
```

Each solution exports one record per nurse-day, including Off. Follow the [shared contract](docs/input_contract.md) and keep solver-specific metadata separate.

Rebuild the complete set with `uv run python scripts/convert_dataset.py`. For one new case: `uv run python -m rostering convert --history 0 --week-data 4 --out outputs/instances/h0_wd4.json`.

## Solution A

```sh
uv run python -m rostering.classical --instance converted/n005w4/h0_wd1.json --out outputs/classical/roster.json
uv run python -m rostering evaluate --instance converted/n005w4/h0_wd1.json --roster outputs/classical/roster.json
```

The solver uses required staffing slots as variables, qualified nurses as values, and depth-first backtracking with MRV, degree tie-break and LCV. Specialized AC-3, global capacity checks, identical-slot symmetry breaking and bitset domains reduce search. It enforces minimum coverage, qualified skills, single daily assignments and legal shift transitions, including history into Monday. Unused nurse-days are Off.

Defaults: stop at the first valid roster, with a 240-second search limit. Use `--time-limit SECONDS` to change the limit or `--exhaustive` to disable it. The roster is independently evaluated before return; runtime, search statistics and proof flags are saved separately in `roster.metadata.json`. A timeout returns `unknown`; exhaustive failure proves infeasibility. Soft penalties are not optimized, and no soft-cost optimality is claimed.

Run cases from the smallest scenario folders, or run all 690 inputs:

```sh
uv run python scripts/run_classical.py --folders 10 --cases-per-folder 30 --workers 4 --time-limit 420
uv run python scripts/run_classical.py --folders 23 --cases-per-folder 30 --workers 4 --time-limit 420
```

Runner defaults: 10 folders, 30 cases per folder, 4 workers and 420 seconds per case. Folders are selected by nurse count, then horizon; `--list-only` previews selection. Each run preserves previous outputs under `outputs/classical/runs/`, saving per-case rosters, metadata and evaluations, plus CSV/JSON summaries. The final summary reports correctness (hard-valid cases / cases tested), failed or unresolved cases, and shortest/longest recorded runtimes. Reported soft scores are diagnostic only.

## Solution B

```sh
uv run python -m rostering llm --instance converted/n005w4/h0_wd1.json --dry-run
uv run python -m rostering llm --instance converted/n005w4/h0_wd1.json --variant baseline
```

Variants: `baseline`, `structured`, `critique`, `combined`. A baseline/structured trial makes one call; critique/combined makes up to three. Defaults: 16,000 generation tokens, 8,000 audit tokens, 240 seconds per request. Outputs are saved under ignored `outputs/`.

Repeat the recorded experiment (15 baseline + 45 safeguard trials; up to 120 calls):

```sh
uv run python -m rostering.llm.batch --plan config/experiments/pilot_baseline_v1.json
uv run python -m rostering.llm.batch --plan config/experiments/pilot_safeguards_v1.json
uv run python scripts/summarize_ablation.py --baseline outputs/experiments/BASELINE_SUITE --safeguards outputs/experiments/SAFEGUARD_SUITE --out outputs/reports/pilot
```

See [safeguards](docs/safeguards.md) and [recorded results](reports/pilot_chat_v1.md). The 60-trial pilot produced no hard-valid rosters; raw historical traces remain in the previous workspace archive.

## Checks and scope

```sh
uv run python -m unittest discover -s tests -v
```

Tests, conversion, evaluation and dry runs are offline. Optional live provider check: `uv run python -m rostering.llm.probe` (four small calls).

This is a one-week pilot. Both solutions use the same four hard constraint categories and the shared evaluator reports three soft penalties: preferred coverage, requests and complete weekends. Solution A searches only for hard-constraint feasibility; Solution B's current prompt additionally requests soft-cost minimization. Their objectives therefore differ, and soft scores are not an equivalent-objective optimization comparison. Full-horizon scoring and automatic history advancement are not implemented. Exit codes: 0 valid/dry run, 2 evaluated but invalid/unresolved, 1 setup/API error.
