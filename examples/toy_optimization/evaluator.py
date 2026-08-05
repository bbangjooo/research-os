#!/usr/bin/env python3
"""Protected deterministic evaluator for the optimization example."""

import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1]).resolve()
project = Path(__file__).resolve().parent
x = float(json.loads((workspace / "parameter.json").read_text())["x"])
target = float(json.loads((project / "data" / "target.json").read_text())["target"])
loss = (x - target) ** 2
out = workspace / "outputs"
out.mkdir(exist_ok=True)
(out / "result.json").write_text(
    json.dumps(
        {
            "metrics": {"loss": loss, "distance": abs(x - target)},
            "constraints": [],
            "resource_usage": {"evaluations": 1},
        },
        sort_keys=True,
    )
    + "\n"
)
