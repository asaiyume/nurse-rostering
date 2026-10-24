# Ready-to-use inputs

Both solutions load these JSON files directly. No conversion is needed.

| File | Use |
| --- | --- |
| [n005w4/h0_wd1.json](n005w4/h0_wd1.json) | Starter/development case |
| [n005w4/h0_wd0.json](n005w4/h0_wd0.json) | Experiment case |
| [n005w4/h0_wd4.json](n005w4/h0_wd4.json) | Experiment case |
| [n005w4/h1_wd5.json](n005w4/h1_wd5.json) | Experiment case |
| [n005w4/h2_wd6.json](n005w4/h2_wd6.json) | Experiment case |
| [n005w4/h2_wd9.json](n005w4/h2_wd9.json) | Experiment case |

Each file contains five nurses over Monday–Sunday, following the [shared contract](../docs/input_contract.md). `h` is the initial-history variant; `wd` is the weekly-data variant.

```python
import json
from pathlib import Path

instance = json.loads(Path("converted/n005w4/h0_wd1.json").read_text())
```

The converter is retained in `rostering/inrc2.py` and available through `python -m rostering convert`. Raw inputs and hashes are recorded inside every converted file.
