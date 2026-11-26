# VCU118 Rocket Linux SoC

在 AMD VCU118（XCVU9P）上实现一颗能启动 Linux 的 64 位 RISC-V 软核。从上游 Chipyard 生成板级 RTL；本仓库提供启动 ROM、诊断固件、Linux 镜像构建、真实 Rocket RTL 测试和实板自动验收脚本。这里发布的是**源码和构建方法**，不分发 bitstream。**五级 Rocket 已在真实 VCU118 上启动 Linux 6.6.65 并进入 BusyBox shell。** 不用 SD：通过 JTAG 易失配置 FPGA，然后通过 J4 串口上传固件。

| 配置 | 基线 |
|---|---|
| 处理器 | 单核五级顺序 Rocket，RV64GC、Sv39；L1 I/D 各 32 KiB，L2 512 KiB |
| 时钟 | CPU/总线设计目标 **100 MHz**；CLINT 时基 100 kHz。目标频率不是实测 Fmax |
| 存储与外设 | 2 GiB DDR4 地址窗（`0x80000000`）；SPI SDHC、SiFive UART、CLINT 和 PLIC |
| 软件 | OpenSBI 1.5.1 → Linux 6.6.65 → BusyBox 1.36.1 内置 initramfs |
| 工具 | Chipyard 1.13.0 固定提交、Verilator、Vivado 2024.2；Windows + WSL 构建 |

## 验证进度 · 2026-11-26

- **真实 Rocket RTL**：候选 ROM 通过 SPI 读取主 GPT 并装入裸机自检程序；UART 报告两轮 1 MiB 内存读写和定时器前进。GPT 头、分区表、分区越界、载荷扇区 CRC 四种异常都停在 ROM。外部 RAM 和卡为模型，不验证 DDR PHY。
- **不用 SD 的启动路径**：另一版 600 B 恢复 ROM 已在真实 Rocket RTL 中，通过 UART 引脚接收并执行 422 B 裸机诊断；魔数、长度、CRC 错误分别被拒绝。调试缓冲版已在实板通过同一恢复路径装入并执行裸机程序。
- **QEMU virt**：同一基线固件通过 10 次独立启动，每次执行 16 MiB 用户态自检并返回交互 shell 挑战。这个机器模型与 VCU118 的板级互连不同。
- **Rocket 上的 Linux 进度（RTL）**：模拟 JTAG 预载基线固件后，第 40,000,000 周期读到 hart 已在 S 态执行 Linux 的 `memmap_init_range`，Sv39 已开启。另一个限制为 128 MiB 的诊断配置已执行 `/init`，通过 RTL 串口输出 `VCU118_INITRAMFS_READY` 与 Linux 6.6.65 的 `uname`。两者都不是实板 shell 记录。
- **调试总线与时序**：已在生成的 RTL 上对调试从设备缓冲做 4,112 拍双向反压测试；整机综合网表仍发现一路跨时钟域的组合停核信号。未门控调试时钟的整机对照版首次在 100 MHz 约束下完成布线，建立/保持/脉宽裕量分别为 **+0.349 / +0.011 / +0.143 ns**，已生成 bitstream。该版仍有 7 条 Critical CDC 记录，未获准上板。
- **VCU118 实板**：独立串口探针的 260/260 随机问答后，已换上完整的 100 MHz Rocket 调试缓冲版。串口上传两种裸机程序：1 MiB 两轮读写及定时器通过；在四个分隔 512 MiB 的位置，各刷出并校验 4 KiB，两轮通过。板上 DDR4 MIG 报告 **CAL PASS**。这是独立的高地址抽测。另一次裸机扫描覆盖 **2,032 / 2,048 MiB**：先写全窗再逐字校验，地址图样和反相图样均通过；未覆盖的 16 MiB 留给诊断程序和 ROM 栈。
- **Linux 实板启动**：J4 收到完整 5,341,704 字节 OpenSBI + Linux 载荷，经 ROM 校验后跳转。Linux 执行 `/init`，完成 16 MiB 用户态校验；BusyBox 1.36.1 `ash` 正确计算并返回主机本轮的随机命令结果。
- **Linux 进程隔离实测**：另一版将两路停核信号分别同步，再做合并。在这版板上，两个进程完成 64 轮交接，检查 4 KiB 写时复制、共享内存的 128 次原子加法和浮点上下文，随后返回可用 shell。
- **同一固件的启动时间**：在同一块板、同一 bit、115200 串口上，从开始发送到 BusyBox 回答，未压缩为 **495.050 秒**，自解压为 **194.469 秒**。内层固件逐字节相同；这是一对观察值，不含 JTAG 配置。
- **Linux 性能基线**：单 hart、100 MHz，CoreMark® 单上下文，同一 Linux 启动连续测三组，每组两套种子各 6,000 次，性能/验证中位数分别为 **216.990 / 215.610 次每秒**。发布编译选项、CRC 和采集摘要；这是独立实测，非认证成绩。
- **下一个性能目标：单核 1,000 次/秒**。以同一块实板的 Linux 用户态单上下文为准。同一启动交错九次后，`-O3 + Zba/Zbb` 三次中位数 **246.655**，相差 4.05 倍；[实验方法与达标条件](docs/coremark-1000.md)。
- **四核新目标：150 MHz、九级流水线。** 已生成 100 MHz 的四核参考 RTL；独立 SMP Linux 镜像通过 QEMU 四核固定线程测试与单核反例。150 MHz 九级版尚无实板成绩。见[论文、开源核对照和九级定义](docs/quad-nine.md)。
- **为什么保留五级对照？** 在 100 MHz 配置上，用实板硬件计数器测三段热循环：连续加法、加载后立即使用、交替分支的中位 CPI 分别为 **1.00002、1.25001、1.66666**。同一负载的耗时取决于指令数 × CPI ÷ 频率；目前没有十级实现的数据表明能更快。
- **可选实验**：四路有符号 INT8 点积已接入可选配置的 TileLink 总线。Rocket 裸机通过 MMIO 核对 257 组结果，另验空取、重复提交两种错误。组合调试缓冲的版本也已通过从 UART 接收、原位启动裸机自检的全套 RTL 测试。Linux 驱动已编入可选内核，尚未通过 Rocket 上的 ioctl 验收；没有实板加速比。首版 Dot4 在实际路由中有一个三 LUT 组合环，Vivado 拒绝写 bit；未豁免。

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
