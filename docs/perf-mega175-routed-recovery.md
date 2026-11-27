# 同一份四路 BOOM 布线网表：175 MHz 卡在哪里？

北京时间 2026-11-28 04:00 截点。单 hart、单上下文；四路是译码/提交宽度。**[截止目标](status-2026-11-27-1800.md)未达；性能 0/3 次、验证 0/3 次完成，无实板分数。**

原作业写完[布线检查点](perf-mega175-route-start.md)后，单独的 `phys_opt_design -directive Explore` 在 Phase 2 异常退出（进程退出码 `0xC0000374`）。没有最终 `post_route.dcp` 或 bitstream。没有据此认定软件崩溃的根因。另起 Vivado 2024.2，只读打开原先已完整写出的 **`routed_before_physopt.dcp`**，未再布局、布线或修改约束。以下来自这个检查点，不是崩溃步骤的输出，也不是板测。

| 检查 | 实际结果 |
|---|---|
| 连通性 | 498,213 / 498,213 个可布网络完成，0 个布线错误 |
| 全设计建立时序 | WNS **−9.237 ns**，TNS **−747,889.875 ns**；164,801 / 372,265 个端点违反，集中在 CPU 时钟组 |
| 保持 / 脉宽 | 最差余量分别为 +0.010 / +0.143 ns，两项均无违反端点 |
| 约束覆盖 | 无时钟端点 0、未约束内部端点 0；5 个输入、6 个输出缺 delay，须按接口审查 |
| CDC / 默认 DRC | CDC 有 6 条 Critical，见下；默认 DRC 有 135 条 Warning，未报 Error。都不是发布签核 |

## 40 个最差 CPU 建立端点

用 `get_timing_paths -to $cpu -delay_type max -max_paths 40 -nworst 1` 提取，40 个终点互不相同；`$cpu` 为周期 5.714 ns 的 `clk_out1_harnessSysPLL`。再用含 input pins 的逐段报告核对前两条。

| 源寄存器（省略公共层次） | 端点数 | 逐段证据 |
|---|---:|---|
| `core/brinfos_0_valid_reg` | 16 | 最差 −9.237 ns，至整数发射槽 8 的 `p2_reg/D`。经过 D-cache MSHR/RPQ、LSU 的 load-miss 信号到发射槽。32 层，数据延时 14.725 ns，其中布线 12.112 ns。`_lsu_io_core_ld_miss` 网络扇出 122，该段 1.640 ns。|
| 循环预测器 `columns_0/f3_scnt_REG_reg[35]` | 19 | 次差 −9.230 ns，至 I-cache BRAM 地址脚。经过 F3 预测方向与全局历史选择；28 层，数据延时 14.528 ns，其中布线 11.851 ns。生成 RTL 中 `f3_scnt_REG <= io_f2_req_idx`，该寄存器保存请求索引。|
| `dcache/s2_req_1_addr_reg[19]` | 5 | 第三个源族；未把上述两条逐段结果推广到它。|

前两条只差 **7 ps**，且两者数据延时均逾 80% 来自布线。下一轮分别对照 **F3 预测方向到取指地址**、**load-miss 到发射槽就绪**：先检查能否提前算出候选值或在消费端局部选择，做保持时序行为的等价对照，再比较相同约束下的整机时序。仅重写发射仲裁器不足以覆盖前端问题。这是下一轮实验，不是已取得的改善。

### 后端：从 load-miss 到槽 8 不只是一次就绪判断

在上述 −9.237 ns 的同一条路径中，`lsu/io_core_ld_miss3` 后的 miss 网络跨 SLR 1 → 2，扇出 122，本段 1.640 ns。随后经过槽 9 的 `io_will_be_valid`，再到 `issue_slots_8_in_uop_valid`（扇出 151，本段 0.634 ns）。对照同版 `IssueSlot_32` 和 `IssueUnitCollapsing_1`：当源槽获准发射，但依赖推测唤醒且此次 load miss 时，槽可能需要保留；槽 8 搬入有效位的一个数据来源正是槽 9。再往后的两条单负载网络分别跨 SLR 2 → 1、1 → 2，用了 1.132 和 1.012 ns，最后抵达 `slots_8/p2_reg/D`。这是报告中的物理网络名与 RTL 的对照，不把中间组合逻辑的归属名解读成队列实际移动了多次。

因此后端实验应比较两个量：miss 到搬入有效位的选择深度，以及搬入有效位到 `p2` 的布线。直接把 miss 寄存会改变推测唤醒失败时的行为；即便前端修好，这一条仍可能限制整机。

## 六条 CDC Critical 的去向

- `CDC-7` 两条：MIG `mmcm_clkout0` 的复位、`sys_clock` 的上电复位，分别到 CPU 域同一 `deglitched_deglitch/reg_0_reg/PRE`。后一条上有 `False Path`，仍须核实复位的断言和释放。
- `CDC-10` 四条：CPU ↔ `JTCK` 各一条，终点在调试模块异步队列有效位同步链的 `CLR`；CPU ↔ MIG `mmcm_clkout0` 各一条，终点在 AXI AW 异步队列有效位同步链的 `CLR`。逐项核对同步链之前的组合逻辑，不沿用 Rocket 的处理结论。

### 私有原件复核指纹（SHA-256）

| 原件 | SHA-256 |
|---|---|
| `routed_before_physopt.dcp` | `d0ead1ae8498f90d6ec268dc12c7f26d745448bcf2c20b4ce681a4dd356ef581` |
| `full-timing.rpt` | `120b9ea1c595fabe7db8aaa657f000c036a3dfbd92b86ee9342f9868b4096d8a` |
| `cpu-max.tsv` | `df1c4915dbf7d2aa48b17bd232709d84b17582b38ff5b3d96b92c3a4d1b7f399` |
| `cdc.rpt` | `b7b4ff7357a3f7f21b5c79a1cc8ed90f21e925c374712f6ade8d7aa767b5c3a6` |
| `routed-drc.rpt` | `5432682eef3f66fed23d763137203c535f049aab1c32fe9976914ffe18ca23b9` |

### 补记：同一检查点的离线审查已运行完毕

11 月 28 日 04:07，独立诊断正常退出，复核后原 DCP 的 SHA-256 未变。`report_methodology` 有 1,307 条 Warning、1 条 Advisory（包含 1,000 条 `TIMING-16`）。两条 `TIMING-47` 分别指向 CPU 时钟与 `mmcm_clkout0` 两个方向：Vivado 将它们判作同步时钟，但同版第 41 号约束把它们分在异步组。时钟交互报告列出的两个方向分别有 188 和 119 个总端点，均显示 `Ignored / Asynchronous Groups`。这不等同于跨域正确：需核对实际相位/复位关系、异步队列及指针约束的命中，再决定是否缩窄例外。未删除约束，也未自动豁免。

可追溯到本版 `shell.sdc` 第 7 行的三组声明：MIG UI、CPU PLL 输出、JTCK。`report_clocks` 显示 CPU（5.714 ns）和 MIG UI（5.000 ns）各由独立 MMCM 输出，但都列同一 4.000 ns 的 `sys_clock` 为 master。共同 master 是 Vivado 告警的具体背景，不代表独立复位之后两者一定有可依赖的固定相位。

逐位核对同一 CDC 报告中的 AXI `AW/W/B/AR/R` 五个通道，每个通道的读、写 Gray 指针各四位；40 个源位均对应另一域正确方向和相同位号的第一级同步器。两个方向各 20 位；全部为 `CDC-2 Warning`、深度 3、缺少工具认可的 `ASYNC_REG` 属性，受异步组例外覆盖。它们是 40 条 Warning，不是那 6 条 Critical 的重复计数；结构识别不能证明布局、偏斜、复位或 MTBF 合格。

本次 `report_bus_skew` 的 4 个报告项都属于调试集线器的读写 FIFO，最差余量 +19.496 ns；这不能替代对 MIG/CPU 桥 Gray 指针的审查。`report_exceptions -ignored` 另列 5 条无实际路径的例外。完成报告采集不代表签核通过。

前端慢路径的首个实体 RTL 候选及整组等价验证见[循环预测修复旁路](perf-mega175-loop-repair.md)。
