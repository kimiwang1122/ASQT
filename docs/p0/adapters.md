# 组件可替换边界

状态：**已确认**  
来源：`asqt/ports.py`、技术设计第 2 / 7 章  
修订：2026-09-03

业务代码只依赖协议，不依赖厂商 SDK。P1 起新增实现必须放在独立模块（建议 `asqt/adapters/`），由组合根注入。

## 协议与允许的实现位置


| 协议                | 职责              | 允许出现的实现依赖                                    | 禁止泄漏到               |
| ----------------- | --------------- | -------------------------------------------- | ------------------- |
| DataSourceAdapter | 拉 raw           | baostock / AkShare / Tushare / 商业源 / FTShare | `api.py`、策略、订单      |
| DataNormalizer    | raw → 标准契约      | 自研                                           | 厂商私有 DataFrame 模式   |
| QualityChecker    | 过关或阻断           | 自研                                           | 在 checker 外改标准表「圆场」 |
| ResearchEngine    | 回测 / 因子         | Qlib（可辅 VectorBT）                            | 业务层 import qlib     |
| StrategyService   | 版本与目标仓          | 自研                                           | 直接调券商               |
| OrderService      | 目标仓 → 标准订单 + 风控 | 自研                                           | 通道私有订单对象            |
| ExecutionAdapter  | 提交 / 撤 / 查 / 状态 | PaperBroker；其后 XtQuant / vn.py               | 策略层                 |
| ReviewService     | 复盘              | MLflow 或自研报表                                 | 研究层写死 MLflow UI     |
| Scheduler         | 任务编排            | 先 CLI/cron，后队列                               | 任务里绕过质检             |
| AlertService      | 告警              | 本地 jsonl + 飞书自定义机器人 webhook（`asqt/adapters/feishu_alert.py`） | 硬编码 IM SDK 到 `api.py` |


当前 `asqt/api.py` 只读 SQLite/Parquet，不 import 厂商 SDK。已接线的 port：`DataSourceAdapter` / `DataNormalizer` / `QualityChecker` / `ResearchEngine` / `StrategyService`。P2 研究实现是 `asqt/research_engine.py`，禁止在该层之外 import `qlib`。

## 依赖检查清单（P1 起每次 PR 自检）

下列名称不得出现在 `asqt/api.py`、`asqt/bootstrap.py`、`asqt/db.py`、`asqt/contracts.py`、策略/订单核心模块中：

`qlib`、`xtquant`、`xtquant.qmttools`、`baostock`、`akshare`、`tushare`、`ftshare`、`vnpy`、`mlflow`

允许出现在 `asqt/adapters/*` 或明确标注的 engine 实现文件中。

## 替换不改的契约

换数据源：仍写同一套 `market_daily` / `instrument_master`。  
换研究引擎：仍产出 `factor_signal` 与回测报告元数据。  
换执行通道：仍消费 `standard_order`，仍回写 `execution_fill`。

## 确认

- [x] 已确认：厂商 SDK 只允许在 adapters / engine 实现里

- 确认人 / 日期：Kimi.wang / 20260903

