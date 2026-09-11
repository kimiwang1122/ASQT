# P4 执行通道（QMT）

状态：**暂缓接线；预留适配器已落地，禁止当真实通道用**  
修订：2026-09-11  
前置：Q2（QMT / XtQuant / 券商模拟盘权限）  
整体进度：[../progress.md](../progress.md)

P3 PaperBroker 仍是唯一可下单通道。本阶段**不**在业务层 import `xtquant`，不提交券商私有订单。设置页 / `/api/ports` 对 QMT 必须显示不可用，禁止标成「已接」。

## 本阶段明确不做

- 真实 MiniQMT 登录、报单、撤单、成交订阅
- 把一张 `standard_order` 拆成 N 张业务订单（拆单只允许映射为多条 `execution_fill`）
- 用设置页「当前佣金」重算历史费用（核对仍认成交当时写入的 `fee`）

## 已落地（预留，必须验收）

| ID | 项 | 验收 |
|---|---|---|
| QMT0 | `asqt/adapters/qmt_broker.py` `QmtExecutionAdapter` | `channel_id=qmt`；`channel_status.available=false`；`reason=q2_pending` |
| QMT1 | 提交/撤/查 | `submit` / `cancel` / `query_order` 抛错，不得静默当成功 |
| QMT2 | 默认通道 | `PaperBroker.channel_id == paper`；控制台执行仍走 Paper |
| QMT3 | 依赖禁令 | `asqt/` 源码不含 `xtquant`；`api.py` 不 import `qmt_broker` |

```bash
.venv/bin/pytest tests/test_p4_qmt_stub.py
```

## Q2 具备后才开的验收（未实现）

必须同时成立，缺一不可：

1. SDK 只出现在 `asqt/adapters/qmt_broker.py`（或其后继），`api.py` / `paper.py` / 策略层零引用
2. 消费同一 `standard_order`，回写 `execution_fill`；一笔业务单可对应多笔成交；订单走 `submitted → partial_filled → filled`
3. 费用以通道回报为准；旁路公式只用**该笔委托/成交时点**的佣金费率 + 代码里的印花税/过户费，禁止用设置页现值
4. `channel_status.available=true` 仅在 MiniQMT 心跳成功时；失败时 Paper 不得被静默替换，也不得双通道同时报单
5. 调佣不假设「一定收盘后生效」；新费率只作用于之后新委托
6. pytest 用假回报夹具覆盖：全成、部分成、拒单、通道不可用；禁止 CI 依赖真实券商

## 确认

- [x] Q2 未关闭前不得把 QMT 标成「完成」
- [x] 预留适配器不可用，由 `tests/test_p4_qmt_stub.py` 锁住
