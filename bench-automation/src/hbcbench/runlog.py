# Copyright 2026 ETH Zürich. Author: Lucas Köhli.
"""Run output: a data CSV, a per-step summary CSV and a JSON metadata sidecar.

The CSVs contain only a header row and data, so they load directly with
``numpy.genfromtxt`` or ``pandas.read_csv``. Everything describing the run
(configuration, instruments, timing, software version) goes into the JSON.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

from . import __version__


def _git_describe(path: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


class RunLog:
    def __init__(
        self,
        out_dir: str | Path,
        name: str,
        columns: list[str],
        summary_columns: list[str],
        meta: dict[str, Any],
    ):
        self.started = dt.datetime.now().astimezone()
        stem = f"{self.started:%Y%m%d-%H%M%S}_{name}"
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.data_path = self.dir / f"{stem}.csv"
        self.summary_path = self.dir / f"{stem}_summary.csv"
        self.meta_path = self.dir / f"{stem}.json"
        self.meta = dict(meta)
        self.n_rows = 0
        self.notes: list[str] = []

        self._data_fh = self.data_path.open("w", newline="", encoding="utf-8")
        self._data = csv.writer(self._data_fh)
        self._data.writerow(columns)
        self._sum_fh = self.summary_path.open("w", newline="", encoding="utf-8")
        self._sum = csv.DictWriter(self._sum_fh, fieldnames=summary_columns)
        self._sum.writeheader()

    def row(self, values: list[Any]) -> None:
        self._data.writerow(values)
        self.n_rows += 1

    def flush(self) -> None:
        self._data_fh.flush()
        self._sum_fh.flush()

    def summary(self, values: dict[str, Any]) -> None:
        self._sum.writerow(values)
        self._sum_fh.flush()

    def note(self, text: str) -> None:
        self.notes.append(text)

    def finish(self, status: str, results: dict[str, Any] | None = None) -> None:
        self._data_fh.close()
        self._sum_fh.close()
        ended = dt.datetime.now().astimezone()
        meta = {
            **self.meta,
            "status": status,
            "started": self.started.isoformat(timespec="seconds"),
            "ended": ended.isoformat(timespec="seconds"),
            "rows": self.n_rows,
            "notes": self.notes,
            "results": results or {},
            "software": {
                "hbcbench": __version__,
                "python": platform.python_version(),
                "git": _git_describe(Path(__file__).parent),
            },
            "files": {"data": self.data_path.name, "summary": self.summary_path.name},
        }
        self.meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
