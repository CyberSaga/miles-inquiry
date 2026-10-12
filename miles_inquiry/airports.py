"""Airport database: trimmed OurAirports data keyed by IATA code.

``data/airports.csv`` columns: iata,name,municipality,iso_country,type,lat,lon,scheduled_service
It is regenerated with ``python -m miles_inquiry update-airports``.
"""
from __future__ import annotations

import csv
import io
import os
import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

OURAIRPORTS_URLS = (
    "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv",
)

TRIMMED_COLUMNS = ("iata", "name", "municipality", "iso_country", "type", "lat", "lon", "scheduled_service")

# Larger is better when several OurAirports rows share one IATA code.
_TYPE_RANK = {
    "large_airport": 5,
    "medium_airport": 4,
    "small_airport": 3,
    "seaplane_base": 2,
    "heliport": 1,
    "balloonport": 0,
    "closed": -1,
}


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    municipality: str
    iso_country: str
    type: str
    lat: float
    lon: float
    scheduled_service: bool = True

    @property
    def label(self) -> str:
        city = self.municipality or ""
        return f"{self.iata} {self.name}" + (f" ({city}, {self.iso_country})" if city else f" ({self.iso_country})")


class AirportDB:
    def __init__(self, airports: Iterable[Airport]):
        self._by_iata: Dict[str, Airport] = {a.iata.upper(): a for a in airports}

    def __len__(self) -> int:
        return len(self._by_iata)

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and code.upper() in self._by_iata

    def get(self, code: str) -> Optional[Airport]:
        return self._by_iata.get(code.upper())

    @classmethod
    def load(cls, path: Path) -> "AirportDB":
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(
                f"找不到機場資料 {path}；請先執行 python -m miles_inquiry update-airports"
            )
        airports = []
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                iata = (row.get("iata") or "").strip().upper()
                if not iata:
                    continue
                try:
                    lat, lon = float(row["lat"]), float(row["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                airports.append(Airport(
                    iata=iata,
                    name=(row.get("name") or "").strip(),
                    municipality=(row.get("municipality") or "").strip(),
                    iso_country=(row.get("iso_country") or "").strip(),
                    type=(row.get("type") or "").strip(),
                    lat=lat, lon=lon,
                    scheduled_service=(row.get("scheduled_service") or "yes").strip().lower() != "no",
                ))
        return cls(airports)


# ---------------------------------------------------------------------------
# update-airports
# ---------------------------------------------------------------------------

def _row_score(row: dict) -> tuple:
    scheduled = 1 if (row.get("scheduled_service") or "").strip().lower() == "yes" else 0
    return (scheduled, _TYPE_RANK.get((row.get("type") or "").strip(), 0))


def trim_ourairports(text: str) -> list:
    """Reduce full OurAirports CSV text to one trimmed row per IATA code."""
    best: Dict[str, dict] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        iata = (row.get("iata_code") or "").strip().upper()
        if len(iata) != 3 or not iata.isalnum():
            continue
        try:
            lat = float(row["latitude_deg"])
            lon = float(row["longitude_deg"])
        except (KeyError, TypeError, ValueError):
            continue
        trimmed = {
            "iata": iata,
            "name": (row.get("name") or "").strip(),
            "municipality": (row.get("municipality") or "").strip(),
            "iso_country": (row.get("iso_country") or "").strip(),
            "type": (row.get("type") or "").strip(),
            "lat": f"{lat:.6f}".rstrip("0").rstrip("."),
            "lon": f"{lon:.6f}".rstrip("0").rstrip("."),
            "scheduled_service": "yes" if (row.get("scheduled_service") or "").strip().lower() == "yes" else "no",
        }
        prev = best.get(iata)
        if prev is None or _row_score(row) > prev["_score"]:
            trimmed["_score"] = _row_score(row)
            best[iata] = trimmed
    rows = sorted(best.values(), key=lambda r: r["iata"])
    for r in rows:
        r.pop("_score", None)
    return rows


def write_trimmed(rows: list, dest: Path) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(TRIMMED_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=cafile if cafile and Path(cafile).is_file() else None)


def download_ourairports(urls: Iterable[str] = OURAIRPORTS_URLS, timeout: int = 60) -> str:
    last_err: Optional[Exception] = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "miles-inquiry"})
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                return resp.read().decode("utf-8-sig")
        except Exception as exc:  # noqa: BLE001 – try the mirror next
            last_err = exc
    raise RuntimeError(f"無法下載 OurAirports 資料（{last_err}）；可改用 --source 指定本機 airports.csv")


def update_airports(dest: Path, source: Optional[Path] = None) -> int:
    """Regenerate the trimmed airports.csv. Returns number of airports written."""
    if source is not None:
        text = Path(source).read_text(encoding="utf-8-sig")
    else:
        text = download_ourairports()
    rows = trim_ourairports(text)
    if len(rows) < 1000:
        raise RuntimeError(f"來源資料僅解析出 {len(rows)} 個 IATA 機場，疑似格式錯誤，未寫入")
    write_trimmed(rows, dest)
    return len(rows)
