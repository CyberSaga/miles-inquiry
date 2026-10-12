import pytest

from miles_inquiry.hsr import hsr_note, is_hsr_like, station_for


@pytest.mark.parametrize("o, d, oi, di", [
    ("新竹", "台北", None, "TSA"),
    ("台中", "台北", "RMQ", "TSA"),
    ("TSA", "KHH", "TSA", "KHH"),
    ("tsa", "khh", "TSA", "KHH"),
    ("高雄", "台北", "KHH", "TSA"),
    ("臺北", "臺南", None, None),
    ("TPE", "RMQ", "TPE", "RMQ"),
    ("左營", "南港", None, None),
    ("板橋", "嘉義", None, "CYI"),
    ("台中站", "台北站", None, None),           # station suffix
    ("高鐵台中", "高鐵台北", None, None),       # 高鐵 prefix
    ("台北車站", "新左營站", None, None),
    ("桃園", "高雄", "TPE", "KHH"),             # names → HSR even though the airports have a real flight
    ("TPE", "TSA", "TPE", "TSA"),               # 桃園 ↔ 台北 stations
])
def test_hsr_like(o, d, oi, di):
    assert is_hsr_like(o, d, oi, di)


@pytest.mark.parametrize("o, d, oi, di", [
    ("澎湖", "高雄", "MZG", "KHH"),     # outlying island
    ("MZG", "TSA", "MZG", "TSA"),
    ("金門", "高雄", "KNH", "KHH"),
    ("LZN", "TSA", "LZN", "TSA"),       # 馬祖
    ("TPE", "JFK", "TPE", "JFK"),
    ("新竹", "SHA", None, "SHA"),       # only one end in Taiwan corridor
    ("新竹", "無", None, None),
    ("", "", None, None),
    ("TPE", "KHH", "TPE", "KHH"),       # real China Airlines connecting flight entered as codes
    ("khh", "tpe", "KHH", "TPE"),
    ("桃園", "TPE", "TPE", "TPE"),       # same station (not a trip)
    ("台北", "TSA", "TSA", "TSA"),
    ("台北", "台北", "TSA", "TSA"),
    ("新竹", "", None, None),
])
def test_not_hsr_like(o, d, oi, di):
    assert not is_hsr_like(o, d, oi, di)


def test_station_aliases():
    assert station_for("高雄") == "左營"
    assert station_for("臺中") == "台中"
    assert station_for("KHH") == "左營"
    assert station_for("xx", "TSA") == "台北"
    assert station_for("澎湖", "MZG") is None
    assert station_for("台中站") == "台中" and station_for("高鐵台中站") == "台中"
    assert station_for("台北車站") == "台北" and station_for("新左營站") == "左營"
    assert station_for("站") is None and station_for("高鐵") is None


def test_hsr_note_text():
    assert hsr_note("新竹", " 台北 ") == "疑似高鐵(新竹↔台北)，請確認交通方式並移至高鐵表"
