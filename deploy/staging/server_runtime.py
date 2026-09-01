"""Load the staging runtime configuration before importing the application."""

import json
import os
from pathlib import Path


def prepare() -> None:
    config_path = Path(
        os.environ.get(
            "SOCIALPILOT_SERVER_CONFIG",
            "/etc/socialpilot-staging/runtime.json",
        )
    )
    data = json.loads(config_path.read_text(encoding="utf-8"))
    for name, value in data.items():
        os.environ[name] = str(value)
    os.environ["SOCIALPILOT_DISABLE_DOTENV"] = "1"


prepare()
