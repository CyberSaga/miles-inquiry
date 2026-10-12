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
])
def test_not_hsr_like(o, d, oi, di):
    assert not is_hsr_like(o, d, oi, di)


def test_station_aliases():
    assert station_for("高雄") == "左營"
    assert station_for("臺中") == "台中"
    assert station_for("KHH") == "左營"
    assert station_for("xx", "TSA") == "台北"
    assert station_for("澎湖", "MZG") is None


def test_hsr_note_text():
    assert hsr_note("新竹", " 台北 ") == "疑似高鐵(新竹↔台北)，請確認交通方式並移至高鐵表"
