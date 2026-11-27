# CPU 失锁时，DDR 写地址会在哪一拍停下？

旧版[同一布线检查点](perf-mega175-routed-recovery.md)的六条 CDC Critical 中，两条 CDC-10 终止于 CPU ↔ MIG 写地址（AW）队列有效位同步器的异步清零脚。表中是对新版封存 RTL 的离线功能测试；新旧版被测队列、复位逻辑和生成的 MIG AXI 源内容相同。下述时钟组合不是实际板卡采样，也没有模型能在此证明亚稳安全。

**复位不是对称的。** AW 队列的写端使用 CPU 域经 `ResetWrangler` 处理的复位；读端使用 MIG 原始 UI 复位。MIG AXI 前端自身的 `aresetn` 则来自 UI 域经 `ResetWrangler` 处理的复位取反。单独注入 CPU PLL 失锁时，AW 写端和 MIG AXI 可以处于复位，而 AW 读端仍未复位。测试没有让 PLL 或 UI 时钟停振。

| 测试边界 | 观察结果 |
|---|---|
| [只接真实 AW 队列两端](perf-mega175-aw-reset.json) | 四种相位/周期，800 ps 单侧复位。在给定激励下，已开启的远端流在隔离前又接受或送出 3 个地址；每例另校验 81 笔正常有序传输。删去任一方向第一级对远端复位的捕获，四例均触发预期的有效位延迟断言。 |
| [加入实际板级复位逻辑](perf-mega175-aw-board-reset.json) | 核对 34 个实例引脚及两条直连。UI 单侧复位，在指定窗口内 CPU 端新增接收为 0；最后的复位原因释放后，第 17,504 个 CPU 上升沿解除 CPU 复位。只注入 CPU 失锁、预置 6 个地址时，AWVALID 在三个 UI 上升沿仍为 1。人为令 AWREADY 始终为 1 或与 `aresetn` 门控，两种引脚重叠数分别为 3 和 0；此行没有使用 MIG IP 行为。 |
| [接入实际生成的 MIG AXI 前端](perf-mega175-mig-aw-pins.json) | Vivado 2024.2 XSim、原 IP 和功能原语库，核对 12 项参数。连续提供 AW、不提供 W 数据，首个地址待发时注入 800 ps CPU 失锁。取 `aresetn=0` 时的十个 UI 上升沿，四种工况均为 **AWVALID `1110000000`、AWREADY `1000000000`**。跨复位区间内未见新的内存控制器请求或写数据；故障前、恢复后各一次单拍写均收到匹配 ID 的 OKAY 响应。 |

因此不能用“`aresetn` 拉低就会组合清掉 `AWREADY`”来豁免这处告警。复位期间第一个采样沿的引脚同高也不能记作协议认可的事务，更不能据此断言 DDR 被写。测试的内存控制器应用侧为已校准、可接收模型，没有 DDR PHY 或外部存储；这项仅 AW 的测试没有覆盖同时在途的 AW/W/B 或背压；完整写的补充测试见下节。此结果未改变约束、未解除任何 CDC Critical，也不产生 CoreMark 成绩。

## 完整写通路：CPU 没收到确认，写是否已经发生？

沿真实板级 `TileLink → TLToAXI4 → AXI 跨时钟队列 → MIG AXI → 内存控制器应用接口` 分别计数。模型包括封存包中的 41 个桥接/复位 RTL 文件、生成 IP 的 AXI 前端和 Vivado 2024.2 功能原语；时钟、校准和内存控制器应用侧由夹具提供。每例发三笔不同地址、数据和 source ID 的单拍 8 字节写，只对中间一笔施压。两端的正常写均核对地址、数据、掩码和返回的确认。

| 中间一笔：AXI 已接收地址和数据，CPU 暂不接收确认 | 不复位，解除反压 | 注入 800 ps CPU 失锁，再解除反压 |
|---|---|---|
| 内存控制器命令/数据任一路或两路不就绪。观察的 32 个 UI 周期内，两路都没有握手。 | 命令、数据、AXI B 响应和 CPU 确认各一次。 | 在观察窗口内，没有迟到的命令、数据、B 或 CPU 确认；恢复后的新写通过。 |
| 命令和数据均就绪。失锁前两路都已握手、AXI 已回 B，CPU 侧确认有效但尚未握手。 | CPU 收到待交付的确认，命令和数据均未重复。 | CPU 没有收到原来的确认，但**内存控制器接口在失锁前已经接受过这笔写的命令和数据**；恢复后新写通过。 |

[32 组逐例计数与输入指纹](perf-mega175-mig-tl-abort.json)：四种时钟/相位组合 × 四种反压条件 × 复位或不复位；另把恢复后的写数据翻转一位，监测器在 AXI W 数据检查处按预期报错。**上层没收到确认，不能据此判定外部写没有发生。** 此处只观察到接口握手，没有 DDR PHY 或存储内容读回，不能据此保证重复提交安全。这里只覆盖时钟连续、单笔在途和指定反压窗口，不覆盖逐拍变化的反压、多笔并行、时钟停振/重锁或亚稳态；未豁免 CDC，也不是板测。

## 复现

`STOCK` 和 `CANDIDATE` 是[原版与双路径优化版](perf-mega175-miss-select.md)的完整封存输入。`OLD_IP`、`NEW_IP` 是对应 Vivado 生成的 `vcu118mig` 目录，`IVL` 是包含 `usr/bin/iverilog` 与 `usr/bin/vvp` 的工具根。输出使用彼此独立、不存在的新目录。

```sh
python3 scripts/test-mega-aw-reset.py "$STOCK" "$CANDIDATE" "$OUT_QUEUE" "$IVL"
python3 scripts/test-mega-aw-board-reset.py "$STOCK" "$CANDIDATE" "$OUT_BOARD" "$IVL"
python3 scripts/test-mega-mig-aw-pins.py "$CANDIDATE" "$OLD_IP" "$NEW_IP" "$VIVADO_INSTALL" "$OUT_PINS"
python3 scripts/test-mega-mig-tl-abort.py "$CANDIDATE" "$OLD_IP" "$NEW_IP" "$VIVADO_INSTALL" "$OUT_TL"
```

公开记录仅含自写测试与引脚观察、输入指纹；不分发厂商生成的 IP 或私有原始日志。
