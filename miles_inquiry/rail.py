"""高鐵表的 距離：台灣高鐵官方站間碳足跡表換算的距離，加上人工維護的站對站距離。

Data files (``data/``, UTF-8 with BOM, ``#`` lines are comments):

``thsr_distances.csv`` – ``from,to,kg_co2e,km``
    The 66 station pairs of THSRC's official「車站間旅客運輸碳足跡」table
    (kg CO2e per passenger trip, label 29 gCO2e/pkm) with ``km = kg_co2e ÷ 0.029``,
    so 距離 × 人次 × 0.029 reproduces THSRC's published footprint.  Direction-independent.

``hsr_lookup.csv`` – ``value,station,review,note``
    Spelling variants → station (臺北/台北車站→台北, 高雄→左營, 粄橋→板橋 …).  The
    target need not be a THSR station: 苏州北→蘇州北 merges spellings so one
    override row covers both.  An empty ``station`` marks a known non-station
    (斗六, 屏東 …) – distance stays blank and 備註 gets the note.  ``review=yes`` also writes the note to 備註.
    Values ending in 站/車站 and 臺 vs 台 are normalised before lookup.

``rail_distance_overrides.csv`` – ``from,to,km,source``
    Distances for pairs that are not on the THSR line (China HSR, …) or that
    should not use the chainage table.  Direction-independent.  Station names are
    merged through ``hsr_lookup.csv`` first, so 苏州北 and 蘇州北 are the same row;
    two rows for one pair must agree on ``km``.  A listed pair with at least one end that
    is not a THSR station counts as "outside Taiwan HSR" – see ``is_non_thsr``; a pinned
    pair of two THSR stations stays Taiwan HSR.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from .lookup import display, is_review_flag, normalize, read_csv_text

STATIONS_FILENAME = "thsr_distances.csv"
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
    source: str                # 'thsr' | 'override' | 'missing_pair' | ''
    note: str = ""             # why km is None, or where it came from


class RailData:
    def __init__(self, pairs: Dict[Tuple[str, str], float], lookup: Dict[str, Tuple[str, str, bool]],
                 overrides: Dict[Tuple[str, str], Tuple[float, str]], data_dir: Optional[Path] = None):
        self.pairs = pairs              # (key_a, key_b) sorted → km (THSR)
        self.stations = {name for pair in pairs for name in pair}
        self.lookup = lookup            # key → (station, note, review)
        self.overrides = overrides      # (key_a, key_b) sorted → (km, source)
        self.data_dir = data_dir

    @classmethod
    def load(cls, data_dir: Path) -> "RailData":
        data_dir = Path(data_dir)
        pairs: Dict[Tuple[str, str], float] = {}
        path = data_dir / STATIONS_FILENAME
        if not path.is_file():
            raise FileNotFoundError(f"找不到高鐵站間距離表 {path}")
        for row in _rows(path):
            a, b = station_key(row.get("from")), station_key(row.get("to"))
            if not a or not b:
                continue
            try:
                pairs[tuple(sorted((a, b)))] = float(row.get("km", ""))
            except ValueError:
                raise ValueError(f"{path}: {row.get('from')}-{row.get('to')} 的 km「{row.get('km')}」不是數字") from None

        lookup: Dict[str, Tuple[str, str, bool]] = {}
        path = data_dir / LOOKUP_FILENAME
        if path.is_file():
            for row in _rows(path):
                key = station_key(row.get("value"))
                if not key:
                    continue
                target = station_key(row.get("station")) if row.get("station") else ""
                lookup[key] = (target, row.get("note", ""), is_review_flag(row.get("review")))

        def canonical(value) -> str:
            key = station_key(value)
            return (lookup[key][0] or key) if key in lookup else key

        overrides: Dict[Tuple[str, str], Tuple[float, str]] = {}
        path = data_dir / OVERRIDES_FILENAME
        if path.is_file():
            for row in _rows(path):
                a, b = canonical(row.get("from")), canonical(row.get("to"))
                if not a or not b or not row.get("km"):
                    continue
                try:
                    km = float(row["km"])
                except ValueError:
                    raise ValueError(f"{path}: {row.get('from')}-{row.get('to')} 的 km「{row['km']}」不是數字") from None
                key = tuple(sorted((a, b)))
                if key in overrides and overrides[key][0] != km:
                    raise ValueError(f"{path}: {a}-{b} 出現兩次且距離不同（{overrides[key][0]:g} 與 {km:g} km），請保留一個")
                overrides[key] = (km, row.get("source", ""))
        return cls(pairs, lookup, overrides, data_dir)

    # -- resolving ---------------------------------------------------------

    def resolve(self, value) -> RailResolution:
        raw = display(value)
        key = station_key(value)
        if key in self.lookup:
            target, note, review = self.lookup[key]
            return RailResolution(raw, target if target in self.stations else None, target or key, note, review,
                                  known=True, non_station=not target)
        return RailResolution(raw, key if key in self.stations else None, key)

    def corrected_name(self, res: RailResolution) -> str:
        """How to write the station a review alias points to (广东南→廣州南): the spelling the data itself uses
        (a non-review alias such as 广州南) if there is one, else the canonical name.  For notes only."""
        if not res.review:
            return res.raw
        for key, (target, _note, review) in self.lookup.items():
            if not review and target == res.canonical and key != res.canonical:
                return key
        return res.canonical

    def is_non_thsr(self, a_value, b_value) -> bool:
        """True for a trip outside Taiwan HSR (China HSR …): the pair is listed in the overrides and is not a
        pinned pair of two THSR stations.  Only listed pairs count – a mistyped Taiwan station must never
        silently pick up another emission factor – and known non-stations (斗六, 屏東 …) never count."""
        ra, rb = self.resolve(a_value), self.resolve(b_value)
        if ra.non_station or rb.non_station or (ra.station and rb.station):
            return False
        return tuple(sorted((ra.canonical, rb.canonical))) in self.overrides

    def distance(self, a_value, b_value) -> Tuple[RailDistance, RailResolution, RailResolution]:
        ra, rb = self.resolve(a_value), self.resolve(b_value)
        keys = tuple(sorted((ra.canonical, rb.canonical)))
        if keys in self.overrides:
            km, source = self.overrides[keys]
            return RailDistance(km, "override", f"距離來自 {OVERRIDES_FILENAME}" + (f"（{source}）" if source else "")), ra, rb
        if ra.station and rb.station:
            if ra.station == rb.station:
                return RailDistance(0, "thsr", "起迄相同"), ra, rb
            km = self.pairs.get(tuple(sorted((ra.station, rb.station))))
            if km is None:
                return RailDistance(None, "missing_pair", f"{ra.station}-{rb.station}"), ra, rb
            return RailDistance(km, "thsr"), ra, rb
        return RailDistance(None, ""), ra, rb
