"""Write the API's OpenAPI schema to packages/api-client/openapi.json (no server needed).

Run: uv run python -m scripts.export_openapi   (or `just gen-client`, which also regenerates the TS types)
"""

import json
import os
import sys
from pathlib import Path

# Settings require a JWT key at import time; the schema does not depend on its value.
os.environ.setdefault("JWT_SECRET_KEY", "openapi-export-only")

from app.main import app  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "packages" / "api-client" / "openapi.json"


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
