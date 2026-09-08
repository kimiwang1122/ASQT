# 数据契约

状态：**已确认**  
来源：`asqt/contracts.py`、`asqt/storage.py`、PRD 10.1–10.2、技术设计 4.1  
修订：2026-09-03

代码里的**列名**已经存在。本文冻结口径；P1 实现适配器时必须遵守。缺关键口径不得进 P1 全量拉数。

## 通用约定


| 项                | 口径                                                |
| ---------------- | ------------------------------------------------- |
| 证券代码 `symbol`    | `代码.市场`，市场为 `SH` / `SZ`；例 `000001.SZ`、`510300.SH` |
| 交易日 `trade_date` | `YYYY-MM-DD`，中国大陆日历，不含时区后缀                        |
| 交易时段             | 默认 `09:30`–`15:00`（含午休，日频不拆段）                     |
| 货币               | CNY                                               |
| 价格               | 元 / 股（或 ETF 份额），未复权成交价写入 OHLC；复权只通过 `adj_factor`  |
| 成交量 `volume`     | 股（ETF 为份额），整数                                     |
| 成交额 `amount`     | 元                                                 |
| 主键时间             | 日频表以 `(symbol, trade_date)` 或文档标明的主键为准            |
| 禁止静默覆盖           | 源数据修正必须换 `version` / 批次，并留下 raw                   |


## 行情 `market_daily`（Parquet）

路径：`data/standard_data/market_daily.parquet`  
主键：`(symbol, trade_date)`  
实现：`asqt/storage.py`


| 字段                        | 类型口径 | 说明                                                                |
| ------------------------- | ---- | ----------------------------------------------------------------- |
| symbol                    | 文本   | 见上                                                                |
| trade_date                | 日期文本 | 见上                                                                |
| open / high / low / close | 浮点，元 | 当日未复权；须满足 high ≥ max(open,close,low) 且 low ≤ min(open,close,high) |
| volume                    | 整数，股 | ≥ 0                                                               |
| amount                    | 浮点，元 | ≥ 0                                                               |
| adj_factor                | 浮点   | 后复权因子，当日有效；缺失则该行不得进入可交易版本                                         |
| source                    | 文本   | 标准化所依据的 `data_source.source_id`                                   |
| version                   | 文本   | 数据版本 / 批次号，可追溯到 raw 文件                                            |


复权：研究侧用 `close * adj_factor / adj_factor_base` 得到可比价格；交易下单仍用未复权价格与数量。基准日在研究配置中声明，不写进本表。

## SQLite 主数据



### `instrument_master`

主键：`symbol`


| 字段                      | 口径                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------- |
| instrument_type         | 仅 `stock` | `etf`（一期）                                                                       |
| exchange                | `SH` | `SZ`                                                                                 |
| board                   | 股票：`main` / `chinext` / `star` / `bse` 等；ETF：`broad_index` / `sector` / `bond` 等，P1 落名单时补枚举 |
| status                  | `listed` | `delisted` | `suspended`                                                         |
| is_st                   | 0/1；ETF 为 0                                                                                 |
| list_date / delist_date | `YYYY-MM-DD`；在市则 delist 为空                                                                  |




### `trade_calendar`

主键：`(trade_date, market)`  
`market` 一期仅 `CN`。`is_open=1` 才允许日 K 与交易。

### `limit_suspension`

主键：`(symbol, trade_date)`  
`limit_up` / `limit_down` 为价格（元）；`is_suspended=1` 当日不得新开仓。缺失涨跌停价时，质量闸门按「P0 数据缺失」处理。

### `data_source`

主键：`source_id`  
必须有 `quota`、`cost`、`owner`、`priority`（数字越小越优先）、`auth_status`、`health_status`。未授权或配额未确认的源不得作交易主源。

### `quality_issue`

主键：`issue_id`  
`check_type` 至少覆盖：`missing`（缺失）、`range`（越界）、`adj_conflict`（复权冲突）、`point_in_time`（时点错误）。  
`severity`：`block` 必须停止新订单；`warn` 可继续但必须告警。  
不允许用「修好标准表、不记 issue」的方式覆盖。

### `factor_signal`

主键建议：`(trade_date, symbol, factor_name, model_version)`  
P2 才写入；P1 表可空。

### 策略 / 订单 / 账本

字段以 `asqt/contracts.py` 为准。状态枚举见 [order_state_machine.md](order_state_machine.md)。

- `target_position`：同一 `strategy_id` + `trade_date` 只允许一个有效版本；必须带 `data_version`。
- `standard_order.idem_key`：同一策略、交易日、标的、方向唯一。
- `account_snapshot`：每个账户每个交易日一行，用于重建权益。



## P1 质量闸门最小规则（契约层）

构造下列样例时必须记 `quality_issue` 且 `severity=block`：

1. 交易日或标的缺失、OHLC/volume/adj_factor 空值
2. 价格/量额越界，或开高低收关系错误
3. 同一标的相邻日 `adj_factor` 跳变无法用已核实公司行为解释（P1 先做阈值告警；解释规则见 [corporate_actions.md](corporate_actions.md)）
4. 用未来才可知的 ST/退市/成分股信息生成当日信号（时点错误）



## 确认

- [x] 已确认：代码格式、未复权 OHLC + `adj_factor`、质量四类样例

- 确认人 / 日期：Kimi.wang / 20260903

