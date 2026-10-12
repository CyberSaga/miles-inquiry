from pathlib import Path

import pytest

from miles_inquiry.airports import (CONFLICT_KM, GCM_FILENAME, OURAIRPORTS_FILENAME, SOURCE_GCM, SOURCE_OURAIRPORTS,
                                    AirportDB, merge_sources, read_greatcirclemap, read_ourairports_trimmed,
                                    trim_ourairports, update_airports, update_all, validate_greatcirclemap_text,
                                    write_greatcirclemap, write_trimmed)
from miles_inquiry.geo import site_km

DATA = Path(__file__).resolve().parent.parent / "data"

FULL_HEADER = ('"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent",'
               '"iso_country","iso_region","municipality","scheduled_service","icao_code","iata_code",'
               '"gps_code","local_code","home_link","wikipedia_link","keywords"\n')

SAMPLE = FULL_HEADER + "\n".join([
    '1,"RCTP","large_airport","Taiwan Taoyuan International Airport",25.0777,121.233002,106,"AS","TW","TW-TAO","Taoyuan","yes","RCTP","TPE","RCTP",,,,',
    '2,"XXXX","heliport","Some Heliport",25.0,121.0,10,"AS","TW","TW-TAO","Taoyuan","no",,"TPE","XXXX",,,,',   # duplicate TPE, worse
    '3,"RCSS","large_airport","Taipei Songshan International Airport",25.067244,121.552822,18,"AS","TW","TW-TPE","Taipei","yes","RCSS","TSA","RCSS",,,,',
    '4,"00A","heliport","Total RF Heliport",40.070985,-74.933689,11,"NA","US","US-PA","Bensalem","no",,,"K00A","00A",,,',  # no iata
    '5,"ZZZZ","small_airport","Bad coords",abc,def,,"NA","US","US-PA","X","no",,"BAD",,,,,',
    '6,"VDTI","large_airport","Techo International Airport",11.28,104.93,0,"AS","KH","KH-8","Phnom Penh","yes","VDTI","KTI","VDTI",,,,',
    '7,"VDSA","large_airport","Siem Reap-Angkor International Airport",13.36974,104.223831,0,"AS","KH","KH-17","Siem Reap","yes","VDSA","SAI","VDSA",,,,',
    '8,"ZLSN","medium_airport","Xi\'an Xiguan Airport",34.3767,109.12,0,"AS","CN","CN-61","Xi\'an","no","ZLSN","SIA","ZLSN",,,,',
]) + "\n"

GCM_SAMPLE = "id,name,city,iata,icao,lat,lng\n" + "\n".join([
    '1,Taiwan Taoyuan International Airport,Taipei,TPE,RCTP,25.078,121.233',
    '2,Taipei Songshan Airport,Taipei,TSA,RCSS,25.069,121.552',
    '3,Kratie Airport,Kratie,KTI,VDKT,12.488,106.055',           # re-assigned since: now Techo (Phnom Penh)
    '4,"Xi\'an Xiguan Airport",Xi\'an,SIA,ZLSN,34.377,109.120',
    '5,Francisco de Miranda Airport,Caracas,N/A,SVFM,10.485,-66.844',   # junk codes present in the real file
    '6,Issyk-Kul International Airport,Tamchy,ИКУ,UCFL,42.353,76.428',
    '7,Magas,Nazran,%u0,%u04,43.324,45.018',
    '8,Duplicate Songshan,Taipei,TSA,XXXX,0,0',                    # duplicate code → first wins
]) + "\n"


# -- OurAirports trimming -----------------------------------------------------

def test_trim_prefers_scheduled_and_larger():
    rows = trim_ourairports(SAMPLE)
    by = {r["iata"]: r for r in rows}
    assert set(by) == {"TPE", "TSA", "KTI", "SAI", "SIA"}
    assert by["TPE"]["type"] == "large_airport" and by["TPE"]["scheduled_service"] == "yes"
    assert by["TPE"]["lat"] == "25.0777" and by["TPE"]["lon"] == "121.233002"


def test_write_and_load_roundtrip(tmp_path: Path):
    dest = tmp_path / "airports.csv"
    write_trimmed(trim_ourairports(SAMPLE), dest)
    assert dest.read_bytes().startswith(b"\xef\xbb\xbf")
    db = AirportDB.load(dest)
    assert len(db) == 5 and "tpe" in db and db.get("TSA").lat == pytest.approx(25.067244)
    assert db.get("TPE").scheduled_service is True and db.get("SIA").scheduled_service is False
    assert db.get("TPE").source == SOURCE_OURAIRPORTS


def test_update_airports_refuses_tiny_source(tmp_path: Path):
    src = tmp_path / "src.csv"
    src.write_text(SAMPLE, encoding="utf-8")
    with pytest.raises(RuntimeError):
        update_airports(tmp_path / "out.csv", source=src)


# -- greatcirclemap file ------------------------------------------------------

def test_read_greatcirclemap_filters_junk_and_duplicates(tmp_path: Path):
    p = tmp_path / "gcm.csv"
    p.write_text(GCM_SAMPLE, encoding="utf-8")
    ap = read_greatcirclemap(p)
    assert set(ap) == {"TPE", "TSA", "KTI", "SIA"}
    assert ap["TSA"].lat == 25.069 and ap["TSA"].name == "Taipei Songshan Airport"   # first occurrence kept
    assert ap["TPE"].source == SOURCE_GCM and ap["TPE"].on_site and ap["TPE"].municipality == "Taipei"


def test_validate_and_write_greatcirclemap(tmp_path: Path):
    assert validate_greatcirclemap_text(GCM_SAMPLE, min_codes=3) == 4
    with pytest.raises(RuntimeError):
        validate_greatcirclemap_text(GCM_SAMPLE, min_codes=5000)
    with pytest.raises(RuntimeError):
        validate_greatcirclemap_text("iata,lat,lng\nTPE,1,2\n", min_codes=0)
    dest = tmp_path / GCM_FILENAME
    write_greatcirclemap("﻿" + GCM_SAMPLE, dest)
    assert dest.read_text(encoding="utf-8") == GCM_SAMPLE          # stored verbatim, BOM stripped


def test_format_autodetect(tmp_path: Path):
    g = tmp_path / "g.csv"
    g.write_text(GCM_SAMPLE, encoding="utf-8")
    o = tmp_path / "o.csv"
    write_trimmed(trim_ourairports(SAMPLE), o)
    assert AirportDB.load(g).get("TPE").source == SOURCE_GCM
    assert AirportDB.load(o).get("TPE").source == SOURCE_OURAIRPORTS


# -- layering ----------------------------------------------------------------

@pytest.fixture
def layered(tmp_path: Path) -> AirportDB:
    g = tmp_path / GCM_FILENAME
    g.write_text(GCM_SAMPLE, encoding="utf-8")
    o = tmp_path / OURAIRPORTS_FILENAME
    write_trimmed(trim_ourairports(SAMPLE), o)
    return AirportDB.load_layered(g, o)


def test_layered_site_coordinates_with_ourairports_metadata(layered: AirportDB):
    tpe = layered.get("TPE")
    assert tpe.source == SOURCE_GCM and tpe.on_site
    assert (tpe.lat, tpe.lon) == (25.078, 121.233)                 # site coordinates …
    assert tpe.iso_country == "TW" and tpe.type == "large_airport"   # … OurAirports metadata
    assert layered.get("SIA").scheduled_service is False             # flag comes from OurAirports


def test_layered_fallback_for_codes_the_site_lacks(layered: AirportDB):
    sai = layered.get("SAI")
    assert sai is not None and sai.source == SOURCE_OURAIRPORTS and not sai.on_site
    assert sai.conflict_note == "" and sai.lat == pytest.approx(13.36974)


def test_layered_conflict_prefers_current_ourairports(layered: AirportDB):
    kti = layered.get("KTI")
    assert kti.source == SOURCE_OURAIRPORTS and not kti.on_site
    assert kti.name == "Techo International Airport" and kti.lat == pytest.approx(11.28)
    assert "Kratie Airport" in kti.conflict_note and "km" in kti.conflict_note


def test_merge_conflict_threshold():
    from miles_inquiry.airports import Airport
    a = Airport("AAA", "Site", "", "", "", 10.0, 10.0)
    b_near = Airport("AAA", "OA", "", "XX", "large_airport", 10.1, 10.0, source=SOURCE_OURAIRPORTS)
    merged = merge_sources({"AAA": a}, {"AAA": b_near})["AAA"]
    assert merged.source == SOURCE_GCM and merged.lat == 10.0 and merged.iso_country == "XX"
    b_far = Airport("AAA", "OA", "", "XX", "large_airport", 12.0, 10.0, source=SOURCE_OURAIRPORTS)
    merged = merge_sources({"AAA": a}, {"AAA": b_far}, conflict_km=CONFLICT_KM)["AAA"]
    assert merged.source == SOURCE_OURAIRPORTS and merged.lat == 12.0 and merged.conflict_note


def test_load_layered_requires_at_least_one_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        AirportDB.load_layered(tmp_path / "none1.csv", tmp_path / "none2.csv")
    g = tmp_path / GCM_FILENAME
    g.write_text(GCM_SAMPLE, encoding="utf-8")
    assert len(AirportDB.load_layered(g, tmp_path / "none2.csv")) == 4


def test_update_all_from_local_sources(tmp_path: Path, monkeypatch):
    import miles_inquiry.airports as mod
    monkeypatch.setattr(mod, "validate_greatcirclemap_text", lambda text, min_codes=5000: 4)
    monkeypatch.setattr(mod, "trim_ourairports", lambda text: [dict(zip(mod.TRIMMED_COLUMNS, ["X%02d" % i] + [""] * 4 + ["1", "2", "yes"])) for i in range(1000)])
    g = tmp_path / "gsrc.csv"
    g.write_text(GCM_SAMPLE, encoding="utf-8")
    o = tmp_path / "osrc.csv"
    o.write_text(SAMPLE, encoding="utf-8")
    done = update_all(tmp_path / "data", gcm_source=g, oa_source=o)
    assert [d[0] for d in done] == ["greatcirclemap.com", "OurAirports"]
    assert (tmp_path / "data" / GCM_FILENAME).exists() and (tmp_path / "data" / OURAIRPORTS_FILENAME).exists()
    assert update_all(tmp_path / "data", gcm_source=g, skip_ourairports=True)[0][2] == 4


# -- committed data ---------------------------------------------------------

def test_committed_snapshot_loads_and_matches_site_values():
    db = AirportDB.load_layered(DATA / GCM_FILENAME, DATA / OURAIRPORTS_FILENAME)
    assert len(db) > 9000
    gcm_only = AirportDB.load(DATA / GCM_FILENAME)
    assert 6000 < len(gcm_only) < 7000
    for code in ("TPE", "TSA", "MZG", "KHH", "KNH", "RMQ", "TNN", "CYI", "JFK", "HKG", "SHA", "LZN", "MFK"):
        assert db.get(code).on_site, code
    # values the website displays
    pairs = {("TPE", "JFK"): 12566, ("MZG", "KHH"): 132, ("TSA", "MZG"): 256, ("SHA", "TSA"): 680}
    for (a, b), km in pairs.items():
        pa, pb = db.get(a), db.get(b)
        assert site_km(pa.lat, pa.lon, pb.lat, pb.lon) == km, (a, b)
    # fallback-only and re-assigned codes
    assert db.get("SAI").source == SOURCE_OURAIRPORTS and not db.get("SAI").conflict_note
    assert db.get("KTI").source == SOURCE_OURAIRPORTS and "Kratie" in db.get("KTI").conflict_note
    assert db.get("SIA").scheduled_service is False and db.get("PNH").scheduled_service is False
    assert "N/A" not in db


def test_lookup_codes_all_exist_in_committed_data():
    """Every iata in data/lookup.csv must resolve (site or fallback)."""
    import csv
    db = AirportDB.load_layered(DATA / GCM_FILENAME, DATA / OURAIRPORTS_FILENAME)
    missing = []
    with (DATA / "lookup.csv").open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0].startswith("#") or row[0] == "value":
                continue
            code = row[1].strip().upper()
            if code and code not in db:
                missing.append((row[0], code))
    assert missing == []
