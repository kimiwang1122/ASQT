# 策略生命周期与订单状态机

状态：**已确认**  
来源：PRD 10.4 / 10.6；Archify `docs/archify/asqt-strategy.lifecycle.html`  
修订：2026-09-03

`strategy_version.status` 与 `standard_order.status` 必须使用下列枚举。代码实现属于 P2–P3；本文件冻结语义，禁止跳级。

## 策略生命周期


| 枚举          | 含义                 | 可否生成目标持仓 | 可否下单          |
| ----------- | ------------------ | -------- | ------------- |
| `draft`     | 草稿，还在试想法           | 否        | 否             |
| `backtest`  | 回测中                | 否        | 否             |
| `candidate` | 样本外说得通，待准入         | 否        | 否             |
| `paper`     | 本地模拟盘跟踪            | 是        | 仅 PaperBroker |
| `paused`    | 人工叫停               | 否        | 否             |
| `failed`    | 回测未过（不可复现 / 未来函数等） | 否        | 否             |
| `retired`   | 停用，不再参与交易          | 否        | 否             |
| `archived`  | 归档，留下完整记录          | 否        | 否             |


允许迁移：

```
draft → backtest
backtest → candidate | failed
failed → draft
candidate → paper | retired
paper → paused | archived | retired
paused → paper | retired
```

禁止：`draft` / `backtest` / `candidate` / `failed` 直接下单；`retired` / `archived` 再产生新订单。  
进入 `paper` 前必须能指出：数据版本、参数组版本、回测实验、风控配置。  
暂停恢复必须写原因，并再次检查质量闸门与急停开关。迁移写入 `operation_audit`。

已进入 `paper` 的参数组禁止原地修改；变更必须新版本并重新准入。

## 订单状态机

业务层只认下列状态，禁止理解 QMT/券商私有状态。


| 枚举               | 含义             |
| ---------------- | -------------- |
| `risk_pending`   | 待风控            |
| `submit_pending` | 待提交            |
| `submitted`      | 已提交通道          |
| `partial_filled` | 部分成交           |
| `filled`         | 全部成交           |
| `cancelled`      | 已撤单            |
| `rejected`       | 失败（风控/通道拒绝）    |
| `error`          | 异常（回报缺失、状态对不上） |


允许迁移：

```
risk_pending → submit_pending | rejected
submit_pending → submitted | rejected | cancelled
submitted → partial_filled | filled | cancelled | rejected | error
partial_filled → filled | cancelled | error
```

终态：`filled`、`cancelled`、`rejected`。`error` 必须告警，人工处理后只能进入 `cancelled` 或保持 `error` 并禁止自动重发。

## 幂等与下单前检查

`idem_key` = 策略 ID + 交易日 + symbol + side。调度重试不得生成第二张有效单。

提交前必须全部通过，否则停在 `risk_pending` 或进入 `rejected`：

- 质量闸门当日通过
- 全局急停未打开
- 策略状态为 `paper`
- 非停牌、非涨跌停限制（按 `limit_suspension`）
- 交易时段 / 交易日（`trade_calendar.is_open`）
- 数量满足 [risk_defaults.md](risk_defaults.md) 的交易单位
- 资金与仓位上限
- 通道 `channel_status` 可用



## 目标持仓

策略只输出目标仓（权重 / 数量 / 金额 + 理由 + `data_version`），不直接报券商私有订单对象。  
`OrderService` 负责与当前持仓做差、生成 `standard_order`。

## 确认

- [x] 已确认：策略八态与禁止跳级
- [x] 已确认：订单八态与幂等键定义

- 确认人 / 日期：Kimi.wang / 20260903

