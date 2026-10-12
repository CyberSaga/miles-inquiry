from pathlib import Path

import pytest

from miles_inquiry.airports import AirportDB, trim_ourairports, update_airports, write_trimmed

FULL_HEADER = ('"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent",'
               '"iso_country","iso_region","municipality","scheduled_service","icao_code","iata_code",'
               '"gps_code","local_code","home_link","wikipedia_link","keywords"\n')

SAMPLE = FULL_HEADER + "\n".join([
    '1,"RCTP","large_airport","Taiwan Taoyuan International Airport",25.0777,121.233002,106,"AS","TW","TW-TAO","Taoyuan","yes","RCTP","TPE","RCTP",,,,',
    '2,"XXXX","heliport","Some Heliport",25.0,121.0,10,"AS","TW","TW-TAO","Taoyuan","no",,"TPE","XXXX",,,,',   # duplicate TPE, worse
    '3,"RCSS","large_airport","Taipei Songshan International Airport",25.067244,121.552822,18,"AS","TW","TW-TPE","Taipei","yes","RCSS","TSA","RCSS",,,,',
    '4,"00A","heliport","Total RF Heliport",40.070985,-74.933689,11,"NA","US","US-PA","Bensalem","no",,,"K00A","00A",,,',  # no iata
    '5,"ZZZZ","small_airport","Bad coords",abc,def,,"NA","US","US-PA","X","no",,"BAD",,,,,',
]) + "\n"


def test_trim_prefers_scheduled_and_larger():
    rows = trim_ourairports(SAMPLE)
    by = {r["iata"]: r for r in rows}
    assert set(by) == {"TPE", "TSA"}
    assert by["TPE"]["type"] == "large_airport" and by["TPE"]["scheduled_service"] == "yes"
    assert by["TPE"]["lat"] == "25.0777" and by["TPE"]["lon"] == "121.233002"


def test_write_and_load_roundtrip(tmp_path: Path):
    dest = tmp_path / "airports.csv"
    write_trimmed(trim_ourairports(SAMPLE), dest)
    assert dest.read_bytes().startswith(b"\xef\xbb\xbf")
    db = AirportDB.load(dest)
    assert len(db) == 2 and "tpe" in db and db.get("TSA").lat == pytest.approx(25.067244)
    assert db.get("TPE").scheduled_service is True


def test_update_airports_refuses_tiny_source(tmp_path: Path):
    src = tmp_path / "src.csv"
    src.write_text(SAMPLE, encoding="utf-8")
    with pytest.raises(RuntimeError):
        update_airports(tmp_path / "out.csv", source=src)


def test_missing_db_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        AirportDB.load(tmp_path / "none.csv")


def test_committed_airports_csv_loads():
    db = AirportDB.load(Path(__file__).resolve().parent.parent / "data" / "airports.csv")
    assert len(db) > 8000
    for code in ("TPE", "TSA", "MZG", "KHH", "KNH", "RMQ", "TNN", "CYI", "JFK", "HKG"):
        assert code in db
    assert db.get("SIA").scheduled_service is False
