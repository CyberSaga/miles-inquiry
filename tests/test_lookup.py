import pytest

from miles_inquiry.airports import AirportDB
from miles_inquiry.airports import Airport
from miles_inquiry.lookup import Lookup, is_review_flag, is_skip_value, normalize
from tests.conftest import SYNTH_AIRPORTS


def test_normalize_variants():
    assert normalize("kHH") == "KHH"
    assert normalize(" HONG KONG ") == "HONG KONG"
    assert normalize("ＨＯＮＧ　ＫＯＮＧ") == "HONG KONG"      # full-width letters + ideographic space
    assert normalize("ｋｈｈ") == "KHH"
    assert normalize("臺北　") == "臺北"
    assert normalize(None) == ""
    assert normalize(0) == "0"


def test_skip_values():
    for v in ("無", "0", 0, 0.0, "", None, "-", "—", "N/A", "n/a", " 無 "):
        assert is_skip_value(v), v
    for v in ("TPE", "澎湖", "1"):
        assert not is_skip_value(v), v


def test_direct_iata_case_insensitive(lookup):
    r = lookup.resolve("kHH")
    assert r.status == "ok" and r.iata == "KHH" and r.via == "direct"
    assert not r.mapped and r.note_for_cell is None


def test_lookup_name_and_whitespace(lookup):
    assert lookup.resolve(" HONG KONG ").iata == "HKG"
    assert lookup.resolve("澎湖").iata == "MZG"
    r = lookup.resolve("澎湖")
    assert r.mapped and r.note_for_cell is None and r.note_for_report == "澎湖→MZG"


def test_explicit_row_beats_direct_code_and_flags_correction(lookup):
    r = lookup.resolve("tas")
    assert r.iata == "TSA" and r.correction and r.via == "lookup"
    assert "TAS→TSA" in r.note_for_cell and "疑為代碼誤植" in r.note_for_cell


def test_review_flag_values():
    for v in ("yes", "Y", "TRUE", "1", "是", "v", " yes "):
        assert is_review_flag(v), v
    for v in ("", None, "no", "N", "0", "否"):
        assert not is_review_flag(v), v


def test_review_row_writes_note_to_cell(lookup):
    r = lookup.resolve("台北")
    assert r.status == "ok" and r.iata == "TSA" and r.review and not r.correction
    assert r.note_for_cell == "台北→TSA：台北預設松山；國際線請改 TPE"
    assert r.note_for_report is None


def test_review_row_unresolved_when_code_missing_from_airports(lookup):
    # LGA is not in the synthetic airport DB → unresolved with lookup note
    r = lookup.resolve("LGA/EWR")
    assert r.status == "unresolved" and "LGA" in r.note and r.review
    db = AirportDB(SYNTH_AIRPORTS + [Airport("LGA", "LaGuardia", "New York", "US", "large_airport", 40.7772, -73.8726)])
    r = Lookup(lookup.entries, db).resolve("lga/ewr")
    assert r.status == "ok" and r.iata == "LGA" and r.review and not r.correction
    assert r.note_for_cell == "lga/ewr→LGA：原值含兩個機場"


def test_same_code_review_row(tmp_path, airports):
    p = tmp_path / "l.csv"
    p.write_text("value,iata,review,note\nSZX,SZX,yes,深圳而非蘇州\nKHH,KHH,,高雄\n", encoding="utf-8")
    db = AirportDB(SYNTH_AIRPORTS + [Airport("SZX", "Shenzhen Bao'an", "Shenzhen", "CN", "large_airport", 22.6393, 113.8108)])
    lk = Lookup.load(p, db)
    r = lk.resolve("szx")
    assert r.status == "ok" and r.iata == "SZX" and not r.mapped and r.note_for_cell == "SZX：深圳而非蘇州"
    r = lk.resolve("KHH")
    assert r.note_for_cell is None and r.note_for_report == "KHH（高雄）"


def test_correction_without_review_still_notes(lookup):
    r = lookup.resolve("SIA")
    assert r.correction and r.iata == "SAI" and "SIA→SAI 疑為代碼誤植（SIA 已停用）請確認" == r.note_for_cell


def test_legacy_three_column_layout(tmp_path, airports):
    p = tmp_path / "legacy.csv"
    p.write_text("\ufeffvalue,iata,note\n澎湖,MZG,馬公\nTAS,TSA,誤植\n", encoding="utf-8")
    lk = Lookup.load(p, airports)
    r = lk.resolve("澎湖")
    assert r.iata == "MZG" and r.note == "馬公" and not r.review
    assert lk.resolve("TAS").correction


def test_header_columns_in_any_order(tmp_path, airports):
    p = tmp_path / "order.csv"
    p.write_text("note,review,iata,value\n備註,yes,KHH,高雄\n", encoding="utf-8")
    r = Lookup.load(p, airports).resolve("高雄")
    assert r.iata == "KHH" and r.review and r.note == "備註"


def test_headerless_file_uses_default_order(tmp_path, airports):
    p = tmp_path / "nohdr.csv"
    p.write_text("高雄,KHH,yes,備註\n", encoding="utf-8")
    r = Lookup.load(p, airports).resolve("高雄")
    assert r.iata == "KHH" and r.review and r.note == "備註"


def test_missing_iata_header_raises(tmp_path, airports):
    p = tmp_path / "bad.csv"
    p.write_text("value,code\n高雄,KHH\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Lookup.load(p, airports)


def test_known_unresolvable(lookup):
    r = lookup.resolve("新竹")
    assert r.status == "unresolved" and r.iata is None and r.via == "lookup" and r.note == "新竹無民航機場"


def test_unknown_value(lookup):
    r = lookup.resolve("火星")
    assert r.status == "unresolved" and r.via == ""
    # 3 letters but not an airport → unresolved too
    assert lookup.resolve("ZZZ").status == "unresolved"


def test_skip_resolution(lookup):
    assert lookup.resolve("無").status == "skip"
    assert lookup.resolve(0).status == "skip"


def test_bad_iata_in_lookup_raises(tmp_path, airports):
    p = tmp_path / "bad.csv"
    p.write_text("value,iata,note\n澎湖,MZGX,\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Lookup.load(p, airports)


def test_missing_lookup_raises(tmp_path, airports):
    with pytest.raises(FileNotFoundError):
        Lookup.load(tmp_path / "nope.csv", airports)
