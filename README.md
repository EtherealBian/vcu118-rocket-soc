# RISC-V Linux SoC

在 AMD VCU118 上部署 100 MHz 五级 Rocket，通过串口将固件送入 DDR4，启动 Linux 6.6.65 并进入 BusyBox shell。工程基于 Chipyard 生成 SoC，包含板级配置、启动 ROM、自解压固件和实板验收脚本。

[项目图解](https://etherealbian.github.io/work/vcu118-rocket.html) · [构建与上板](docs/bring-up.md) · [English](#english)

[![VCU118 上五级 Rocket 的启动地址、串口自解压路径，以及 Rocket 实板与 BOOM RTL 的性能对照](https://raw.githubusercontent.com/EtherealBian/etherealbian.github.io/910765ec1837954a5edca253dc3f2b28fa3f061e/assets/plates/atlas-09-rocket.svg)](https://etherealbian.github.io/work/vcu118-rocket.html)

## 代表性结果

| 项目 | 结果 | 测量口径 |
|---|---|---|
| 串口引导 · VCU118 实板 | **495.050 s → 194.469 s** | 同一块板、同一比特流、相同内层固件。从 J4 开始发送到 BusyBox 正确应答，两种载荷各测一次；不含 JTAG 配置。[启动记录](docs/validation.md) |
| 单核 CoreMark · Rocket 实板 | **254.2 次/秒** | 100 MHz，Linux 用户态，单 hart、单上下文。GCC 15.1 启用 `-O3 -flto` 和 Zba/Zbb；性能种子运行三次，取中位数。独立测量，非认证成绩。[逐次读数](docs/coremark-1000-compilers-board.json) |
| 三路与四路 BOOM · RTL 仿真 | **四路少用 8.5% 周期** | 同一份 `-O2` 裸机程序，性能种子每轮周期中位数从 177,191.75 降到 162,125.50。三路、四路均为单核配置；此处不折算为实板吞吐。[周期对照](docs/perf-mega-o2.json) |

## 从 Boot ROM 到 BusyBox

单核 Rocket 采用 RV64GC、Sv39 和五级顺序流水。一级指令、数据缓存各 32 KiB，二级缓存 512 KiB。DDR4 的 2 GiB 地址窗从 `0x80000000` 开始。

1. **接收固件。** J106 通过 JTAG 配置 FPGA，J4 以 115200 baud、8N1 发送载荷。片上 [UART Boot ROM](software/boot-uart/) 校验帧头、长度与 CRC32，通过后跳转到 DDR4 中的入口地址。
2. **缩短串口传输。** 主机用 LZ4 压缩固件，将串口发送量从 5,341,704 字节减至 2,018,528 字节。板上的[自解压程序](software/boot-pack/)先将自身搬到 `0x84000000`，把原始固件还原至 `0x80000000`，复核 CRC32 后跳入 OpenSBI。
3. **进入用户态。** OpenSBI 将控制权交给 Linux；内核从内置 initramfs 启动 BusyBox 1.36.1。主机向 `ash` 发送随机算术命令，以正确返回的计算结果作为引导计时终点。

## 复现入口

不接开发板也可以先检查串口帧和启动载荷。克隆仓库后，在根目录运行：

```bash
python3 -m unittest discover -s tests -p 'test_uart_frame.py'
python3 -m unittest discover -s tests -p 'test_boot_transport.py'
```

重建完整系统请按[上板指南](docs/bring-up.md)准备 Chipyard 1.13.0、Verilator 与 Vivado 2024.2。仓库发布源码、构建脚本与测量摘要，不分发预构建 bitstream、Linux 镜像或 AMD IP 生成物。未另行标注的原创文件采用 [MIT](LICENSE)，Linux 驱动采用 [GPL-2.0-only](LICENSES/GPL-2.0-only.txt)；上游组件保留各自许可，见[第三方说明](THIRD-PARTY.md)。

## English

This project boots Linux 6.6.65 on a 100 MHz, five-stage RV64GC Rocket implemented on an AMD VCU118. The on-chip ROM receives firmware over UART. An LZ4 self-extractor restores the original payload in DDR4 before handing control to OpenSBI, Linux and BusyBox.

On the board, the time from the first transmitted byte to a verified shell reply fell from **495.050 s to 194.469 s**. Single-core Rocket reached **254.2 CoreMark iterations/s** in Linux userspace (median of three performance-seed runs). In a separate **RTL simulation**, a four-wide BOOM used **8.5% fewer cycles per iteration** than a three-wide BOOM on the same bare-metal binary.
