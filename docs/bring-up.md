# 重建与上板指南

Windows 使用 PowerShell 7、WSL Ubuntu-20.04 (x86_64)、Vivado/Vitis 2024.2。以下 Linux 命令在 WSL 运行。宿主需要 git、GNU 编译工具、Python 3、curl、tar/xz、flex、bison、bc、libssl-dev、libelf-dev、device-tree-compiler、gdisk、dosfstools、mtools 等。Linux 源和交叉工具链解压在 WSL 原生文件系统，须同时检查 VHDX 所在 Windows 卷的实际空余。不要以 root 启动整个工程。

```bash
cd /mnt/c/risc_v
bash scripts/checkout.sh                   # 核对 Chipyard 1.13.0 commit
bash scripts/fetch-cross.sh
bash scripts/fetch-generator-tools.sh && bash scripts/fetch-jq.sh && bash scripts/fetch-make.sh
bash scripts/init-generator.sh && bash scripts/warm-sbt.sh
bash scripts/build-image.sh && bash scripts/pack-image.sh
bash scripts/fetch-qemu.sh && bash scripts/repeat-qemu.sh 10
# 不覆盖已有镜像；选择新的 .img 文件名
python3 scripts/make-data-sd.py artifacts/fw_payload.bin artifacts/rebuilt-data.img
python3 scripts/qemu-storage.py artifacts/fw_payload.bin artifacts/rebuilt-data.img
bash scripts/test-host.sh && python3 -m unittest discover -s tests
```

```powershell
Set-Location C:\risc_v
.\scripts\build-rom.ps1
.\scripts\build-bare.ps1
python .\scripts\test-release.py
.\scripts\build-fpga.ps1
```

`build-fpga.ps1` 先运行 WSL elaboration，后在 Windows 运行 Vivado。`-Distro` 及 `-Vivado` 可覆盖默认值；示例路径没有空格。开源依赖身份见 `sources.sha256`、锁定的 Git 提交及子模块 gitlinks；默认用户工具和缓存分别在 `~/.local/share/vcu118-tools`、`~/.cache/vcu118-build`，可用 `VCU_TOOLS` / `VCU_BUILD` 指定其它私有位置。

## 实板验收流程

1. 接板电源、FPGA 配置 USB-JTAG、板级 USB-UART、与板参考引脚表核对过的 PMOD 转 SPI SD。CPU 的 RISC-V 调试 JTAG 是另一接口（本配置导到 FMC_J2）。用 `scripts/probe_board.tcl` 枚举器件，明确目标身份后再编程。
2. 用确认过的空卡制作裸机诊断卡；由操作人选择目标设备并备份，不要把 `.img` 当一个普通文件复制到 FAT。接串口 115200、8N1，记录整段复位输出和本轮 bit/SD SHA-256；先看 `VCU118_DIAG_PASS`。可用 `scripts/capture-board-uart.ps1 -Port COM实际编号 -Mode bare` 在复位前开始捕获；Linux 则换 `-Mode linux`。出现 DDR 故障时要单独取得 DDR 控制器训练/校准证据。
3. 更换 Linux 镜像。OpenSBI 从 DDR 0x80000000 运行并跳至 Linux 0x80200000；控制台必须能输入命令并看到真实回显。板上观察 `VCU118_INITRAMFS_READY`、`SOC_CHECK_PASS`、`cat /proc/cpuinfo` 和 `cat /proc/interrupts`；分别验证定时器和外部中断。第一阶段不要在固件原始分区上创建文件系统。
4. 记录冷启动次数、失败次数和内存压力持续时间。检查最终时钟关系、未约束端点、setup/hold/脉宽、CDC 与 DRC。单独记录硬件频率、资源和基准；不把 QEMU 时间或估算峰值当实测性能。

初始需求快照见 `VCU118-SOC-v0.1.md`。工具和第三方源码遵守各自随附许可；见 `THIRD-PARTY.md`。
## 已生成 RTL、设备树和启动链（2026-11-26）

| 层次 | 已观察到的结果 | 证据/边界 |
|---|---|---|
| 生成的板级源码 | 371 个 HDL 源文件；已通过全 SoC Vivado 综合与布局 | `artifacts/vcu118-stock-rtl-r2.zip` 附相对路径清单、PLL/DDR IP 的重建 Tcl、ROM；不是 bitstream。原版运行 `artifacts/fpga-20261126-121211-c8bd99/`。|
| ROM 与硬件描述 | 逐字节比对实际 TLROM（2,968 B 启动代码 + 3,880 B DTB），UART/SPI 总线 100 MHz、CLINT 时基 **100 kHz**、启用 DDR 窗口 2 GiB。OpenSBI v3 的反汇编确认下一阶段 DTB 搬到可写 DDR `0x82200000` | `logs/board-dt-v2.txt`、`logs/fdt-relocation-v3.txt`；设备树中的 CPU `clock-frequency=0` 不是时序结果。|
| 原版真实 Rocket RTL 从复位读 SD | 已看到 CMD18 从 LBA 34 读取并开始第 4 个扇区；**尚不等于读完 30 MiB 或进入 Linux** | `logs/rtl-boot-b.txt`；保留真实 Rocket、ROM、缓存、互连、SPI/UART、定时器，使用外部 RAM 与 SD 卡模型。|
| 原版真实 Rocket RTL 用 JTAG 启动裸机 | 9,035,776 个周期；串口确认 1 MiB 两轮读写、mtime 前进；TL 读 56,849 笔、写 30,763 笔。| `logs/rtl-debug-bare-c.txt`；使用外部 JTAG/DMI 设置入口、预装模拟内存。既非 SD 全链路，也非实际 DDR 训练。|
| 改进候选 ROM4 + 两级 UART 输入同步 | 保留五级 Rocket 和 100 MHz 目标。独立 ROM 先以 400 kHz 初始化 SDHC，再以 12.5 MHz 读主 GPT；核验主表和扇区 CRC，限长 30 MiB，出错留在 ROM，不执行部分载入的 DDR 程序。有效载荷分区可以精确到扇区，422 B 裸机只需 1 个数据扇区而非 61,440 个（另读 GPT 33 个扇区）。| `software/boot-gpt/`、`scripts/prepare-candidate.py`、`logs/board4-prepare.txt`。这是功能/防误启动改进，不是加密认证，不支持 SDSC 或所有分区布局；原版 ROM、原版 v3 固件均未覆盖。|

RTL 仿真的长日志在 `logs/rtl-*`。测试通过必须同时出现自检串口标志、相应模式的 `ROCKET_RTL_PASS` 和成功退出；只显示 OpenSBI 标题不能算 Linux 已启动。原版 shell 约束对数个 INOUT 端口找不到寄存器，且 UART RX 直接扇出到多个逻辑端点（`logs/io-cones-console.txt`）。候选版单独处理 UART 同步和可识别的 IOB 端点，但不能替代外部接线/时序预算与实际板测。PCIe、以太网、多核均不在本次实现内。

### 复现 RTL 仿真与候选版

```bash
# cwd: /mnt/c/risc_v，先完成上述原版 RTL 生成
bash scripts/fetch-verilator.sh && bash scripts/build-rtl-sim.sh
bash scripts/test-rtl-boot.sh sd-prefix artifacts/vcu118-linux.img 3000000
bash scripts/test-rtl-boot.sh debug-bare artifacts/bare/bringup-vcu118.img 70000000 artifacts/bare/bringup.bin
# 以下目录和输出文件必须未使用
python3 scripts/package-rtl.py --out artifacts/stock-next.zip
bash scripts/build-boot-gpt.sh artifacts/rom-next
python3 scripts/prepare-candidate.py artifacts/stock-next.zip artifacts/rom-next cache/kit-next
python3 scripts/make_sd.py --compact artifacts/bare/bringup.bin artifacts/bare-next.img
export VCU_SIM_KIT=$PWD/cache/kit-next VCU_SIM_OBJ=$HOME/.cache/vcu118-build/verilated-next
bash scripts/build-rtl-sim.sh
bash scripts/test-rtl-boot.sh gpt-bare artifacts/bare-next.img 70000000
bash scripts/test-rtl-boot.sh gpt-badcrc artifacts/bare-next.img 30000000
```

在 Windows 已安装 Vivado 2024.2 的环境中，可在独立候选目录运行 `vivado -mode batch -source build.tcl`，无须重新编译 Scala。`.img` 都是普通镜像文件，脚本不会写实体卡。本次工程记录明确区分原版、候选、功能仿真和实板结果。

## 不插 SD 的启动方式：UART5 恢复 ROM

这是**单独选择的 ROM**，不自动切换已有的原版或 ROM4。它从 FPGA 侧串口收一个程序到 DDR，不访问 SPI。使用者必须信任提供程序的电脑；CRC32 不能认证固件。下载只写易失 DDR，不会改写配置 Flash 或实体卡。

在收到 `UART5_READY v1` 后，主机用 115200 baud、8N1 发送一个二进制帧：8 字节 ASCII `VCU118U5`、4 字节小端载荷长度、4 字节小端 IEEE CRC32（与 `zlib.crc32(payload)` 相同），随后是原始载荷。接收地址固定为 `0x80000000`，允许 1 字节至 30 MiB（含上限）。ROM 在首字节前等主机；帧一旦开始，相邻字节静默 2 秒即报 `UART5_STOP TIMEOUT`。魔数、长度或 CRC 错误也会停在 ROM，需要复位重试。只有完整帧通过才输出 `UART5_HANDOFF`，执行 `fence.i` 并以 `a0=mhartid`、`a1=本版本实际 DTB 地址` 交接。HANDOFF 本身不算载荷运行成功。

```bash
# 均须选择新目录。stock-next.zip、bare-next.img 的生成见上节。
bash scripts/build-boot-gpt.sh artifacts/rom5-next uart5
python3 scripts/prepare-candidate.py artifacts/stock-next.zip artifacts/rom5-next cache/kit5-next --boot uart5
python3 scripts/package-candidate.py cache/kit5-next artifacts/recovery5-next.zip
export VCU_SIM_KIT=$PWD/cache/kit5-next VCU_SIM_OBJ=$HOME/.cache/vcu118-build/verilated-5-next
bash scripts/build-rtl-sim.sh
bash scripts/test-uart5-rtl.sh logs/recovery5-next artifacts/bare-next.img artifacts/bare/bringup.bin
```

测试台在 `ChipTop` 的 RX 引脚逐位送入真实帧，在 TX 引脚解码输出；卡仅为通用测试台夹具，ROM5 模式要求零个 SD 命令。正例不经调试接口预装 RAM。失败用例只在错误码出现后才用模拟 JTAG 读停机 PC。截断用例按真实 100 kHz mtime 等待（约 2 亿个模型周期），未跑完不能判通过。

**实板操作仅在 ROM5 对应的 bit 已签核时执行。** Windows 使用前述 `test-connected-board.ps1 -Program ...`，另加 `-UartPayload <裸机或固件.bin>`。Linux 建议 `-Mode linux -TimeoutSeconds 1500`：5.3 MB 载荷光串行线传输就需要约 8 分钟，还要留编程、DDR 启动、shell 自检的时间。脚本先验证 bit、线缆和 FPGA 身份；只有编程完成且捕获 `UART5_READY v1` 才开始发送。没有名单明确的签核 bit 或没有本次载荷的最终串口验收标志，均不记录板测通过。
