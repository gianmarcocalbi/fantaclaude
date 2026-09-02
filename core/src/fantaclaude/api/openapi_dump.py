"""Write the API's OpenAPI document (no server needed): `poe types` feeds it
to openapi-typescript so the dashboard's types are generated from the same
pydantic models FastAPI serves — the spec's "types are generated, not
hand-written"."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fantaclaude.api.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(create_app(None).openapi()), encoding="utf-8")


if __name__ == "__main__":
    main()
