# UART、SD-SPI 和软核 JTAG：十个 `inout` 是否真的双向？

四路 BOOM 的[原版布线报告](perf-mega175-routed-recovery.md)中，十个引脚各有一条 `RPBF-3`（双向端口缺少一侧缓冲），其中五个输出另有 `HPDR-1`（层次端口方向不一致）。旧版与正在综合的恢复版使用完全相同的顶层、两个方向转换器和 shell XDC。候选只在一份派生的顶层把这些引脚改成实际方向，换成等价的直接连线；没有修改任何封存输入，没有改动 DDR4 数据引脚或未使用的引脚。

| 通路 | 板 → 核 | 核 → 板 |
|---|---|---|
| UART | RXD AW25 | TXD BB21 |
| SD-SPI | MISO AW15 | SCK AV15、MOSI AY15、CS_n AY14 |
| 软核调试 TAP | TCK AL12、TDI AP15、TMS AN15 | TDO AM12 |

引脚方向取自实际连线：`sdio_spi_cs` 驱动 MOSI，`sdio_spi_dat_3` 驱动 CS_n。原顶层五个输出的使能都固定为 1，不能把该做法套用到真正会释放总线的输出。这里的软核 TAP 不是配置 FPGA 的 JTAG 下载通道。

**逻辑核对。** 从原顶层和派生顶层分别抽取十段实际边界连线，在相同的五个发射和五个采样寄存器之间测试。XSim 逐拍对照外部输入和预期驱动值：1,024 种二值组合，加 20 个带 X/Z 的样本，两版均通过。作为负对照，故意让 CS_n 跟随 MOSI，1,044 个样本中有 516 个检测到错误。未从板外反向驱动已使能的输出。此测试不涵盖 UART 字符、SD 事务或 TAP 调试协议。

**物理工具对照。** 在同一 `xcvu9p-flga2104-2L-e` 上按正常顶层分别综合（允许插入 I/O 缓冲；不布局布线）。Vivado 2024.2 的两条原生检查均启用，原版命中与旧整机相同的端口集合。两个夹具使用同样的十组封装引脚和 LVCMOS18；其余十个数据位和一个时钟仅用于夹具。

| 综合后，同一组十个引脚 | 原版 | 候选 |
|---|---|---|
| 顶层端口方向 | 10 个 INOUT | 5 个 IN，5 个 OUT |
| 输入叶级缓冲 | 5 个 INBUF | 同左 |
| 输出叶级缓冲 | 5 个 OBUFT；逐个追溯到 `T = NOT(VCC) = 0`，始终驱动 | 5 个 OBUF，无三态使能 |
| `RPBF-3`（DRC） | 10 条 | 0 条 |
| `HPDR-1`（methodology） | 5 条 | 0 条 |

零条是本夹具选定规则的实际报告计数，不是整机剩余 DRC 数。各端口、综合检查点及报告指纹见[机器可读记录](perf-mega175-board-pads.json)。

**验收边界。** 这不是 CPU 慢路径优化，也不是板测。软核 TCK 专用时钟路由告警 `PLCK-58`、UART TX 输出寄存器放置告警 `REQP-1618`、5 个输入和 6 个输出的 delay 覆盖、6 条 CDC Critical 都须在整机分别审查。本实验没有豁免这些问题，也没有改时序例外。没有新 bitstream 或新版板上 CoreMark 分数。

## 复核路径

1. `scripts/test-mega-board-pads.py prepare OLD_KIT NEW_KIT OLD_REPORTS NEW_INPUT_DIR` 校验两个输入版本及四份历史报告，派生本地实验材料。`check NEW_INPUT_DIR` 会拒收变更的夹具、方向桥、引脚约束或父顶层。
2. `scripts/test-mega-board-pads.py sim NEW_INPUT_DIR VIVADO_ROOT NEW_SIM_DIR` 运行三份实例共用的 XSim 自检。
3. 分两个独立 Vivado 进程执行 `-mode batch -source scripts/probe-mega-board-pads.tcl -tclargs NEW_INPUT_DIR NEW_STOCK_DIR stock` 与对应的 `NEW_TYPED_DIR typed`。派生文件、检查点与原生报告均留在私有构建目录。
4. `scripts/review-mega-board-pads.py NEW_INPUT_DIR NEW_SIM_DIR NEW_STOCK_DIR NEW_TYPED_DIR` 对照综合检查点自身的端口声明、逐引脚叶级缓冲、规则属性、报告检查数与实际告警端口，再导出去敏结果。
