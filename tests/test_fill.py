"""End-to-end tests on a SYNTHETIC workbook built here (never the real sample)."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
from pathlib import Path

import openpyxl
import pytest
from openpyxl.styles import Font, PatternFill

from miles_inquiry.cli import main
from miles_inquiry.fill import (Options, append_note, default_output_path, fill_workbook, find_header, next_free_path,
                                write_report)
from miles_inquiry.overrides import Overrides

HEADERS = ["公司", "單位代號", "單位名稱", "日期", "航班(起站)", "航班(迄站)", "距離", "人次", "碳排量", "備註"]

# (origin, dest, pax, existing_note, existing_distance)
ROWS = [
    ("SHA", "TSA", 1, None, None),                     # 2: direct codes (SHA not in synth DB → unresolved)
    ("無", "無", 0, "排除：人次為0或起迄為「無」", None),  # 3: skipped
    ("澎湖", "高雄", 2, None, None),                   # 4: lookup names
    ("新竹", "台北", 1, None, None),                   # 5: HSR
    ("台中", "台北", 1, None, None),                   # 6: HSR
    ("TAS", "MZG", 1, None, None),                     # 7: correction
    ("MZG", "kHH", 1, "既有備註", None),               # 8: lowercase + existing note
    ("TPE", "JFK", 3, None, None),                     # 9: long haul
    ("TPE", "HONG KONG", 1, None, None),               # 10: name with spaces
    ("火星", "TPE", 1, None, None),                    # 11: unresolved
    ("TSA", "KHH", 1, None, 999),                      # 12: HSR-like with existing distance
    ("MZG", "TSA", 1, None, 123),                      # 13: existing distance kept
    ("0", "TPE", 1, None, None),                       # 14: skipped by '0'
    ("TPE", "MZG", 0, None, None),                     # 15: skipped by pax 0
    ("TPE", "SIA", 1, None, None),                     # 16: correction SIA→SAI
    ("MZG", "MZG", 1, None, None),                     # 17: same airport
    ("台北", "澎湖", 1, None, None),                   # 18: review-flagged lookup (台北→TSA) → note in 備註
    ("TPE", "PNH", 1, None, None),                     # 19: direct code without scheduled service
    ("TPE", "KHH", 1, None, None),                     # 20: real connecting flight between corridor airports → NOT HSR
    ("TPE", None, 2, None, None),                      # 21: blank destination next to a real trip → flag, not skip
    ("", "TPE", 1, "人工備註;舊", None),                # 22: blank origin, existing note kept verbatim
    ("台中站", "台北站", 1, None, None),               # 23: station names with 站 suffix → HSR
    ("TPE", " ", 0, None, None),                       # 24: blank + 人次 0 → still an ordinary skip
]


def build_workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "航空"
    ws.append(HEADERS)
    ws["A1"].font = Font(name="微軟正黑體", bold=True)
    ws["A1"].fill = PatternFill("solid", fgColor="FFDDDDDD")
    ws.column_dimensions["E"].width = 15.9
    for i, (o, d, pax, note, dist) in enumerate(ROWS, start=2):
        ws.append(["測試公司", f"A{i:04d}", "測試分行", dt.datetime(2026, 5, 1), o, d, dist, pax, None, note])
    ws["I2"].value = "=距離*人次*係數"           # literal TEXT that looks like a formula (as in real workbooks)
    ws["I2"].data_type = "s"
    ws["I3"] = "=G3*H3*0.123"                    # real formula
    ws["L2"] = "https://www.greatcirclemap.com/"  # ad-hoc reference note (column L)
    ws["K5"] = "誤植，交通方式應調整為高鐵"
    other = wb.create_sheet("高鐵")
    other.append(["公司", "高鐵(起站)", "高鐵(迄站)", "距離", "人次"])
    other.append(["測試公司", "台北", "左營", 345, 2])
    other["F2"] = "=D2*E2"
    wb.save(path)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def workbook(tmp_path) -> Path:
    return build_workbook(tmp_path / "synthetic.xlsx")


def run(workbook: Path, lookup, out: Path, **kw):
    return fill_workbook(workbook, out, lookup, Overrides({}), Options(**kw))


def test_find_header_tolerates_whitespace_and_fullwidth(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "航空"
    ws.append(["title row"])
    ws.append(["公司", " 航班（起站） ", "航班(迄站)\n", "距離 ", "人次", "備註"])
    p = tmp_path / "h.xlsx"
    wb.save(p)
    row, cols = find_header(openpyxl.load_workbook(p)["航空"])
    assert row == 2 and cols == {"origin": 2, "dest": 3, "distance": 4, "pax": 5, "note": 6}


def test_append_note_idempotent():
    assert append_note(None, "a") == "a"
    assert append_note("x", "a") == "x；a"
    assert append_note("x；a", "a") == "x；a"
    assert append_note("x; a ", "a") == "x; a "
    assert append_note("", "a") == "a"
    assert append_note("   ", "a") == "a"
    # the user's existing text is never rewritten (separators, spacing, numbers)
    assert append_note("人工備註;第二段", "新") == "人工備註;第二段；新"
    assert append_note("x ; y ", "x") == "x ; y "
    assert append_note(12345, "新") == "12345；新"
    assert append_note("x；", "a") == "x；a"
    # notes that themselves contain the separator must not be re-appended
    assert append_note("x", "a；b") == "x；a；b"
    assert append_note("x；a；b", "a；b") == "x；a；b"
    assert append_note("a；x；b", "a；b") == "a；x；b；a；b"
    assert append_note("x", "") == "x"


def test_end_to_end(workbook, lookup, tmp_path):
    before = sha(workbook)
    out = tmp_path / "out.xlsx"
    summary = run(workbook, lookup, out)
    assert sha(workbook) == before, "input file must not be modified"
    assert out.exists()

    by_row = {r.row: r for r in summary.results}
    assert summary.counts["skipped"] == 4 and {3, 14, 15, 24} == {r for r, x in by_row.items() if x.status == "skipped"}
    assert by_row[4].status == "filled" and by_row[4].km == 132          # exactly what greatcirclemap.com shows
    assert by_row[4].origin_iata == "MZG" and by_row[4].dest_iata == "KHH"
    assert by_row[4].url == "https://www.greatcirclemap.com/?routes=MZG-KHH"
    assert by_row[5].status == "hsr" and by_row[5].km is None
    assert by_row[6].status == "hsr" and by_row[6].km is None
    assert by_row[7].status == "filled" and by_row[7].origin_iata == "TSA" and by_row[7].km == 256
    assert by_row[8].status == "filled" and by_row[8].dest_iata == "KHH"
    assert by_row[9].status == "filled" and by_row[9].km == 12566
    assert by_row[10].status == "filled" and by_row[10].dest_iata == "HKG"
    assert by_row[2].status == "unresolved" and by_row[11].status == "unresolved"
    assert by_row[12].status == "hsr" and by_row[12].km == 999
    assert by_row[13].status == "kept" and by_row[13].km == 123
    assert by_row[16].status == "filled" and by_row[16].dest_iata == "SAI"
    assert by_row[17].status == "filled" and by_row[17].km == 0
    assert by_row[18].status == "filled" and by_row[18].origin_iata == "TSA" and by_row[18].km == 256
    assert by_row[19].status == "filled"
    assert by_row[20].status == "filled" and by_row[20].km == 291           # TPE-KHH is a real flight, not HSR
    assert by_row[21].status == "unresolved" and by_row[21].km is None and by_row[21].dest_iata is None
    assert by_row[22].status == "unresolved" and by_row[22].km is None
    assert by_row[23].status == "hsr" and by_row[23].km is None
    assert dict(summary.unresolved) == {"SHA": 1, "火星": 1}                # blanks are not "values to add to lookup.csv"
    assert dict(summary.unresolved_known) == {}
    assert summary.blank_rows == [21, 22]
    assert "火星,,,   # 出現 1 次" in summary.console_summary()
    assert "空白、請補填的列：21、22" in summary.console_summary()

    ws = openpyxl.load_workbook(out)["航空"]
    assert ws["G4"].value == 132 and isinstance(ws["G4"].value, int)
    assert ws["G5"].value is None and ws["G6"].value is None           # HSR rows left blank
    assert ws["G12"].value == 999 and ws["G13"].value == 123           # existing kept
    assert ws["G3"].value is None and ws["G14"].value is None          # skipped
    assert ws["J3"].value == "排除：人次為0或起迄為「無」"             # not duplicated/changed
    assert ws["J5"].value == "疑似高鐵(新竹↔台北)，請確認交通方式並移至高鐵表"
    assert ws["J6"].value == "疑似高鐵(台中↔台北)，請確認交通方式並移至高鐵表"
    assert "TAS→TSA 疑為代碼誤植" in ws["J7"].value and "疑為 TSA 誤植" in ws["J7"].value
    assert ws["J8"].value == "既有備註"                                 # untouched (no note needed)
    # short data/lookup.csv-style name in the workbook, never the machine's absolute path
    assert ws["J11"].value == f"無法對應機場代碼：火星，請更新 {lookup.path.parent.name}/lookup.csv"
    assert str(lookup.path.parent.parent) not in ws["J11"].value
    assert "疑似高鐵(TSA↔KHH)" in ws["J12"].value
    assert ws["J20"].value is None and ws["G20"].value == 291
    assert ws["J21"].value == "迄站空白，請補填" and ws["G21"].value is None
    assert ws["J22"].value == "人工備註;舊；起站空白，請補填"              # existing text untouched, note appended
    assert ws["J23"].value == "疑似高鐵(台中站↔台北站)，請確認交通方式並移至高鐵表"
    assert ws["J24"].value is None and ws["G24"].value is None               # skipped: untouched
    # correction note + "coordinates not from the site" note (SAI is absent from greatcirclemap data)
    assert ws["J16"].value == ("迄站 SIA→SAI 疑為代碼誤植（SIA 已停用）請確認；"
                               "迄站 SAI 不在 greatcirclemap 資料庫，座標取自 OurAirports（Siem Reap-Angkor International Airport）")
    assert "greatcirclemap" not in ws["J4"].value if ws["J4"].value else True   # on-site codes get no such note
    assert ws["J18"].value == "起站 台北→TSA：台北預設松山；國際線請改 TPE"
    assert "PNH" in ws["J19"].value and "無定期航班" in ws["J19"].value
    # HSR rows get ONLY the HSR note, not the 台北→TSA review note
    assert "台北→TSA" not in ws["J5"].value and "台北→TSA" not in ws["J6"].value
    # preserved content
    assert ws["I2"].value == "=距離*人次*係數" and ws["I2"].data_type == "s"
    assert ws["I3"].value == "=G3*H3*0.123" and ws["I3"].data_type == "f"
    assert ws["L2"].value == "https://www.greatcirclemap.com/" and ws["K5"].value == "誤植，交通方式應調整為高鐵"
    assert ws["A1"].font.name == "微軟正黑體" and ws["A1"].font.bold
    assert ws.column_dimensions["E"].width == pytest.approx(15.9)
    other = openpyxl.load_workbook(out)["高鐵"]
    assert [c.value for c in other[2]][:5] == ["測試公司", "台北", "左營", 345, 2] and other["F2"].value == "=D2*E2"


def test_rerun_is_idempotent(workbook, lookup, tmp_path):
    out1 = tmp_path / "pass1.xlsx"
    out2 = tmp_path / "pass2.xlsx"
    run(workbook, lookup, out1)
    s2 = run(out1, lookup, out2)
    ws1 = openpyxl.load_workbook(out1)["航空"]
    ws2 = openpyxl.load_workbook(out2)["航空"]
    for r in range(1, ws1.max_row + 1):
        for c in range(1, ws1.max_column + 1):
            assert ws1.cell(r, c).value == ws2.cell(r, c).value, ws1.cell(r, c).coordinate
    assert s2.counts["kept"] >= 1 and s2.counts["filled"] == 0  # everything already filled is kept


def test_overwrite_and_fill_hsr(workbook, lookup, tmp_path):
    out = tmp_path / "ow.xlsx"
    s = run(workbook, lookup, out, overwrite=True, fill_hsr_distance=True, method="haversine", decimals=1)
    by_row = {r.row: r for r in s.results}
    ws = openpyxl.load_workbook(out)["航空"]
    assert ws["G13"].value != 123 and ws["G13"].value == pytest.approx(255.8, abs=1.0)
    assert by_row[12].status == "hsr" and ws["G12"].value == pytest.approx(302.9, abs=1.0)   # TSA-KHH filled
    assert by_row[6].status == "hsr" and isinstance(ws["G6"].value, float)                 # RMQ-TSA filled
    assert by_row[5].status == "unresolved"   # 新竹 still has no airport even with --fill-hsr-distance
    assert dict(s.unresolved_known) == {"新竹": 1} and "需人工決定" in s.console_summary()


def test_overrides_take_precedence(workbook, lookup, tmp_path):
    ov_path = tmp_path / "ov.csv"
    ov_path.write_text("from,to,km,source\n#comment\nJFK,TPE,12570,gcm\n", encoding="utf-8-sig")
    ov = Overrides.load(ov_path)
    s = fill_workbook(workbook, tmp_path / "ov.xlsx", lookup, ov, Options())
    r = {x.row: x for x in s.results}[9]
    assert r.km == 12570 and "distance_overrides" in r.note and "gcm" in r.note


def test_output_equals_input_refused(workbook, lookup):
    with pytest.raises(ValueError):
        run(workbook, lookup, workbook)


def test_missing_sheet(workbook, lookup, tmp_path):
    with pytest.raises(ValueError):
        run(workbook, lookup, tmp_path / "x.xlsx", sheet="不存在")


def test_report_csv(workbook, lookup, tmp_path):
    s = run(workbook, lookup, tmp_path / "r.xlsx")
    rp = write_report(s, tmp_path / "r.csv")
    raw = rp.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(rp.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == len(ROWS)
    assert rows[0].keys() >= {"row", "origin_raw", "dest_raw", "origin_iata", "dest_iata", "km", "status", "url", "note"}
    assert any(r["status"] == "hsr" for r in rows)
    assert "ultimately" not in s.console_summary() and "火星" in s.console_summary()


def test_default_output_path():
    assert default_output_path(Path("/x/碳盤查.xlsx")) == Path("/x/碳盤查_距離.xlsx")
    assert default_output_path(Path("/x/巨集.xlsm")) == Path("/x/巨集_距離.xlsm")


def test_next_free_path(tmp_path):
    p = tmp_path / "a_距離.xlsx"
    assert next_free_path(p) == p
    p.write_bytes(b"x")
    assert next_free_path(p) == tmp_path / "a_距離(2).xlsx"
    (tmp_path / "a_距離(2).xlsx").write_bytes(b"x")
    assert next_free_path(p) == tmp_path / "a_距離(3).xlsx"
    assert next_free_path(tmp_path / "a_距離(2).xlsx") == tmp_path / "a_距離(3).xlsx"


def test_blank_endpoint_is_flagged_not_skipped(lookup, tmp_path):
    """A missing 起站/迄站 next to a real trip is a data-entry gap: flag it, keep the distance blank."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "航空"
    ws.append(HEADERS)
    ws.append(["c", "1", "u", None, None, "TPE", None, 1, None, None])        # origin None
    ws.append(["c", "1", "u", None, "TPE", "", None, 2, None, None])          # dest ''
    ws.append(["c", "1", "u", None, "  ", "TPE", None, 1, None, "舊備註"])    # whitespace origin
    ws.append(["c", "1", "u", None, None, None, None, 3, None, None])         # both blank but 3 pax
    ws.append([None] * 10)                                                    # really empty row → ignored
    src = tmp_path / "b.xlsx"
    wb.save(src)
    s = run(src, lookup, tmp_path / "b_out.xlsx")
    assert [r.status for r in s.results] == ["unresolved"] * 4 and s.counts["skipped"] == 0
    assert s.blank_rows == [2, 3, 4, 5]
    out = openpyxl.load_workbook(tmp_path / "b_out.xlsx")["航空"]
    assert out["J2"].value == "起站空白，請補填"
    assert out["J3"].value == "迄站空白，請補填"
    assert out["J4"].value == "舊備註；起站空白，請補填"
    assert out["J5"].value == "起站空白，請補填；迄站空白，請補填"
    assert all(out.cell(r, 7).value is None for r in range(2, 6))
    assert "排除" not in (s.results[0].note or "")
    # idempotent
    s2 = run(tmp_path / "b_out.xlsx", lookup, tmp_path / "b_out2.xlsx")
    assert openpyxl.load_workbook(tmp_path / "b_out2.xlsx")["航空"]["J5"].value == "起站空白，請補填；迄站空白，請補填"


def test_same_code_lookup_row_suppresses_scheduled_service_warning(tmp_path, airports):
    """CMJ/WOT/GNI/PNH-style entries: a same-code row in lookup.csv replaces the generic OurAirports warning."""
    from miles_inquiry.lookup import Lookup
    lp = tmp_path / "l.csv"
    lp.write_text("value,iata,review,note\nPNH,PNH,,金邊舊機場\n", encoding="utf-8")
    lk = Lookup.load(lp, airports)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "航空"
    ws.append(HEADERS)
    ws.append(["c", "1", "u", None, "TPE", "PNH", None, 1, None, None])
    src = tmp_path / "p.xlsx"
    wb.save(src)
    s = run(src, lk, tmp_path / "p_out.xlsx")
    assert s.results[0].status == "filled" and "無定期航班" not in s.results[0].note and "金邊舊機場" in s.results[0].note
    assert openpyxl.load_workbook(tmp_path / "p_out.xlsx")["航空"]["J2"].value is None


def test_xlsm_keeps_macro_content_type_and_refuses_xlsx_output(workbook, lookup, tmp_path):
    import shutil
    import zipfile
    src = tmp_path / "m.xlsm"
    shutil.copy(workbook, src)
    out = tmp_path / "m_距離.xlsm"
    run(src, lookup, out)
    with zipfile.ZipFile(out) as z:
        assert "macroEnabled" in z.read("[Content_Types].xml").decode()
    with pytest.raises(ValueError):
        run(src, lookup, tmp_path / "m.xlsx")


def test_unsupported_or_corrupt_input_gives_chinese_error(lookup, tmp_path):
    xls = tmp_path / "old.xls"
    xls.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 64)
    with pytest.raises(ValueError, match="不支援"):
        run(xls, lookup, tmp_path / "o.xlsx")
    fake = tmp_path / "fake.xlsx"
    fake.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不是有效"):
        run(fake, lookup, tmp_path / "o2.xlsx")


def test_cli_end_to_end(workbook, lookup_path, tmp_path, monkeypatch, capsys):
    # synthetic airports.csv for the CLI
    from tests.conftest import SYNTH_AIRPORTS
    ap = tmp_path / "airports.csv"
    with ap.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["iata", "name", "municipality", "iso_country", "type", "lat", "lon", "scheduled_service"])
        for a in SYNTH_AIRPORTS:
            w.writerow([a.iata, a.name, a.municipality, a.iso_country, a.type, a.lat, a.lon, "yes" if a.scheduled_service else "no"])
    out = tmp_path / "cli_out.xlsx"
    rc = main(["fill", str(workbook), "-o", str(out), "--lookup", str(lookup_path), "--airports", str(ap)])
    assert rc == 0
    assert out.exists() and (tmp_path / "cli_out_report.csv").exists()
    text = capsys.readouterr().out
    assert "filled=" in text and "火星" in text

    # default output path next to the input, never the input itself
    rc = main(["fill", str(workbook), "--lookup", str(lookup_path), "--airports", str(ap), "--no-report"])
    assert rc == 0 and (tmp_path / "synthetic_距離.xlsx").exists()
    capsys.readouterr()

    # an existing output (and report) is never clobbered: the re-run goes to 檔名(2).xlsx
    (tmp_path / "cli_out.xlsx").write_bytes(b"hand-edited")
    (tmp_path / "cli_out_report.csv").write_bytes(b"hand-edited")
    rc = main(["fill", str(workbook), "-o", str(out), "--lookup", str(lookup_path), "--airports", str(ap)])
    text = capsys.readouterr().out
    assert rc == 0 and "已存在" in text and "cli_out(2).xlsx" in text
    assert (tmp_path / "cli_out.xlsx").read_bytes() == b"hand-edited"
    assert (tmp_path / "cli_out_report.csv").read_bytes() == b"hand-edited"
    assert (tmp_path / "cli_out(2).xlsx").exists() and (tmp_path / "cli_out(2)_report.csv").exists()
    # … unless --overwrite-output is given
    rc = main(["fill", str(workbook), "-o", str(out), "--lookup", str(lookup_path), "--airports", str(ap), "--overwrite-output"])
    assert rc == 0 and (tmp_path / "cli_out.xlsx").read_bytes() != b"hand-edited"
    assert (tmp_path / "cli_out_report.csv").read_bytes() != b"hand-edited"
    assert not (tmp_path / "cli_out(3).xlsx").exists()
    capsys.readouterr()

    # --data-dir is accepted after the sub-command too (README documents it in the fill options table)
    rc = main(["fill", str(workbook), "-o", str(tmp_path / "dd.xlsx"), "--lookup", str(lookup_path),
               "--airports", str(ap), "--no-report", "--data-dir", str(tmp_path)])
    assert rc == 0 and (tmp_path / "dd.xlsx").exists()
    capsys.readouterr()

    rc = main(["fill", str(tmp_path / "missing.xlsx"), "--lookup", str(lookup_path), "--airports", str(ap)])
    assert rc == 1 and "錯誤" in capsys.readouterr().err


def test_cli_file_errors_are_chinese_not_tracebacks(workbook, lookup_path, tmp_path, capsys):
    from tests.conftest import SYNTH_AIRPORTS
    ap = tmp_path / "airports.csv"
    with ap.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["iata", "name", "municipality", "iso_country", "type", "lat", "lon", "scheduled_service"])
        for a in SYNTH_AIRPORTS:
            w.writerow([a.iata, a.name, a.municipality, a.iso_country, a.type, a.lat, a.lon, "yes"])
    common = ["--lookup", str(lookup_path), "--airports", str(ap), "--no-report"]
    # text file with an .xlsx name
    fake = tmp_path / "fake.xlsx"
    fake.write_text("not a workbook", encoding="utf-8")
    assert main(["fill", str(fake), *common]) == 1
    err = capsys.readouterr().err
    assert err.startswith("錯誤：") and "不是有效" in err
    # legacy .xls
    xls = tmp_path / "old.xls"
    xls.write_bytes(b"\xd0\xcf\x11\xe0")
    assert main(["fill", str(xls), *common]) == 1 and "不支援" in capsys.readouterr().err
    # output path that cannot be written (a directory stands in for a file locked by Excel)
    locked = tmp_path / "locked.xlsx"
    locked.mkdir()
    assert main(["fill", str(workbook), "-o", str(locked), *common, "--overwrite-output"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("錯誤：") and "Traceback" not in err
    # report path unwritable
    rep_dir = tmp_path / "rep.csv"
    rep_dir.mkdir()
    assert main(["fill", str(workbook), "-o", str(tmp_path / "r.xlsx"), "--lookup", str(lookup_path), "--airports", str(ap),
                 "--report", str(rep_dir), "--overwrite-output"]) == 1
    assert capsys.readouterr().err.startswith("錯誤：")
