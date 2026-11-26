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
| **未门控调试时钟版 · 完整布线后** | 100 MHz 系统时钟，113,342 / 113,342 网络布通，建立/保持/脉宽最差裕量 +0.349 / +0.011 / +0.143 ns，各 0 个失败端点。全局最差建立路径在 200 MHz DDR 控制器校准逻辑；100 MHz 同域最差 +1.032 ns，在 L2 调度至 BRAM 地址之间。59,918 LUT、42,497 寄存器、203.5 BRAM tile、28 DSP | 首个满足已设时序约束的整机 bitstream，不等于实板签核。7 条 Critical CDC（含停核 SRL）；两条 TIMING-47 指向被时钟组忽略的系统 ↔ DDR UI；5 个输入和 6 个输出缺外部延迟。未用此版配置 FPGA。 |
| ROM4 · 完整 VCU118 布线后 | Vivado 2024.2：113,426 / 113,426 个网络完全布线。100 MHz 时最差建立 −0.631 ns，1,228 个端点失败（TNS −294.418 ns）；最差保持 +0.001 ns，脉宽裕量 +0.143 ns | **时序不通过**，构建拒绝生成 bit。最差路径是控制总线至调试寄存器写使能，不据此更改 CPU 级数或宣称达到目标频率 |
| 初始物理板，只读快照 | Vivado 2024.2 识别单一 XCVU9P，读取 3 个 SLR 的配置状态；Windows 打开 FPGA 侧 CP2105 Standard 串口（115200、8N1），6 秒被动窗口收到 0 字节 | 该次只读观察时板内设计归属未知；不能作为本工程的启动、双向 UART 或 DDR 测试 |
| **VCU118 实板 · 独立 UART 诊断** | 14:22（上海时间），J106 易失配置后，读回三个 SLR 的 DONE=1、CRC_ERROR=0。在 J4 的 FPGA 侧串口发送 260 个随机字节，收到并逐项独立复算 260 个四字节回复，覆盖 8 位序号回绕。137/137 个网络完全布线，100 MHz 约束下 WNS +8.198 ns、WHS +0.038 ns、脉宽裕量 +0.600 ns；DRC 和 methodology 各 0 项 | 这是独立时钟和 UART 电路，非 Rocket、DDR 或 Linux。100 MHz 为此设计的 MMCM 配置与 STA 约束，不是对实板频率的仪器测量。没有写 Flash 或 SD |

## 调试总线缓冲与跨时钟复查

- 生成的调试从设备 A（请求）和 D（响应）各有一个两项队列。在该 RTL 上独立改变两端的 ready/valid，共 4,112 拍：A 接收 2,611 项、交付 2,607 项，D 接收 1,955 项、交付 1,951 项；每个方向还有 4 项由两次满队列复位明确丢弃。逐拍核对已阻塞的首项、消费顺序与结束时的空队列。
- 同一候选的完整 ChipTop 通过 SBA 回包测试；坏魔数、超长、CRC 错误三例均读回预期停机地址。**这些是 RTL 测试，不是实板。** 100 MHz 的完整实现仍按布线后的数据判定。
- 对 ROM4 的全部 580 行 CDC 明细逐条与汇总计数对账，9 行 Critical 涉及复位整形器、调试与 DDR 异步队列、dmactive 双接收和调试中断。仅检查同步器单模块会漏掉问题：未标属性时，单模块能综合成三个触发器，整机却变成一个 FDRE 和一个 SRL16E。给缓冲候选的该同步器加属性后，整机综合网表确认为三个带 ASYNC_REG 的 FDRE，两级中间连接均只有一个后继。
- **尚未解决的细节**：第一级 D 的实际驱动是 LUT2（真值表 `4'hE`），把 JTCK 域的普通停核请求和系统时钟域的复位停核请求相或。移除 SRL 不等于移除了这个跨域组合路径。没有因此新增时序豁免或批准下载。
- 128 MiB 诊断 Linux 的 RTL 串口已报告 125,148 KiB 可用、PLIC 两个上下文、100 kHz 的 sched_clock；默认 2 GiB 内核在第 8,000 万和 1 亿拍的停核样本分别位于 `__free_pages_ok` 和 `__free_pages_core`。这是内核执行进展，不是用户态自检或实板启动记录。

## 调试访存与停核请求实测（RTL）

- 在时钟对照版和带两项缓冲的版本上，分别用 JTAG 停核，让 hart 通过程序缓冲区访问调试数据区，再从独立 DMI 口读回。两版各完成 180 次写、180 次读，涵盖 32 字节数据区内全部对齐位置和 1/2/4/8 字节宽度，也验证未写入的字节保持原值。每版 7,688,092 拍；停核前有一次 ROM 栈的 64 字节写分配读，测试期间无额外外存访问、无 SD 命令。
- 新增一个独立候选：JTCK 发起的停核和本地复位停核各经过两级寄存，随后才在调试时钟域相或。原 tile 的三级接收器保留，因此多两个接收时钟边沿。这不是处理器流水级的变化。
- 在两版真实生成的调试模块中用公开 DMI 接口各测 9 种时钟比/相位组合，覆盖普通停核、复位停核屏蔽/使能、复位记录清除和两路停核重叠后的两种撤销顺序。将原模块输出在目标时钟延迟两拍后，与新版本的引脚和握手逐事件比较：110,205 个事件全部相符，其中 536 个事件与未延迟输出不同。这里由测试台驱动 hart 复位状态，不能据此宣称板级复位接线或亚稳态可靠性已验证。
- 这一候选的完整 ChipTop 也通过了 SBA 上传、裸机回包和相同的 180 写/180 读矩阵，仍需整机综合网表复核、布线后时序和实板测试。具体命令见重建指南。

- 在时钟对照版的板级 `ResetWrangler` 真实生成 RTL 上，分别驱动系统和 MIG 两侧的复位原因与独立时钟，验证了双因重叠、接近门限的短暂重置、任意一侧时钟停止及恢复。9 组时钟比/相位各逐事件核对 367,174 次；每个输出在各自的时钟边沿释放 4 次。复位消抖计数需 10,000 个系统边沿，随后还有释放寄存器及各域三级复位链。此项**不**验证模拟亚稳、恢复/移除时序、MIG 校准或实板 DDR。

## 如何复核

基线：`scripts/repeat-qemu.sh 10`。RTL：用 `scripts/build-rtl-sim.sh` 与 `scripts/test-rtl-boot.sh`；候选 ROM 及 compact 镜像生成见[指南](bring-up.md)。对主 GPT 三种坏卡运行 `scripts/test-rom4-faults.sh`（按脚本指定提供独立输出、模拟器及镜像）；载荷错误用 `gpt-badcrc` 模式。只有明确 PASS 标志和正常退出同时成立才算成功。

## 接线与自动测试

配置 FPGA 用 **J106** 的 USB-JTAG；它不是软核调试 TAP（后者在 FMC_J2）。USB-UART 用 **J4**：CP2105 **Standard** 是软核控制台；Enhanced 接板管，不发送测试命令。板载管理 microSD 不接 XCVU9P。使用 SD 启动时，J52 PMOD 侧需单独的 3.3 V SPI SDHC 模块；按板上标号核对 J52.1 = CS_n、J52.3 = MOSI、J52.5 = MISO、J52.7 = SCLK，另接电源和公共地。板卡参考：AMD *VCU118 Evaluation Board User Guide* (UG1224)，USB、SD 与 PMOD 章节。

先用 `scripts/probe_board.tcl` 枚举，用 `scripts/identify-board.tcl` 只读核对线缆和器件。Windows 预检：`./scripts/test-connected-board.ps1 -Bridge <USB串口芯片序列号>`，默认不编程。确定目标与引脚、人工审查完整布线时序/CDC/DRC 后，显式传入 `-Program -Mode bare` 或 `linux`、`-Run <实现目录>`、`-ReviewedBitSha256 <已审核bit哈希>`、`-Bridge`、`-Cable`、`-Slr0Dna`。脚本先开正确的串口，再核对片上身份，易失编程，核对三片 SLR 配置状态，最后核验诊断输出或随机 shell 挑战。不写 Flash 或 SD；选用适合当前模式且已准备的启动介质。所有物理标识、日志和镜像均保留在本机。
