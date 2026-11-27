# 四路 BOOM：把整数发射队列的 load-miss 选择移到搬移之后

原[完整布线检查点](perf-mega175-routed-recovery.md)中，最差建立路径从分支状态，经 D-cache 和 LSU，到整数发射槽 9 的保留判断，再经槽 8 的搬入有效位，到其第二操作数就绪寄存器。5.714 ns 周期下余量 −9.237 ns。此处测试的是单 hart、40 槽的整数发射队列，不是 24 槽的访存队列；也不是增加流水级。

### 改了什么

一条 load miss 会撤销推测唤醒。若源槽本来可以发射并离开、但其操作数依赖该唤醒，则当拍仍须保留。原设计先在**每个来源**判断是否保留，再从最多四个来源搬入。实验候选把每个来源拆成“不靠 miss 也保留”与“若 miss 则保留”两路，由原来的搬移控制分别选出两位，最后才消费共同的 `io_ld_miss`。39 个有驻留来源的目的槽使用该式，只有分发输入的槽 39 原样。没有寄存 miss，没有推迟失败加载处理；访存与浮点队列未改。

### 怎样排除接错槽和模拟假阳性

| 范围 | 实际检查 |
|---|---|
| 组合等价 | 从原版与候选的实际 RTL 提取 40 个驻留有效位和 40 个搬入有效位；485 位输入任意，不假设选择互斥。80 个输出二态 SAT 等价。故意漏掉第二操作数的推测依赖，以及把槽 8 来源由槽 9 错接槽 10，两者都有反例。|
| 完整队列、定向组合对照 | 两份完整 SV 队列各含 40 个真实槽。控制驻留状态、授权和推测依赖，保持原优先选择逻辑。150 对驻留来源/目的分别用两个操作数测试，共 300 次 miss 的低→高→低；另外测 10 对分发入口和目的。两边 80 个有效位均一致；错接在槽 8 的定向测试中被拒绝。不是时序状态空间证明。|
| 完整队列、带时钟，无内部强制 | 同样的复位与端口激励，1,200 拍。对比已知的分发/发射控制和有效发射载荷、及各槽的保留/搬入。共 2,686 个有效发射 lane 样本；在沿间切换 miss 时，参考的搬入有效位有 1,135 个样本随之变化（槽 8 有 28 个）。错接槽 10 的负控第 639 个周期被拒绝。人工队列激励，不是 Linux/CoreMark。|

[两套完整队列测试、形式验证和整机输入指纹](perf-mega175-miss-select.json)。与[前端循环预测修复](perf-mega175-loop-repair.md)同时使用时，原版 589 个封存文件只有 3 个 RTL 文件变化；549 项 HDL 的内容清单顺序不变。没有叠加改 IPC 的重命名实验，没有变更时钟、约束、例外、容量、ROM 或基准 ELF。

### 离线复现

以下每个输出目录必须是新目录。`IVL=/path/to/icarus-root`；`KIT` 是封存原版物理输入，不是其它 BOOM 配置。

```sh
python3 scripts/prove-mega-miss-select.py "$KIT" "$PROOF" --yosys "$YOSYS"
python3 scripts/test-mega-miss-queue.py "$KIT" "$DIRECTED" --iverilog "$IVL/usr/bin/iverilog" \
  --vvp "$IVL/usr/bin/vvp" --ivl-dir "$IVL/usr/lib/x86_64-linux-gnu/ivl"
python3 scripts/test-mega-miss-clocked.py "$KIT" "$CLOCKED" "$IVL"
vivado -mode batch -source scripts/implement-mega-miss-select-ooc.tcl -tclargs "$PROOF" "$PAIR" > pair.stdout
python3 scripts/review-mega-miss-select-ooc.py "$PROOF" "$PAIR" pair.stdout
python3 scripts/prepare-mega-route-recovery.py "$KIT" "$NEW_KIT" "$PROOF/result.json" "$DIRECTED/result.json" --with-miss --clocked "$CLOCKED/result.json"
```
### 局部布局布线结果与整机决策（北京时间 2026-11-28 04:37）

在 VCU118 同一型号器件上，前述 80 个输出与 485 位独立输入放进相同的寄存边界，用同一 5.714 ns 约束分别做一次实现。**39 个 miss→搬入端点，33 个余量提高、6 个下降。** 逻辑深度从原来的全部 3 层变为 37 条 1 层、2 条 2 层。变浅不保证布线更快：退化最大的是槽 15（−0.386 ns）。

| 测量项 | 原版 | 候选 |
|---|---:|---:|
| miss → 槽 8 搬入：层数 / 数据延时 | 3 / 1.194 ns | 1 / 1.067 ns |
| 同端点建立余量 | +4.501 ns | +4.627 ns |
| 39 个 miss→搬入中最小余量 | +4.001 ns | +4.197 ns |
| 局部全设计 WNS / WHS | +4.001 / +0.043 ns | +4.180 / +0.057 ns |
| CLB LUT / 触发器（含同一外壳） | 199 / 565 | 276 / 565 |
| 完成布线的网络 / 布线错误 | 642 / 0 | 683 / 0 |

[两次实现的端点、报告指纹与逐槽差值](perf-mega175-miss-select-ooc.json)。端点是寄存边界，不包含真实 LSU 在 miss 上游的逻辑、有效位后面的载荷选择到 `p2_reg`、或器件内跨 SLR 的拥塞。不能把 +0.126 ns 加到整机 WNS、换算频率或推算分数。

**决策：把较快的前端与后端合到一个新版本，实际运行完整物理实现。** 04:36:45 已用 Vivado 2024.2 启动，确认已进入顶层工程/IP 初始化；175.0 MHz 是 PLL 配置，不是实现主频。板级清单 SHA-256 `ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456`。实现仍执行同一封存配方，只在外层加报告采集：布线检查点写完、进入后布线 `phys_opt_design` 前提取该版时序、CDC、DRC、约束覆盖和时钟交互，不修改时序例外。后布线优化若再次异常退出，应明确区分检查点与最终结果。

```sh
vivado -mode batch -source scripts/run-mega-route-recovery.tcl -tclargs "$NEW_KIT" "$FRESH_BUILD"
```

此截点新整机没有 WNS、bitstream 或 Linux 板测。未连接硬件，未写入 flash；继续沿用[相同二进制的历史 Rocket 对照](coremark-target-rocket-control.json)，不把它登记为 BOOM 成绩。
