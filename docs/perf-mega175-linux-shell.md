# 四路 BOOM：从复位走到同一份 Linux 用户程序

**这项实验问的是：原版四路 BOOM 能否靠自己的 Linux 启动路径运行目标 ELF？** [早先的模型](perf-mega175-linux-entry.md)在内核入口后的第 258 次 S 模式提交主动退出；[用户指令重放](perf-strict-user-replay.md)从预制用户态快照起跑。这里从复位开始，不灌入用户态寄存器、页表、堆或栈。它是功能诊断，不测 FPGA 上的每秒迭代数。

| 证据 | 这次能据此判断什么 |
| --- | --- |
| QEMU `virt`，同一份发行固件，真实 BusyBox shell 依次执行三条交互命令 | 性能、验证种子各 4 轮，最终 CRC 分别是 `0x9f95`、`0x19d9`；实际 ELF 的 SHA-256 与发行版一致。同一串口记录未通过 BOOM 身份检查，符合负控预期。短跑只取 CRC。 |
| 原版单 hart 四路 BOOM 整核 RTL，外部行为 TL RAM | 从复位经 OpenSBI 进入 Linux 6.6.65，内核报告的 175 kHz 计时基准与 ROM 一致。已从模型 UART 引脚收到用户态 `/init` 发出的就绪行；该截点尚未到达交互提示符或运行 CoreMark。 |
| VCU118 | 本实验没有连接板卡、配置 FPGA 或访问物理串口；不更改正式成绩登记。175 MHz 是物理实现请求，不是本实验验证的频率。 |

**内核已输出什么？** 这次整核模型没有注入 shell 命令，就已在 UART 上收到完整的 `Linux version 6.6.65 …`。入核时的前 2,352 个串口字节及对应事件仍与[上次证据](perf-mega175-linux-entry.json)的摘要相同。从文件开头保留到版本行的 CRLF 为止，共 **2,540 字节**，SHA-256 为 `6705dacd8703da7d371442012991321fed2012dacb5fd3d4c13cd1d256edd230`。可用 `head -c 2540 linux.uart | sha256sum` 复核同一次运行。

独立对照的是本次固件在偏移 `0x200000` 处包含的完整发行版 `Image`。只剥去串口行首的内核时间戳并把 CRLF 还原为 LF，所得 **163 字节**与镜像内的完整版本字符串相同，SHA-256 为 `8b54aa6bf03f7e4eb012fae5cf3f62f90cf184992c25a86b757173753fe219be`。这比看到内核入口多验证了控制台输出，不证明已进入用户态；行首的 `0.000000` 也不是启动耗时。

**Linux 读到的计时基准。** 在同一次从复位开始的四路 RTL 冷启动中，OpenSBI 报告单 hart、`aclint-mtimer @ 175000Hz`；进入 Linux 后，内核注册 `riscv_clocksource` 并报告 64 位 `sched_clock` 为 **175 kHz**、分辨率 **5,714 ns**。两处使用同一份设备树，不能当作两次独立测频。这个读数与[实现 ROM 的时间基准](perf-mega175-linux-identity.json)一致，也和[独立 RTL 诊断的每 1,000 个输入时钟一个 `mtime` 增量](perf-mega175-timebase.md)相符。这里核对的是从固件到内核的单位和配置；**175 kHz 是定时器频率，不是 CPU 主频**，也不证明板上时钟准确。

这次检查复核了原入核事件及串口前缀、运行中模型的可执行文件和固件身份。从第一个 UART 字节截至完整 `sched_clock` 行的 CRLF，共 **4,801 字节**；可用 `head -c 4801 linux.uart | sha256sum` 复核本次原始前缀，预期 `bef03033a565351b9c6ff670dcc506b0c3c84de32f846211f9e0dcd13bb2c0df`。这个截点没有进入用户态，也没有运行严格 ELF 中的两次计时调用。实板仍须用主机墙钟核对全部六次运行。

**用户态第一次给出了什么证据？** 北京时间 2026-11-28 02:43，从同一运行的 UART 引脚先收到内核行 `Run /init as init process`，再收到完整的 `VCU118_INITRAMFS_READY`。第一行只说明内核尝试执行 `/init`；第二行才是用户脚本的输出。在与固件逐字节对过的发行版 `Image` 中，解开内置 initramfs，这个标记只出现一次：528 字节的 `/init` 用 `#!/bin/sh` 启动，依次挂载 devtmpfs、proc、sysfs，每次失败即退出，之后才执行 `echo`。归档内的 `/bin/sh` 指向 `/bin/busybox`。到此模型尚未发送任何 shell 命令；该结果不证明 16 MiB 自检、交互 shell 或 CoreMark 通过。

| 本次 UART 原始前缀（从第一个字节起、含行尾 CRLF） | 字节数 | SHA-256 |
| --- | ---: | --- |
| 至内核宣告执行 `/init` | 6,381 | `1677c320c88144c1fda4a9d8a0ae1750e30b6fb572deb00797a9751669f74e68` |
| 至 `/init` 的就绪行 | 6,405 | `3d69df6a046fc517ce8566d9c94ff253717ab505950c8d2d8631336ecfcb08ab` |

可用 `head -c 6405 linux.uart | sha256sum` 复核第二个截点。另用 `dd if=Image iflag=skip_bytes,count_bytes bs=1M skip=1780552 count=415629 status=none | gzip -dc | cpio --quiet -i --to-stdout init | sha256sum` 从[该版镜像](perf-mega175-linux-entry.json)只读核对脚本；预期 `960e8017d045c84afb0b514b269055feb485dacc632c7d0e0415d90eb1bf0432`。将 `init` 换为 `bin/busybox` 可核对解释器，预期 `04fd02c757ed114677bcc167a5d07917f4a5ebf21aa76d2359195390f04d4297`。

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
