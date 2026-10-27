# Matched benchmark selection

This fixed 15-case subset covers five nurse counts and controlled changes in history and weekly demand. The plan was fixed from input metadata before LLM evaluation; all selected cases are reported. It is a purposive sample, not a statistically representative sample of all 690 inputs.

## Design

Each nurse-count stratum contains three cases: an anchor, a history contrast with identical weekly coverage and a different initial history, and a demand contrast with the anchor history held fixed. All H0/H1/H2 labels occur five times overall. History contrasts were checked to change eligibility for actually required Monday shifts; nominally different histories with identical relevant shifts are avoided.

Rank WD0–WD9 within each family by total minimum staff-days, peak daily minimum and WD number. The anchor uses rank 5/10 (lower median); the demand contrast alternates highest/lowest total loading across sizes. These are loading labels, not claims about empirical difficulty or feasibility.

| Scenario | Nurses | Anchor | History contrast | Demand contrast | Weekly minimum staff-days: anchor → demand |
| --- | --- | --- | --- | --- | --- |
| n005w4 | 5 | H0/WD6 | H1/WD6 | H0/WD4 (higher) | 23 → 26 |
| n012w8 | 12 | H1/WD1 | H2/WD1 | H1/WD4 (lower) | 48 → 43 |
| n021w4 | 21 | H2/WD8 | H0/WD8 | H2/WD2 (higher) | 63 → 67 |
| n035w4 | 35 | H0/WD7 | H2/WD7 | H0/WD2 (lower) | 89 → 86 |
| n050w4 | 50 | H1/WD6 | H2/WD6 | H1/WD5 (higher) | 139 → 149 |

## Interpretation and parity

All cases cover Monday–Sunday at week zero. H0/H1/H2 are alternative initial histories, not consecutive weeks. WD numbers identify alternative weekly demand files, not chronological weeks. The n012w8 source has an eight-week horizon label; only its first weekly input is used. No conclusion about long-horizon drift or multiweek scheduling follows.

Only history last_shift affects the current feasibility task. The rest of the history and contract fields remain in the common input for compatibility, without creating extra constraints. Demand contrasts alter the pattern as well as the total loading. Nurse count also changes with shift/skill mix (two skills in the small scenarios, four in the larger ones), so this design does not isolate a causal effect of nurse count.

Solution A searches required staffing slots and turns unused nurse-days into Off. This is an internal feasibility-preserving reduction: surplus assignments can be removed without breaking minimum coverage or creating a forbidden transition because Off breaks successions. It is not an extra rule imposed on B; the shared evaluator accepts legal surplus staffing from either method. This argument depends on the agreed hard-only scope and would need revisiting if workload or consecutive-day constraints were added.

Classical and LLM methods receive the exact same file for each case, with SHA-256 fingerprints frozen in the plan. Both use the same evaluator and hard-only objective. A runs once per input; B runs all four variants three times per input (180 trials, at most 360 calls). Validity is per attempt, not best-of-three. All failures, incomplete outputs and abstentions remain in the denominator. A establishes feasible witnesses or infeasibility proofs when it resolves a case; a timeout remains unknown. Cases are not filtered after those outcomes.

The full benchmark includes one controlled history comparison and one controlled demand comparison per nurse-count stratum. It cannot estimate independent effects of every history, demand variant and nurse count; that would require a larger factorial design.

## Model settings and interpretation

All four LLM variants request high reasoning effort, provider-default temperature and no model sampling seed. The fixed token limits are 32,000 for generation/revision and 16,000 for auditing, including reasoning tokens. No client or whole-trial deadline is imposed on B, and A runs without a search deadline. Token limits still bound generated reasoning and answers. Provider/network failures are unresolved attempts, not evidence of infeasibility. Provider load, prompt caching and network latency are not controlled; timing results describe this run and are not pure CPU-time comparisons.

All jobs are shuffled using scheduling seed 4263. This seed controls job ordering, not model sampling.

Tables distinguish 15 unique input cases from the 45 trials per LLM variant (three repetitions on each input). Live progress tables contain only completed trials and must not be interpreted as final comparisons.

## Execution environment

The classical solver and local orchestration run on an Apple M3 Pro with 18 GiB RAM, using Python 3.13.14. The LLM is served remotely by SoCLaas; its server hardware is not specified. Classical timings cover its solver work and internal validation, while LLM runtime also includes local request/artifact processing, the remote service and network time. These are observed application runtimes, not equal-hardware CPU benchmarks.
