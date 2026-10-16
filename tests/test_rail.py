"""高鐵表 距離 from a THSR chainage table + rail_distance_overrides.csv (synthetic data only)."""
from __future__ import annotations

import csv
from pathlib import Path

import openpyxl
import pytest

from miles_inquiry.fill import Options, fill_workbook, write_rail_todo
from miles_inquiry.overrides import Overrides
from miles_inquiry.rail import RailData, station_key

# made-up chainage, NOT the real THSR numbers
STATIONS = "﻿station,km,source\n#c\n台北,10,t\n板橋,17,t\n台中,170,t\n彰化,200,t\n雲林,,\n左營,350.5,t\n"
LOOKUP = ("﻿value,station,review,note\n高雄,左營,,高雄站即左營\n粄橋,板橋,yes,疑為板橋誤植\n"
          "斗六,,,斗六為台鐵站\n苏州北,蘇州北,,\n")
OVERRIDES = "﻿from,to,km,source\n#c\n徐州東,蘇州北,300,12306\n"


@pytest.fixture
def rail_dir(tmp_path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    (d / "thsr_stations.csv").write_text(STATIONS, encoding="utf-8")
    (d / "hsr_lookup.csv").write_text(LOOKUP, encoding="utf-8")
    (d / "rail_distance_overrides.csv").write_text(OVERRIDES, encoding="utf-8")
    return d


def test_station_key():
    assert station_key("臺北車站") == "台北" and station_key(" 彰化站 ") == "彰化"
    assert station_key("左營高鐵站") == "左營" and station_key("站") == "站"


def test_distance_rules(rail_dir):
    rail = RailData.load(rail_dir)
    assert rail.distance("台北", "台中")[0].km == 160
    assert rail.distance("臺中", "台北車站")[0].km == 160          # 臺/台, 車站 suffix, either direction
    d, ra, rb = rail.distance("高雄", "台北")
    assert d.km == 340.5 and ra.station == "左營"
    assert rail.distance("苏州北", "徐州東")[0].km == 300            # alias merges spellings for the override
    assert rail.distance("台中", "雲林")[0].source == "missing_km"
    d, _, rb = rail.distance("台北", "斗六")
    assert d.km is None and rb.non_station
    assert rail.distance("南京南", "全椒")[0].km is None


def build(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "航空"
    ws.append(["公司", "航班(起站)", "航班(迄站)", "距離", "人次", "碳排量", "備註"])
    hsr = wb.create_sheet("高鐵")
    hsr.append(["公司", "單位代號", "單位名稱", "日期", "高鐵(起站)", "高鐵(迄站)", "距離", "人次", "碳排量", "備註"])
    rows = [
        ("台中", "桃園", 1, None),      # 2: J2 is the factor cell – nothing may be written into it
        ("臺北", "臺中", 2, None),      # 3
        ("高雄", "台北", 1, None),      # 4: alias
        ("粄橋", "台中", 1, None),      # 5: review alias → note
        ("台北", "斗六", 1, None),      # 6: non-station
        ("苏州北", "徐州東", 1, None),  # 7: override
        ("南京南", "全椒", 2, None),    # 8: missing pair
        ("全椒", "南京南", 1, None),    # 9: same pair, other direction
        ("無", "無", 0, "排除"),        # 10: skipped
        ("台北", "火星", 1, None),      # 11: unknown value
        ("台中", "雲林", 1, None),      # 12: station without km
    ]
    for o, d, pax, note in rows:
        hsr.append(["X", "B", "C", None, o, d, None, pax, None, note])
    hsr["J2"] = 0.029
    hsr.append(["X", "B", "C", None, "台北", "左營", 345, 1, None, None])   # 13: hand-typed distance kept
    wb.save(path)
    return path


def run(path, lookup, rail_dir, out, **kw):
    return fill_workbook(path, out, lookup, Overrides({}), Options(**kw), RailData.load(rail_dir))


def test_fill_hsr_sheet(lookup, rail_dir, tmp_path):
    out = tmp_path / "o.xlsx"
    s = run(build(tmp_path / "w.xlsx"), lookup, rail_dir, out)
    ws = openpyxl.load_workbook(out)["高鐵"]
    g = {r: ws.cell(r, 7).value for r in range(2, 14)}
    j = {r: ws.cell(r, 10).value for r in range(2, 14)}
    assert g[2] is None and j[2] == 0.029                       # 桃園 not in synthetic table, factor untouched
    assert g[3] == 160 and isinstance(g[3], int) and j[3] is None
    assert g[4] == 340.5 and j[4] is None                        # 高雄→左營 is report-only
    assert g[5] == 153 and j[5] == "起站 粄橋→板橋：疑為板橋誤植"
    assert g[6] is None and j[6] == "迄站「斗六」非高鐵站（斗六為台鐵站），請確認"
    assert g[7] == 300 and j[7] is None
    assert g[8] is None and "非台灣高鐵路段（南京南→全椒）" in j[8]
    assert g[10] is None and j[10] == "排除"
    assert g[11] is None and j[11] == "無法對應高鐵站：火星，請更新 data/hsr_lookup.csv"
    assert g[12] is None and j[12] is None and s.hsr_missing_km["雲林"] == 1
    assert g[13] == 345 and s.hsr_distance_counts["kept"] == 1
    assert s.hsr_distance_counts["thsr"] == 3 and s.hsr_distance_counts["override"] == 1
    assert s.hsr_missing_pairs == {("全椒", "南京南"): [8, 9]}
    # the 碳排量 formula picks the new distance up
    assert ws["I3"].value == '=IF(G3="","",G3*H3*$J$2)'
    text = s.console_summary()
    assert "雲林（1 列）" in text and "火星" in text and "缺距離的站對 1 組" in text

    todo = write_rail_todo(s, tmp_path / "todo.csv")
    rows = list(csv.reader(todo.read_text(encoding="utf-8-sig").splitlines()))
    assert rows == [["from", "to", "km", "source", "rows"], ["全椒", "南京南", "", "", "8 9"]]


def test_hsr_rerun_idempotent_and_flag(lookup, rail_dir, tmp_path):
    src = build(tmp_path / "w.xlsx")
    run(src, lookup, rail_dir, tmp_path / "1.xlsx")
    run(tmp_path / "1.xlsx", lookup, rail_dir, tmp_path / "2.xlsx")
    a, b = (openpyxl.load_workbook(tmp_path / n)["高鐵"] for n in ("1.xlsx", "2.xlsx"))
    assert [[c.value for c in r] for r in a.iter_rows()] == [[c.value for c in r] for r in b.iter_rows()]
    run(src, lookup, rail_dir, tmp_path / "n.xlsx", hsr_distance=False)
    assert openpyxl.load_workbook(tmp_path / "n.xlsx")["高鐵"]["G3"].value is None
