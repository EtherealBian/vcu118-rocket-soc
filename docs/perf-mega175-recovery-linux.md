# 正在实现的四路 BOOM：从冷复位验证同一份 Linux

[用户态快照对照](perf-mega175-recovery-fullcore.json)从预存的寄存器、页表和内存起跑，不能证明修改后的核还能启动 Linux。这里用相同封存处理器重新从复位起跑，将正在综合的板级输入清单逐项与模型 kit 比对。选顶是 `ChipTop`，不含板壳、物理 DDR4/MIG 或板上时钟电路。[原版从复位到交互命令的证据](perf-mega175-linux-shell.md)另列，不计入恢复版。

**先做两次独立复位，只改入口帧。** 外部行为 TileLink RAM 预置未压缩固件，保留其前 8 字节不写；必须由 ROM 通过 UART 引脚收齐 24 字节帧。第一回把帧的 CRC 字段翻转一个比特，数据保留不变，预期 ROM 拒绝，并安静至少 20 个位周期。第二回重新实例化同一可执行模型并冷复位，发送正确帧，预期 ROM 交接启动。后一回不在 ROM 处停止，可继续经 OpenSBI、Linux 到 BusyBox，由来宾核验严格 ELF，对两种种子各运行 4 轮取 CRC。

**本次实际观测。** 错帧回传 `UART5_STOP CRC`，到第 **883,890** 个模型拍满足安静窗口并正常退出。新进程中的正确帧在第 **838,329** 拍回传 `UART5_HANDOFF`，与原版相同。检查的是错帧两份完整记录、正确帧的 31 字节串口前缀及 94 字节事件前缀，[摘要可复核](perf-mega175-recovery-rom.json)。额外把原版物理清单交给此驱动，预检拒绝与恢复版对象混搭。截至这个截点，恢复版还没有 Linux 入核或用户态 CRC 结果。模型拍数不换算成板上时间。

**可比性。** 模型从[已验证的恢复版对象](perf-mega175-recovery-fullcore.json)串行重链接，没有再次翻译 RTL。驱动检查物理和模型 kit 的完整清单、549 项有序 HDL 的翻译记录、选顶、对象库、根头文件、运行时对象、固件、Linux 镜像、ELF 和两个帧的摘要。观测程序 C++ 源和控制引脚的头文件，与原版的字节摘要相同。对照不放宽：如果早期入核事件和原版不能逐字匹配，保留差异，不颁发整段通过结果。

复现（WSL/Linux，不连接 FPGA；`PREVIOUS` 为上次恢复版快照实验的输出，`OUT` 必须是 `KIT` 在私有目录中新建的同级目录）：

```sh
nice -n 19 python3 -B scripts/test-mega-recovery-linux.py run "$PHYSICAL" "$KIT" "$PREVIOUS" "$RELEASE" "$VERILATOR" "$OUT"
# 第二回运行期间即可独立核验 ROM；只有完整正常退出后才可 review：
python3 -B scripts/test-mega-recovery-linux.py rom "$PHYSICAL" "$KIT" "$PREVIOUS" "$RELEASE" "$VERILATOR" "$OUT"
python3 -B scripts/test-mega-recovery-linux.py review "$PHYSICAL" "$KIT" "$PREVIOUS" "$RELEASE" "$VERILATOR" "$OUT"
```

UART 和模型事件原件保留在私有目录。`rom` 只检查第一回完整记录和第二回的固定 ROM 前缀；入核需要下面的独立检查；Linux 用户态与短跑 CRC 则要等完整 `review`。这些检查均不能证明 175 MHz 时序、六次实板验收或 1,000 次/秒。

## 恢复版实际进入了 Linux 内核吗？

进入了内核入口，还未凭这个窗口证明用户态运行。正确帧从冷复位开始：第 **30,779,723** 拍出现对内核入口的 64 字节总线读；直到第 **40,822,114** 拍才观测到 OpenSBI 执行 `mret`，从 M 模式切到 S 模式，`mepc=0x80200000`。第 **40,822,448** 拍，累计观测到 **258 条 S 模式架构提交**。这三个事件不能互相替代，预取尤其不能当作已开始执行内核。

对照的是恢复版正在运行的 `ChipTop` 模型，而非另一个已经启动的原版模型。按观察器标记截取 2,352 字节 UART 和标记前 641 字节事件；两段内容、独立错帧的两个完整记录，以及从这些记录重新解析的计数，均与原版入核实验相同。[结果和输入指纹](perf-mega175-recovery-entry.json)中没有私有串口原文。本次 RTL 复核还检查了活动进程的可执行文件、启动参数、工作目录、两个输出文件描述符和物理输入封印；不使用进程号的离线复算得到了相同的 JSON。删除 `mret`、更改提交数、截短 UART 或截断边界标记均被拒绝。只读截取没有停止或重启模型。

```sh
python3 -B scripts/review-mega-recovery-entry.py "$PHYSICAL" "$KIT" "$PREVIOUS" "$RELEASE" "$VERILATOR" "$OUT" > entry.json
diff -u docs/perf-mega175-recovery-entry.json entry.json
# 在模型仍运行时，额外传 --pid <模型进程号> 可核对实际进程与输出文件。
```
