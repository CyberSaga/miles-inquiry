"""Command-line interface.

    python -m miles_inquiry fill INPUT.xlsx [...]
    python -m miles_inquiry update-airports [...]
    python -m miles_inquiry verify-online (--report REPORT.csv | --routes TPE-JFK,MZG-KHH) [...]
    python -m miles_inquiry screenshots (--report REPORT.csv | --routes TPE-JFK,MZG-KHH) [--out DIR] [...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__, default_data_dir
from .airports import GCM_FILENAME, OURAIRPORTS_FILENAME, AirportDB, update_all
from .fill import (DEFAULT_HSR_FACTOR_CELL, DEFAULT_HSR_SHEET, DEFAULT_SHEET, Options, default_output_path,
                   default_report_path, fill_workbook, next_free_path, write_rail_todo, write_report)
from .geo import DEFAULT_METHOD, HAVE_GEOGRAPHICLIB, METHODS
from .lookup import Lookup
from .overrides import Overrides
from .rail import STATIONS_FILENAME, RailData


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="miles_inquiry",
        description="將碳盤查活頁簿「航空」表的起迄站轉為 IATA 機場代碼並填入大圓距離（km，與 greatcirclemap.com 一致）。",
    )
    p.add_argument("--version", action="version", version=f"miles-inquiry {__version__}")
    p.add_argument("--data-dir", type=Path, default=None,
                   help="資料目錄（lookup.csv / airports_greatcirclemap.csv / airports.csv / distance_overrides.csv），預設為專案 data/")
    sub = p.add_subparsers(dest="command", required=True)

    # fill ------------------------------------------------------------------
    f = sub.add_parser("fill", help="填入距離")
    f.add_argument("input", type=Path, help="輸入 .xlsx")
    f.add_argument("-o", "--output", type=Path, default=None,
                   help="輸出 .xlsx（預設：輸入檔名_距離.xlsx，絕不覆寫輸入檔）")
    f.add_argument("--sheet", default=DEFAULT_SHEET, help=f"工作表名稱（預設 {DEFAULT_SHEET}）")
    f.add_argument("--method", choices=METHODS, default=DEFAULT_METHOD,
                   help=f"距離演算法（預設 {DEFAULT_METHOD}＝GeographicLib WGS-84，與 greatcirclemap.com 相同）")
    f.add_argument("--decimals", type=int, default=0, help="小數位數（預設 0，寫入整數，四捨五入同網站）")
    f.add_argument("--overwrite", action="store_true", help="覆寫已有的距離值")
    f.add_argument("--overwrite-output", action="store_true",
                   help="輸出檔/報表已存在時直接覆寫（預設改存為 檔名(2).xlsx，不覆蓋任何既有檔案）")
    f.add_argument("--fill-hsr-distance", action="store_true", help="疑似高鐵列仍填入飛航距離（預設留空）")
    f.add_argument("--keep-names", action="store_true",
                   help="起迄站保留原文（預設把 澎湖、HONG KONG 等改為 IATA 代碼，原值寫入備註）")
    f.add_argument("--no-carbon", action="store_true", help="不填碳排量（預設以公式 =距離*人次*係數 填入航空與高鐵表）")
    f.add_argument("--no-hsr-distance", action="store_true",
                   help="不填高鐵表距離（預設依 data/thsr_distances.csv、rail_distance_overrides.csv 填入）")
    f.add_argument("--hsr-sheet", default=DEFAULT_HSR_SHEET, help=f"高鐵工作表名稱（預設 {DEFAULT_HSR_SHEET}）")
    f.add_argument("--hsr-factor-cell", default=DEFAULT_HSR_FACTOR_CELL,
                   help=f"高鐵表碳排係數所在儲存格（預設 {DEFAULT_HSR_FACTOR_CELL}）")
    f.add_argument("--lookup", type=Path, default=None, help="自訂 lookup.csv 路徑")
    _add_airport_args(f)
    f.add_argument("--overrides", type=Path, default=None, help="自訂 distance_overrides.csv 路徑")
    f.add_argument("--report", type=Path, default=None, help="報表 CSV 路徑（預設：輸出檔名_report.csv）")
    f.add_argument("--no-report", action="store_true", help="不產生報表")
    _add_data_dir_arg(f)
    f.set_defaults(func=cmd_fill)

    # update-airports ---------------------------------------------------------
    u = sub.add_parser("update-airports",
                       help=f"下載 greatcirclemap.com 機場資料（{GCM_FILENAME}）與 OurAirports 備援資料（{OURAIRPORTS_FILENAME}）")
    u.add_argument("--source", type=Path, default=None, help="改用本機完整 OurAirports airports.csv")
    u.add_argument("--gcm-source", type=Path, default=None, help="改用本機 greatcirclemap airports.csv")
    u.add_argument("--skip-greatcirclemap", action="store_true", help="不更新 greatcirclemap 資料")
    u.add_argument("--skip-ourairports", action="store_true", help="不更新 OurAirports 資料")
    _add_data_dir_arg(u)
    u.set_defaults(func=cmd_update_airports)

    # verify-online -----------------------------------------------------------
    v = sub.add_parser("verify-online",
                       help="（選用）以 Playwright 開啟 greatcirclemap.com 核對距離；需 Node.js + playwright")
    src = v.add_mutually_exclusive_group(required=True)
    src.add_argument("--report", type=Path, help="fill 產生的報表 CSV，核對其中所有不同的路線")
    src.add_argument("--routes", help="以逗號分隔的路線，如 TPE-JFK,MZG-KHH")
    v.add_argument("--method", choices=METHODS, default=DEFAULT_METHOD, help="本機距離演算法")
    v.add_argument("--batch", type=int, default=20, help="每頁路線數（預設 20）")
    v.add_argument("--out", type=Path, default=None, help="核對結果 CSV")
    _add_airport_args(v)
    _add_data_dir_arg(v)
    v.set_defaults(func=cmd_verify_online)

    # screenshots -------------------------------------------------------------
    s = sub.add_parser("screenshots",
                       help="（選用）每條路線擷取一張 greatcirclemap.com 截圖存到獨立資料夾，作為距離佐證；需 Node.js + playwright")
    src = s.add_mutually_exclusive_group(required=True)
    src.add_argument("--report", type=Path, help="fill 產生的報表 CSV：為其中每條有距離的路線截圖，並與表內距離比對")
    src.add_argument("--routes", help="以逗號分隔的路線，如 TPE-JFK,MZG-KHH")
    s.add_argument("--out", type=Path, default=None,
                   help="截圖資料夾（預設：報表旁的「<檔名>_greatcirclemap截圖」）。資料夾已有 index.csv 時為增量模式："
                        "已截過的路線直接沿用、只補新路線；已有其他內容但沒有 index.csv 時自動加 (2)、(3)…")
    s.add_argument("--fresh", action="store_true", help="不沿用既有截圖：資料夾已存在時改存到新的 (2)、(3)… 資料夾並全部重截")
    s.add_argument("--method", choices=METHODS, default=DEFAULT_METHOD, help="--routes 模式下比對用的本機演算法")
    s.add_argument("--width", type=int, default=1280, help="截圖寬度（像素，預設 1280）")
    s.add_argument("--height", type=int, default=800, help="截圖高度（像素，預設 800）")
    _add_airport_args(s)
    _add_data_dir_arg(s)
    s.set_defaults(func=cmd_screenshots)
    return p


def _add_data_dir_arg(sp: argparse.ArgumentParser) -> None:
    # Also accepted after the sub-command; SUPPRESS keeps the top-level value when not given here.
    sp.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def _add_airport_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--airports", type=Path, default=None,
                    help=f"自訂主要機場資料（預設 data/{GCM_FILENAME}；也接受 OurAirports 精簡格式）")
    sp.add_argument("--fallback-airports", type=Path, default=None,
                    help=f"自訂備援機場資料（預設 data/{OURAIRPORTS_FILENAME}；指定 --airports 而未指定本項時不使用備援）")


def _data_dir(args) -> Path:
    return Path(args.data_dir) if args.data_dir else default_data_dir()


def _load_airports(args) -> AirportDB:
    data_dir = _data_dir(args)
    if args.airports is not None:
        return AirportDB.load(args.airports, args.fallback_airports)
    return AirportDB.load_layered(data_dir / GCM_FILENAME, args.fallback_airports or data_dir / OURAIRPORTS_FILENAME)


def cmd_fill(args) -> int:
    data_dir = _data_dir(args)
    airports = _load_airports(args)
    lookup = Lookup.load(args.lookup or data_dir / "lookup.csv", airports)
    overrides = Overrides.load(args.overrides or data_dir / "distance_overrides.csv")

    output = Path(args.output or default_output_path(args.input))
    if output.exists() and not args.overwrite_output:
        new_output = next_free_path(output)
        print(f"注意：{output} 已存在，改寫入 {new_output}（加 --overwrite-output 可直接覆寫）")
        output = new_output
    options = Options(sheet=args.sheet, method=args.method, decimals=args.decimals,
                      overwrite=args.overwrite, fill_hsr_distance=args.fill_hsr_distance,
                      convert_names=not args.keep_names, carbon=not args.no_carbon,
                      hsr_sheet=args.hsr_sheet, hsr_factor_cell=args.hsr_factor_cell,
                      hsr_distance=not args.no_hsr_distance)
    rail = None
    if not args.no_hsr_distance:
        if (data_dir / STATIONS_FILENAME).is_file():
            rail = RailData.load(data_dir)
        else:
            print(f"注意：找不到 {data_dir / STATIONS_FILENAME}，高鐵表距離不填")
    summary = fill_workbook(args.input, output, lookup, overrides, options, rail)

    report_path: Optional[Path] = None
    if not args.no_report:
        report_path = Path(args.report or default_report_path(output))
        if report_path.exists() and not args.overwrite_output:
            report_path = next_free_path(report_path)
        report_path = write_report(summary, report_path)

    todo_path = None
    if summary.hsr_missing_pairs:
        todo_path = next_free_path(output.with_name(f"{output.stem}_高鐵待補距離.csv"))
        write_rail_todo(summary, todo_path)

    print(summary.console_summary())
    if report_path:
        print(f"報表：{report_path}")
    if todo_path:
        print(f"高鐵待補距離：{todo_path}（填好 km、source 後貼到 data/rail_distance_overrides.csv 再重跑）")
    print(f"機場資料 {len(airports)} 筆、對應表 {len(lookup.entries)} 筆、距離覆寫 {len(overrides)} 筆")
    if args.method == "geodesic" and not HAVE_GEOGRAPHICLIB:
        print("警告：未安裝 geographiclib，改用內建 Vincenty 公式：一般航線結果相同，"
              "但近對蹠點（地球另一端）的路線可能相差最多約 20 km；pip install geographiclib 可與網站完全一致")
    return 0


def cmd_update_airports(args) -> int:
    done = update_all(_data_dir(args), gcm_source=args.gcm_source, oa_source=args.source,
                      skip_gcm=args.skip_greatcirclemap, skip_ourairports=args.skip_ourairports)
    for label, path, n in done:
        print(f"已寫入 {label} 機場 {n} 個 → {path}")
    return 0


def cmd_verify_online(args) -> int:
    from .verify_online import parse_routes, routes_from_report, summarize, verify_routes, write_verify_csv

    routes = routes_from_report(args.report) if args.report else parse_routes(args.routes)
    if not routes:
        print("沒有可核對的路線")
        return 0
    db = _load_airports(args)
    results = verify_routes(routes, db, method=args.method, batch=args.batch)
    print(summarize(results))
    if args.out:
        print(f"結果：{write_verify_csv(results, args.out)}")
    return 2 if any(r.status == "mismatch" for r in results) else 0


def cmd_screenshots(args) -> int:
    from .screenshots import default_out_dir, free_dir, jobs_from_report, jobs_from_routes, summarize, take_screenshots
    from .verify_online import parse_routes

    jobs = jobs_from_report(args.report) if args.report else jobs_from_routes(parse_routes(args.routes))
    if not jobs:
        print("沒有可截圖的路線（報表中沒有已填距離的列）")
        return 0
    target = Path(args.out or default_out_dir(args.report))
    incremental = not args.fresh and (target / "index.csv").is_file()
    out_dir = target if incremental else free_dir(target)
    print(("增量模式：只截尚未截過的路線" if incremental else "擷取") +
          f"（報表共 {len(jobs)} 條路線，greatcirclemap.com 每條約 3–5 秒）…")
    results = take_screenshots(jobs, out_dir, db=_load_airports(args), method=args.method,
                               width=args.width, height=args.height, reuse=incremental)
    print(summarize(results, out_dir))
    print(f"索引：{out_dir / 'index.csv'}、{out_dir / 'index.html'}")
    return 2 if any(r.status in ("mismatch", "error") for r in results) else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    except PermissionError as exc:
        print(f"錯誤：無法讀寫 {exc.filename or exc}；檔案可能正被 Excel 開啟或為唯讀，請關閉後再執行", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"錯誤：檔案存取失敗（{exc}）；請確認路徑正確、檔案未被其他程式開啟", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
