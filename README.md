# miles-inquiry — 航空差旅距離自動填入工具

把碳盤查活頁簿「航空」工作表中的 **航班(起站) / 航班(迄站)** 轉成 IATA 機場代碼、
計算大圓距離（公里，與 <https://www.greatcirclemap.com/> 同為 WGS-84 計算）填入 **距離** 欄，
並把看起來像 **高鐵** 的列（例如 新竹↔台北、台中↔台北）標註在備註，請人工確認。

* 只需 Python 3.9+ 與 `openpyxl`，離線可用。
* 絕不覆寫原始檔：輸出為 `<檔名>_距離.xlsx`，並附 `<檔名>_距離_report.csv` 報表。
* 可重複執行（idempotent）：已填的距離預設保留、備註不會重複追加。
* 對應表 `data/lookup.csv` 由使用者持續維護；不認得的值會列在畫面與報表上，照提示加進去即可。

## 安裝

```bash
git clone <this repo> miles-inquiry
cd miles-inquiry
pip install -e .          # 或只 pip install openpyxl
```

Windows 使用者：把 `.xlsx` 直接**拖曳到 `fill.bat`** 上即可（需先安裝 Python 並勾選加入 PATH）。

## 使用

```bash
python -m miles_inquiry fill 碳盤查_2026-05.xlsx
# → 碳盤查_2026-05_距離.xlsx、碳盤查_2026-05_距離_report.csv（放在輸入檔旁）
```

常用選項：

| 選項 | 說明 |
|---|---|
| `-o OUTPUT.xlsx` | 指定輸出檔（不可與輸入檔相同） |
| `--sheet 航空` | 工作表名稱（預設 `航空`） |
| `--method vincenty\|haversine` | 距離演算法，預設 `vincenty`（WGS-84 橢球，與 greatcirclemap.com 一致） |
| `--decimals 0` | 小數位數，預設 0（寫入整數） |
| `--overwrite` | 覆寫已有的距離 |
| `--fill-hsr-distance` | 疑似高鐵列仍填入飛航距離（預設留空） |
| `--lookup PATH` / `--airports PATH` / `--overrides PATH` | 自訂資料檔 |
| `--data-dir DIR` | 一次指定資料目錄（預設專案 `data/`，亦可用環境變數 `MILES_INQUIRY_DATA`） |
| `--report PATH` / `--no-report` | 報表路徑 / 不產生報表 |

欄位是用**標題文字**找的（航班(起站)、航班(迄站)、距離、人次、備註；容忍空白與全半形），
不是固定欄位字母。其他欄、其他工作表、公式、格式與欄寬一律保留不動。

### 每列的處理規則

| 狀況 | 距離 | 備註 | 報表 status |
|---|---|---|---|
| 起/迄為「無」「0」「-」「N/A」或 人次=0 | 不動 | 不動（不重複寫「排除」） | `skipped` |
| 兩端皆在台灣高鐵走廊（見下） | 留空（`--fill-hsr-distance` 才填） | `疑似高鐵(新竹↔台北)，請確認交通方式並移至高鐵表` | `hsr` |
| 任一端無法對應機場代碼 | 留空 | `無法對應機場代碼：XXX，請更新 data/lookup.csv` | `unresolved` |
| 已有距離且未加 `--overwrite` | 保留 | — | `kept` |
| 正常 | 寫入公里數 | 僅在需人工確認時寫（見下） | `filled` |

會寫入備註請人工確認的情形：

* `lookup.csv` 的**誤植修正**（原值本身是機場代碼卻對應到別的代碼，如 `TAS,TSA`）：
  `起站 TAS→TSA 疑為代碼誤植（…note…）請確認`
* `lookup.csv` 的 note 以 `!` 開頭（如 `LGA/EWR,LGA,!原值含兩個機場，暫以 LGA 計算`）
* 直接輸入的代碼在 OurAirports 中**無定期航班**（如 `SIA` 西安西關，已停用）：`無定期航班，請確認代碼`

一般的中文→代碼對應（澎湖→MZG 等）只寫在報表，不佔用備註。

## 資料檔（`data/`）

### `lookup.csv` — 值 → IATA 對應表（持續更新）

UTF-8（含 BOM，Excel 直接開），三欄：`value,iata,note`；`#` 開頭為註解。

```csv
value,iata,note
澎湖,MZG,
高雄,KHH,
台北,TSA,台北預設松山機場 TSA；若實際為桃園請改 TPE
新竹,,新竹無民航機場；新竹↔台北多為高鐵
HONG KONG,HKG,
LGA/EWR,LGA,!原值含兩個機場 LGA/EWR，暫以 LGA 計算
TAS,TSA,澎湖分行 TAS→MZG 中的 TAS（塔什干）疑為 TSA（松山）誤植
```

比對規則：

1. 原值先做 NFKC 正規化、去頭尾空白、不分大小寫（`kHH`、`ＫＨＨ`、` HONG KONG ` 都能比對）。
2. **有明確列的一律優先**，所以可做誤植修正（`TAS,TSA`）。
3. 沒有明確列、但本身就是 `airports.csv` 內的 3 碼代碼 → 直接使用。
4. `iata` 留空 = 已知無法對應（如「新竹」）：距離留空並寫備註。
5. 都不符合 → `unresolved`，執行結束時會列出：

```
無法對應的值（請加入 data/lookup.csv，格式 value,iata,note）：
  首爾,,   # 出現 3 次
```

把這些列貼進 `lookup.csv` 填上代碼再執行一次即可。

### `distance_overrides.csv` — 精確距離覆寫

`from,to,km,source`，對稱（A,B 與 B,A 相同）。若要和 greatcirclemap.com 畫面上的數字完全一致，
把該數字貼進來，計算時會直接採用：

```csv
from,to,km,source
TPE,JFK,12566,greatcirclemap.com 2026-10-12
```

報表每列都附 `https://www.greatcirclemap.com/?routes=XXX-YYY` 連結，方便點開核對。

### `airports.csv` — 機場座標

取自 [OurAirports](https://ourairports.com/data/)（公眾領域），已精簡為
`iata,name,municipality,iso_country,type,lat,lon,scheduled_service`。更新：

```bash
python -m miles_inquiry update-airports                 # 線上下載
python -m miles_inquiry update-airports --source airports.csv   # 或讀本機完整檔
```

同一 IATA 代碼若有多筆，取 `scheduled_service=yes`、機場等級較大者。

## 高鐵判定規則

兩端**都**位於台灣高鐵走廊時標記為疑似高鐵：

* 站名/城市：南港 台北 板橋 桃園 新竹 苗栗 台中 彰化 雲林 嘉義 台南 左營，
  以及常見別名（高雄→左營、臺北/台北市、新北→板橋、中壢→桃園、竹北→新竹、虎尾→雲林…）。
* 走廊城市的機場代碼：TSA、TPE、RMQ、TNN、KHH、CYI（例如 `TSA↔KHH` 也會被標記）。
* 離島（澎湖 MZG、金門 KNH、馬祖 LZN/MFK、台東、花蓮…）不會被標記，正常計算飛航距離。

別名寫在 `miles_inquiry/hsr.py` 的 `_ALIASES`，可自行增補。

## 限制與注意事項

* **距離算法**：本機以 WGS-84 橢球 Vincenty 公式計算（`--method haversine` 為球面近似，約短 0.1–0.3 %）。
  與 greatcirclemap.com 顯示值可能有 ±1 km 左右差異（四捨五入、座標來源不同）；需要完全一致時請用 `distance_overrides.csv`。
* 機場座標來自 OurAirports，代表點為機場參考點，與網站所用座標可能略有差異。
* 以 openpyxl 讀寫：公式、格式、欄寬、其他工作表會保留，但**圖表、圖片、巨集（.xlsm 的 VBA）可能遺失**；輸出另存新檔，原檔不動。
* 「台北」預設對應松山機場 TSA；若多數實際為桃園，請改 `lookup.csv`。
* `LGA/EWR` 這種同時寫兩個機場的值，請在 `lookup.csv` 指定採用哪一個。
* 工具只做「代碼→距離」；碳排量欄位（距離×人次×係數）仍由活頁簿公式計算。

## 開發 / 測試

```bash
pip install -e .[test]
pytest
```

測試全部使用程式內建的合成活頁簿，不含任何實際資料。

---

## English summary

`miles-inquiry` fills the 距離 (distance, km) column of the 航空 (air travel) sheet in a
carbon-inventory workbook. It maps the raw origin/destination values to IATA codes via a
user-maintained lookup table (`data/lookup.csv`, UTF-8-BOM CSV: `value,iata,note`),
computes the WGS-84 geodesic distance (Vincenty; `--method haversine` optional) from
OurAirports coordinates (`data/airports.csv`, refreshed with `update-airports`), and flags
rows whose both endpoints lie on Taiwan's HSR corridor as probable HSR trips
(`疑似高鐵(...)`, distance left blank unless `--fill-hsr-distance`).

```bash
pip install -e .
python -m miles_inquiry fill INPUT.xlsx [-o OUT.xlsx] [--sheet 航空] [--method vincenty|haversine]
                                        [--decimals 0] [--overwrite] [--lookup PATH] [--report PATH]
```

The input file is never modified; output defaults to `INPUT_距離.xlsx` plus a CSV report
(`row, raw origin/dest, IATA origin/dest, km, status, greatcirclemap.com URL, note`).
Unresolved values are listed at the end so you can paste them into `lookup.csv`.
Exact figures from greatcirclemap.com can be pinned in `data/distance_overrides.csv`
(`from,to,km,source`, symmetric). Re-runs are idempotent; existing distances are kept
unless `--overwrite`; notes are appended to 備註 without duplication.
Limitations: distances are computed locally (may differ by ~1 km from the website);
openpyxl drops charts/images/VBA on save.
