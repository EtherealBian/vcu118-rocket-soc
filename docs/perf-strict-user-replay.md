# 四路 BOOM 确认的是多少拍，而不是多少分

对同一份待上板 ELF，**性能种子四轮的用户态热区共 653,447 个 RTL 周期，平均 163,361.75 拍/轮，平均提交 2.062 条指令/拍**。[此前只知道这段 Linux 代码要执行多少条指令](perf-strict-user-window.md)；现在从四路 BOOM 的 RTL 提交端测到了这些指令花的周期。它不是 VCU118 实测，不是 BOOM 上完整 Linux 的计时，也不替代 [18:00 的未达标报告](status-2026-11-27-1800.md)。

| 标准 2,000 字节，1 个上下文，4 轮 | 性能种子 | 验证种子 |
|---|---:|---:|
| 与 QEMU 顺序匹配的用户指令 | 1,347,261 | 1,348,735 |
| 四轮 RTL 周期（首条提交至结束计时调用提交，不含该调用） | 653,447 | 657,536 |
| 第 1 / 2 / 3 / 4 轮周期 | 171,404 / 161,746 / 160,691 / 159,606 | 173,150 / 162,949 / 161,180 / 160,257 |
| QEMU Linux 完整运行的四轮最终 CRC | `0x9f95` | `0x19d9` |

**对设计的意义。** 目标 1,000 次/秒时，150 MHz 每轮只有 150,000 拍；在这个四轮样本里，四轮各自都超出这个预算。175 MHz 每轮有 175,000 拍，平均仅比本模型热区多 11,638 拍，且该频率尚未签核。模型不含 Linux 调度、中断、真实 MIG/DDR 延迟，也不代表 24,000 轮的稳态；不把两数相除当跑分。下一项优先证据是本次布局布线能否收敛；仅凭这个窗口没有理由把四路改称九级，或直接复制更多核。

## 两个不同来源怎样对上

1. 在 **QEMU 模拟的单 hart Linux** 中运行发行镜像里 SHA-256 已锁定的 ELF，每种种子各跑四轮。通过模拟客体的 GDB 在起止 PC 抓 32 个通用寄存器、可写段、栈、2,000 字节堆；比较代码与原始 ELF。此处 QEMU 用同次构建的 `fw_jump.bin`、同一 Linux `Image`，而非板子封装的 `fw_payload.bin`；`no4lvl` 固定 Sv39，仅在模拟客体内关闭 ASLR。退出后核验两种 CRC。
2. 使用[已核对的四路 BOOM RTL 归档](perf-mega175-linux-entry.json)。在外部 TileLink 行为 RAM 预载 ELF、用户数据、六页新 Sv39 页表和诊断入口。模型中的原版 ROM 经 UART 引脚收 24 字节帧，写入最前八字节；入口配置 PMP、恢复通用寄存器，经 MRET 进入 U 模式。这里是从快照重放，BOOM 未从 Linux 冷启动进入应用。
3. 在同一时钟上升沿之前按顺序读取四个 ROB 提交槽。用 FTQ 对应块 PC、ROB 低六位及跨界半指令标记重建逐条 PC。从首个 `0x106b0` 至首个 `0x10f3a` 之前为完整热区，校对每轮两次链表调用。**两个种子的完整有序 PC 流**均匹配此前独立建立的 QEMU Linux-user SHA-256，而非只比总数。详见[分轮周期与有序摘要](perf-strict-user-replay.json)。
4. 原始代码随后进入 libc 的时钟调用并触发用户 ECALL。M 态处理器核对异常及全部 32 个寄存器槽（对随后三条指令改变的 `ra/a3/a7` 作已知修正）、3,120 字节可写段、1,728 字节栈、2,000 字节堆，逐字节相符才经 RTL UART 发 `K`。BOOM 没有打印最终 CRC；这与 QEMU 打印的 CRC 是不同证据。

**四条额外的 `arch_valid` 从哪里来？** 若只按 CSR 权限切换数，从 MRET 至 U→M 异常的性能区间有 653,686 拍，读到 1,347,265 个 `arch_valid` 槽，比目标热区多四个。逐 PC 核对发现，前一个是权限已变成 U 后才出现在该接口的 MRET (`0x800000ec`)；后三个是结束计时 JAL 和 libc 的两条指令 (`0x10f3a / 0x147ac / 0x147b0`)。ECALL 在 `0x147b4` 触发 cause 8，没有当成第四条提交。因而没有用 `用户权限周期 × 提交宽度` 来猜 IPC。

## 离线复核

从工程根目录运行以下命令；需要已有的 Ubuntu QEMU 4.2.1 工具前缀、`gdb-multiarch`、RISC-V 交叉工具和已封存的 stock Verilator 对象。`PRIVATE` 为已有的私有父目录，输出子目录必须尚不存在。抓取器只在本机回环接口开启模拟客体的 GDB 端口；不访问板卡。快照、二进制、串口原始日志及全 PC 流不公开。

```sh
python3 scripts/capture-strict-user-guest.py "$RELEASE" "$FW_JUMP" "$QEMU_PREFIX" "$PRIVATE/guest"
python3 scripts/build-strict-user-replay.py "$PRIVATE/guest" "$RELEASE/coremark-g15-gc-lto-ooo-strict.elf" "$CROSS_PREFIX"
bash scripts/test-strict-user-replay.sh "$STOCK_KIT" "$STOCK_OBJ" "$PRIVATE/guest" "$PRIVATE/stock"
python3 scripts/test-strict-replay-oracle.py "$PRIVATE/stock" "$PRIVATE/guest" "${CROSS_PREFIX}nm" "$PRIVATE/fault"
```

最后一步是负对照：仅翻转异常处理器用来比较的预期堆区中的一位，不动用户初始内存或 ELF。它要求完整性能 PC 序列仍匹配，但 RTL UART 须改报 `!`，模型以非零退出；否则负对照本身失败。

本次负对照实跑：性能热区 PC 摘要仍完全相同，RTL UART 最后的结果从 `K` 变为 `!`，模型按预期以状态 1 拒绝。只核对指令条数、甚至只核对完整 PC 顺序，都抓不到这次数据故障。

[后续：原版与 LVT 寄存器堆在相同两段热区的逐轮对照](perf-strict-user-lvt.md)。

[外部读响应刻意推迟 32 拍：首轮和后三轮的周期分别变了多少？](perf-strict-tl-wait.md)

[计时前置检查：四路 BOOM 的 mtime、机器定时器中断和严格 ELF 的起止调用](perf-mega175-timebase.md)。

[逐条追踪后端重定向：哪条链表比较分支最常重新取指，正确路径几拍后派发？](perf-strict-redirects.md)
