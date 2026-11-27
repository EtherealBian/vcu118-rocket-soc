# 四路 BOOM 的系统计时器：一个 tick 是多少拍？

**封存的单 hart 四路 BOOM 整核 RTL 中，连续 1,120 个 `mtime` 增量间隔均为 1,000 个输入时钟周期。** 由核内软件独立用 `rdcycle` 夹住相隔 256 个 `mtime` 增量的两个边沿，实际界限是 **255,879–256,097 拍**。它包含分频 1,000 对应的 256,000 拍，并排除相邻分频 999 和 1,001。这是 Linux 上板计时的一项前置检查，**不是 CoreMark 性能提升，也没有测量物理 MHz**。[结构化记录](perf-mega175-timebase.json)

### 从时钟到软件读数

1. 在原版 `ChipTop` 的每个模型上升沿旁观分频器和 CLINT 的 `mtime`；有 tick 时应加一，没有时应保持。从第 1,102 拍到第 1,121,102 拍，逐个检查间距，不只比较首末平均。
2. M 模式诊断经 ROM UART 引脚交接：24 字节帧中含入口前 8 字节，其余 396 字节预放在外部行为 RAM。不改核内寄存器。软件用 `rdcycle`、I/O 栅栏、对 `0x0200bff8` 的 64 位 MMIO 读、I/O 栅栏、`rdcycle` 界定一次采样。对每个指定 tick，用最后一次读到旧值之前的拍号、第一次读到目标值之后的拍号给出区间；两个边沿的区间相减得到上述上下界。两项界限均由软件经 UART 发回。
3. 软件再将 hart 0 的 `mtimecmp` 设为 969。第 969,102 拍计数抵达门限；第 969,111 拍 CSR 记录机器定时器中断（`mcause=0x8000000000000007`）。处理器确认 `mip.MTIP` 置位，把比较门限改为全 1，再读到 MTIP 清零。第 969,285 拍 `mret` 返回；主程序核实只处理一次后发出成功回执。这 9 拍是本次忙等诊断从门限到 `mcause` 更新的观测值，不是 Linux 中断时延保证。

两次独立启动得到逐拍一致的三组记录。第二次还核对了中断入口清除、返回恢复 `mstatus.MIE` 和原始 UART 回执。离线负对照分别把声明的分频改成 999、1,001，或翻转回执界限字段的一位；三种都被复核器拒绝，未修改 DUT。

### 与目标 ELF 有什么关系？

[实现 ROM 内的设备树](perf-mega175-linux-identity.json)声明外设总线 175,000,000 Hz，`/cpus/timebase-frequency` 为 175,000 Hz。二者之比与模型一致；只有实际时钟也正确，tick 才具有声明的物理时长。锁定的严格对齐 Linux ELF 在起止点 `0x106ac`、`0x10f3a` 调同一个 `__clock_gettime`，传入时钟 ID 0（`CLOCK_REALTIME`），在 `0x147b4` 以系统调用号 113 执行 `ecall`。因此不能用模拟器运行速度、裸机 `mcycle` 或这个 IRQ 窗口代替两次 Linux 系统调用之间的时间。

本实验没有运行 Linux 时钟服务，不验证 OpenSBI 的时间读取路径、墙钟校准、调度或 DDR4。实测仍须等同次布线和约束签核、板卡重新接入，在 Linux 上完成固定 ELF 的三对性能与验证种子，再把每次运行时间与主机独立计时核对。

### 复核

需要已封存的原版模型套件与对象、Linux 严格 ELF、生成该 ROM 时使用的设备树工具。脚本重新检查模型来源、重建 ROM/DTB 对照、诊断、UART 回执和软件调用点；不会启动另一次完整 Verilation 或访问板卡。传入未使用过的输出目录。

```bash
bash scripts/test-mega-timebase.sh "$STOCK_KIT" "$STOCK_OBJ" "$PRIVATE/timebase" "$STRICT_ELF"
cmp "$PRIVATE/timebase/result.json" docs/perf-mega175-timebase.json
```
