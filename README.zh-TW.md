# The Day Trader skill(台股版)

[English](README.md) | 繁體中文

原專案簡介:"11 Claude skills for day trading: scan thousands of charts, track breaking news, time every entry and exit, and replay every outcome before you risk a dollar."
(11 個當沖用的 Claude skill:掃描上千張線圖、追蹤即時新聞、抓準每次進出場時機,下單前先重播每一種可能的結果。)

**這是 [leohsiehtw/day-trader-skill](https://github.com/leohsiehtw/day-trader-skill),
Jake Schincariol 原作 [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
的台股(上市 TWSE、上櫃 TPEx)fork。** 台股版放在 `tw-equities` 分支,沿用 MIT 授權,
保留原作者的著作權聲明與署名(見 `LICENSE`)。

免費、MIT 授權、不用註冊、不用 API key。工具都是純 Python,讀免費的公開資料:Yahoo Finance
線圖、交易所自己的股票清單(台股版用證交所與櫃買中心的清單,其他部分用 Nasdaq Trader)、
SEC EDGAR 與美國眾議院書記處。

一個 skill 掃描上千張線圖找型態,一個追蹤你關注股票的即時新聞,一個逐根 K 棒盯著型態、告訴你
進場時機,另一個在你進場前先設好停損與停利。最特別的是 Time Machine:下單前用這檔股票自己最近的
K 棒把當天剩下的走勢重播 10,000 次,再加上過去每一次出現同樣型態的日子,告訴你實際的勝率。

沒有你點頭,任何交易都不會送出。這套工具不會自己下單,預設是模擬交易(paper trading)。

> **找原本的 Trader skill?** 複製投資人 13F、選股器、稅務批次與再平衡在
> [github.com/Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill)。
> 這個 repo 是它的當沖續作:Trader skill v2。

## 台股版

下單路徑上的五個 skill 已經台股化,處理上市(`2317.TW`)與上櫃(`6488.TWO`)的四碼普通股:
`trader-scanner`、`trader-entry`、`trader-exit`、`trader-risk`、`trader-budget`。共用的台股規則
放在 `trader-risk/twmarket.py`,所以這幾個資料夾要一起安裝。

**尚未台股化**(仍是美股版:紐約時間、美元、NYSE 假日):`trader-news`、`trader-timemachine`、
`trader-broker`、`trader-alerts`、`trader-analyst`、`trader-pelosi`。拿它們處理台股會把時區與
幣別弄錯,`trader-broker` 也只對接美國券商 Alpaca,所以台股委託請自己到台灣的券商下單。證交所
沒有 bracket 單,停損與停利要在券商用條件單或 OCO 設定,或自己盯盤。

### 程式套用的台股規則

| 規則 | 內容 |
| --- | --- |
| 升降單位 | 未滿 10 元:0.01;10 元至未滿 50 元:0.05;50 元至未滿 100 元:0.1;100 元至未滿 500 元:0.5;500 元至未滿 1,000 元:1;1,000 元以上:5 |
| 漲跌幅 | 前一日收盤價上下 10% |
| 交易時間 | 台北時間 09:00 到 13:30(固定 UTC+8,沒有日光節約,沒有提早收盤) |
| 進場時段與出清 | 09:15 之前、13:00 之後不進場,13:20 前出清(`config.example.json` 的預設值) |
| 現股當沖賣出證交稅 | 交易日在 2027-12-31(`day_trade_tax_halved_until`)以前是 0.15%,之後 0.3% |
| 資券當沖 | 0.3%,把 `day_trade_mode` 設成 `margin_daytrade`(預設 `cash_daytrade`) |
| 一般賣出證交稅 | 0.3%(`sell_tax_pct`) |
| 手續費 | 每邊 0.1425% x `fee_discount`(預設 0.6),逐筆進位到整數元,最低 `min_fee_twd`(20 元) |
| 一張 | 1,000 股;委託是整張,或單一筆 1 到 999 股的零股,不能混合 |
| 零股 | 依證交所現行規定不能當沖:零股進場會有強烈警告(會變成留倉部位),成本與停損最大虧損改用一般賣出證交稅 0.3%(`sell_tax_pct`),不用當沖稅率 |
| 型態當沖交易者(PDT) | 台灣沒有 PDT 規定,所以不做 PDT 檢查 |
| 標的 | 只處理四碼普通股;00 開頭的 ETF、特別股、權證、DR 都會被拒絕 |

證交稅的交易日看工具的 `--now` 日期,沒給就用今天的台北日期。減半是暫行措施,期限變動時改
`day_trade_tax_halved_until`。最大虧損與風報比都把手續費和證交稅算進去。內建假日表只有 2026 年
(來源是證交所 OpenAPI 的休市日清單),其他年份請自己核對證交所行事曆。

### 當沖資格(程式不檢查)

券商與新聞常見的說法(請向你的券商或證交所確認):開戶滿 3 個月、最近一年成交 10 筆以上、簽署
當沖風險預告書(當沖同意書)。先賣後買另外要有信用交易(融資融券)或借券契約。程式不檢查以上任何
一項,`size.py` 與 `exit.py` 的輸出會提醒一行。

可當沖的股票以證交所每日公布的名單為準(TW Stock 連接器的 `get_daily_day_trading_targets`,
或 twse.com.tw),程式不假設任何股票可以當沖,也不檢查處置股、全額交割股與信用交易限制。

### 已查證與未查證

已查證:

- 現股當沖賣出證交稅 0.15% 延長到 2027-12-31(新聞報導的財政部延長措施);
- 零股不能當沖(證交所當沖頁面);
- 漲跌幅 10% 以前一日收盤價為基準。

未查證,請自行核對:

- 最低手續費 NT$20(各券商不同);
- 融券賣出不得低於前一日收盤價(平盤以下不得放空)的限制,程式不檢查;
- 零股日後是否開放當沖(主管機關只是在評估);
- 漲跌幅價位的進位方向(程式往內取到升降單位)與升降單位表,請對照證交所正式規定。

## 安裝

把這段貼給 Claude:

```
https://github.com/leohsiehtw/day-trader-skill

install skill
```

或在 Claude Code 裡當成 plugin 安裝:

```
/plugin marketplace add leohsiehtw/day-trader-skill
/plugin install day-trader-skill@day-trader-skill
```

上面兩種都從這個 fork 安裝(marketplace 與 plugin 都叫 `day-trader-skill`)。原版(美股)仍在
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)。
也可以從這個 fork 的 `tw-equities` 分支手動複製資料夾:

```bash
git clone -b tw-equities https://github.com/leohsiehtw/day-trader-skill.git
cp -r day-trader-skill/trader-* ~/.claude/skills/
```

Claude Code 會替 plugin 的 skill 加上命名空間,用 plugin 安裝時指令會是
`/day-trader-skill:trader-scanner` 這種形式。複製資料夾則是單純的 `/trader-scanner`。

只想裝在單一專案:把同樣的資料夾複製到 repo 的 `.claude/skills/`。完全沒有 Claude Code?把任一個
`SKILL.md` 貼在對話最前面,它就會當成一種模式運作。這樣用不到 Python 工具,但方法一樣適用。

工具需要 Python 3.8 以上,不用 pip install 任何東西。把 `trader-budget/config.example.json` 複製成
`trader/config.json`,改成你自己的資金、限制與手續費折扣。SEC 相關工具(新聞的申報文件、analyst)
需要表明身分:在 `trader/config.json` 填入姓名與 email(`"sec_user_agent": "Your Name you@example.com"`),
或設定 `SEC_USER_AGENT` 環境變數。

## 十一個 skill

| 指令 | 角色 | 功能 | 台股版 |
| --- | --- | --- | --- |
| `/trader-scanner` | 線圖掃描 | 掃描上千張線圖找型態:開盤區間突破、旗形、超跌反彈。 | 已台股化 |
| `/trader-news` | 新聞監控 | 追蹤你關注股票的即時新聞,標出會影響股價的消息。 | 尚未(美股) |
| `/trader-entry` | 進場計時 | 逐根 K 棒盯著型態,告訴你進場時機。 | 已台股化 |
| `/trader-exit` | 出場規劃 | 進場前先設好停損與停利,讓你知道何時出場。 | 已台股化 |
| `/trader-timemachine` | Time Machine | 下單前重播一筆交易所有可能的結果:10,000 次模擬盤勢,加上過去每次出現同樣型態的日子。 | 尚未(美股) |
| `/trader-risk` | 風險控管 | 用你的限制檢查每筆交易,超過就擋下。 | 已台股化 |
| `/trader-budget` | 資金控管 | 依資金與單筆最大虧損計算每筆部位大小。 | 已台股化 |
| `/trader-broker` | 下單執行 | 把核准的委託送到券商,預設模擬交易,沒有你點頭絕不送出。 | 尚未(美股,Alpaca) |
| `/trader-alerts` | 價格警示 | 價格、停損或開盤鐘響時提醒你。 | 尚未(美股) |
| `/trader-analyst` | 財報分析 | 讀財報,整理出有什麼改變。 | 尚未(美股) |
| `/trader-pelosi` | Pelosi 追蹤 | 美國國會議員的股票交易申報一出來就讀取。 | 尚未(美股) |

## 使用方式

所有輸出都放在專案的 `trader/` 資料夾,每個 skill 讀上一個寫的檔案:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (一筆交易)
alerts: stop, target, flat by the close                                       (持有期間)
news / analyst / pelosi                                                        (定期執行)
```

台股的流程是 scanner -> entry -> exit -> budget -> risk,接著自己到券商下單。

範例是一個虛構的台股交易日:2317.TW,2026 年 10 月 19 日(星期一)。範例資料是合成的,為測試
而建,不是市場資料。這裡只出現五個已台股化的 skill。

1. **`/trader-scanner`** 台北時間 9:45:合成掃描中 8 張可用的線圖,有 6 張收在 15 分鐘開盤區間
   之上。2317.TW 是其中之一:區間 200.50 到 204.00,9:25 那根收 205.00,高出區間上緣 0.49%。
2. **`/trader-entry`** 逐根盯著 2317.TW。9:27 時回報等待(9:25 那根還沒走完)。9:30 時回報觸發:
   第一根收在區間之上的 5 分鐘 K 棒,205.00。前一日收盤 200.00,所以當天跌停 180.00、漲停 220.00。
3. **`/trader-exit`** 在進場前設好計畫:停損設在區間中點,往下取到 0.5 的升降單位,202.00,每股
   風險 3.00;停利是風險的兩倍,211.00;不論如何 13:20 前出清。來回的手續費與證交稅約為部位的 0.32%。
4. **`/trader-budget`** 用 NT$500,000 的帳戶、單筆最大虧損 NT$5,000:算進手續費與證交稅後可以買
   1,369 股,往下取整成一張 1,000 股(NT$205,000)。停損在 202.00 成交時,虧損是 NT$3,000 加上
   NT$652 的手續費與證交稅,共 NT$3,652。停利成交時,扣除成本後的風報比是 1.46(未扣成本 2.00)。
   它寫出一筆委託:買進 2317.TW 1,000 股,停損 202.00,停利 211.00。
5. **`/trader-risk`** 用你的限制檢查:張數、升降單位、漲跌幅、最大虧損、單日虧損上限、每日交易
   次數、扣除成本後的風報比、進場時段、部位大小與現金。結果是 PASS 或 BLOCK,並附上原因。

接著你自己到台灣的券商下單,停損與停利用條件單設定。證交所沒有 bracket 單。

## 工具

全部只用 Python 標準函式庫。讀取公開資料的工具會控制請求頻率。

```bash
python3 trader-scanner/scan.py universe                                # ~2,000 TWSE and TPEx stocks
python3 trader-scanner/scan.py daily                                   # pre-market setups, whole universe
python3 trader-scanner/scan.py orb --at 09:45                          # opening-range breakouts so far
python3 trader-news/news.py --tickers TSLA --hours 12                  # headlines, 8-Ks, today's move (US only)
python3 trader-entry/entry.py check 2317.TW --setup orb                # waiting / triggered / expired
python3 trader-entry/entry.py watch 2317.TW --every 30                 # bar by bar until it triggers
python3 trader-exit/exit.py plan --stop or-mid --target 2R --write     # -> trader/plan.json
python3 trader-timemachine/timemachine.py run --write                  # 10,000 replays + the history (US only)
python3 trader-budget/size.py --write                                  # -> trader/orders.json
python3 trader-risk/check.py                                           # PASS / BLOCK per order
python3 trader-broker/ticket.py show                                   # the tickets, READY or not
python3 trader-alerts/alerts.py add --from-plan                        # stop, target, flat by close
python3 trader-alerts/alerts.py check                                  # rings what hit, once
python3 trader-analyst/facts.py TSLA                                   # quarters, growth, EPS
python3 trader-pelosi/ptr.py index --member pelosi                     # her PTRs this year
```

```bash
python3 -m unittest discover -s tests -v
```

測試完全離線。已台股化的 skill 用合成的交易日(2317.TW 2026 年 10 月 19 日,虛構的 K 棒與虛構的
掃描結果),外加少數真實回應:證交所與櫃買清單的幾列、一個 Yahoo spark 回應、一張 2317.TW 的 Yahoo
5 分鐘線圖。仍是美股版的 skill 保留原本的測試資料(TSLA 的 5 分鐘 K 棒、Yahoo 的 TSLA 新聞、眾議院
書記處 2026 年的索引、真實的 PTR 文字與 XBRL 資料)。台股測試重現上面範例的每一個數字,預期值是
另外獨立算出來的,不是抄程式的輸出。

## 注意事項

**不是投資建議。** 這是讀公開資料、做算術的軟體,不知道你的狀況,也看不到未來。大多數當沖的人都
賠錢,你也可能賠錢。請自己判斷,需要建議時請找有執照的專業人士。

**沒有用真實交易驗證過。** 台股版只用合成與存檔資料測試過,從沒下過真實委託。證交稅率、手續費
折扣、最低手續費與當沖資格會變動,各券商也不同,交易前請自己確認。

**沒有你點頭,任何交易都不會送出。** 只有 `/trader-broker` 能產生委託,而且必須先通過
`/trader-risk` 對那筆委託的檢查,並由你在對話中回答 yes。請在 Claude 把券商工具設成「Needs
approval」(Customize、Connectors、tool permissions),不要設成「Always allow」,讓 Claude 自己的
「Allow once / Deny」卡片成為第二道確認。選擇權、融資、放空與槓桿都要你自己打開才會用。

**先用模擬交易。** `config.example.json` 預設 `"paper": true`,Alpaca 的 MCP server 預設也是模擬帳戶。
金鑰放在環境變數,絕不貼進對話。

**Time Machine 是模擬,不是預測。** 它用這檔股票最近 60 天的 5 分鐘 K 棒建立。未來可能出現這 60 天
從沒發生過的事:財報、暫停交易、突發消息。把它的勝率當成現實檢查,不要當成保證。

**停損是計畫,不是保證。** 行情急殺或跳空時,停損單可能成交在離設定價很遠的地方。顯示的最大虧損是
以停損價計算的虧損。

**資料免費但非官方。** Yahoo Finance 的線圖端點不是官方 API,可能延遲、改版或限制請求頻率。掃描器
與進場計時讀的是 1 分鐘或 5 分鐘 K 棒,不是逐筆成交。重要的數字在行動前請和券商核對。

**當沖規則。** 台股版沒有 PDT 檢查,因為台灣沒有 PDT 規定。現股當沖(同一天買賣同一檔股票)需要
券商核可的帳戶與可當沖的股票(見上面的「當沖資格」),依證交所現行規定零股不能當沖,現股當沖賣出
證交稅 0.15% 是暫行稅率(預設到 2027-12-31;資券當沖 0.3%)。`/trader-risk` 不檢查當沖資格,請自己
確認。仍是美股版的 skill 照它們文字描述的美國規則運作(FINRA Regulatory Notice 26-10 在 2026 年
6 月 4 日取消 25,000 美元的 PDT 最低門檻,券商可在 2027 年 10 月 20 日前逐步實施)。

**美國國會議員的交易是公開資訊,不是內線消息。** 依 STOCK Act,議員超過 1,000 美元的交易要在 45 天內
申報。Pelosi skill 在申報一公開時就讀取。

**稅務。** 在美國,當沖獲利屬於短期資本利得,頻繁交易容易觸發 wash sale。這裡的內容都不是稅務建議。

## 檔案

```
README.md           English
README.zh-TW.md     本檔(繁體中文)
trader-scanner/     SKILL.md, scan.py
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py, twmarket.py (shared Taiwan market rules)
trader-budget/      SKILL.md, size.py, config.example.json, targets.example.json
trader-broker/      SKILL.md, ticket.py, claude_desktop_config.example.json
trader-alerts/      SKILL.md, alerts.py, alerts.example.json
trader-analyst/     SKILL.md, facts.py, metrics.example.json
trader-pelosi/      SKILL.md, ptr.py
tests/              unittest suite + offline fixtures
```

MIT 授權。原作者 [Jake Schincariol](https://opusjake.ai)。台股版是他作品的 fork,沿用相同授權。
