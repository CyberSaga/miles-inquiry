"""User-maintained value → IATA lookup table (``data/lookup.csv``).

File format (UTF-8 with BOM so Excel opens it directly)::

    value,iata,review,note
    # lines whose value starts with '#' are comments
    澎湖,MZG,,
    新竹,,,新竹無機場
    台北,TSA,yes,台北預設松山 TSA；國際線多為桃園 TPE，請確認
    TAS,TSA,,澎湖分行 TAS→MZG 疑為 TSA 誤植

Columns are located by the header row (order does not matter; ``review`` is
optional, so the older 3-column ``value,iata,note`` layout still loads).

Matching rules
--------------
* ``value`` is NFKC-normalised, stripped and compared case-insensitively
  (``kHH``, ``ＫＨＨ``, ``' HONG KONG '`` all match).
* Explicit rows win over everything, so typo corrections such as TAS→TSA work.
* A value that is itself a valid 3-letter IATA code in airports.csv maps to
  itself when no explicit row exists.
* An explicit row with an empty ``iata`` marks a *known-unresolvable* value:
  distance stays blank and 備註 gets a note.
* ``note`` always goes to the CSV report.  It is also written to 備註 (so a
  human confirms the row) when ``review`` is truthy (yes/y/true/1/是/v) or when
  the row is a *correction* (value looks like an IATA code but maps to a
  different code, e.g. TAS→TSA).
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Set

from .airports import AirportDB

LOOKUP_COLUMNS = ("value", "iata", "review", "note")
LEGACY_COLUMNS = ("value", "iata", "note")

# Values accepted in the ``review`` column meaning "always ask a human".
REVIEW_TRUE: Set[str] = {"YES", "Y", "TRUE", "T", "1", "V", "是", "要", "需確認", "請確認", "REVIEW", "✓"}

# Values meaning "no flight" – rows are skipped entirely.
SKIP_VALUES: Set[str] = {"無", "0", "", "-", "—", "N/A", "NA", "無資料"}

_IATA_RE = re.compile(r"^[A-Z]{3}$")


def normalize(value) -> str:
    """NFKC-normalise, collapse inner whitespace, strip, upper-case."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text.upper()


def display(value) -> str:
    """Human-friendly normalised form (keeps original case)."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", text).strip()


def is_skip_value(value) -> bool:
    key = normalize(value)
    if key in SKIP_VALUES:
        return True
    # numeric zero in any form (0, 0.0, '0')
    try:
        return float(key) == 0.0
    except ValueError:
        return False


def looks_like_iata(value) -> bool:
    return bool(_IATA_RE.match(normalize(value)))


def is_review_flag(value) -> bool:
    return normalize(value) in REVIEW_TRUE


@dataclass(frozen=True)
class LookupEntry:
    value: str          # normalised key
    raw_value: str      # as written in the file
    iata: str           # '' = known-unresolvable
    note: str = ""
    review: bool = False   # always write note to 備註


@dataclass(frozen=True)
class Resolution:
    """Result of resolving one raw cell value."""
    raw: str                      # display form of the raw value
    iata: Optional[str]           # resolved code, or None
    status: str                   # 'skip' | 'ok' | 'unresolved'
    via: str = ""                 # 'direct' | 'lookup' | ''
    note: str = ""                # note from lookup.csv (if any)
    correction: bool = False      # value looked like IATA but mapped elsewhere
    review: bool = False          # lookup row flagged review=yes

    @property
    def mapped(self) -> bool:
        return self.via == "lookup" and self.iata is not None and normalize(self.raw) != self.iata

    @property
    def note_for_cell(self) -> Optional[str]:
        """Note that should be appended to 備註 (None if nothing)."""
        if self.status != "ok":
            return None
        if self.correction:
            base = f"{normalize(self.raw)}→{self.iata} 疑為代碼誤植"
            return f"{base}（{self.note}）請確認" if self.note else f"{base}，請確認"
        if self.review:
            head = f"{self.raw}→{self.iata}" if self.mapped else f"{self.iata}"
            text = self.note or "請確認"
            return f"{head}：{text}"
        return None

    @property
    def note_for_report(self) -> Optional[str]:
        """Note for the report only (lookup mapping that needs no human action)."""
        if self.status != "ok" or self.via != "lookup" or self.note_for_cell:
            return None
        if self.mapped:
            return f"{self.raw}→{self.iata}" + (f"（{self.note}）" if self.note else "")
        return f"{self.iata}（{self.note}）" if self.note else None


class Lookup:
    def __init__(self, entries: Dict[str, LookupEntry], airports: AirportDB, path: Optional[Path] = None):
        self.entries = entries
        self.airports = airports
        self.path = path

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path, airports: AirportDB) -> "Lookup":
        path = Path(path)
        entries: Dict[str, LookupEntry] = {}
        if not path.is_file():
            raise FileNotFoundError(f"找不到對應表 {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header_seen = False
            cols = {name: i for i, name in enumerate(LOOKUP_COLUMNS)}   # default order
            for row in reader:
                if not row or all(not c.strip() for c in row):
                    continue
                first = row[0].strip()
                if first.startswith("#"):
                    continue
                if not header_seen:
                    header_seen = True
                    names = [normalize(c).lower() for c in row]
                    if "value" in names:   # header row → locate columns by name
                        cols = {n: i for i, n in enumerate(names) if n in LOOKUP_COLUMNS}
                        if "iata" not in cols:
                            raise ValueError(f"{path}: 標題列缺少 iata 欄")
                        continue   # legacy value,iata,note (no review column) loads too

                def col(name: str) -> str:
                    i = cols.get(name)
                    return row[i] if i is not None and i < len(row) else ""

                raw_value = col("value")
                iata = normalize(col("iata"))
                note = col("note").strip()
                review = is_review_flag(col("review"))
                key = normalize(raw_value)
                if not key:
                    continue
                if iata and not _IATA_RE.match(iata):
                    raise ValueError(f"{path}: 「{raw_value}」的 iata 欄「{col('iata')}」不是 3 碼英文字母")
                entries[key] = LookupEntry(value=key, raw_value=display(raw_value), iata=iata, note=note, review=review)
        return cls(entries, airports, path)

    @classmethod
    def empty(cls, airports: AirportDB) -> "Lookup":
        return cls({}, airports, None)

    # -- resolving ---------------------------------------------------------

    def resolve(self, value) -> Resolution:
        raw = display(value)
        key = normalize(value)
        if is_skip_value(key):
            return Resolution(raw=raw, iata=None, status="skip")

        entry = self.entries.get(key)
        if entry is not None:
            note = entry.note
            if not entry.iata:
                return Resolution(raw=raw, iata=None, status="unresolved", via="lookup", note=note, review=entry.review)
            if entry.iata not in self.airports:
                return Resolution(raw=raw, iata=None, status="unresolved", via="lookup",
                                  note=f"lookup.csv 對應的代碼 {entry.iata} 不存在於 airports.csv" + (f"；{note}" if note else ""),
                                  review=entry.review)
            correction = looks_like_iata(key) and key != entry.iata
            return Resolution(raw=raw, iata=entry.iata, status="ok", via="lookup", note=note,
                              correction=correction, review=entry.review)

        if _IATA_RE.match(key) and key in self.airports:
            return Resolution(raw=raw, iata=key, status="ok", via="direct")

        return Resolution(raw=raw, iata=None, status="unresolved")
