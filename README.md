# VCU118 Rocket Linux SoC

在 AMD VCU118（XCVU9P）上实现一颗能启动 Linux 的 64 位 RISC-V 软核。从上游 Chipyard 生成板级 RTL；本仓库提供启动 ROM、诊断固件、Linux 镜像构建、真实 Rocket RTL 测试和实板自动验收脚本。这里发布的是**源码和构建方法**，不分发 bitstream。已做独立串口诊断的实板测试，完整 SoC 仍在验收中。

| 配置 | 基线 |
|---|---|
| 处理器 | 单核五级顺序 Rocket，RV64GC、Sv39；L1 I/D 各 32 KiB，L2 512 KiB |
| 时钟 | CPU/总线设计目标 **100 MHz**；CLINT 时基 100 kHz。目标频率不是实测 Fmax |
| 存储与外设 | 2 GiB DDR4 地址窗（`0x80000000`）；SPI SDHC、SiFive UART、CLINT 和 PLIC |
| 软件 | OpenSBI 1.5.1 → Linux 6.6.65 → BusyBox 1.36.1 内置 initramfs |
| 工具 | Chipyard 1.13.0 固定提交、Verilator、Vivado 2024.2；Windows + WSL 构建 |

## 验证进度 · 2026-11-26

- **真实 Rocket RTL**：候选 ROM 通过 SPI 读取主 GPT 并装入裸机自检程序；UART 报告两轮 1 MiB 内存读写和定时器前进。GPT 头、分区表、分区越界、载荷扇区 CRC 四种异常都停在 ROM。外部 RAM 和卡为模型，不验证 DDR PHY。
- **不用 SD 的启动路径**：另一版 600 B 恢复 ROM 已在真实 Rocket RTL 中，通过 UART 引脚接收并执行 422 B 裸机诊断；魔数、长度、CRC 错误分别被拒绝。板上的串口下载及 Linux 启动仍待验收。
- **QEMU virt**：同一基线固件通过 10 次独立启动，每次执行 16 MiB 用户态自检并返回交互 shell 挑战。这个机器模型与 VCU118 的板级互连不同。
- **Rocket 上的 Linux 进度（RTL）**：模拟 JTAG 预载基线固件后，第 40,000,000 周期读到 hart 已在 S 态执行 Linux 的 `memmap_init_range`，Sv39 已开启。另一个限制为 128 MiB 的诊断配置还通过 RTL 串口输出了 Linux 6.6.65、机器型号和早期控制台地址。两者都不是实板 shell 记录。
- **调试总线与时序**：已在生成的 RTL 上对调试从设备缓冲做 4,112 拍双向反压测试；整机综合网表仍发现一路跨时钟域的组合停核信号。未门控调试时钟的整机对照版首次在 100 MHz 约束下完成布线，建立/保持/脉宽裕量分别为 **+0.349 / +0.011 / +0.143 ns**，已生成 bitstream。该版仍有 7 条 Critical CDC 记录，未获准上板。
- **实板**：已通过 JTAG 易失下载独立诊断设计。FPGA 侧串口以 115200 8N1 完成 **260/260 组随机请求与回包**，1,040 个返回字节全部匹配；三片 SLR 均 DONE=1、无配置 CRC 错误。这一设计不含 CPU 或 DDR。**尚无板上 Linux shell 验收；完整 SoC 的布线时序结果不等于实板测试。**
- **可选实验**：四路有符号 INT8 点积已接入可选配置的 TileLink 总线。Rocket 裸机通过 MMIO 核对 257 组结果，另验空取、重复提交两种错误。Linux 驱动已编入可选内核，尚未通过 Rocket 上的 ioctl 验收；没有实板加速比。

[验证摘要与边界](docs/validation.md) · [重建与连接指南](docs/bring-up.md) · [设计需求与扩展顺序](VCU118-SOC-v0.1.md)

### 从哪里开始？

```bash
# 在仓库根目录运行；只需 Python，不接板、不写实体盘
python3 -m unittest discover -s tests -p 'test_*.py'
# 固定上游提交并创建本地工作目录；完整工具链和 Vivado 流程见指南
bash scripts/checkout.sh
```

| 路径 | 用途 |
|---|---|
| `rtl/boardprobe/` | 可独立重建的 VCU118 配置与双向串口实板诊断，不需要 SD 卡 |
| `software/boot-gpt/`、`software/bare/` | 面向 SDHC 的启动 ROM、DDR 和 mtime 裸机诊断 |
| `scripts/` | 锁定并构建依赖、生成 RTL/镜像、检查布线报告、按器件身份自动验收 |
| `tests/` | Rocket ChipTop UART/SPI/TL/JTAG 测试台、GPT 布局和错误注入测试 |
| `rtl/accel/`、`software/dot4/` | 可选点积单元及配套驱动和程序 |

**发布范围与许可。** 未另行标注的项目原创文件使用 [MIT](LICENSE)；Linux 驱动使用 [GPL-2.0-only](LICENSES/GPL-2.0-only.txt)。上游 Rocket、Chipyard、Linux 等各用原许可。仓库不分发 AMD IP 生成物、Vivado 工具、预构建镜像、机器标识或原始设备日志；指南中的 `artifacts/`、`cache/`、`logs/` 为本地生成路径。详见 [第三方说明](THIRD-PARTY.md)。
