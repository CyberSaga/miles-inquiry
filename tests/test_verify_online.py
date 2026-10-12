"""verify-online logic – tested offline with a fake page fetcher (no network, no Playwright)."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from miles_inquiry.airports import SOURCE_OURAIRPORTS, Airport, AirportDB
from miles_inquiry.verify_online import (batched, dedupe, fetch_site_distances, parse_missing_codes, parse_routes,
                                         parse_site_text, route_url, routes_from_report, summarize, verify_routes,
                                         write_verify_csv)
from tests.conftest import SYNTH_AIRPORTS

PAGE = """Great Circle Map

Enter two or more airports to draw a route between them on the map and calculate the distance.

Name of city or airport-code
GoAbout
Raw input
TPE ⇾ JFK
12566 km
MZG ⇾ KHH
132 km
TSA ⇾ MZG
256 km
SHA ⇾ TSA
680 km
© 2017-2026 Markus Englund
Taipei
New York
"""

MISSING_PAGE = """Great Circle Map
Raw input
'SAI' does not exist in our database
© 2017-2026 Markus Englund
"""


def test_parse_site_text():
    assert parse_site_text(PAGE) == {("TPE", "JFK"): 12566, ("MZG", "KHH"): 132, ("TSA", "MZG"): 256, ("SHA", "TSA"): 680}
    assert parse_site_text("") == {} and parse_site_text(None) == {}
    assert parse_site_text("AAA ⇾ BBB\n1,234 km\n") == {("AAA", "BBB"): 1234}


def test_parse_missing_codes():
    assert parse_missing_codes(MISSING_PAGE) == ["SAI"]
    assert parse_missing_codes(PAGE) == []


def test_parse_routes_and_url():
    assert parse_routes("TPE-JFK, mzg-khh tpe-jfk") == [("TPE", "JFK"), ("MZG", "KHH")]
    with pytest.raises(ValueError):
        parse_routes("TPEJFK")
    assert route_url([("TPE", "JFK"), ("MZG", "KHH")]) == "https://www.greatcirclemap.com/?routes=TPE-JFK%2CMZG-KHH"
    assert batched([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert dedupe([("A", "B"), ("A", "B"), ("B", "A")]) == [("A", "B"), ("B", "A")]


def test_routes_from_report(tmp_path: Path):
    p = tmp_path / "r.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["row", "origin_raw", "dest_raw", "origin_iata", "dest_iata", "km", "status", "url", "note"])
        w.writerow([2, "澎湖", "高雄", "MZG", "KHH", 132, "filled", "", ""])
        w.writerow([3, "無", "無", "", "", "", "skipped", "", ""])
        w.writerow([4, "澎湖", "高雄", "MZG", "KHH", 132, "filled", "", ""])
        w.writerow([5, "TPE", "JFK", "TPE", "JFK", 12566, "filled", "", ""])
        w.writerow([6, "火星", "TPE", "", "TPE", "", "unresolved", "", ""])
    assert routes_from_report(p) == [("MZG", "KHH"), ("TPE", "JFK")]


class FakeFetcher:
    """Pretends to be the website: answers from a table, errors on unknown codes like the real page."""

    def __init__(self, table, known):
        self.table, self.known = table, known
        self.calls = []

    def __call__(self, urls):
        import urllib.parse
        out = []
        for url in urls:
            self.calls.append(url)
            spec = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["routes"][0]
            routes = [tuple(r.split("-")) for r in spec.split(",")]
            unknown = sorted({c for r in routes for c in r if c not in self.known})
            if unknown:
                text = "".join(f"'{c}' does not exist in our database\n" for c in unknown)
            else:   # routes absent from the table are simply not listed (simulates a page that did not render a line)
                text = "Raw input\n" + "".join(f"{a} ⇾ {b}\n{self.table[(a, b)]} km\n" for a, b in routes if (a, b) in self.table)
            out.append({"url": url, "expected": len(routes), "text": text, "error": None})
        return out


def test_verify_routes_offline(tmp_path: Path):
    db = AirportDB(SYNTH_AIRPORTS)
    table = {("TPE", "JFK"): 12566, ("MZG", "KHH"): 132, ("TSA", "MZG"): 999}     # KHH-TPE deliberately absent
    fake = FakeFetcher(table, known={"TPE", "JFK", "MZG", "KHH", "TSA"})
    routes = [("TPE", "JFK"), ("MZG", "KHH"), ("TSA", "MZG"), ("TPE", "SAI"), ("KHH", "TPE")]
    res = verify_routes(routes, db, batch=2, fetch=fake)
    by = {(r.origin, r.dest): r for r in res}
    assert [r.status for r in res] == ["match", "match", "mismatch", "site_missing", "error"]
    assert by[("TSA", "MZG")].local_km == 256 and by[("TSA", "MZG")].site_km == 999 and "-743" in by[("TSA", "MZG")].note
    assert by[("TPE", "SAI")].local_km is not None and "SAI" in by[("TPE", "SAI")].note   # never sent to the site
    assert by[("KHH", "TPE")].site_km is None and 280 < by[("KHH", "TPE")].local_km < 310   # page did not list it → error
    assert all("SAI" not in u for u in fake.calls)
    text = summarize(res)
    assert "match=2" in text and "mismatch=1" in text and "TSA-MZG" in text
    out = write_verify_csv(res, tmp_path / "v.csv")
    rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0]["status"] == "match" and rows[0]["url"].endswith("routes=TPE-JFK")


def test_reassigned_code_is_reported_as_such_and_never_fetched():
    """KTI: the site knows the code but places it at Kratie; our DB uses OurAirports (Techo). Not 'missing'."""
    kti = Airport("KTI", "Techo International Airport", "Phnom Penh", "KH", "large_airport", 11.36, 104.921,
                  source=SOURCE_OURAIRPORTS, conflict_note="greatcirclemap 資料庫中 KTI 為 Kratie Airport（相距 139 km）")
    db = AirportDB(SYNTH_AIRPORTS + [kti])
    fake = FakeFetcher({("TPE", "JFK"): 12566}, known={"TPE", "JFK", "KTI"})
    res = verify_routes([("KTI", "TPE"), ("TPE", "SAI"), ("TPE", "JFK")], db, fetch=fake)
    assert [r.status for r in res] == ["site_reassigned", "site_missing", "match"]
    assert "沒有" not in res[0].note and "Kratie" in res[0].note and res[0].local_km is not None
    assert all("KTI" not in u for u in fake.calls)
    assert "site_reassigned=1" in summarize(res)


def test_verify_routes_error_status_when_page_lacks_route():
    """Page shows no line for a route → 'error' (never a false match or mismatch)."""
    db = AirportDB(SYNTH_AIRPORTS)
    fake = FakeFetcher({("TPE", "JFK"): 12566}, known={"TPE", "JFK", "MZG", "KHH"})
    res = verify_routes([("TPE", "JFK"), ("MZG", "KHH")], db, fetch=fake)
    assert [r.status for r in res] == ["match", "error"]


def test_missing_code_on_page_triggers_retry_of_the_rest():
    """If the snapshot is older than the live site, a batch may hit an unknown code: the rest is re-fetched."""
    fake = FakeFetcher({("TPE", "JFK"): 12566, ("MZG", "KHH"): 132}, known={"TPE", "JFK", "MZG", "KHH"})
    found, missing, errors = fetch_site_distances([("TPE", "JFK"), ("TPE", "ZZZ"), ("MZG", "KHH")], batch=20, fetch=fake)
    assert found == {("TPE", "JFK"): 12566, ("MZG", "KHH"): 132}
    assert missing == ["ZZZ"] and errors == [] and len(fake.calls) == 2


def test_cli_verify_online_offline(tmp_path: Path, monkeypatch, capsys):
    import miles_inquiry.verify_online as vo
    from miles_inquiry.cli import main
    fake = FakeFetcher({("TPE", "JFK"): 12566, ("MZG", "KHH"): 131}, known={"TPE", "JFK", "MZG", "KHH"})
    monkeypatch.setattr(vo, "fetch_site_texts", fake)
    ap = tmp_path / "airports.csv"
    with ap.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["iata", "name", "municipality", "iso_country", "type", "lat", "lon", "scheduled_service"])
        for a in SYNTH_AIRPORTS:
            w.writerow([a.iata, a.name, a.municipality, a.iso_country, a.type, a.lat, a.lon, "yes"])
    # trimmed OurAirports format → nothing is "on site" → everything is site_missing, exit 0
    rc = main(["verify-online", "--routes", "TPE-JFK", "--airports", str(ap)])
    assert rc == 0 and "site_missing=1" in capsys.readouterr().out
    # greatcirclemap format → fetched; one mismatch → exit code 2
    g = tmp_path / "g.csv"
    g.write_text("id,name,city,iata,icao,lat,lng\n" + "".join(
        f"{i},{a.name},{a.municipality},{a.iata},,{a.lat},{a.lon}\n" for i, a in enumerate(SYNTH_AIRPORTS, 1)), encoding="utf-8")
    out = tmp_path / "v.csv"
    rc = main(["verify-online", "--routes", "TPE-JFK,MZG-KHH", "--airports", str(g), "--out", str(out)])
    text = capsys.readouterr().out
    assert rc == 2 and "mismatch=1" in text and out.exists()
