# ASQT 图册（给非技术人员）

用浏览器直接打开下面的 HTML 即可，不需要启动服务。双击文件，或把路径拖进 Chrome。

| 打开这个文件 | 看什么 | 一句话 |
|---|---|---|
| [asqt-now.architecture.html](asqt-now.architecture.html) | 现在能做什么 | 今天只能打开控制台看演示数据，还不能自动买卖 |
| [asqt-next.architecture.html](asqt-next.architecture.html) | 下一步接通后 | 行情先质检，再进模拟盘，仍然不接实盘 |
| [asqt-delta.architecture.html](asqt-delta.architecture.html) | 现在 vs 下一步 | 绿线是新增，红虚线是去掉，黄点线是改了含义 |
| [asqt-data.dataflow.html](asqt-data.dataflow.html) | 数据过关规则（早期） | 不合格就告警并停交易，不能悄悄改数 |
| [asqt-data-layer.dataflow.html](asqt-data-layer.dataflow.html) | 数据层怎么走 | 名单 → 主备拉取 → 标准化 → 闸门落盘 → 只读巡检与对账 |
| [asqt-schema.architecture.html](asqt-schema.architecture.html) | 库表怎么连 | 主数据与日K、涨跌停、策略订单台账；逻辑键不是外键 |
| [asqt-day.sequence.html](asqt-day.sequence.html) | 收盘后顺序 | 先更新、再质检、最后才模拟成交 |
| [asqt-strategy.lifecycle.html](asqt-strategy.lifecycle.html) | 策略能不能上 | 草稿和回测中的策略不许自动下单 |

## 怎么点

- `P` 播放讲解章节（适合给别人演示）
- `/` 搜索方块名称
- 点带 **SRC** 的方块，可跳到 GitHub 上对应源码（钉在提交 `12d41cde`）
- `T` 切换白天/黑夜
- 对比图上方可切换 **Before / Delta / After**；变更列表较长时页面可以滚动

数据层图反映的是 **P1 已接通的拉取、标准化、闸门与对账**。模拟成交与研究回测仍未接线。
