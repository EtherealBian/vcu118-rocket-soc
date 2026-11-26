# 验证记录 · 2026-11-26

| 测试对象 | 观察 | 不覆盖 |
|---|---|---|
| Verilator，ROM4 + 真实 Rocket ChipTop | 12,780,544 模拟周期；33 个 GPT 扇区 + 1 个载荷扇区；56,937 笔 TL 读，30,865 笔 TL 写；UART 输出 `VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced`，进程正常退出 | 模拟外存/SD，不证明真实 DDR 训练、SD 电气特性或最高频率 |
| ROM4 错误注入 | 主 GPT 头、分区表 CRC、分区超出 30 MiB、载荷扇区传输 CRC 各自单独测试；通过模拟 JTAG 读取异常停机 DPC `0x1003c`，未执行 DDR 载荷 | 能查传输错误，不提供固件签名认证 |
| ROM5，真实 Rocket 双向 UART 引脚 | 发送 422 B 裸机程序，未预装模型 RAM、未读 SD；13,049,856 模拟周期后收到完整两轮 1 MiB 读写及 mtime PASS。坏魔数、超长、错误 CRC 三项分别拒绝，调试端实读 DPC `0x1003c` | 帧中断的 2 秒超时已有原生 C 测试；长周期 RTL 用例进行中。不证明整份 Linux 已通过串口启动或实板 DDR 正常 |
| JTAG 系统总线访问 · Rocket ChipTop | 无 RAM 预载，经模拟 TAP 逐字写入并读回 177 B 程序和 32 个输入；非对齐访问返回 `sberror=3`，清错后可访问。Rocket 运行后，JTAG 读回计算结果 `0xc0ff8be1` 与宿主一致，串口报告 `SBA_GUEST_REPLIED v1`；共 1,041,532 周期 | 功能模型覆盖调试系统总线、CPU 和 UART；不经过板载配置 JTAG，也不测真实 DDR |
| 基线 Linux · Rocket ChipTop | 模拟 JTAG 预载固件。第 40,000,000 周期停核读回 DPC `0xffffffff8018fe8e`、S 态、`satp=0x8000000000080522`（Sv39）。在该固件对应的 `vmlinux` 匹配 `memmap_init_range+0xfe`；恢复借用的 x5 并恢复执行 | 证明 Linux 已执行内存初始化，单次取样不证明已完成初始化，也不是 shell、SD 启动或实板 DDR 验收 |
| 128 MiB 诊断 Linux · Rocket ChipTop | 同一内核 Image、独立启动参数；UART 引脚解码出 `Linux version 6.6.65`、`Machine model: ucb-bar,chipyard`、SiFive 早期控制台地址 `0x64000000` 以及 `Memory limited to 128MB` | 固件预载到模拟内存；这个证据点尚未看到 shell，不代表默认 2 GiB 固件或板上启动 |
| 调试时钟对照 · Rocket ChipTop | 只在 FPGA 配置中去掉调试逻辑的门控时钟，保持原上游时钟、reset、dmactiveAck；生成的板级 DTS 对比一致。在新生成的模型里重新通过上表 SBA mailbox，结果和基线相同 | 不改变 CPU 流水级数，不据此宣称时序收敛或实板下载成功 |
| QEMU virt 基线 Linux | 10 个独立进程：initramfs、16 MiB 用户内存以及交互命令回显全部成功；基线载荷 SHA-256 `7a8f9932796747be2cd54390af7adf88ba5b156e54069884946185fef47b41c9` | 非板级现场测试 |
| 可选 Dot4 · Rocket ChipTop | JTAG 设置 PC、预装模拟 RAM，Rocket 自己访问 `0x64002000`。695,296 个模拟周期，完整 UART 标志 `DOT4_MMIO_PASS vectors=257 protocol_errors_checked=2`；空取、重复提交均被识别 | 不是从卡加载；此数包含启动和打印，不是算术单元延迟或加速比。Linux ioctl 和实板仍未验证 |
| 原版 · 从原布局检查点重跑路由 | 113,436 / 113,436 个网络完全布线；最差建立 −3.977 ns、保持 +0.010 ns，最差建立从控制总线指向调试 program buffer | 这是 route-only 恢复运行，未做布线后物理优化，与下一行不是相同构建阶段，不能用差值当提速 |
| ROM4 · 完整 VCU118 布线后 | Vivado 2024.2：113,426 / 113,426 个网络完全布线。100 MHz 时最差建立 −0.631 ns，1,228 个端点失败（TNS −294.418 ns）；最差保持 +0.001 ns，脉宽裕量 +0.143 ns | **时序不通过**，构建拒绝生成 bit。最差路径是控制总线至调试寄存器写使能，不据此更改 CPU 级数或宣称达到目标频率 |
| 初始物理板，只读快照 | Vivado 2024.2 识别单一 XCVU9P，读取 3 个 SLR 的配置状态；Windows 打开 FPGA 侧 CP2105 Standard 串口（115200、8N1），6 秒被动窗口收到 0 字节 | 该次只读观察时板内设计归属未知；不能作为本工程的启动、双向 UART 或 DDR 测试 |
| **VCU118 实板 · 独立 UART 诊断** | 14:22（上海时间），J106 易失配置后，读回三个 SLR 的 DONE=1、CRC_ERROR=0。在 J4 的 FPGA 侧串口发送 260 个随机字节，收到并逐项独立复算 260 个四字节回复，覆盖 8 位序号回绕。137/137 个网络完全布线，100 MHz 约束下 WNS +8.198 ns、WHS +0.038 ns、脉宽裕量 +0.600 ns；DRC 和 methodology 各 0 项 | 这是独立时钟和 UART 电路，非 Rocket、DDR 或 Linux。100 MHz 为此设计的 MMCM 配置与 STA 约束，不是对实板频率的仪器测量。没有写 Flash 或 SD |

## 如何复核

基线：`scripts/repeat-qemu.sh 10`。RTL：用 `scripts/build-rtl-sim.sh` 与 `scripts/test-rtl-boot.sh`；候选 ROM 及 compact 镜像生成见[指南](bring-up.md)。对主 GPT 三种坏卡运行 `scripts/test-rom4-faults.sh`（按脚本指定提供独立输出、模拟器及镜像）；载荷错误用 `gpt-badcrc` 模式。只有明确 PASS 标志和正常退出同时成立才算成功。

## 接线与自动测试

配置 FPGA 用 **J106** 的 USB-JTAG；它不是软核调试 TAP（后者在 FMC_J2）。USB-UART 用 **J4**：CP2105 **Standard** 是软核控制台；Enhanced 接板管，不发送测试命令。板载管理 microSD 不接 XCVU9P。使用 SD 启动时，J52 PMOD 侧需单独的 3.3 V SPI SDHC 模块；按板上标号核对 J52.1 = CS_n、J52.3 = MOSI、J52.5 = MISO、J52.7 = SCLK，另接电源和公共地。板卡参考：AMD *VCU118 Evaluation Board User Guide* (UG1224)，USB、SD 与 PMOD 章节。

先用 `scripts/probe_board.tcl` 枚举，用 `scripts/identify-board.tcl` 只读核对线缆和器件。Windows 预检：`./scripts/test-connected-board.ps1 -Bridge <USB串口芯片序列号>`，默认不编程。确定目标与引脚、人工审查完整布线时序/CDC/DRC 后，显式传入 `-Program -Mode bare` 或 `linux`、`-Run <实现目录>`、`-ReviewedBitSha256 <已审核bit哈希>`、`-Bridge`、`-Cable`、`-Slr0Dna`。脚本先开正确的串口，再核对片上身份，易失编程，核对三片 SLR 配置状态，最后核验诊断输出或随机 shell 挑战。不写 Flash 或 SD；选用适合当前模式且已准备的启动介质。所有物理标识、日志和镜像均保留在本机。
