# miles-inquiry — 航空差旅距離自動填入工具

把碳盤查活頁簿「航空」工作表中的 **航班(起站) / 航班(迄站)** 轉成 IATA 機場代碼、
計算大圓距離（公里）填入 **距離** 欄（起迄站若是地名，例如 HONG KONG、西雅圖、洛杉磯，會直接改成代碼，原值寫在備註），並把看起來像 **高鐵** 的列（例如 新竹↔台北、台中↔台北）標註在備註，請人工確認。
同時在「航空」與「高鐵」兩表的 **碳排量** 欄填入公式 `=距離*人次*係數`（見[碳排量](#碳排量)）。

**計算結果與 <https://www.greatcirclemap.com/> 顯示的數字完全相同**：

| 網站怎麼算 | 本工具怎麼做 |
|---|---|
| 機場座標：網站自己的 `airports.csv`（約 6,470 筆，含少數非 IATA 識別碼，座標 3 位小數） | 同一份檔案的快照 `data/airports_greatcirclemap.csv`（`update-airports` 可重新下載） |
| 距離：GeographicLib `Geodesic.WGS84.Inverse(...).s12`（Karney 演算法，WGS-84 橢球） | Python `geographiclib` 同一演算法（預設 `--method geodesic`） |
| 顯示：`Math.round(s12 / 1000)` km（0.5 進位） | `floor(km + 0.5)`（非 Python 預設的四捨六入五成雙） |

已核對：TPE-JFK 12566、MZG-KHH 132、TSA-MZG 256、SHA-TSA 680 km，以及樣本活頁簿中全部 58 條網站能算的路線，皆與網站一致（`verify-online` 子命令可隨時重新核對）。

網站沒有的代碼（例如 2023 年啟用的暹粒吳哥 SAI、北京大興 PKX、成都天府 TFU）改用 [OurAirports](https://ourairports.com/data/)
的座標（`data/airports.csv`），並在備註寫明「不在 greatcirclemap 資料庫，座標取自 OurAirports」。

* 只需 Python 3.9+ 與 `openpyxl`、`geographiclib`，離線可用。
* 絕不覆寫原始檔：輸出為 `<檔名>_距離.xlsx`，並附 `<檔名>_距離_report.csv` 報表；輸出檔已存在時也不覆蓋，改存為 `<檔名>_距離(2).xlsx`（加 `--overwrite-output` 才覆寫）。
* 可重複執行（idempotent）：已填的距離預設保留、備註不會重複追加。
* 對應表 `data/lookup.csv` 由使用者持續維護；不認得的值會列在畫面與報表上，照提示加進去即可。

## 安裝

```bash
git clone <this repo> miles-inquiry
cd miles-inquiry
pip install -e .          # 或只 pip install openpyxl geographiclib
```

Windows 使用者：把 `.xlsx` 直接**拖曳到 `fill.bat`** 上即可（需先安裝 Python 並勾選加入 PATH，再 `pip install openpyxl geographiclib`）。
`fill.bat` 也可在命令列用 `fill.bat 檔案.xlsx` 執行（相對路徑以目前目錄為準）；不帶檔案直接雙擊則開啟圖形介面。
`.bat` 檔一律只用 ASCII＋CRLF：cmd.exe 讀含中文（UTF-8）的批次檔會錯位，把半行字當成指令執行；中文訊息由 Python 輸出，主控台可正常顯示。

## 圖形介面（GUI）

```bash
python -m miles_inquiry gui            # 或安裝後執行 miles-inquiry-gui
```

Windows：雙擊 **`gui.bat`**（或把 `.xlsx` 拖到 `gui.bat` 上，開啟時預先帶入該檔）。
在視窗中選擇活頁簿、勾選選項（覆寫已有距離、保留原文、疑似高鐵仍填距離、不填碳排量、直接覆寫輸出檔），
按「開始填入」即可；執行訊息顯示在下方，「開啟資料夾」可直接打開輸出檔所在位置。
GUI 使用 Python 內建的 tkinter，不需另外安裝（Linux 若缺少請 `apt install python3-tk`）。

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
| `--method geodesic\|vincenty\|haversine` | 距離演算法，預設 `geodesic`（GeographicLib WGS-84，與網站相同）；`vincenty` 為內建無依賴版本（一般航線差 <1 m，近對蹠點路線最多差約 20 km）；`haversine` 為球面近似（與橢球值相差最多約 ±0.35 %，正負視航線而定） |
| `--decimals 0` | 小數位數，預設 0（寫入整數，0.5 進位同網站） |
| `--overwrite` | 覆寫已有的距離 |
| `--overwrite-output` | 輸出檔／報表已存在時直接覆寫（預設改存為 `檔名(2).xlsx`） |
| `--fill-hsr-distance` | 疑似高鐵列仍填入飛航距離（預設留空） |
| `--keep-names` | 起迄站保留原文，不改為 IATA 代碼（預設會改，見下） |
| `--no-carbon` | 不填碳排量 |
| `--no-hsr-distance` | 不填高鐵表距離 |
| `--hsr-sheet NAME` / `--hsr-factor-cell CELL` | 高鐵工作表名稱（預設 `高鐵`）/ 高鐵碳排係數儲存格（預設 `J2`） |
| `--lookup PATH` / `--airports PATH` / `--fallback-airports PATH` / `--overrides PATH` | 自訂資料檔 |
| `--data-dir DIR` | 一次指定資料目錄（預設專案 `data/`，亦可用環境變數 `MILES_INQUIRY_DATA`） |
| `--report PATH` / `--no-report` | 報表路徑 / 不產生報表 |

欄位是用**標題文字**找的（航班(起站)、航班(迄站)、距離、人次、備註；容忍空白與全半形），
不是固定欄位字母。除了起迄站、距離、碳排量與備註，其他欄、其他工作表、公式、格式與欄寬一律保留不動。

### 每列的處理規則

| 狀況 | 距離 | 備註 | 報表 status |
|---|---|---|---|
| 起/迄為「無」「0」「-」「N/A」或 人次=0 | 不動 | 不動（不重複寫「排除」） | `skipped` |
| 起或迄**空白**但人次>0（漏填） | 留空 | `起站空白，請補填` | `unresolved` |
| 兩端皆在台灣高鐵走廊（見下） | 留空（`--fill-hsr-distance` 才填） | `疑似高鐵(新竹↔台北)，請確認交通方式並移至高鐵表` | `hsr` |
| 任一端無法對應機場代碼 | 留空 | `無法對應機場代碼：XXX，請更新 data/lookup.csv` | `unresolved` |
| 已有距離且未加 `--overwrite` | 保留 | — | `kept` |
| 正常 | 寫入公里數 | 僅在需人工確認時寫（見下） | `filled` |

會寫入備註請人工確認的情形：

* `lookup.csv` 的**誤植修正**（原值本身是機場代碼卻對應到別的代碼，如 `TAS,TSA`）：
  `起站 TAS→TSA 疑為代碼誤植（…note…）請確認`
* `lookup.csv` 的 `review` 欄為 `yes`（如 `LGA/EWR,LGA,yes,…`、`台北,TSA,yes,…`）：`起站 台北→TSA：…note…`
* 直接輸入的代碼在 OurAirports 中**無定期航班**（如 `SIA` 西安西關）：`無定期航班，請確認代碼`。OurAirports 標錯的（七美 `CMJ`、望安 `WOT`、綠島 `GNI` 實際有德安航空定期航班）已在 `lookup.csv` 以同碼列（`CMJ,CMJ,,…`）取代這個警告；`PNH` 金邊舊機場（2025-09 停用）則以 `review=yes` 列提醒改用 `KTI`
* 代碼**不在 greatcirclemap 資料庫**（如 `SAI`）：`SAI 不在 greatcirclemap 資料庫，座標取自 OurAirports（…）`
* 代碼在網站資料與 OurAirports 相距超過 50 km（代碼已重新指派，如 `KTI` 網站仍是 Kratie、現為金邊德崇）：
  改用 OurAirports 座標並註明 `greatcirclemap 網站數字不適用`

### 起迄站改為 IATA 代碼

起迄站是地名或誤植代碼時（`澎湖`、`HONG KONG`、`西雅圖`、`LGA/EWR`、`TAS`…），儲存格會直接改成對應的代碼，
原值寫進備註：`迄站原值「HONG KONG」→HKG`（誤植修正與 `review=yes` 的備註本身已含「原值→代碼」，不再重複）。
已經是代碼的值（含大小寫不同如 `kHH`）、無法對應的值、疑似高鐵列（火車行程，且新竹沒有機場）都保留原文。
重跑輸出檔時代碼直接通過，不會再加備註。加 `--keep-names` 可保留原文（此時一般對應只寫在報表）。

### 碳排量

碳排量欄寫入 Excel **公式**（不是數值），係數改了 Excel 會自動重算；報表 CSV 另附 `category`、`factor`、`carbon`（工具算出的值）方便核對。

* **航空**：係數依類別取自類別文字右邊那格（實際活頁簿為 K3:L5）：

  | 類別（K 欄文字含） | 係數 | 判定 | 公式範例 |
  |---|---|---|---|
  | 國際線 | `$L$3` | 其他（含兩岸、港澳、海外分行在當地的航段） | `=G9*H9*$L$3` |
  | 國內線 | `$L$4` | 起迄機場都在台灣 | `=G4*H4*$L$4` |
  | 中國分行 | `$L$5` | 起迄機場都在中國大陸 | `=G7*H7*$L$5` |

  只填有距離的列（`filled`、`kept`）；排除、無法對應、疑似高鐵的列留空。表格搬位置也找得到（依文字找，不靠固定位址）。
* **高鐵**：係數固定為 `J2`（`--hsr-factor-cell` 可改），公式為 `=IF(G2="","",G2*H2*$J$2)`：
  距離還沒填時顯示空白，填入距離後自動算出。人次為 0 或起迄為「無」的列不寫。
* 碳排量欄是空白、範本文字 `=距離*人次*係數`、或本工具先前寫的公式時才會寫入；其他手打的值或公式保留不動
  （列在畫面上，`--overwrite` 才覆寫）。

### 高鐵表距離

高鐵表的「距離」依下列順序填入（已有值的格子保留，`--overwrite` 才覆寫；`--no-hsr-distance` 不填）：

1. `data/rail_distance_overrides.csv`（`from,to,km,source`，方向不拘）：不在台灣高鐵線上的站對（例如中國高鐵 蘇州北→徐州東）或要指定距離的站對。
2. `data/thsr_distances.csv`（`from,to,kg_co2e,km`）：台灣高鐵 12 站、66 組站對的距離，取自**高鐵官網**
   [「高速鐵路旅客運輸服務碳足跡」](https://www.thsrc.com.tw/ArticleContent/5a1f4c72-b564-4706-bcdd-efbda93c3d93)
   的「車站間旅客運輸碳足跡」表（kg CO2e／每人次，依環境部碳標 29 gCO2e／人公里計算），`km = kg_co2e ÷ 0.029` 取 1 位小數。
   因此高鐵表 `距離 × 人次 × J2(0.029)` 會等於高鐵公司公布的每人次碳足跡。
   不用維基百科的沿線里程：維基可任意編輯、非官方，而且數字比官方表短約 1.3%（例如台北—左營維基 339.1 km、官方換算 343.4 km）。
   官方表更新（新碳標）時，整份換掉並同步更新高鐵表 J2。
3. 都查不到：距離留空並寫備註。若起迄兩站都不是台灣高鐵站（例如中國高鐵），會另外輸出
   `<輸出檔名>_高鐵待補距離.csv`，每組站對一列並附上列號。填好 `km`、`source` 後貼進 `rail_distance_overrides.csv`，再重跑一次。

站名寫法由 `data/hsr_lookup.csv`（`value,station,review,note`）統一：臺/台、結尾的「站」「車站」會自動忽略；
`高雄→左營`、`粄橋→板橋`（review，寫入備註）、`苏州北→蘇州北`（簡繁合併）等列在表中。`station` 留空表示確定不是高鐵站
（斗六、屏東、旗山分行…），備註會說明。J2 是碳排係數，工具絕不會把備註寫進那一格。

## 資料檔（`data/`）

### `lookup.csv` — 值 → IATA 對應表（持續更新）

UTF-8（含 BOM，Excel 直接開），四欄：`value,iata,review,note`；`#` 開頭為註解（檔內以 `# ===== 台灣 =====` 等分區）。
舊的三欄格式 `value,iata,note` 也能讀。

用 Excel 編輯後請以「**CSV UTF-8（逗號分隔）**」另存；若不小心存成一般「CSV」（繁中 Windows 為 ANSI/cp950），工具也會自動改用 cp950 讀取，兩種編碼都無法解讀時才報錯。

```csv
value,iata,review,note
澎湖,MZG,,澎湖馬公機場
台北,TSA,yes,預設松山 TSA（國內/離島線）；國際線多為桃園 TPE，請依航段確認
新竹,,,新竹無民航機場（HSZ 為空軍基地）；多為高鐵誤植
HONG KONG,HKG,,香港國際機場
LGA/EWR,LGA,yes,原值含 LGA/EWR 兩機場，暫以 LGA 計算，請確認
TAS,TSA,,TAS=塔什干；澎湖分行無此航線，應為 TSA 松山字母顛倒
```

比對規則：

1. 原值先做 NFKC 正規化、去頭尾空白、不分大小寫、忽略「/」兩側空白（`kHH`、`ＫＨＨ`、` HONG KONG `、`Taipei`/`TAIPEI`、`LGA / EWR` 都能比對），所以每個拼法只需列一次。
2. **有明確列的一律優先**，所以可做誤植修正（`TAS,TSA`）。
3. 沒有明確列、但本身就是機場資料內的 3 碼代碼 → 直接使用。
4. `iata` 留空 = 已知無法對應（如「新竹」「蘇州」「TAP」）：距離留空並寫備註。
5. `review` 為 `yes`（也接受 y/true/1/是）= 可對應，但**每次**都把 note 寫進備註請人工確認（多機場城市、二擇一的值）。
6. 都不符合 → `unresolved`，執行結束時會列出：

```
無法對應的值（請加入 data/lookup.csv，格式 value,iata,review,note）：
  首爾,,,   # 出現 3 次
```

把這些列貼進 `lookup.csv` 填上代碼再執行一次即可。

目前內建的判斷（可自行修改）：

| 值 | 對應 | 理由 |
|---|---|---|
| `TAS` | `TSA`（自動寫備註） | TAS 為塔什干，本行無此航線；澎湖分行 TAS→MZG 必為松山字母顛倒。若日後真有塔什干行程，刪除此列即可 |
| `SIA` | `SAI`（自動寫備註） | SIA 為西安西關舊碼，已無民航；暹粒支行用，應為暹粒吳哥 SAI |
| `REP` | `SAI`（自動寫備註） | 暹粒舊機場 2023-10 關閉 |
| `TAP` | （留空） | 塔帕丘拉（墨西哥）為真實機場，但洛杉磯分行 LAX→TAP 疑為 TPE/TPA 誤植，須人工決定 |
| `SZX` | `SZX` | 深圳寶安；苏州單位的 SHA↔SZX、SZX↔WUX 等為深圳↔蘇州地區實際航線，維持深圳（只寫報表）。需逐列確認時把該列 `review` 改 `yes` |
| `LGA/EWR` | `LGA`（review） | 二擇一（兩機場相距約 30 km），暫以 LGA 計算 |
| `CMJ`、`WOT`、`GNI` | 同碼 | OurAirports 誤標為無定期航班，實際有德安航空航線；列出即不再警告 |
| `PNH` | `PNH`（review） | 金邊舊機場 2025-09 停用；之後行程請改 KTI |
| `安大略`/`Ontario` | `ONT`（review） | 暫以加州安大略機場計算；若指加拿大安大略省請改 YYZ |
| `台北` | `TSA`（review） | 國內/離島線用松山；國際線多為桃園 |
| `上海`/`東京`/`北京`/`紐約`/`首爾`/`大阪`/`成都`… | `SHA`/`HND`/`PEK`/`JFK`/`ICN`/`KIX`/`CTU` | 依本行既有用法選預設，note 列出替代機場 |
| `金邊` | `KTI`（review） | 2025-09 德崇機場取代 PNH；之前的行程請改 PNH |
| `新竹`、`苗栗`、`彰化`、`雲林`、`板橋`、`南港`、`左營`、`屏東`、`蘇州` | （留空） | 無民航機場 |

### `distance_overrides.csv` — 精確距離覆寫

`from,to,km,source`，對稱（A,B 與 B,A 相同）。計算時直接採用，優先於一切：

```csv
from,to,km,source
TPE,JFK,12566,greatcirclemap.com 2026-10-12
```

報表每列都附 `https://www.greatcirclemap.com/?routes=XXX-YYY` 連結，方便點開核對。

### `airports_greatcirclemap.csv` 與 `airports.csv` — 機場座標

* `airports_greatcirclemap.csv`：網站 <https://www.greatcirclemap.com/airports.csv> 的原樣快照（主要來源）。
* `airports.csv`：[OurAirports](https://ourairports.com/data/)（公眾領域）精簡為
  `iata,name,municipality,iso_country,type,lat,lon,scheduled_service`（備援來源，並提供國家、是否有定期航班等資訊）。

更新兩者：

```bash
python -m miles_inquiry update-airports                        # 線上下載（會自動重試）
python -m miles_inquiry update-airports --source airports.csv --gcm-source gcm.csv   # 或讀本機檔
python -m miles_inquiry update-airports --skip-ourairports      # 只更新網站資料
```

同一 IATA 代碼在 OurAirports 若有多筆，取 `scheduled_service=yes`、機場等級較大者。

### `verify-online` — 和網站逐條核對（選用）

需要 Node.js 與 Playwright（核心功能不需要）：

```bash
npm install -g playwright && npx playwright install chromium
export NODE_PATH=$(npm root -g)          # Windows: set NODE_PATH=%APPDATA%\npm\node_modules

python -m miles_inquiry verify-online --report 碳盤查_2026-05_距離_report.csv --out 核對.csv
python -m miles_inquiry verify-online --routes TPE-JFK,MZG-KHH
```

它會開啟 `https://www.greatcirclemap.com/?routes=AAA-BBB,CCC-DDD`（每頁約 20 條），讀取網頁上
「AAA ⇾ BBB / 12566 km」的文字與本機計算比較，列出 `match / mismatch / site_missing（網站沒有該代碼）/ error`；
另有 `site_reassigned`：代碼在網站資料與 OurAirports 相距超過 50 km（如 `KTI`），本機採 OurAirports 座標，網站數字不可比對，不會送去核對。有 mismatch 時結束碼為 2。

### `screenshots` — 每條路線一張網站截圖作為佐證（選用）

需求同 `verify-online`（Node.js + Playwright）。對 `fill` 報表中**每條有距離的路線**（依表內起→迄方向，重複路線只截一次）
開啟 `https://www.greatcirclemap.com/?routes=AAA-BBB` 並截圖，存到**獨立資料夾**：

```bash
python -m miles_inquiry screenshots --report 碳盤查_2026-05_距離_report.csv
#  → 碳盤查_2026-05_距離_greatcirclemap截圖/  （已存在且非空時自動改用 …(2)）
python -m miles_inquiry screenshots --routes TPE-JFK,MZG-KHH --out 截圖
```

資料夾內容：

| 檔案 | 說明 |
|---|---|
| `TPE-JFK_12566km.png` | 網站顯示的距離＝表內距離（檔名的 km 是從網頁讀到的數字） |
| `KHH-SAI_網站無此機場.png` | 網站資料庫沒有該代碼，截圖會顯示網站的錯誤訊息（此類距離取自 OurAirports） |
| `AAA-BBB_網站XXkm_表內YYkm.png` | 不符（理論上不會發生；結束碼 2） |
| `index.csv` | 路線、網站 km、表內 km、結果、對應的工作表列號、網址、擷取時間 |
| `index.html` | 同上附縮圖，用瀏覽器開啟即可逐張檢視 |

每張截圖底部有一條黑色列，寫明網址與擷取時間（瀏覽器截圖沒有網址列，故由本工具加註，並標示「此列為 miles_inquiry 加註」）；
網站本身的畫面（路線、距離、地圖）不做任何修改。

## 高鐵判定規則

兩端**都**位於台灣高鐵走廊時標記為疑似高鐵：

* 站名/城市：南港 台北 板橋 桃園 新竹 苗栗 台中 彰化 雲林 嘉義 台南 左營，
  以及常見別名（高雄→左營、臺北/台北市、新北→板橋、中壢→桃園、竹北→新竹、虎尾→雲林…）。
* 走廊城市的機場代碼：TSA、TPE、RMQ、TNN、KHH、CYI（例如 `TSA↔KHH` 也會被標記）。
* 站名可帶「高鐵」前綴或「站／車站」後綴（`高鐵台中`、`台中站`、`台北車站`）。
* 離島（澎湖 MZG、金門 KNH、馬祖 LZN/MFK）與東部（台東、花蓮）不會被標記，正常計算飛航距離。
* 例外：以代碼輸入的 `TPE↔KHH` 是華航實際營運的國際線接駁航班，不標記、正常填距離（以站名輸入的「桃園↔高雄」仍視為高鐵）；兩端同一站（`桃園↔TPE`、`台北↔TSA`）不是行程，不標記。

別名寫在 `miles_inquiry/hsr.py` 的 `_ALIASES`，可自行增補。

## 限制與注意事項

* 距離與網站一致的前提是：代碼在網站資料庫內、且 `airports_greatcirclemap.csv` 與網站目前的檔案相同
  （網站更新資料時請執行 `update-airports`）。網站沒有的代碼以 OurAirports 座標計算，備註會註明；
  若需指定數字，用 `distance_overrides.csv`。
* 只接受 `.xlsx` 與 `.xlsm`（.xls、.csv 會以中文訊息拒絕，請先在 Excel 另存為 .xlsx）。以 openpyxl 讀寫：公式、格式、欄寬、其他工作表會保留；`.xlsm` 會保留 VBA 專案並輸出為 `.xlsm`，但**圖表、圖片可能遺失**；輸出另存新檔，原檔不動。
* 備註只會在原文之後以「；」追加，不改寫既有文字；寫入的提示只用 `data/lookup.csv` 這類短名稱，不含電腦路徑。
* 「台北」預設對應松山機場 TSA（並寫備註）；若多數實際為桃園，請改 `lookup.csv`。
* 工具只做「代碼→距離」；碳排量欄位（距離×人次×係數）仍由活頁簿公式計算。

## 開發 / 測試

```bash
pip install -e .[test]
pytest
```

測試全部使用程式內建的合成活頁簿與合成機場表，不含任何實際資料；`verify-online`、`screenshots` 的測試以假網頁離線執行。

---

## English summary

`miles-inquiry` fills the 距離 (distance, km) column of the 航空 (air travel) sheet in a
carbon-inventory workbook. It maps the raw origin/destination values to IATA codes via a
user-maintained lookup table (`data/lookup.csv`, UTF-8-BOM CSV: `value,iata,review,note`)
and computes the distance **exactly as <https://www.greatcirclemap.com/> displays it**: the
same airport coordinates (a snapshot of the site's `airports.csv`), the same algorithm
(GeographicLib `Geodesic.WGS84.Inverse`, via the `geographiclib` package) and the same
rounding (`Math.round`, i.e. half-up to whole km). Codes the site lacks (e.g. SAI, PKX, TFU)
fall back to OurAirports coordinates and are flagged in 備註. Station cells holding a name or a
mistyped code (澎湖, HONG KONG, 西雅圖, TAS…) are rewritten to the IATA code and the original value is
noted in 備註 (`迄站原值「HONG KONG」→HKG`); codes, unresolved values and HSR rows keep their text
(`--keep-names` disables the rewrite). A blank origin/destination next to a
real trip is flagged (`起站空白，請補填`) rather than skipped; only 無/0/-/N/A or 人次=0 skip a row. Rows whose both endpoints lie on
Taiwan's HSR corridor are flagged as probable HSR trips (`疑似高鐵(...)`, distance left blank
unless `--fill-hsr-distance`).
It also writes 碳排量 (carbon) as live Excel formulas `=距離*人次*係數`: on 航空 the factor is
picked by category from the label/number pairs in K3:L5 (both airports in Taiwan → 國內線,
both in mainland China → 中國分行, otherwise 國際線); on 高鐵 the factor is `J2` and the formula
is `=IF(G2="","",G2*H2*$J$2)` so it stays blank until a distance is entered (`--no-carbon` disables this).

```bash
pip install -e .
python -m miles_inquiry fill INPUT.xlsx [-o OUT.xlsx] [--sheet 航空] [--method geodesic|vincenty|haversine]
                                        [--decimals 0] [--overwrite] [--lookup PATH] [--report PATH]
python -m miles_inquiry update-airports          # refresh data/airports_greatcirclemap.csv + data/airports.csv
python -m miles_inquiry verify-online --report OUT_report.csv   # optional: compare with the live site (Node + Playwright)
python -m miles_inquiry screenshots --report OUT_report.csv     # optional: one site screenshot per route, in its own folder
```

The input file is never modified; output defaults to `INPUT_距離.xlsx` plus a CSV report
(`row, raw origin/dest, IATA origin/dest, km, status, greatcirclemap.com URL, note`).
Unresolved values are listed at the end so you can paste them into `lookup.csv`; a lookup row
with `review=yes` always writes its note to 備註 for human confirmation, and a row that maps
one code to another (e.g. `TAS,TSA`) is treated as a typo correction and flagged too.
Exact figures can be pinned in `data/distance_overrides.csv` (`from,to,km,source`, symmetric).
Re-runs are idempotent; existing distances are kept unless `--overwrite`; notes are appended
to 備註 without duplication and without rewriting existing text. An existing output file is never
clobbered (the run goes to `NAME(2).xlsx` unless `--overwrite-output`). `.xlsm` keeps its VBA; openpyxl drops charts/images on save.
