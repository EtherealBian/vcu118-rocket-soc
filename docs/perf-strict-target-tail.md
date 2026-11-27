# 第 23,993 至 24,000 轮：四路 BOOM 能否重放两个种子的最后八轮？

这里验证的是**固定 Linux ELF 的连续八轮用户态执行**，不是板上的 24,000 轮计时。先让 Linux 客体实际执行前 23,992 轮，再取寄存器和内存快照；原版四路 BOOM RTL 从该架构状态开始重放末八轮。没有导入前 23,992 轮留下的缓存、TLB 或预测器状态，外部存储为 TileLink 行为 RAM，不是 VCU118 的 DDR4。

| 种子 | 末八轮指令数 | 前四轮周期 | 后四轮周期 | 八轮总周期 | 客体 24,000 轮最终 CRC |
|---|---:|---:|---:|---:|---|
| 性能 | 2,695,170 | 652,858 | 635,191 | 1,288,049 | `0x4983` |
| 验证 | 2,698,341 | 657,394 | 639,059 | 1,296,453 | `0xeb93` |

逐轮指令数、周期及有序 PC 指纹见[去敏 JSON](perf-strict-target-tail.json)。模型周期从第 23,993 轮首条指令提交算到结束计时调用提交（不含该调用）。前四轮与后四轮均来自同一次连续回放。不能据此估计全程周期或把目标时钟乘成板分。

## 如何验证没有取错八轮？

- **先确认轮号。** 两个种子在 QEMU 系统客体中都实际跑完 24,000 轮、单上下文、2,000 字节，使用同一份严格对齐 ELF。入口为用户态 `0x10af0`，`x14 = 23992, x25 = 24000`；出口为 `0x10f3a`，两寄存器都为 24000。首轮试验只靠调试器命中次数定位，被验证种子的轮号断言拒绝，未纳入结果。正式采集按寄存器条件停下，并要求入口、出口同属 U 模式和同一 Sv39 地址空间。
- **再比每条指令。** 独立的 QEMU Linux-user 插件记录全程逐轮指令数，与[已封存的 24,000 项序列](perf-strict-target-window.md)比对摘要，再输出末八轮的全部 PC。RTL 从四个 ROB 提交槽重建的序列必须逐种子完全匹配，每轮还要恰有两次链表调用。
- **最后比数据。** 模型走 ROM、MRET 进入 U 模式，直到结束计时调用触发 ECALL。诊断代码核对 32 个整数寄存器槽（计入出口之后三条指令的已知影响）及 3,120 字节可写段、1,728 字节栈、2,000 字节堆，全部相符才由模拟 UART 输出 `K`。表内全程 CRC 由 QEMU 客体输出，**不是 BOOM RTL 输出的 CRC**。本次未改处理器 RTL；只重链接记录该窗口的测试台。不启用 `--target-tail` 时，两个种子的既有四轮重放 RAM 也与归档逐字节相同。

## 离线复核

所需工具与私有模型归档见[四轮重放说明](perf-strict-user-replay.md)和[全程指令计数说明](perf-strict-target-window.md)。`QEMU_PREFIX` 是系统模拟器前缀；`QEMU_USER` 是启用 TCG 插件的独立用户态模拟器。`GUEST`、`ORACLE`、`RUN` 为尚不存在的私有输出目录。以下命令从工程根目录运行，不访问板卡、不改目标 ELF。

```sh
ELF="$RELEASE/coremark-g15-gc-lto-ooo-strict.elf"
python3 scripts/capture-strict-user-guest.py "$RELEASE" "$FW_JUMP" "$QEMU_PREFIX" "$GUEST" --target-tail
python3 scripts/build-strict-user-replay.py "$GUEST" "$ELF" "$CROSS_PREFIX" --target-tail
python3 scripts/test-strict-target-tail.py oracle "$QEMU_USER" "$QEMU_HEADER_DIR" "$ELF" "$ORACLE"
python3 scripts/test-strict-target-tail.py run "$STOCK_KIT" "$STOCK_OBJ" "$VERILATOR_INCLUDE" "$GUEST" "$ORACLE" "$RUN"
python3 scripts/test-strict-target-tail.py review "$GUEST" "$ORACLE" "$RUN" > "$RUN/review.json"
diff -u docs/perf-strict-target-tail.json "$RUN/review.json"
```
