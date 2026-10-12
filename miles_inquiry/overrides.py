"""Exact distance overrides (``data/distance_overrides.csv``).

Columns: from,to,km,source – symmetric (A,B == B,A).  Use it to paste exact
figures read off https://www.greatcirclemap.com/ when they must match.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from .lookup import normalize


@dataclass(frozen=True)
class Override:
    km: float
    source: str = ""


class Overrides:
    def __init__(self, table: Dict[Tuple[str, str], Override]):
        self._table = table

    def __len__(self) -> int:
        return len(self._table)

    @staticmethod
    def _key(a: str, b: str) -> Tuple[str, str]:
        a, b = normalize(a), normalize(b)
        return (a, b) if a <= b else (b, a)

    def get(self, a: str, b: str) -> Optional[Override]:
        return self._table.get(self._key(a, b))

    @classmethod
    def load(cls, path: Optional[Path]) -> "Overrides":
        table: Dict[Tuple[str, str], Override] = {}
        if path is None or not Path(path).is_file():
            return cls(table)
        with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
            header_seen = False
            for row in csv.reader(fh):
                if not row or all(not c.strip() for c in row) or row[0].strip().startswith("#"):
                    continue
                if not header_seen:
                    header_seen = True
                    if normalize(row[0]) == "FROM":
                        continue
                if len(row) < 3:
                    continue
                try:
                    km = float(str(row[2]).replace(",", "").strip())
                except ValueError:
                    raise ValueError(f"{path}: 「{row[0]}→{row[1]}」的 km 欄「{row[2]}」不是數字")
                source = row[3].strip() if len(row) > 3 else ""
                table[cls._key(row[0], row[1])] = Override(km=km, source=source)
        return cls(table)
