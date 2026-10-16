"""screenshots logic – tested offline with a fake shooter (no network, no Playwright)."""
from __future__ import annotations

import csv
from pathlib import Path

from miles_inquiry import cli
from miles_inquiry.screenshots import (RouteJob, default_out_dir, free_dir, jobs_from_report, jobs_from_routes,
                                       take_screenshots)

PNG = b"\x89PNG\r\n\x1a\n fake"


def page(a: str, b: str, km: int) -> str:
    return f"Great Circle Map\nRaw input\n{a} ⇾ {b}\n{km} km\n© 2017-2026 Markus Englund\n"


def fake_shooter(site: dict):
    """site: {"TPE-JFK": 12566 | None (missing code) | "boom" (page error)}."""
    def shoot(specs):
        out = []
        for spec in specs:
            route = spec["url"].rsplit("=", 1)[1]
            a, b = route.split("-")
            v = site[route]
            if v == "boom":
                out.append({"url": spec["url"], "path": spec["path"], "text": "", "error": "Timeout"})
                continue
            Path(spec["path"]).write_bytes(PNG)
            text = page(a, b, v) if isinstance(v, int) else f"'{b}' does not exist in our database"
            out.append({"url": spec["url"], "path": spec["path"], "text": text,
                        "captured_at": "2026-10-12 21:00:00 UTC+08:00", "error": None})
        return out
    return shoot


def write_report(path: Path, rows) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["row", "origin_raw", "dest_raw", "origin_iata", "dest_iata", "km", "status", "url", "note"])
        w.writerows(rows)
    return path


def test_jobs_from_report_dedupes_directed_routes(tmp_path: Path):
    rep = write_report(tmp_path / "x_report.csv", [
        [2, "TPE", "JFK", "TPE", "JFK", 12566, "filled", "", ""],
        [3, "無", "無", "", "", "", "skipped", "", ""],
        [4, "TPE", "JFK", "TPE", "JFK", "12566", "kept", "", ""],
        [5, "JFK", "TPE", "JFK", "TPE", 12566, "filled", "", ""],
        [6, "新竹", "台北", "", "TSA", "", "hsr", "", ""],
        [7, "LAX", "TAP", "LAX", "", "", "unresolved", "", ""],
    ])
    jobs = jobs_from_report(rep)
    assert [(j.route, j.sheet_km) for j in jobs] == [("TPE-JFK", 12566), ("JFK-TPE", 12566)]


def test_take_screenshots_names_files_and_writes_index(tmp_path: Path):
    jobs = [RouteJob("TPE", "JFK", 12566), RouteJob("KHH", "SAI", 1986),
            RouteJob("LAX", "SEA", 1536), RouteJob("SEA", "IAH", 3020)]
    out = tmp_path / "shots"
    res = take_screenshots(jobs, out, shoot=fake_shooter(
        {"TPE-JFK": 12566, "KHH-SAI": None, "LAX-SEA": 1535, "SEA-IAH": "boom"}))
    assert [r.status for r in res] == ["match", "site_missing", "mismatch", "error"]
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted(["TPE-JFK_12566km.png", "KHH-SAI_網站無此機場.png", "LAX-SEA_網站1535km_表內1536km.png",
                            "index.csv", "index.html"])
    assert not any(n.startswith("_tmp_") for n in names)
    with (out / "index.csv").open(encoding="utf-8-sig") as fh:
        idx = list(csv.DictReader(fh))
    assert "rows" not in idx[0] and idx[0]["site_km"] == "12566" and idx[0]["screenshot"] == "TPE-JFK_12566km.png"
    assert idx[0]["url"] == "https://www.greatcirclemap.com/?routes=TPE-JFK"
    assert idx[3]["status"] == "error" and idx[3]["screenshot"] == "" and "Timeout" in idx[3]["note"]
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'src="TPE-JFK_12566km.png"' in html and "網站無此機場" in html and "工作表列" not in html


def test_routes_mode_without_sheet_value_still_records_site_km(tmp_path: Path):
    res = take_screenshots(jobs_from_routes([("MZG", "KHH")]), tmp_path / "s",
                           shoot=fake_shooter({"MZG-KHH": 132}))
    assert res[0].status == "match" and res[0].site_km == 132 and res[0].screenshot == "MZG-KHH_132km.png"


def test_default_and_free_dir(tmp_path: Path):
    rep = tmp_path / "碳盤查_距離_report.csv"
    assert default_out_dir(rep) == tmp_path / "碳盤查_距離_greatcirclemap截圖"
    d = tmp_path / "shots"
    assert free_dir(d) == d
    d.mkdir()
    assert free_dir(d) == d                      # empty folder is reused
    (d / "old.png").write_bytes(PNG)
    assert free_dir(d) == tmp_path / "shots(2)"  # never mixes two runs


def test_cli_screenshots_offline(tmp_path: Path, monkeypatch, capsys):
    import miles_inquiry.screenshots as shots
    monkeypatch.setattr(shots, "run_screenshot_js", fake_shooter({"TPE-JFK": 12566}))
    rep = write_report(tmp_path / "x_report.csv", [[2, "TPE", "JFK", "TPE", "JFK", 12566, "filled", "", ""]])
    rc = cli.main(["screenshots", "--report", str(rep)])
    assert rc == 0
    assert (tmp_path / "x_greatcirclemap截圖" / "TPE-JFK_12566km.png").is_file()
    assert "match=1" in capsys.readouterr().out


def counting(site: dict):
    inner, seen = fake_shooter(site), []

    def shoot(specs):
        seen.extend(s["url"].rsplit("=", 1)[1] for s in specs)
        return inner(specs)
    shoot.seen = seen
    return shoot


def test_incremental_reuses_existing_routes(tmp_path: Path):
    out = tmp_path / "shots"
    site = {"TPE-JFK": 12566, "KHH-SAI": None, "LAX-SEA": 1535, "SEA-IAH": 3020, "MZG-KHH": 132}
    first = counting(site)
    take_screenshots([RouteJob("TPE", "JFK", 12566), RouteJob("KHH", "SAI", 1986), RouteJob("LAX", "SEA", 1536)],
                     out, shoot=first, reuse=True)
    assert first.seen == ["TPE-JFK", "KHH-SAI", "LAX-SEA"]
    (out / "TPE-JFK_12566km.png").write_bytes(b"original evidence")

    second = counting(site)
    res = take_screenshots([RouteJob("TPE", "JFK", 12566), RouteJob("KHH", "SAI", 1986),
                            RouteJob("LAX", "SEA", 1536), RouteJob("SEA", "IAH", 3020)],
                           out, shoot=second, reuse=True)
    # kept: match + site_missing; retried: the earlier mismatch; new: SEA-IAH
    assert sorted(second.seen) == ["LAX-SEA", "SEA-IAH"]
    assert (out / "TPE-JFK_12566km.png").read_bytes() == b"original evidence"
    assert [(r.job.route, r.reused) for r in res] == [("TPE-JFK", True), ("KHH-SAI", True),
                                                       ("LAX-SEA", False), ("SEA-IAH", False)]
    idx = list(csv.DictReader((out / "index.csv").open(encoding="utf-8-sig")))
    assert [r["route"] for r in idx] == ["TPE-JFK", "KHH-SAI", "LAX-SEA", "SEA-IAH"]
    assert idx[0]["captured_at"] == "2026-10-12 21:00:00 UTC+08:00"
    assert not any(p.name.startswith("_tmp_") for p in out.iterdir())


def test_incremental_reshoots_when_sheet_value_differs_and_keeps_dropped_routes(tmp_path: Path):
    out = tmp_path / "shots"
    take_screenshots([RouteJob("TPE", "JFK", 12566), RouteJob("MZG", "KHH", 132)], out,
                     shoot=fake_shooter({"TPE-JFK": 12566, "MZG-KHH": 132}), reuse=True)
    again = counting({"TPE-JFK": 12570})
    res = take_screenshots([RouteJob("TPE", "JFK", 12570)], out, shoot=again, reuse=True)
    assert again.seen == ["TPE-JFK"]                       # the old shot no longer proves 12570
    names = sorted(p.name for p in out.iterdir())
    assert "TPE-JFK_12566km.png" not in names and "TPE-JFK_網站12570km_表內12570km.png" not in names
    assert "TPE-JFK_12570km.png" in names and "MZG-KHH_132km.png" in names   # dropped route's file stays
    assert [(r.job.route, r.reused) for r in res] == [("TPE-JFK", False), ("MZG-KHH", True)]


def test_cli_incremental_and_fresh(tmp_path: Path, monkeypatch, capsys):
    import miles_inquiry.screenshots as shots
    shooter = counting({"TPE-JFK": 12566, "MZG-KHH": 132})
    monkeypatch.setattr(shots, "run_screenshot_js", shooter)
    rep = write_report(tmp_path / "x_report.csv", [[2, "TPE", "JFK", "TPE", "JFK", 12566, "filled", "", ""]])
    assert cli.main(["screenshots", "--report", str(rep)]) == 0
    capsys.readouterr()
    rep = write_report(tmp_path / "x_report.csv", [[2, "TPE", "JFK", "TPE", "JFK", 12566, "filled", "", ""],
                                                   [9, "MZG", "KHH", "MZG", "KHH", 132, "filled", "", ""]])
    assert cli.main(["screenshots", "--report", str(rep)]) == 0
    text = capsys.readouterr().out
    assert shooter.seen == ["TPE-JFK", "MZG-KHH"]           # TPE-JFK only once overall
    assert "沿用既有截圖 1 條，本次新截 1 條" in text
    d = tmp_path / "x_greatcirclemap截圖"
    assert (d / "TPE-JFK_12566km.png").is_file() and (d / "MZG-KHH_132km.png").is_file()
    assert not (tmp_path / "x_greatcirclemap截圖(2)").exists()
    assert cli.main(["screenshots", "--report", str(rep), "--fresh"]) == 0
    assert (tmp_path / "x_greatcirclemap截圖(2)" / "MZG-KHH_132km.png").is_file()
