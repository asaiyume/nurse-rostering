# Ready-to-use inputs

All **690 inputs** are included: 23 scenario families × 3 initial histories × 10 weekly-data variants. Both solutions load the JSON directly. Browse [index.csv](index.csv) to choose a case.

Files follow `converted/<scenario>/h<history>_wd<variant>.json`, for example [n005w4/h0_wd1.json](n005w4/h0_wd1.json).

Each JSON schedules Monday–Sunday at week 0 using the selected initial history. The scenario retains its original four/eight-week horizon; `wd` identifies a data variant, not a chronological week. Source paths, hashes and declared scenario IDs are preserved, including `n021w4_2` inside the `n021w4` folder.

```python
import json
from pathlib import Path

instance = json.loads(Path("converted/n005w4/h0_wd1.json").read_text())
```

Rebuild the dataset with `uv run python scripts/convert_dataset.py`. Existing identical conversions are retained; conflicting files are not overwritten. See [the shared contract](../docs/input_contract.md).
