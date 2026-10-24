# Nurse rostering with LLMs

CS4263 Solution B: an LLM generates nurse rosters directly from standardised INRC2 inputs. The pipeline compares a single-shot baseline with structured output, bounded LLM critique/revision, and both safeguards together. An independent evaluator checks the resulting rosters afterwards.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run these commands from this repository's root:

```sh
uv sync --locked
```

This creates `.venv` using Python 3.13 and installs the locked dependencies. Commands below use `uv run`, so activating the environment is optional.

For live model requests, provide the API key through your shell:

```sh
export SOCLAAS_API_KEY="your-api-key"
```

The non-secret settings are in `config/llm.json`: SoCLaas, model `x-test-2` (locally labelled DeepSeek V4.1 Flash 1017), Chat Completions, and requested reasoning effort `none`. Change that file to configure the endpoint or model. The project reads the named environment variable directly; it does not load `.env` files or read Codex credentials.

Conversion, offline evaluation, dry runs and tests need no API key. Live runs use the configured provider account.

## Repository layout

| Path | Purpose |
| --- | --- |
| `nurse_llm/` | Input conversion, API client, prompts, safeguards, evaluation and batch execution. |
| `schemas/` | Versioned input and output JSON contracts. |
| `prompts/baseline.txt` | Shared generation prompt used by all four variants. |
| `config/llm.json` | Non-secret provider/model settings. |
| `config/experiments/` | The two plans used for the completed experiment. |
| `inrc2/` | Original scenario/history/week inputs and three evaluation references. |
| `data/instances/` | Standardised five-nurse JSON example. |
| `scripts/summarize_ablation.py` | Verify and merge newly generated matched suites into reports. |
| `tests/` | Offline regression checks for the included pipeline and reporting code. |
| `docs/` | Shared input specification and safeguard methodology. |
| `reports/` | Portable summary and per-trial metrics from the completed pilot. |
| `outputs/` | Generated local run artifacts; created on demand and ignored by Git. |

## Standardise INRC2 inputs

The included example is `data/instances/n005w4_h0_wd1.json`: five nurses, initial history 0, and week-data variant 1, scheduled over Monday–Sunday. A WD suffix identifies a data variant, not a chronological week number.

Convert another combination:

```sh
uv run python -m nurse_llm convert \
  --scenario-dir inrc2/n005w4 \
  --history 0 \
  --week-data 4 \
  --out outputs/instances/n005w4_h0_wd4.json
```

The converter preserves nurses, qualifications, contracts, forbidden successions, minimum/preferred coverage, requests, history and source hashes. It rejects inconsistent inputs and refuses to overwrite an existing converted file. See [the shared input contract](docs/input_contract.md) for the interface proposed for Solutions A and B.

## Generate and evaluate one roster

Inspect the saved prompt/request without calling the model:

```sh
uv run python -m nurse_llm run \
  --instance data/instances/n005w4_h0_wd1.json \
  --dry-run
```

Generate a baseline roster and independently evaluate it:

```sh
uv run python -m nurse_llm run \
  --instance data/instances/n005w4_h0_wd1.json \
  --variant baseline
```

| Variant | Behaviour | Maximum calls per trial |
| --- | --- | --- |
| `baseline` | Prompt requests JSON; no response-format parameter. | 1 |
| `structured` | Same prompt plus a case-specific generation schema. | 1 |
| `critique` | Generation, one LLM audit, one LLM revision. | 3 |
| `combined` | Structured generation, audit, structured revision. | 3 |

Select another variant with `--variant structured`, `--variant critique`, or `--variant combined`. Generation/revision have a default output cap of 16,000 tokens, and the audit cap is 8,000. The timeout is 240 seconds per request. Use `--max-output-tokens` and `--timeout` to adjust generation settings.

Each invocation prints a unique run directory under `outputs/`. It contains the input, prompt, exact requests, raw responses, parsed roster, evaluation, dependency lock and metadata. Each model stage is retained under `stages/`. Metadata records the requested/returned model, settings, token usage, latency, source hashes and call count. No automatic retries are performed, and no deterministic evaluator feedback is given to the model.

Exit code 0 means a hard-valid roster or successful dry run; 2 means a recorded model run without a hard-valid roster; 1 means an input/setup/API failure. An invalid roster is an experimental outcome and is retained.

Evaluate a saved JSON roster without another API call:

```sh
uv run python -m nurse_llm evaluate \
  --instance data/instances/n005w4_h0_wd1.json \
  --roster outputs/YOUR_RUN/roster.json
```

Check the supplied five-nurse reference offline:

```sh
uv run python -m nurse_llm evaluate \
  --instance data/instances/n005w4_h0_wd1.json \
  --reference inrc2/n005w4/Solution_H_0-WD_1-2-3-3/Sol-n005w4-1-0.txt
```

## Repeat the experiment

The experiment uses five cases and three independent repetitions per case. Run the baseline plan first, then the safeguard plan:

```sh
uv run python -m nurse_llm.batch \
  --plan config/experiments/pilot_baseline_v1.json

uv run python -m nurse_llm.batch \
  --plan config/experiments/pilot_safeguards_v1.json
```

These are live experiments: 15 baseline trials plus 45 safeguard trials, up to 120 model requests in total. Each suite uses two workers and writes its own directory under `outputs/experiments/`, including a frozen manifest, input copies, raw trials and summaries. Repetitions are separate calls, not deterministic model seeds. Copy the two suite paths printed by the commands into:

```sh
uv run python scripts/summarize_ablation.py \
  --baseline outputs/experiments/YOUR_BASELINE_SUITE \
  --safeguards outputs/experiments/YOUR_SAFEGUARD_SUITE \
  --out outputs/reports/new_pilot
```

The summarizer makes no API requests. It checks matching configurations and input/prompt fingerprints, re-evaluates saved outputs, and writes Markdown, JSON and CSV reports. Keep new reports under `outputs/` to preserve the included historical pilot summary.

## Evaluation scope and recorded results

Hard validity requires a complete roster, valid identifiers, at most one shift per nurse-day, minimum coverage, qualified skills and legal transitions, including history into Monday. Soft scoring covers preferred coverage, shift-off requests and complete weekends only. Consecutive-day and full-horizon penalties are retained in the input but are not scored; this is a one-week pilot, not full INRC2 evaluation. History is not advanced automatically.

The completed pilot had 60 trials and no hard-valid rosters. All 45 constrained generation/revision stages matched the generation-schema subset, which did not ensure full contract validity or scheduling correctness. See [the results report](reports/pilot_chat_v1.md) and [safeguard methodology](docs/safeguards.md).

The included reports contain portable archive identifiers and metrics. Original raw API traces and development attempts remain in the previous workspace archive and are excluded from this repository. The earlier successful Responses development run used a different configuration/case and is excluded from the matched experiment.

## Offline tests and optional provider check

```sh
uv run python -m unittest discover -s tests -v
```

The regression suite exercises conversion, constraint checking, safeguards, API error handling and reporting without live model calls.

The capability probe used to check provider schema behaviour is also retained:

```sh
uv run python -m nurse_llm.probe
```

It makes four small live API requests. Chat Completions followed the valid schema probe, while Responses ignored it; the gateway accepted an invalid schema, so full strict enforcement is not established. Recheck if the provider changes.
