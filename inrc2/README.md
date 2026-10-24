# INRC2 benchmark inputs

This directory retains the supplied INRC2 inputs for all 23 scenario families:

- `Sc-*.txt`: scenario, shift, skill, contract and nurse definitions.
- `H0-*.txt`: three initial histories per scenario.
- `WD-*.txt`: ten weekly data variants per scenario.

It also retains three supplied first-week reference rosters in `n005w4/`: H0/WD1 for offline regression checks, and H1/WD5 plus H2/WD6 for feasibility-witness validation in the experiment plans. References are used only for evaluation and never supplied to generation prompts.

Unused full solution sequences, converted scheduling-format files and validator printouts are excluded. Original input bytes are preserved through `.gitattributes` so source hashes remain reproducible across checkouts.

Dataset format and constraint definitions: [Second International Nurse Rostering Competition problem description](https://arxiv.org/html/1501.04177v1). These are supplied third-party benchmark files; the project does not claim authorship of them.
