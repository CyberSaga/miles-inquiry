"""Core: open the workbook, resolve codes, compute distances, write notes/report."""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from .geo import METHODS, distance_km, round_km
from .hsr import hsr_note, is_hsr_like
from .lookup import Lookup, Resolution
from .overrides import Overrides

GCM_URL = "https://www.greatcirclemap.com/?routes={o}-{d}"
NOTE_SEP = "；"
DEFAULT_SHEET = "航空"

# header text (normalised: NFKC, whitespace removed) → role
HEADER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "origin": ("航班(起站)", "起站", "航班起站"),
    "dest": ("航班(迄站)", "迄站", "航班迄站"),
    "distance": ("距離", "距離(km)", "距離km"),
    "pax": ("人次",),
    "note": ("備註",),
}
REQUIRED_ROLES = ("origin", "dest", "distance")

STATUSES = ("filled", "kept", "hsr", "unresolved", "skipped")


def _norm_header(value) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", "", text)


@dataclass
class Options:
    sheet: str = DEFAULT_SHEET
    method: str = "vincenty"
    decimals: int = 0
    overwrite: bool = False
    fill_hsr_distance: bool = False
    max_header_scan: int = 20

    def __post_init__(self):
        if self.method not in METHODS:
            raise ValueError(f"method 必須是 {METHODS} 之一，收到 {self.method!r}")


@dataclass
class RowResult:
    row: int
    origin_raw: str
    dest_raw: str
    origin_iata: Optional[str]
    dest_iata: Optional[str]
    km: Optional[float]
    status: str
    url: str = ""
    note: str = ""          # everything worth telling (report)
    cell_notes: List[str] = field(default_factory=list)   # what went into 備註

    def as_report_row(self) -> dict:
        return {
            "row": self.row,
            "origin_raw": self.origin_raw,
            "dest_raw": self.dest_raw,
            "origin_iata": self.origin_iata or "",
            "dest_iata": self.dest_iata or "",
            "km": "" if self.km is None else self.km,
            "status": self.status,
            "url": self.url,
            "note": self.note,
        }


REPORT_COLUMNS = ("row", "origin_raw", "dest_raw", "origin_iata", "dest_iata", "km", "status", "url", "note")


@dataclass
class FillSummary:
    input_path: Path
    output_path: Path
    sheet: str
    header_row: int
    columns: Dict[str, int]
    results: List[RowResult]
    counts: Counter = field(default_factory=Counter)
    unresolved: Counter = field(default_factory=Counter)   # raw value → occurrences (not in lookup.csv)
    unresolved_known: Counter = field(default_factory=Counter)   # raw value → occurrences (lookup.csv row with empty iata)
    warnings: List[str] = field(default_factory=list)

    def console_summary(self) -> str:
        lines = [
            f"輸入：{self.input_path}",
            f"輸出：{self.output_path}",
            f"工作表「{self.sheet}」標題列 {self.header_row}，共處理 {len(self.results)} 列",
            "  " + "、".join(f"{s}={self.counts.get(s, 0)}" for s in STATUSES),
        ]
        for w in self.warnings:
            lines.append(f"警告：{w}")
        if self.unresolved:
            lines.append("無法對應的值（請加入 data/lookup.csv，格式 value,iata,review,note）：")
            for raw, n in self.unresolved.most_common():
                lines.append(f"  {raw},,,   # 出現 {n} 次")
        if self.unresolved_known:
            lines.append("lookup.csv 已標為無法對應、需人工決定代碼的值：")
            for raw, n in self.unresolved_known.most_common():
                lines.append(f"  {raw}   # 出現 {n} 次")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def find_header(ws: Worksheet, max_scan: int = 20) -> Tuple[int, Dict[str, int]]:
    """Return (header_row_index, {role: column_index}) – 1-based."""
    alias_to_role = {}
    for role, aliases in HEADER_ALIASES.items():
        for a in aliases:
            alias_to_role[_norm_header(a)] = role
    for r in range(1, min(ws.max_row, max_scan) + 1):
        found: Dict[str, int] = {}
        for c in range(1, ws.max_column + 1):
            role = alias_to_role.get(_norm_header(ws.cell(r, c).value))
            if role and role not in found:
                found[role] = c
        if all(role in found for role in REQUIRED_ROLES):
            return r, found
    raise ValueError(
        f"在工作表「{ws.title}」前 {max_scan} 列找不到標題（需含 航班(起站)、航班(迄站)、距離）"
    )


def split_notes(text) -> List[str]:
    if text is None:
        return []
    parts = re.split(r"[；;]", str(text))
    return [p.strip() for p in parts if p.strip()]


def _contains_run(parts: List[str], run: List[str]) -> bool:
    """True when *run* appears as a contiguous sub-sequence of *parts*."""
    n = len(run)
    return n > 0 and any(parts[i:i + n] == run for i in range(len(parts) - n + 1))


def append_note(existing, note: str) -> str:
    """Append *note* to an existing 備註 string, without duplicating.

    A note may itself contain ``；`` (e.g. a multi-sentence lookup note), so the
    duplicate check compares segment sequences rather than whole strings.
    """
    parts = split_notes(existing)
    new_parts = split_notes(note)
    if not new_parts or _contains_run(parts, new_parts):
        return str(existing) if existing is not None else ""
    parts.extend(new_parts)
    return NOTE_SEP.join(parts)


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _pax_value(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = unicodedata.normalize("NFKC", str(value)).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def unresolved_note(res: Resolution, lookup_name: str = "data/lookup.csv") -> str:
    if res.via == "lookup":  # explicitly marked unresolvable in lookup.csv
        return f"無法對應機場代碼：{res.raw}" + (f"（{res.note}）" if res.note else "")
    return f"無法對應機場代碼：{res.raw}，請更新 {lookup_name}"


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------

def default_output_path(input_path: Path) -> Path:
    input_path = Path(input_path)
    return input_path.with_name(f"{input_path.stem}_距離{input_path.suffix or '.xlsx'}")


def default_report_path(output_path: Path) -> Path:
    output_path = Path(output_path)
    return output_path.with_name(f"{output_path.stem}_report.csv")


def fill_workbook(input_path: Path, output_path: Path, lookup: Lookup,
                  overrides: Optional[Overrides] = None,
                  options: Optional[Options] = None) -> FillSummary:
    options = options or Options()
    overrides = overrides or Overrides({})
    input_path, output_path = Path(input_path), Path(output_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"找不到輸入檔 {input_path}")
    if output_path.resolve() == input_path.resolve():
        raise ValueError("輸出檔不可與輸入檔相同（工具絕不覆寫原始檔）")

    wb = openpyxl.load_workbook(input_path)   # NOT data_only → formulas preserved
    if options.sheet not in wb.sheetnames:
        raise ValueError(f"活頁簿沒有工作表「{options.sheet}」，現有：{wb.sheetnames}")
    ws = wb[options.sheet]
    header_row, cols = find_header(ws, options.max_header_scan)

    summary = FillSummary(input_path, output_path, options.sheet, header_row, cols, [])
    if "note" not in cols:
        summary.warnings.append("找不到「備註」欄，說明只會寫入報表，不會寫入活頁簿")
    if "pax" not in cols:
        summary.warnings.append("找不到「人次」欄，無法依人次=0 排除")

    lookup_name = str(lookup.path) if lookup.path else "data/lookup.csv"

    for r in range(header_row + 1, ws.max_row + 1):
        o_cell = ws.cell(r, cols["origin"])
        d_cell = ws.cell(r, cols["dest"])
        dist_cell = ws.cell(r, cols["distance"])
        pax = _pax_value(ws.cell(r, cols["pax"]).value) if "pax" in cols else None
        note_cell = ws.cell(r, cols["note"]) if "note" in cols else None

        if _is_blank(o_cell.value) and _is_blank(d_cell.value) and pax is None:
            continue  # completely empty row

        res_o = lookup.resolve(o_cell.value)
        res_d = lookup.resolve(d_cell.value)
        result = RowResult(r, res_o.raw, res_d.raw, res_o.iata, res_d.iata, None, "")
        report_notes: List[str] = []

        def add_cell_note(text: str):
            result.cell_notes.append(text)
            if note_cell is not None:
                note_cell.value = append_note(note_cell.value, text)

        # 1. skipped rows ---------------------------------------------------
        if res_o.status == "skip" or res_d.status == "skip" or (pax is not None and pax == 0):
            result.status = "skipped"
            report_notes.append("排除：人次為0或起迄為「無」")
            _finish(result, report_notes, summary)
            continue

        if res_o.iata and res_d.iata:
            result.url = GCM_URL.format(o=res_o.iata, d=res_d.iata)

        # 2. HSR-like (checked first: an HSR row gets only the HSR note) ------
        hsr = is_hsr_like(o_cell.value, d_cell.value, res_o.iata, res_d.iata)
        if hsr:
            add_cell_note(hsr_note(o_cell.value, d_cell.value))
            result.status = "hsr"
            if not options.fill_hsr_distance:
                if not _is_blank(dist_cell.value):
                    result.km = dist_cell.value
                    report_notes.append("已有距離，保留")
                _finish(result, report_notes, summary)
                continue

        # 3. mapping / correction / review notes ----------------------------
        for role, res in (("起站", res_o), ("迄站", res_d)):
            if res.status != "ok":
                continue
            cell_note = res.note_for_cell
            if cell_note:
                add_cell_note(f"{role} {cell_note}")
            else:
                report_note = res.note_for_report
                if report_note:
                    report_notes.append(f"{role} {report_note}")
            if res.via == "direct":
                ap = lookup.airports.get(res.iata)
                if ap is not None and not ap.scheduled_service:
                    add_cell_note(f"{role} {res.iata}（{ap.name}, {ap.iso_country}）無定期航班，請確認代碼")

        # 4. unresolved -----------------------------------------------------
        unresolved = [res for res in (res_o, res_d) if res.status == "unresolved"]
        if unresolved:
            for res in unresolved:
                add_cell_note(unresolved_note(res, lookup_name))
                (summary.unresolved_known if res.via == "lookup" else summary.unresolved)[res.raw] += 1
            result.status = "unresolved"
            if not _is_blank(dist_cell.value):
                result.km = dist_cell.value
                report_notes.append("已有距離，保留")
            _finish(result, report_notes, summary)
            continue

        # 5. distance -------------------------------------------------------
        if not _is_blank(dist_cell.value) and not options.overwrite:
            result.km = dist_cell.value
            if result.status != "hsr":
                result.status = "kept"
            report_notes.append("已有距離，保留（--overwrite 可覆寫）")
            _finish(result, report_notes, summary)
            continue

        ov = overrides.get(res_o.iata, res_d.iata)
        if ov is not None:
            km = round_km(ov.km, options.decimals)
            report_notes.append("距離來自 distance_overrides.csv" + (f"（{ov.source}）" if ov.source else ""))
        else:
            a = lookup.airports.get(res_o.iata)
            b = lookup.airports.get(res_d.iata)
            km = round_km(distance_km(a.lat, a.lon, b.lat, b.lon, options.method), options.decimals)
            if res_o.iata == res_d.iata:
                report_notes.append("起迄相同，距離為 0")
        dist_cell.value = km
        result.km = km
        if result.status != "hsr":
            result.status = "filled"
        _finish(result, report_notes, summary)

    wb.save(output_path)
    return summary


def _finish(result: RowResult, report_notes: List[str], summary: FillSummary) -> None:
    notes = list(result.cell_notes) + [n for n in report_notes if n not in result.cell_notes]
    result.note = NOTE_SEP.join(notes)
    summary.results.append(result)
    summary.counts[result.status] += 1


def write_report(summary: FillSummary, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REPORT_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for res in summary.results:
            writer.writerow(res.as_report_row())
    return path
