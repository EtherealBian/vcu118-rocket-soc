# 验证记录 · 2026-11-26

| 测试对象 | 观察 | 不覆盖 |
|---|---|---|
| Verilator，ROM4 + 真实 Rocket ChipTop | 12,780,544 模拟周期；33 个 GPT 扇区 + 1 个载荷扇区；56,937 笔 TL 读，30,865 笔 TL 写；UART 输出 `VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced`，进程正常退出 | 模拟外存/SD，不证明真实 DDR 训练、SD 电气特性或最高频率 |
| ROM4 错误注入 | 主 GPT 头、分区表 CRC、分区超出 30 MiB、载荷扇区传输 CRC 各自单独测试；通过模拟 JTAG 读取异常停机 DPC `0x1003c`，未执行 DDR 载荷 | 能查传输错误，不提供固件签名认证 |
| ROM5，真实 Rocket 双向 UART 引脚 | 发送 422 B 裸机程序，未预装模型 RAM、未读 SD；13,049,856 模拟周期后收到完整两轮 1 MiB 读写及 mtime PASS。坏魔数、超长、错误 CRC 三项分别拒绝，调试端实读 DPC `0x1003c` | 帧中断的 2 秒超时已有原生 C 测试；长周期 RTL 用例进行中。不证明整份 Linux 已通过串口启动或实板 DDR 正常 |
| 基线 Linux · Rocket ChipTop | 模拟 JTAG 预载固件。第 40,000,000 周期停核读回 DPC `0xffffffff8018fe8e`、S 态、`satp=0x8000000000080522`（Sv39）。在该固件对应的 `vmlinux` 匹配 `memmap_init_range+0xfe`；恢复借用的 x5 并恢复执行 | 证明 Linux 已执行内存初始化，单次取样不证明已完成初始化，也不是 shell、SD 启动或实板 DDR 验收 |
| QEMU virt 基线 Linux | 10 个独立进程：initramfs、16 MiB 用户内存以及交互命令回显全部成功；基线载荷 SHA-256 `7a8f9932796747be2cd54390af7adf88ba5b156e54069884946185fef47b41c9` | 非板级现场测试 |
| 可选 Dot4 · Rocket ChipTop | JTAG 设置 PC、预装模拟 RAM，Rocket 自己访问 `0x64002000`。695,296 个模拟周期，完整 UART 标志 `DOT4_MMIO_PASS vectors=257 protocol_errors_checked=2`；空取、重复提交均被识别 | 不是从卡加载；此数包含启动和打印，不是算术单元延迟或加速比。Linux ioctl 和实板仍未验证 |
| 物理板，只读 | Vivado 2024.2 识别单一 XCVU9P，读取 3 个 SLR 的配置状态；Windows 打开 FPGA 侧 CP2105 Standard 串口（115200、8N1），6 秒被动窗口收到 0 字节 | 当前板内设计归属未知；不能作为本工程的启动、双向 UART 或 DDR 测试 |

## 如何复核

基线：`scripts/repeat-qemu.sh 10`。RTL：用 `scripts/build-rtl-sim.sh` 与 `scripts/test-rtl-boot.sh`；候选 ROM 及 compact 镜像生成见[指南](bring-up.md)。对主 GPT 三种坏卡运行 `scripts/test-rom4-faults.sh`（按脚本指定提供独立输出、模拟器及镜像）；载荷错误用 `gpt-badcrc` 模式。只有明确 PASS 标志和正常退出同时成立才算成功。

## 接线与自动测试

配置 FPGA 用 **J106** 的 USB-JTAG；它不是软核调试 TAP（后者在 FMC_J2）。USB-UART 用 **J4**：CP2105 **Standard** 是软核控制台；Enhanced 接板管，不发送测试命令。板载管理 microSD 不接 XCVU9P。使用 SD 启动时，J52 PMOD 侧需单独的 3.3 V SPI SDHC 模块；按板上标号核对 J52.1 = CS_n、J52.3 = MOSI、J52.5 = MISO、J52.7 = SCLK，另接电源和公共地。板卡参考：AMD *VCU118 Evaluation Board User Guide* (UG1224)，USB、SD 与 PMOD 章节。

先用 `scripts/probe_board.tcl` 枚举，用 `scripts/identify-board.tcl` 只读核对线缆和器件。Windows 预检：`./scripts/test-connected-board.ps1 -Bridge <USB串口芯片序列号>`，默认不编程。确定目标与引脚、人工审查完整布线时序/CDC/DRC 后，显式传入 `-Program -Mode bare` 或 `linux`、`-Run <实现目录>`、`-ReviewedBitSha256 <已审核bit哈希>`、`-Bridge`、`-Cable`、`-Slr0Dna`。脚本先开正确的串口，再核对片上身份，易失编程，核对三片 SLR 配置状态，最后核验诊断输出或随机 shell 挑战。不写 Flash 或 SD；选用适合当前模式且已准备的启动介质。所有物理标识、日志和镜像均保留在本机。
