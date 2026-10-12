"""Detection of rows that look like Taiwan HSR (台灣高鐵) trips mis-entered as flights.

A row is HSR-like when BOTH endpoints lie on the HSR corridor – either by
station/city name (新竹, 台北, 高雄 …) or by an airport serving a corridor
city (TSA, TPE, RMQ, TNN, KHH, CYI).  Outlying islands (澎湖 MZG, 金門 KNH,
馬祖 LZN/MFK, 台東, 花蓮 …) are never HSR-like.
"""
from __future__ import annotations

from typing import Dict, Optional

from .lookup import normalize

# Station name → canonical HSR station
HSR_STATIONS = ("南港", "台北", "板橋", "桃園", "新竹", "苗栗", "台中", "彰化", "雲林", "嘉義", "台南", "左營")

_ALIASES: Dict[str, str] = {
    # 臺 / 台 variants and city-level names
    "臺北": "台北", "台北市": "台北", "臺北市": "台北", "台北車站": "台北", "TAIPEI": "台北",
    "新北": "板橋", "新北市": "板橋", "板橋站": "板橋",
    "桃園市": "桃園", "中壢": "桃園", "青埔": "桃園", "TAOYUAN": "桃園",
    "新竹市": "新竹", "新竹縣": "新竹", "竹北": "新竹", "HSINCHU": "新竹",
    "苗栗縣": "苗栗", "MIAOLI": "苗栗",
    "臺中": "台中", "台中市": "台中", "臺中市": "台中", "烏日": "台中", "TAICHUNG": "台中",
    "彰化縣": "彰化", "田中": "彰化", "CHANGHUA": "彰化",
    "雲林縣": "雲林", "虎尾": "雲林", "YUNLIN": "雲林",
    "嘉義市": "嘉義", "嘉義縣": "嘉義", "太保": "嘉義", "CHIAYI": "嘉義",
    "臺南": "台南", "台南市": "台南", "臺南市": "台南", "TAINAN": "台南",
    "高雄": "左營", "高雄市": "左營", "新左營": "左營", "KAOHSIUNG": "左營", "ZUOYING": "左營",
}

# Airports serving HSR-corridor cities → canonical station
CORRIDOR_AIRPORTS: Dict[str, str] = {
    "TSA": "台北",   # 松山
    "TPE": "桃園",   # 桃園國際機場
    "RMQ": "台中",   # 台中清泉崗
    "CYI": "嘉義",   # 嘉義
    "TNN": "台南",   # 台南
    "KHH": "左營",   # 高雄小港
}


def station_for(raw_value, iata: Optional[str] = None) -> Optional[str]:
    """Return the canonical HSR station for an endpoint, or None.

    The raw (name) value is checked first, then the resolved IATA code.
    """
    key = normalize(raw_value)
    if key in HSR_STATIONS:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    for code in (key, normalize(iata) if iata else ""):
        if code in CORRIDOR_AIRPORTS:
            return CORRIDOR_AIRPORTS[code]
    return None


def is_hsr_like(origin_raw, dest_raw, origin_iata: Optional[str] = None,
                dest_iata: Optional[str] = None) -> bool:
    a = station_for(origin_raw, origin_iata)
    b = station_for(dest_raw, dest_iata)
    return a is not None and b is not None


def hsr_note(origin_raw, dest_raw) -> str:
    from .lookup import display
    return f"疑似高鐵({display(origin_raw)}↔{display(dest_raw)})，請確認交通方式並移至高鐵表"
