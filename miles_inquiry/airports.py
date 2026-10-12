"""Airport database keyed by IATA code – two layered sources.

Primary  : ``data/airports_greatcirclemap.csv`` – the exact airport file that
           https://www.greatcirclemap.com/ loads in the browser
           (columns ``id,name,city,iata,icao,lat,lng``, 3-decimal coordinates).
           Using the same coordinates as the site is what makes our numbers
           identical to the ones it displays.
Fallback : ``data/airports.csv`` – trimmed OurAirports data
           (``iata,name,municipality,iso_country,type,lat,lon,scheduled_service``)
           for codes the site does not know (e.g. SAI, PKX, TFU).

When both sources know a code but place it more than ``CONFLICT_KM`` apart, the
code has been re-assigned since the site's data was compiled (e.g. KTI: Kratie
on the site, Techo/Phnom Penh in OurAirports).  OurAirports is then used and the
row gets a note saying the website figure does not apply.

Both files are regenerated with ``python -m miles_inquiry update-airports``.
"""
from __future__ import annotations

import csv
import io
import os
import re
import ssl
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

GCM_AIRPORTS_URL = "https://www.greatcirclemap.com/airports.csv"
OURAIRPORTS_URLS = (
    "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv",
)

GCM_FILENAME = "airports_greatcirclemap.csv"
OURAIRPORTS_FILENAME = "airports.csv"

GCM_COLUMNS = ("id", "name", "city", "iata", "icao", "lat", "lng")
TRIMMED_COLUMNS = ("iata", "name", "municipality", "iso_country", "type", "lat", "lon", "scheduled_service")

SOURCE_GCM = "greatcirclemap"
SOURCE_OURAIRPORTS = "ourairports"

#: Same code, coordinates further apart than this → treat as a re-assigned code.
CONFLICT_KM = 50.0

_IATA_RE = re.compile(r"^[A-Z0-9]{3}$")

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
    source: str = SOURCE_GCM          # where lat/lon come from
    conflict_note: str = ""           # non-empty when the site places this code elsewhere

    @property
    def on_site(self) -> bool:
        """True when greatcirclemap.com would compute this code the same way we do."""
        return self.source == SOURCE_GCM

    @property
    def label(self) -> str:
        city = self.municipality or ""
        country = f", {self.iso_country}" if self.iso_country else ""
        return f"{self.iata} {self.name}" + (f" ({city}{country})" if city or country else "")


class AirportDB:
    def __init__(self, airports: Iterable[Airport]):
        self._by_iata: Dict[str, Airport] = {a.iata.upper(): a for a in airports}

    def __len__(self) -> int:
        return len(self._by_iata)

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and code.upper() in self._by_iata

    def get(self, code: str) -> Optional[Airport]:
        return self._by_iata.get(code.upper())

    def codes(self) -> List[str]:
        return sorted(self._by_iata)

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path, fallback: Optional[Path] = None) -> "AirportDB":
        """Load one file (format auto-detected) with an optional OurAirports fallback.

        ``path`` may be either the greatcirclemap file or a trimmed OurAirports
        file; ``fallback`` (trimmed OurAirports) fills in codes ``path`` lacks.
        """
        primary = _read_any(Path(path))
        if fallback is None or not Path(fallback).is_file():
            return cls(primary.values())
        return cls(merge_sources(primary, _read_any(Path(fallback))).values())

    @classmethod
    def load_layered(cls, gcm_path: Optional[Path], ourairports_path: Optional[Path]) -> "AirportDB":
        """Load primary (site) + fallback (OurAirports); either may be missing, not both."""
        gcm = _read_any(Path(gcm_path)) if gcm_path and Path(gcm_path).is_file() else {}
        oa = _read_any(Path(ourairports_path)) if ourairports_path and Path(ourairports_path).is_file() else {}
        if not gcm and not oa:
            raise FileNotFoundError(
                f"找不到機場資料（{gcm_path} / {ourairports_path}）；請先執行 python -m miles_inquiry update-airports"
            )
        if gcm and oa:
            return cls(merge_sources(gcm, oa).values())
        return cls((gcm or oa).values())


# ---------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------

def _read_any(path: Path) -> Dict[str, Airport]:
    if not path.is_file():
        raise FileNotFoundError(
            f"找不到機場資料 {path}；請先執行 python -m miles_inquiry update-airports"
        )
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        head = fh.readline()
    names = [c.strip().strip('"').lower() for c in head.split(",")]
    if "lng" in names and "iata" in names:
        return read_greatcirclemap(path)
    return read_ourairports_trimmed(path)


def read_greatcirclemap(path: Path) -> Dict[str, Airport]:
    """Parse the site's ``airports.csv`` (id,name,city,iata,icao,lat,lng)."""
    out: Dict[str, Airport] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("iata") or "").strip().upper()
            if not _IATA_RE.match(code) or code == "N/A":   # the file holds a few junk codes
                continue
            try:
                lat, lon = float(row["lat"]), float(row["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            if code in out:          # keep the first occurrence, like the site's lookup does
                continue
            out[code] = Airport(
                iata=code,
                name=(row.get("name") or "").strip(),
                municipality=(row.get("city") or "").strip(),
                iso_country="",
                type="",
                lat=lat, lon=lon,
                scheduled_service=True,
                source=SOURCE_GCM,
            )
    return out


def read_ourairports_trimmed(path: Path) -> Dict[str, Airport]:
    out: Dict[str, Airport] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("iata") or "").strip().upper()
            if not code:
                continue
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            out[code] = Airport(
                iata=code,
                name=(row.get("name") or "").strip(),
                municipality=(row.get("municipality") or "").strip(),
                iso_country=(row.get("iso_country") or "").strip(),
                type=(row.get("type") or "").strip(),
                lat=lat, lon=lon,
                scheduled_service=(row.get("scheduled_service") or "yes").strip().lower() != "no",
                source=SOURCE_OURAIRPORTS,
            )
    return out


def merge_sources(primary: Dict[str, Airport], fallback: Dict[str, Airport],
                  conflict_km: float = CONFLICT_KM) -> Dict[str, Airport]:
    """Site coordinates first, OurAirports metadata + fallback, conflicts → OurAirports."""
    from .geo import distance_km   # local import: geo has no dependency on this module

    merged: Dict[str, Airport] = {}
    for code, fb in fallback.items():
        merged[code] = fb
    for code, pa in primary.items():
        fb = fallback.get(code)
        if fb is None:
            merged[code] = pa
            continue
        apart = distance_km(pa.lat, pa.lon, fb.lat, fb.lon)
        if apart > conflict_km:
            merged[code] = Airport(
                iata=code, name=fb.name, municipality=fb.municipality, iso_country=fb.iso_country,
                type=fb.type, lat=fb.lat, lon=fb.lon, scheduled_service=fb.scheduled_service,
                source=SOURCE_OURAIRPORTS,
                conflict_note=f"greatcirclemap 資料庫中 {code} 為 {pa.name}（相距 {int(round(apart))} km）",
            )
        else:
            # site coordinates (so results match the site) + OurAirports metadata
            merged[code] = Airport(
                iata=code, name=fb.name or pa.name, municipality=fb.municipality or pa.municipality,
                iso_country=fb.iso_country, type=fb.type, lat=pa.lat, lon=pa.lon,
                scheduled_service=fb.scheduled_service, source=SOURCE_GCM,
            )
    return merged


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


def validate_greatcirclemap_text(text: str, min_codes: int = 5000) -> int:
    """Check downloaded site data looks right; return number of IATA codes."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or [c.strip().lower() for c in reader.fieldnames] != list(GCM_COLUMNS):
        raise RuntimeError(f"greatcirclemap airports.csv 標題列不符（{reader.fieldnames}），未寫入")
    codes = {(row.get("iata") or "").strip().upper() for row in reader}
    n = sum(1 for c in codes if _IATA_RE.match(c) and c != "N/A")
    if n < min_codes:
        raise RuntimeError(f"greatcirclemap airports.csv 僅含 {n} 個 IATA 代碼（預期 ≥ {min_codes}），未寫入")
    return n


def write_greatcirclemap(text: str, dest: Path) -> None:
    """Store the site file verbatim (so the snapshot is exactly what the browser loads)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as fh:   # Path.write_text(newline=) needs 3.10+
        fh.write(text.lstrip("﻿"))


def _ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=cafile if cafile and Path(cafile).is_file() else None)


def download_text(urls: Iterable[str], retries: int = 4, timeout: int = 60, backoff: float = 1.5) -> str:
    """GET the first URL that answers; each URL is retried (the proxy sometimes resets)."""
    last_err: Optional[Exception] = None
    for url in urls:
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "miles-inquiry"})
                with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                    return resp.read().decode("utf-8-sig")
            except Exception as exc:  # noqa: BLE001 – retry / next mirror
                last_err = exc
                if attempt + 1 < retries:
                    time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"無法下載（{last_err}）")


def download_ourairports(urls: Iterable[str] = OURAIRPORTS_URLS, timeout: int = 60) -> str:
    try:
        return download_text(urls, timeout=timeout)
    except RuntimeError as exc:
        raise RuntimeError(f"無法下載 OurAirports 資料（{exc}）；可改用 --source 指定本機 airports.csv") from exc


def download_greatcirclemap(url: str = GCM_AIRPORTS_URL, timeout: int = 60) -> str:
    try:
        return download_text((url,), timeout=timeout)
    except RuntimeError as exc:
        raise RuntimeError(f"無法下載 greatcirclemap.com 機場資料（{exc}）；可改用 --gcm-source 指定本機檔") from exc


def update_airports(dest: Path, source: Optional[Path] = None) -> int:
    """Regenerate the trimmed OurAirports ``airports.csv``. Returns number of airports written."""
    if source is not None:
        text = Path(source).read_text(encoding="utf-8-sig")
    else:
        text = download_ourairports()
    rows = trim_ourairports(text)
    if len(rows) < 1000:
        raise RuntimeError(f"來源資料僅解析出 {len(rows)} 個 IATA 機場，疑似格式錯誤，未寫入")
    write_trimmed(rows, dest)
    return len(rows)


def update_greatcirclemap(dest: Path, source: Optional[Path] = None) -> int:
    """Refresh the greatcirclemap.com snapshot. Returns number of IATA codes."""
    if source is not None:
        text = Path(source).read_text(encoding="utf-8-sig")
    else:
        text = download_greatcirclemap()
    n = validate_greatcirclemap_text(text)
    write_greatcirclemap(text, dest)
    return n


def update_all(data_dir: Path, gcm_source: Optional[Path] = None, oa_source: Optional[Path] = None,
               skip_gcm: bool = False, skip_ourairports: bool = False) -> List[Tuple[str, Path, int]]:
    """Refresh both files; returns [(label, path, count), ...]."""
    data_dir = Path(data_dir)
    done: List[Tuple[str, Path, int]] = []
    if not skip_gcm:
        p = data_dir / GCM_FILENAME
        done.append(("greatcirclemap.com", p, update_greatcirclemap(p, gcm_source)))
    if not skip_ourairports:
        p = data_dir / OURAIRPORTS_FILENAME
        done.append(("OurAirports", p, update_airports(p, oa_source)))
    return done
