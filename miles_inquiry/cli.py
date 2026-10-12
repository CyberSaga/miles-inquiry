"""Command-line interface: ``python -m miles_inquiry fill ...`` / ``update-airports``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__, default_data_dir
from .airports import AirportDB, update_airports
from .fill import DEFAULT_SHEET, Options, default_output_path, default_report_path, fill_workbook, write_report
from .geo import METHODS
from .lookup import Lookup
from .overrides import Overrides


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="miles_inquiry",
        description="將碳盤查活頁簿「航空」表的起迄站轉為 IATA 機場代碼並填入大圓距離（km）。",
    )
    p.add_argument("--version", action="version", version=f"miles-inquiry {__version__}")
    p.add_argument("--data-dir", type=Path, default=None,
                   help="資料目錄（lookup.csv / airports.csv / distance_overrides.csv），預設為專案 data/")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fill", help="填入距離")
    f.add_argument("input", type=Path, help="輸入 .xlsx")
    f.add_argument("-o", "--output", type=Path, default=None,
                   help="輸出 .xlsx（預設：輸入檔名_距離.xlsx，絕不覆寫輸入檔）")
    f.add_argument("--sheet", default=DEFAULT_SHEET, help=f"工作表名稱（預設 {DEFAULT_SHEET}）")
    f.add_argument("--method", choices=METHODS, default="vincenty", help="距離演算法（預設 vincenty，WGS-84 橢球）")
    f.add_argument("--decimals", type=int, default=0, help="小數位數（預設 0，寫入整數）")
    f.add_argument("--overwrite", action="store_true", help="覆寫已有的距離值")
    f.add_argument("--fill-hsr-distance", action="store_true", help="疑似高鐵列仍填入飛航距離（預設留空）")
    f.add_argument("--lookup", type=Path, default=None, help="自訂 lookup.csv 路徑")
    f.add_argument("--airports", type=Path, default=None, help="自訂 airports.csv 路徑")
    f.add_argument("--overrides", type=Path, default=None, help="自訂 distance_overrides.csv 路徑")
    f.add_argument("--report", type=Path, default=None, help="報表 CSV 路徑（預設：輸出檔名_report.csv）")
    f.add_argument("--no-report", action="store_true", help="不產生報表")
    f.set_defaults(func=cmd_fill)

    u = sub.add_parser("update-airports", help="下載 OurAirports 資料並更新 data/airports.csv")
    u.add_argument("--source", type=Path, default=None, help="改用本機完整 OurAirports airports.csv")
    u.add_argument("--dest", type=Path, default=None, help="輸出路徑（預設 data/airports.csv）")
    u.set_defaults(func=cmd_update_airports)
    return p


def _data_dir(args) -> Path:
    return Path(args.data_dir) if args.data_dir else default_data_dir()


def cmd_fill(args) -> int:
    data_dir = _data_dir(args)
    airports = AirportDB.load(args.airports or data_dir / "airports.csv")
    lookup = Lookup.load(args.lookup or data_dir / "lookup.csv", airports)
    overrides = Overrides.load(args.overrides or data_dir / "distance_overrides.csv")

    output = args.output or default_output_path(args.input)
    options = Options(sheet=args.sheet, method=args.method, decimals=args.decimals,
                      overwrite=args.overwrite, fill_hsr_distance=args.fill_hsr_distance)
    summary = fill_workbook(args.input, output, lookup, overrides, options)

    report_path: Optional[Path] = None
    if not args.no_report:
        report_path = write_report(summary, args.report or default_report_path(output))

    print(summary.console_summary())
    if report_path:
        print(f"報表：{report_path}")
    print(f"機場資料 {len(airports)} 筆、對應表 {len(lookup.entries)} 筆、距離覆寫 {len(overrides)} 筆")
    return 0


def cmd_update_airports(args) -> int:
    dest = args.dest or _data_dir(args) / "airports.csv"
    n = update_airports(dest, args.source)
    print(f"已寫入 {n} 個機場 → {dest}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
