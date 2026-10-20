"""Run dbt using existing DATABASE_URL for dev, isolated loopback config for local."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database import _database_url

ROOT = Path(__file__).resolve().parents[1]


def main():
    args = sys.argv[1:]
    target = args[args.index("--target") + 1] if "--target" in args else "local"
    if target not in {"local", "dev"}:
        raise SystemExit("Only local/dev targets are supported.")
    if target == "dev":
        url = _database_url()
        for key, value in {
            "HOST": url.host,
            "PORT": url.port or 5432,
            "USER": url.username,
            "PASSWORD": url.password or "",
            "DATABASE": url.database,
        }.items():
            os.environ["DBT_DEV_" + key] = str(value or "")
    os.environ["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
    executable = Path(sys.executable).parent / "dbt"
    result = subprocess.run(
        [
            str(executable),
            *args,
            "--project-dir",
            str(ROOT / "dbt-modeling"),
            "--profiles-dir",
            str(ROOT / "dbt-modeling"),
        ],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
