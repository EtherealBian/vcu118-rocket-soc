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

UART 和模型事件原件保留在私有目录。`rom` 只检查第一回完整记录和第二回的固定 ROM 前缀；后续启动、内核身份和短跑 CRC 在完整 `review` 之前均不记为通过。两者均不能证明 175 MHz 时序、六次实板验收或 1,000 次/秒。
