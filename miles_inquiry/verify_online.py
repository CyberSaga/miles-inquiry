"""Optional online check: compare our distances with what greatcirclemap.com displays.

The core tool never needs this.  It drives a headless Chromium through
Playwright (Node) – see ``gcm_probe.js`` – opens pages such as
``https://www.greatcirclemap.com/?routes=TPE-JFK,MZG-KHH`` (about 20 routes per
page), reads the ``AAA ⇾ BBB / 12566 km`` lines from the page text and compares
them with the values computed locally.

Requirements (any one of)::

    npm install -g playwright && npx playwright install chromium   # then NODE_PATH=$(npm root -g)
    npm install playwright && npx playwright install chromium       # inside the project folder
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .airports import AirportDB
from .geo import DEFAULT_METHOD, distance_km, round_km

SITE = "https://www.greatcirclemap.com/"
DEFAULT_BATCH = 20
PROBE_JS = Path(__file__).with_name("gcm_probe.js")

Route = Tuple[str, str]

# "TPE ⇾ JFK" on one line, "12566 km" on the next (the site may insert thousands separators one day)
_LINE_RE = re.compile(r"^\s*([A-Z0-9]{3})\s*⇾\s*([A-Z0-9]{3})\s*\n\s*([\d,]+)\s*km\s*$", re.MULTILINE)
# "'SAI' does not exist in our database" – the page then shows NO distances at all for that batch
_MISSING_RE = re.compile(r"'([A-Za-z0-9]{3})' does not exist in our database")

STATUSES = ("match", "mismatch", "site_missing", "site_reassigned", "error")


@dataclass
class VerifyResult:
    origin: str
    dest: str
    local_km: Optional[int]
    site_km: Optional[int]
    status: str          # one of STATUSES
    note: str = ""

    @property
    def url(self) -> str:
        return route_url([(self.origin, self.dest)])


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

def parse_routes(spec: str) -> List[Route]:
    """``"TPE-JFK, mzg-khh"`` → ``[("TPE","JFK"), ("MZG","KHH")]``."""
    out: List[Route] = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"([A-Za-z0-9]{3})-([A-Za-z0-9]{3})", part)
        if not m:
            raise ValueError(f"路線格式應為 AAA-BBB，收到「{part}」")
        out.append((m.group(1).upper(), m.group(2).upper()))
    return dedupe(out)


def routes_from_report(path: Path) -> List[Route]:
    """Distinct (origin_iata, dest_iata) pairs from a ``fill`` report CSV."""
    routes: List[Route] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            a = (row.get("origin_iata") or "").strip().upper()
            b = (row.get("dest_iata") or "").strip().upper()
            if a and b:
                routes.append((a, b))
    return dedupe(routes)


def dedupe(routes: Iterable[Route]) -> List[Route]:
    seen = set()
    out: List[Route] = []
    for r in routes:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def route_url(routes: Sequence[Route]) -> str:
    return SITE + "?" + urllib.parse.urlencode({"routes": ",".join(f"{a}-{b}" for a, b in routes)})


def batched(routes: Sequence[Route], size: int = DEFAULT_BATCH) -> List[List[Route]]:
    size = max(1, size)
    return [list(routes[i:i + size]) for i in range(0, len(routes), size)]


# ---------------------------------------------------------------------------
# page text → distances
# ---------------------------------------------------------------------------

def parse_site_text(text: str) -> Dict[Route, int]:
    """Extract ``{(A, B): km}`` from ``document.body.innerText`` of a routes page."""
    out: Dict[Route, int] = {}
    for a, b, km in _LINE_RE.findall(text or ""):
        out.setdefault((a, b), int(km.replace(",", "")))
    return out


def parse_missing_codes(text: str) -> List[str]:
    """Codes the page says are not in the site's database."""
    return sorted({m.upper() for m in _MISSING_RE.findall(text or "")})


# ---------------------------------------------------------------------------
# Playwright runner
# ---------------------------------------------------------------------------

def find_node() -> Optional[str]:
    return os.environ.get("MILES_INQUIRY_NODE") or shutil.which("node")


def node_env() -> dict:
    """Environment for the probe: make globally installed playwright resolvable."""
    env = dict(os.environ)
    if not env.get("NODE_PATH"):
        npm = shutil.which("npm")
        if npm:
            try:
                root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=30).stdout.strip()
                if root:
                    env["NODE_PATH"] = root
            except Exception:  # noqa: BLE001 – best effort only
                pass
    return env


def fetch_site_texts(urls: Sequence[str], timeout: int = 600) -> List[dict]:
    """Run ``gcm_probe.js`` once for all *urls*; returns ``[{url, expected, text, error}]``."""
    node = find_node()
    if not node:
        raise RuntimeError("找不到 node；verify-online 需要 Node.js 與 playwright（見 README）")
    if not PROBE_JS.is_file():
        raise RuntimeError(f"找不到 {PROBE_JS}")
    # The probe prints UTF-8 JSON (page text holds '⇾'); never decode it with the console
    # code page (cp950 on zh-TW Windows would fail on the first non-Big5 byte).
    proc = subprocess.run([node, str(PROBE_JS), *urls], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=node_env(), timeout=timeout)
    out = proc.stdout.strip()
    try:
        data = json.loads(out) if out else []
    except json.JSONDecodeError:
        data = []
    if proc.returncode != 0 and not any(d.get("text") for d in data):
        err = (data[0].get("error") if data else "") or proc.stderr.strip()[-800:] or f"exit {proc.returncode}"
        hint = ""
        if "Cannot find module 'playwright'" in err or "Cannot find module" in err:
            hint = "；請先 npm install -g playwright && npx playwright install chromium，並設定 NODE_PATH=$(npm root -g)"
        raise RuntimeError(f"Playwright 探測失敗：{err}{hint}")
    return data


Fetcher = Callable[[Sequence[str]], List[dict]]


def fetch_site_distances(routes: Sequence[Route], batch: int = DEFAULT_BATCH,
                         fetch: Optional[Fetcher] = None,
                         _depth: int = 0) -> Tuple[Dict[Route, int], List[str], List[str]]:
    """Return ``({route: site_km}, [codes the site lacks], [page errors])`` for all *routes*.

    A page holding a code the site does not know shows no distances at all, so
    such codes are recorded and the remaining routes of that page are fetched again.
    """
    fetch = fetch or fetch_site_texts      # resolved at call time (tests monkeypatch the module attribute)
    groups = batched(routes, batch)
    urls = [route_url(group) for group in groups]
    found: Dict[Route, int] = {}
    missing: List[str] = []
    errors: List[str] = []
    retry: List[Route] = []
    for group, item in zip(groups, fetch(urls)):
        if item.get("error"):
            errors.append(f"{item.get('url')}: {item['error']}")
        text = item.get("text") or ""
        found.update(parse_site_text(text))
        bad = parse_missing_codes(text)
        if bad:
            missing.extend(c for c in bad if c not in missing)
            retry.extend(r for r in group if r[0] not in bad and r[1] not in bad and r not in found)
    if retry and _depth < 3:
        f2, m2, e2 = fetch_site_distances(retry, batch, fetch, _depth + 1)
        found.update(f2)
        missing.extend(c for c in m2 if c not in missing)
        errors.extend(e2)
    return found, missing, errors


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

def local_km(db: AirportDB, a: str, b: str, method: str = DEFAULT_METHOD) -> Optional[int]:
    pa, pb = db.get(a), db.get(b)
    if pa is None or pb is None:
        return None
    return round_km(distance_km(pa.lat, pa.lon, pb.lat, pb.lon, method), 0)


def verify_routes(routes: Sequence[Route], db: AirportDB, method: str = DEFAULT_METHOD,
                  batch: int = DEFAULT_BATCH, fetch: Optional[Fetcher] = None) -> List[VerifyResult]:
    """Compare local values with the site for *routes* (codes the site lacks are reported, not fetched)."""
    results: Dict[Route, VerifyResult] = {}
    to_fetch: List[Route] = []
    for a, b in routes:
        lk = local_km(db, a, b, method)
        off_site = [c for c in (a, b) if db.get(c) is None or not db.get(c).on_site]
        reassigned = [c for c in off_site if db.get(c) is not None and db.get(c).conflict_note]
        if reassigned:
            # the site knows the code but puts it at a different airport (e.g. KTI = Kratie there)
            results[(a, b)] = VerifyResult(a, b, lk, None, "site_reassigned",
                                           "網站的 " + "、".join(reassigned) + " 座標不同，數字不可比對（"
                                           + "；".join(db.get(c).conflict_note for c in reassigned) + "）")
        elif off_site:
            results[(a, b)] = VerifyResult(a, b, lk, None, "site_missing",
                                           "greatcirclemap 資料庫沒有 " + "、".join(off_site))
        else:
            to_fetch.append((a, b))

    site: Dict[Route, int] = {}
    missing: List[str] = []
    errors: List[str] = []
    if to_fetch:
        site, missing, errors = fetch_site_distances(to_fetch, batch, fetch)

    for a, b in to_fetch:
        lk = local_km(db, a, b, method)
        sk = site.get((a, b))
        bad = [c for c in (a, b) if c in missing]
        if bad:
            results[(a, b)] = VerifyResult(a, b, lk, None, "site_missing",
                                           "網站回應：" + "、".join(bad) + " does not exist in our database")
        elif sk is None:
            results[(a, b)] = VerifyResult(a, b, lk, None, "error",
                                           "網站頁面未顯示此路線" + (f"（{errors[0]}）" if errors else ""))
        elif lk == sk:
            results[(a, b)] = VerifyResult(a, b, lk, sk, "match")
        else:
            results[(a, b)] = VerifyResult(a, b, lk, sk, "mismatch", f"差 {lk - sk:+d} km")
    return [results[r] for r in routes]


VERIFY_COLUMNS = ("origin", "dest", "local_km", "site_km", "status", "url", "note")


def write_verify_csv(results: Sequence[VerifyResult], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(VERIFY_COLUMNS), lineterminator="\n")
        w.writeheader()
        for r in results:
            w.writerow({"origin": r.origin, "dest": r.dest,
                        "local_km": "" if r.local_km is None else r.local_km,
                        "site_km": "" if r.site_km is None else r.site_km,
                        "status": r.status, "url": r.url, "note": r.note})
    return path


def summarize(results: Sequence[VerifyResult]) -> str:
    counts = {s: sum(1 for r in results if r.status == s) for s in STATUSES}
    lines = [f"verify-online：共 {len(results)} 條路線 → " + "、".join(f"{s}={n}" for s, n in counts.items())]
    for r in results:
        if r.status != "match":
            lines.append(f"  {r.status:<12} {r.origin}-{r.dest}  本機={r.local_km}  網站={r.site_km}  {r.note}")
    return "\n".join(lines)
