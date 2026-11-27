# MIG 输入复位：综合时匹配不到引脚，是否说明布线后没有这条路径？

**不能。** 四路 BOOM 的新旧两次整机综合均在生成的 `vcu118mig.xdc:295` 报 `Synth 8-3321`：按 `u_ddr4_infrastructure/sys_rst` 查找例外的经过点时结果为空。这不是 CPU 数据通路的 WNS，也不能据此删除或扩大约束。新旧两版所用 MIG XDC 和本实验涉及的三个生成 RTL 文件逐字节一致；物理结论仍须分版本。

### 旧版的物理证据

在原版综合后、优化后、布局后及布线后四份 DCP 的 `early.xdc` 中，均查到该例外、源文件编号、295 行及对应 MIG 实例作用域。这里只读取归档中的小型 XML/XDC 成员：**保存了约束文本不代表查找命中了引脚**。在已经与原版布线 DCP 绑定的详细时序报告里，另有如下实际路径，经所指复位网络到达第一级触发器的异步置位脚（`rst_input_async_reg[0]/PRE`）。

| 原版报告的起点 | Recovery 数据延时 | Removal 数据延时 |
|---|---:|---:|
| 板级 `reset` 输入 | 2.666 ns | 1.066 ns |
| 上电复位寄存器 | 0.544 ns | 0.244 ns |

四条报告路径均为 `Timing Exception: False Path`、`Slack: inf`，没有可用于验收的恢复/移除余量。上电复位还有单独的板级例外；仅凭这些路径不把例外唯一归因于第 295 行，也不把第一级的报告推广到第二级。原版另外两条 `CDC-7` 终点在 **CPU 域 ResetWrangler**，不是这里的 MIG 输入脚。[旧版检查点与路径指纹](perf-mega175-mig-sysrst-physical.json)。

### 新版生成 RTL 上的功能实验

沿封存的板级 RTL 核对复位引脚与上电复位经过 OR 合并、经 MIG 外壳和岛进入 IP 的实际接线。用 Vivado 2024.2 XSim 单独实例化**新版生成的完整时钟/复位基础模块**，沿用父模块的全部 11 个覆盖参数、真实 BUFG 和 MMCM 功能模型。夹具驱动这两个复位原因，时钟正常时参考周期为 4 ns，并固定测试输入 `pll_lock=1`。观察点是 **MMCM 前的输入复位链和展宽器**，不包括 DDR PHY、校准、存储器内容、UI 复位最终释放或完整板级 POR 的实际脉宽。

以下六例均检查了最后一次有效复位释放后 57 个参考时钟上升沿：停钟时完整落入停钟区间的 800 ps 脉冲、仅上电复位的 650 ps 短脉冲、两个原因交叠、跨单个上升沿、计数器装满后停钟期间释放、倒计数中再次触发。两级异步置位触发器在恢复计数的第 2 沿后均为 0；第 6 沿计数仍为 50，第 56 沿计数归零，第 57 沿 `input_rst_design` 清零。短脉冲在停钟时确实被前级保留；在这些场景里**钟没走就不会走完复位释放序列**。这是数字模型中的观测，不是器件最小可捕获脉宽。

- 屏蔽 POR 的负对照在仅 POR 工况报错；仅把第二级异步置位改成同步的负对照在第一个停钟脉冲工况报错，两个均命中指定断言。
- 停/启参考钟时 MMCM 功能模型报了一次输入抖动警告。这里没有据此宣称 MMCM 已重锁、PHY 已恢复或不存在亚稳态。
- 未改实现输入或约束。新版必须在自己的布线网表上检查受例外影响的**两级置位脚**、例外覆盖/重叠、同步链及时序；原版证据和本次功能仿真都不能代替这一步，也不产生 CoreMark 成绩。[仿真用例与指纹](perf-mega175-mig-sysrst.json)。

复现（检查点检查从生成该 DCP 的原始构建目录运行，以便核对内部记录的 XDC 路径）：

```sh
python scripts/review-mega-mig-sysrst.py "$DCP"
python scripts/review-mega-mig-sysrst.py "$ORIGINAL_ROUTED_DCP" --archived-timing "$ORIGINAL_TIMING_REPORT"
python scripts/test-mega-mig-sysrst.py "$KIT" "$OLD_MIG_IP" "$NEW_MIG_IP" "$VIVADO_INSTALL" "$FRESH_OUT"
```
