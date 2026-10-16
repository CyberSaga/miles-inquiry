"""高鐵表的 距離：台灣高鐵站間里程，加上人工維護的站對站距離。

Data files (``data/``, UTF-8 with BOM, ``#`` lines are comments):

``thsr_stations.csv`` – ``station,km,source``
    Chainage (里程, km) of each THSR station along the line; distance between two
    stations = |km_a − km_b|.

``hsr_lookup.csv`` – ``value,station,review,note``
    Spelling variants → station (臺北/台北車站→台北, 高雄→左營, 粄橋→板橋 …).  The
    target need not be a THSR station: 苏州北→蘇州北 merges spellings so one
    override row covers both.  An empty ``station`` marks a known non-station
    (斗六, 屏東 …) – distance stays blank and 備註 gets the note.  ``review=yes`` also writes the note to 備註.
    Values ending in 站/車站 and 臺 vs 台 are normalised before lookup.

``rail_distance_overrides.csv`` – ``from,to,km,source``
    Distances for pairs that are not on the THSR line (China HSR, …) or that
    should not use the chainage table.  Direction-independent; keys are the
    values as typed (after the same normalisation).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from .lookup import display, is_review_flag, normalize, read_csv_text

STATIONS_FILENAME = "thsr_stations.csv"
LOOKUP_FILENAME = "hsr_lookup.csv"
OVERRIDES_FILENAME = "rail_distance_overrides.csv"


def station_key(value) -> str:
    """'臺北車站 ' → '台北'; 'ＺＵＯ' → 'ZUO'."""
    text = normalize(value).replace("臺", "台")
    text = re.sub(r"(高鐵)?(車)?站$", "", text) if len(text) > 2 else text
    return text


def _rows(path: Path):
    """Yield dict rows from a commented, header-led CSV."""
    with io.StringIO(read_csv_text(path), newline="") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return
    reader = csv.reader(lines)
    header = [normalize(c).lower() for c in next(reader)]
    for row in reader:
        yield {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(header)}


@dataclass(frozen=True)
class Station:
    name: str
    km: Optional[float]
    source: str = ""


@dataclass(frozen=True)
class RailResolution:
    raw: str
    station: Optional[str]     # THSR station name, or None
    canonical: str = ""        # name used for rail_distance_overrides.csv
    note: str = ""
    review: bool = False
    known: bool = False        # listed in hsr_lookup.csv
    non_station: bool = False  # listed with an empty station: not a rail station at all (斗六, 屏東 …)


@dataclass(frozen=True)
class RailDistance:
    km: Optional[float]
    source: str                # 'thsr' | 'override' | ''
    note: str = ""             # why km is None, or where it came from


class RailData:
    def __init__(self, stations: Dict[str, Station], lookup: Dict[str, Tuple[str, str, bool]],
                 overrides: Dict[Tuple[str, str], Tuple[float, str]], data_dir: Optional[Path] = None):
        self.stations = stations
        self.lookup = lookup            # key → (station, note, review)
        self.overrides = overrides      # (key_a, key_b) sorted → (km, source)
        self.data_dir = data_dir

    @classmethod
    def load(cls, data_dir: Path) -> "RailData":
        data_dir = Path(data_dir)
        stations: Dict[str, Station] = {}
        path = data_dir / STATIONS_FILENAME
        if not path.is_file():
            raise FileNotFoundError(f"找不到高鐵里程表 {path}")
        for row in _rows(path):
            name = station_key(row.get("station"))
            if not name:
                continue
            km_text = row.get("km", "")
            try:
                km = float(km_text) if km_text else None
            except ValueError:
                raise ValueError(f"{path}: 「{row.get('station')}」的 km「{km_text}」不是數字") from None
            stations[name] = Station(name, km, row.get("source", ""))

        lookup: Dict[str, Tuple[str, str, bool]] = {}
        path = data_dir / LOOKUP_FILENAME
        if path.is_file():
            for row in _rows(path):
                key = station_key(row.get("value"))
                if not key:
                    continue
                target = station_key(row.get("station")) if row.get("station") else ""
                lookup[key] = (target, row.get("note", ""), is_review_flag(row.get("review")))

        overrides: Dict[Tuple[str, str], Tuple[float, str]] = {}
        path = data_dir / OVERRIDES_FILENAME
        if path.is_file():
            for row in _rows(path):
                a, b = station_key(row.get("from")), station_key(row.get("to"))
                if not a or not b or not row.get("km"):
                    continue
                try:
                    km = float(row["km"])
                except ValueError:
                    raise ValueError(f"{path}: {row.get('from')}-{row.get('to')} 的 km「{row['km']}」不是數字") from None
                overrides[tuple(sorted((a, b)))] = (km, row.get("source", ""))
        return cls(stations, lookup, overrides, data_dir)

    # -- resolving ---------------------------------------------------------

    def resolve(self, value) -> RailResolution:
        raw = display(value)
        key = station_key(value)
        if key in self.lookup:
            target, note, review = self.lookup[key]
            return RailResolution(raw, target if target in self.stations else None, target or key, note, review,
                                  known=True, non_station=not target)
        return RailResolution(raw, key if key in self.stations else None, key)

    def distance(self, a_value, b_value) -> Tuple[RailDistance, RailResolution, RailResolution]:
        ra, rb = self.resolve(a_value), self.resolve(b_value)
        keys = tuple(sorted((ra.canonical, rb.canonical)))
        if keys in self.overrides:
            km, source = self.overrides[keys]
            return RailDistance(km, "override", f"距離來自 {OVERRIDES_FILENAME}" + (f"（{source}）" if source else "")), ra, rb
        if ra.station and rb.station:
            sa, sb = self.stations[ra.station], self.stations[rb.station]
            missing = [s.name for s in (sa, sb) if s.km is None]
            if missing:
                return RailDistance(None, "missing_km", "、".join(missing)), ra, rb
            return RailDistance(round(abs(sa.km - sb.km), 1), "thsr"), ra, rb
        return RailDistance(None, ""), ra, rb
