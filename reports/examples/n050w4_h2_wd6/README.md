# Full high effort 50 nurse example

Case `n050w4_h2_wd6`, repetition 1: 50 nurses, 7 days, 4 working shifts and 4 skill types, requiring 139 minimum nurse-days. This larger history-contrast case and repetition were selected before the final results, not because a variant succeeded or failed. It is not claimed to be the hardest case.

All LLM variants request high reasoning effort with no imposed request or whole-trial timeout. Token caps are 32,000 for roster generation/revision and 16,000 for audit, including thinking tokens. There is no soft objective. The classical witness uses the same input and hard constraints.

| Method | Initial shortage / illegal transitions | Final shortage / illegal transitions | Final hard-valid | Status | Reported thinking tokens |
| --- | --- | --- | --- | --- | --- |
| classical | unavailable | 0 / 0 | True | candidate | not applicable |
| baseline | unavailable | unavailable | False | api_error | unavailable |
| structured | 0 / 0 | 0 / 0 | True | valid_roster | 17,848 |
| critique | unavailable | unavailable | False | incomplete_response | 26,088 |
| combined | 0 / 0 | 0 / 0 | True | valid_roster | 24,427 |

## Full files

- `instance.json`: complete shared input, including initial history and demand.
- Each method directory: final roster, complete independent evaluator report, metadata and readable full roster grid when available.
- Each model stage: exact request, full assembled prompt, complete provider response, unabridged answer/audit, and `thinking.txt` when the provider exposed reasoning text.
- `generation-evaluation-replayed.json`: original candidate independently evaluated after generation/audit/revision had finished; this was not supplied to the model.

Thinking text is the external model's returned reasoning field, not a reconstructed explanation. A separate audit is an explicit additional model output. The stage response preserves usage counters and termination status. If a provider/network failure prevented a response, no missing reasoning or answer is invented. Baseline and critique are separate generations; assess revision effects by comparing original and final outputs within each critique/combined trial.

This export adds no API calls. The full benchmark includes all cases and repetitions; this one example does not estimate success rates.

## Direct links

- **classical:** [roster](classical/roster.json) · [evaluation](classical/evaluation.json)
- **baseline:** [metadata](baseline/metadata.json) · [generation prompt](baseline/generation/full-prompt.txt)
- **structured:** [metadata](structured/metadata.json) · [generation prompt](structured/generation/full-prompt.txt) · [generation thinking](structured/generation/thinking.txt) · [generation answer](structured/generation/output.txt) · [evaluation](structured/evaluation.json)
- **critique:** [metadata](critique/metadata.json) · [generation prompt](critique/generation/full-prompt.txt) · [generation thinking](critique/generation/thinking.txt) · [generation answer](critique/generation/output.txt) · [evaluation](critique/evaluation.json)
- **combined:** [metadata](combined/metadata.json) · [generation prompt](combined/generation/full-prompt.txt) · [generation thinking](combined/generation/thinking.txt) · [generation answer](combined/generation/output.txt) · [critique prompt](combined/critique/full-prompt.txt) · [critique thinking](combined/critique/thinking.txt) · [critique answer](combined/critique/output.txt) · [revision prompt](combined/revision/full-prompt.txt) · [revision thinking](combined/revision/thinking.txt) · [revision answer](combined/revision/output.txt) · [evaluation](combined/evaluation.json)
