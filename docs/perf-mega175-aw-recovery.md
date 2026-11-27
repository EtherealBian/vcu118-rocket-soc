# CPU 失锁时，DDR 写地址会在哪一拍停下？

旧版[同一布线检查点](perf-mega175-routed-recovery.md)的六条 CDC Critical 中，两条 CDC-10 终止于 CPU ↔ MIG 写地址（AW）队列有效位同步器的异步清零脚。表中是对新版封存 RTL 的离线功能测试；新旧版被测队列、复位逻辑和生成的 MIG AXI 源内容相同。下述时钟组合不是实际板卡采样，也没有模型能在此证明亚稳安全。

**复位不是对称的。** AW 队列的写端使用 CPU 域经 `ResetWrangler` 处理的复位；读端使用 MIG 原始 UI 复位。MIG AXI 前端自身的 `aresetn` 则来自 UI 域经 `ResetWrangler` 处理的复位取反。单独注入 CPU PLL 失锁时，AW 写端和 MIG AXI 可以处于复位，而 AW 读端仍未复位。测试没有让 PLL 或 UI 时钟停振。

| 测试边界 | 观察结果 |
|---|---|
| [只接真实 AW 队列两端](perf-mega175-aw-reset.json) | 四种相位/周期，800 ps 单侧复位。在给定激励下，已开启的远端流在隔离前又接受或送出 3 个地址；每例另校验 81 笔正常有序传输。删去任一方向第一级对远端复位的捕获，四例均触发预期的有效位延迟断言。 |
| [加入实际板级复位逻辑](perf-mega175-aw-board-reset.json) | 核对 34 个实例引脚及两条直连。UI 单侧复位，在指定窗口内 CPU 端新增接收为 0；最后的复位原因释放后，第 17,504 个 CPU 上升沿解除 CPU 复位。只注入 CPU 失锁、预置 6 个地址时，AWVALID 在三个 UI 上升沿仍为 1。人为令 AWREADY 始终为 1 或与 `aresetn` 门控，两种引脚重叠数分别为 3 和 0；此行没有使用 MIG IP 行为。 |
| [接入实际生成的 MIG AXI 前端](perf-mega175-mig-aw-pins.json) | Vivado 2024.2 XSim、原 IP 和功能原语库，核对 12 项参数。连续提供 AW、不提供 W 数据，首个地址待发时注入 800 ps CPU 失锁。取 `aresetn=0` 时的十个 UI 上升沿，四种工况均为 **AWVALID `1110000000`、AWREADY `1000000000`**。跨复位区间内未见新的内存控制器请求或写数据；故障前、恢复后各一次单拍写均收到匹配 ID 的 OKAY 响应。 |

因此不能用“`aresetn` 拉低就会组合清掉 `AWREADY`”来豁免这处告警。复位期间第一个采样沿的引脚同高也不能记作协议认可的事务，更不能据此断言 DDR 被写。测试的内存控制器应用侧为已校准、可接收模型，没有 DDR PHY 或外部存储；同时在途的 AW/W/B、背压、停钟重锁和其它通道仍需独立测试。此结果未改变约束、未解除任何 CDC Critical，也不产生 CoreMark 成绩。

## 复现

`STOCK` 和 `CANDIDATE` 是[原版与双路径优化版](perf-mega175-miss-select.md)的完整封存输入。`OLD_IP`、`NEW_IP` 是对应 Vivado 生成的 `vcu118mig` 目录，`IVL` 是包含 `usr/bin/iverilog` 与 `usr/bin/vvp` 的工具根。输出使用彼此独立、不存在的新目录。

```sh
python3 scripts/test-mega-aw-reset.py "$STOCK" "$CANDIDATE" "$OUT_QUEUE" "$IVL"
python3 scripts/test-mega-aw-board-reset.py "$STOCK" "$CANDIDATE" "$OUT_BOARD" "$IVL"
python3 scripts/test-mega-mig-aw-pins.py "$CANDIDATE" "$OLD_IP" "$NEW_IP" "$VIVADO_INSTALL" "$OUT_PINS"
```

公开记录仅含自写测试与引脚观察、输入指纹；不分发厂商生成的 IP 或私有原始日志。
