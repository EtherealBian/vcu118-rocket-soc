# 四路 BOOM：从复位走到同一份 Linux 用户程序

**这项实验问的是：原版四路 BOOM 能否靠自己的 Linux 启动路径运行目标 ELF？** [早先的模型](perf-mega175-linux-entry.md)在内核入口后的第 258 次 S 模式提交主动退出；[用户指令重放](perf-strict-user-replay.md)从预制用户态快照起跑。这里从复位开始，不灌入用户态寄存器、页表、堆或栈。它是功能诊断，不测 FPGA 上的每秒迭代数。

| 证据 | 这次能据此判断什么 |
| --- | --- |
| QEMU `virt`，同一份发行固件，真实 BusyBox shell 依次执行三条交互命令 | 性能、验证种子各 4 轮，最终 CRC 分别是 `0x9f95`、`0x19d9`；实际 ELF 的 SHA-256 与发行版一致。同一串口记录未通过 BOOM 身份检查，符合负控预期。短跑只取 CRC。 |
| 原版单 hart 四路 BOOM 整核 RTL，外部行为 TL RAM | 已从干净源快照链接并启动。检查从 ROM 到内核入口的原始字节和事件前缀，再经 `/init`、内存与操作系统自检、BusyBox、CPU/设备树、ELF 哈希，最后检查两个种子的返回值和 CRC。此处不预填尚未取得的用户态结果。 |
| VCU118 | 本实验没有连接板卡、配置 FPGA 或访问物理串口；不更改正式成绩登记。175 MHz 是物理实现请求，不是本实验验证的频率。 |

**输入和边界。** 使用[上次入核测试的归档和固件](perf-mega175-linux-entry.json)。除头 8 字节外，将**未压缩**固件预置外部内存；CPU 从复位向量启动，ROM 通过模型 UART 引脚接收补齐入口的 24 字节帧。预置绕过了整份载荷上传、解压与物理 DDR。入核前禁止选中 SD；入核后的内核可按设备树中的 `mmc-spi-slot` 探测空槽，仅记录首次片选，MISO 始终拉高，不提供扇区。沿用上次的 1,519 模型拍/位设置；shell 命令用 8N1，字符间另留 14 位空闲。每一步都等来宾打印求值后的标记，前两步还要等下一个提示符，输入回显不能代替回复。

**如何判定。** 入核前的事件文件和串口前缀须与上次锁定的 SHA-256 完全一致。随后从运行中的 Linux 核对：仅 CPU 0 在线、hart 0、`ucb-bar,boom0`、CPU 兼容串和两个时钟属性的字节哈希，以及 `/bin/coremark-g15-gc-lto-ooo-strict` 的身份。两次诊断均传入 `7 1 2000`，逐项比对编译器、种子、各子项 CRC 和四轮最终 CRC。标准的“少于 10 秒”提示仅在短跑 CRC 校验器中放行；没有给正式计分器添加例外。2,400,000,000 个模型周期是**停止上限**；超时、进程退出异常、提前截断或仅到达 shell 均不通过。

## 复现

在 Linux/WSL 下准备上次入核测试对应的封存 kit、已编译对象、发行目录与匹配的 Verilator include。这里只重新链接观测程序；不重新生成处理器，不启动 Vivado。

```sh
nice -n 15 python3 scripts/test-mega-linux-shell.py "$KIT" "$OBJ" "$RELEASE" "$FRESH_DIR" "$VERILATOR_INCLUDE"
# 单独运行 QEMU 控制，与上面的长时模型使用不同的新目录：
python3 scripts/test-mega-shell-qemu.py "$RELEASE/fw_payload.bin" "$QEMU_ROOT" "$FRESH_QEMU_DIR"
```

运行目录保留模型输入哈希、命令、原始串口和事件，只在模型正常退出、输入不变且复核通过后写 `review.json`。`ENTRY_WITNESS` 是内核入口证据，不是用户态完成标志。QEMU 控制本次原始输出 SHA-256 为 `c968fb0e0dace8fefb7473b3427d3fedee0cca534fafc8b4371619f9023e44b5`；每次新挑战与启动日志会改变串口摘要。单元测试另从生成的 TX 引脚电平解码三条完整命令，并故意破坏入核前缀、回复时刻、CPU 身份、工作负载和 CRC 检查拒绝路径。
