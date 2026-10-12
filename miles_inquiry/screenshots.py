"""Optional evidence: one greatcirclemap.com screenshot per route, saved in a folder of their own.

For every distinct route (origin → destination, as written in the sheet) the page
``https://www.greatcirclemap.com/?routes=AAA-BBB`` is opened in a headless Chromium
(Playwright, Node – see ``gcm_screenshot.js``) and captured.  The distance shown by
the site is read from the same page and compared with the value in 距離, so the
file name and ``index.csv`` say whether the screenshot confirms the number::

    <folder>/
        TPE-JFK_12566km.png             site shows 12566 km = value in the sheet
        KHH-SAI_網站無此機場.png          the site's database lacks a code (page shows its error)
        LAX-SEA_網站1535km_表內1536km.png  mismatch (should never happen)
        index.csv                        route, site km, sheet km, status, sheet rows, file, URL, time
        index.html                       the same as a page with thumbnails (open in a browser)

Requirements are the same as ``verify-online`` (Node.js + the playwright npm package).
"""
from __future__ import annotations

import csv
import html
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .airports import AirportDB
from .geo import DEFAULT_METHOD
from .verify_online import (Route, find_node, local_km, node_env, parse_missing_codes, parse_site_text,
                            route_url)

SHOT_JS = Path(__file__).with_name("gcm_screenshot.js")
DIR_SUFFIX = "_greatcirclemap截圖"
STATUSES = ("match", "mismatch", "site_missing", "error")
INDEX_COLUMNS = ("route", "origin", "dest", "site_km", "sheet_km", "status", "screenshot", "rows", "url",
                 "captured_at", "note")


@dataclass
class RouteJob:
    origin: str
    dest: str
    sheet_km: Optional[int] = None          # value in 距離 (from the fill report), if known
    rows: List[int] = field(default_factory=list)

    @property
    def route(self) -> str:
        return f"{self.origin}-{self.dest}"

    @property
    def url(self) -> str:
        return route_url([(self.origin, self.dest)])


@dataclass
class ShotResult:
    job: RouteJob
    site_km: Optional[int]
    status: str                              # one of STATUSES
    screenshot: str = ""                     # file name inside the folder ("" if none)
    captured_at: str = ""
    note: str = ""


# ---------------------------------------------------------------------------
# input
# ---------------------------------------------------------------------------

def _to_km(value: str) -> Optional[int]:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    try:
        return int(float(value) + 0.5)
    except ValueError:
        return None


def jobs_from_report(path: Path) -> List[RouteJob]:
    """One job per distinct directed route that has a distance in a ``fill`` report CSV."""
    jobs: Dict[Route, RouteJob] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            a = (row.get("origin_iata") or "").strip().upper()
            b = (row.get("dest_iata") or "").strip().upper()
            km = _to_km(row.get("km") or "")
            if not (a and b) or km is None:
                continue
            job = jobs.setdefault((a, b), RouteJob(a, b, km))
            if job.sheet_km is None:
                job.sheet_km = km
            try:
                job.rows.append(int(row.get("row") or 0))
            except ValueError:
                pass
    return list(jobs.values())


def jobs_from_routes(routes: Sequence[Route]) -> List[RouteJob]:
    return [RouteJob(a, b) for a, b in routes]


def default_out_dir(report: Optional[Path]) -> Path:
    if report is None:
        return Path("greatcirclemap截圖")
    report = Path(report)
    stem = report.stem[:-len("_report")] if report.stem.endswith("_report") else report.stem
    return report.with_name(stem + DIR_SUFFIX)


def free_dir(path: Path) -> Path:
    """*path* if it does not exist or is empty, else ``path(2)``, ``path(3)`` … (never mixes runs)."""
    path = Path(path)
    if not path.exists() or (path.is_dir() and not any(path.iterdir())):
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.name}({n})")
        if not candidate.exists():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Playwright runner
# ---------------------------------------------------------------------------

def run_screenshot_js(jobs: Sequence[dict], width: int = 1280, height: int = 800) -> List[dict]:
    """Run ``gcm_screenshot.js`` once for all *jobs* (``[{url, path}]``)."""
    node = find_node()
    if not node:
        raise RuntimeError("找不到 node；screenshots 需要 Node.js 與 playwright（見 README）")
    if not SHOT_JS.is_file():
        raise RuntimeError(f"找不到 {SHOT_JS}")
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "jobs.json"
        spec.write_text(json.dumps({"width": width, "height": height, "jobs": list(jobs)}, ensure_ascii=False),
                        encoding="utf-8")
        proc = subprocess.run([node, str(SHOT_JS), str(spec)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=node_env(),
                              timeout=120 + 60 * len(jobs))
    out = proc.stdout.strip()
    try:
        data = json.loads(out) if out else []
    except json.JSONDecodeError:
        data = []
    if proc.returncode != 0 and not any(d.get("text") for d in data):
        err = (data[0].get("error") if data else "") or proc.stderr.strip()[-800:] or f"exit {proc.returncode}"
        hint = ""
        if "Cannot find module" in err:
            hint = "；請先 npm install -g playwright && npx playwright install chromium，並設定 NODE_PATH=$(npm root -g)"
        raise RuntimeError(f"Playwright 截圖失敗：{err}{hint}")
    return data


Shooter = Callable[[Sequence[dict]], List[dict]]


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------

def _final_name(job: RouteJob, status: str, site_km: Optional[int], expected: Optional[int]) -> str:
    if status == "match":
        return f"{job.route}_{site_km}km.png"
    if status == "mismatch":
        return f"{job.route}_網站{site_km}km_表內{expected}km.png"
    if status == "site_missing":
        return f"{job.route}_網站無此機場.png"
    return f"{job.route}_錯誤.png"


def take_screenshots(jobs: Sequence[RouteJob], out_dir: Path, db: Optional[AirportDB] = None,
                     method: str = DEFAULT_METHOD, width: int = 1280, height: int = 800,
                     shoot: Optional[Shooter] = None) -> List[ShotResult]:
    """Capture every job into *out_dir* (created) and write ``index.csv`` + ``index.html`` there."""
    shoot = shoot or run_screenshot_js
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = [{"url": j.url, "path": str((out_dir / f"_tmp_{i:04d}.png").resolve())} for i, j in enumerate(jobs)]
    raw = shoot(specs) if specs else []
    by_path = {str(d.get("path")): d for d in raw if d.get("path")}

    results: List[ShotResult] = []
    for job, spec in zip(jobs, specs):
        item = by_path.get(spec["path"], {"error": "截圖程式沒有回傳此路線"})
        text = item.get("text") or ""
        site_km = parse_site_text(text).get((job.origin, job.dest))
        missing = [c for c in parse_missing_codes(text) if c in (job.origin, job.dest)]
        expected = job.sheet_km
        if expected is None and db is not None:
            expected = local_km(db, job.origin, job.dest, method)
        note = ""
        if missing:
            status = "site_missing"
            note = "網站資料庫沒有 " + "、".join(missing) + "（截圖顯示網站的錯誤訊息）"
        elif site_km is None:
            status = "error"
            note = item.get("error") or "網站頁面未顯示此路線的距離"
        elif expected is None or site_km == expected:
            status = "match"
            if expected is None:
                note = "無表內數值可比對"
        else:
            status = "mismatch"
            note = f"網站 {site_km} km，表內 {expected} km（差 {expected - site_km:+d} km）"

        tmp = Path(spec["path"])
        name = ""
        if tmp.is_file():
            name = _final_name(job, status, site_km, expected)
            target = out_dir / name
            if target.exists():
                target.unlink()
            tmp.replace(target)
        results.append(ShotResult(job, site_km, status, name, item.get("captured_at") or "", note))

    write_index_csv(results, out_dir / "index.csv")
    write_index_html(results, out_dir / "index.html")
    return results


# ---------------------------------------------------------------------------
# index files
# ---------------------------------------------------------------------------

def _rows_text(rows: Sequence[int]) -> str:
    return ";".join(str(r) for r in rows)


def write_index_csv(results: Sequence[ShotResult], path: Path) -> Path:
    path = Path(path)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(INDEX_COLUMNS), lineterminator="\n")
        w.writeheader()
        for r in results:
            j = r.job
            w.writerow({"route": j.route, "origin": j.origin, "dest": j.dest,
                        "site_km": "" if r.site_km is None else r.site_km,
                        "sheet_km": "" if j.sheet_km is None else j.sheet_km,
                        "status": r.status, "screenshot": r.screenshot, "rows": _rows_text(j.rows),
                        "url": j.url, "captured_at": r.captured_at, "note": r.note})
    return path


_STATUS_LABEL = {"match": "相符", "mismatch": "不符", "site_missing": "網站無此機場", "error": "錯誤"}


def write_index_html(results: Sequence[ShotResult], path: Path) -> Path:
    e = html.escape
    counts = {s: sum(1 for r in results if r.status == s) for s in STATUSES}
    rows = []
    for r in results:
        j = r.job
        img = (f'<a href="{e(r.screenshot)}"><img src="{e(r.screenshot)}" alt="{e(j.route)}" loading="lazy"></a>'
               if r.screenshot else "")
        rows.append(
            f'<tr class="{e(r.status)}"><td>{e(j.route)}</td>'
            f'<td class="n">{"" if r.site_km is None else r.site_km}</td>'
            f'<td class="n">{"" if j.sheet_km is None else j.sheet_km}</td>'
            f'<td>{e(_STATUS_LABEL.get(r.status, r.status))}</td>'
            f'<td>{e(_rows_text(j.rows).replace(";", ", "))}</td>'
            f'<td><a href="{e(j.url)}">開啟網站</a><br><small>{e(r.captured_at)}</small></td>'
            f'<td>{img}<div class="note">{e(r.note)}</div></td></tr>')
    summary = "、".join(f"{_STATUS_LABEL[s]} {n}" for s, n in counts.items())
    page = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>greatcirclemap.com 距離截圖</title>
<style>
body{{font:14px/1.5 system-ui,"Microsoft JhengHei",sans-serif;margin:16px;color:#222;background:#fff}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:6px;vertical-align:top;text-align:left}}
th{{background:#f2f2f2;position:sticky;top:0}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
img{{width:320px;max-width:40vw;border:1px solid #aaa}}
tr.mismatch td,tr.error td{{background:#fde8e8}}
tr.site_missing td{{background:#fff6dc}}
.note{{color:#555;font-size:12px}}
</style></head><body>
<h1>greatcirclemap.com 距離截圖</h1>
<p>共 {len(results)} 條路線：{e(summary)}。每張截圖底部的黑色列為本工具加註的網址與擷取時間。</p>
<table><thead><tr><th>路線</th><th>網站 km</th><th>表內 km</th><th>結果</th><th>工作表列</th><th>網址／時間</th><th>截圖</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table></body></html>
"""
    Path(path).write_text(page, encoding="utf-8")
    return Path(path)


def summarize(results: Sequence[ShotResult], out_dir: Path) -> str:
    counts = {s: sum(1 for r in results if r.status == s) for s in STATUSES}
    lines = [f"screenshots：共 {len(results)} 條路線 → " + "、".join(f"{s}={n}" for s, n in counts.items()),
             f"截圖資料夾：{out_dir}"]
    for r in results:
        if r.status != "match":
            lines.append(f"  {r.status:<12} {r.job.route}  網站={r.site_km}  表內={r.job.sheet_km}  {r.note}")
    return "\n".join(lines)
