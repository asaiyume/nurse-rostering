# Nurse Rostering

CS4263: compare **Solution A (classical CSP)** and **Solution B (LLM)** on the same INRC2 inputs, roster format and evaluator. Solution B is implemented; Solution A has a reserved module for Jevan.

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
- `rostering/classical/`: Solution A implementation location.
- `rostering/llm/`: Solution B, safeguards and batch runner.
- `schemas/`, `converted/`, `inrc2/`: shared formats and inputs.
- `config/`, `prompts/`: LLM settings and experiment plans.
- `scripts/`, `tests/`, `reports/`: reporting, offline checks and recorded results.

## Shared input and evaluation

Both solutions can load the ready-made JSON files in [`converted/`](converted/README.md). The folder includes the starter case and all five experiment cases; the batch plans use these files directly.

```sh
uv run python -m rostering evaluate --instance converted/n005w4/h0_wd1.json --roster outputs/ROSTER.json
```

Each solution exports one record per nurse-day, including Off. Follow the [shared contract](docs/input_contract.md) and keep solver-specific metadata separate.

The converter remains available for new cases: `uv run python -m rostering convert --history 0 --week-data 4 --out outputs/instances/h0_wd4.json`.

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

This is a one-week pilot. Both solutions must use the same four hard constraint categories and three soft penalties: preferred coverage, requests and complete weekends. Full-horizon scoring and automatic history advancement are not implemented. Exit codes: 0 valid/dry run, 2 evaluated but invalid/unresolved, 1 setup/API error.
