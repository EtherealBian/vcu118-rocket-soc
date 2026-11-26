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

## 可选的四路 INT8 点积外设

`RocketVCU118Config` 不含 Dot4。选择 `Dot4RocketVCU118Config` 后，处理器仍是五级 Rocket；CPU 把两个 32 位字各自拆成四个有符号 8 位数的工作交给 `0x64002000` 的外设，读回四项乘积之和。集成测试用软件标量参考核对边界值和伪随机向量，同时检查没有结果时取数、上次结果未取时再次提交这两个错误。测试路径经过 CPU 和 TileLink，不使用主机替代乘加输出。

```bash
# 先完成基线生成、交叉工具链和 Verilator 安装。输出目录都需选未使用的名称。
VCU_GEN_HEAP=3G VCU_GEN_CPUS=2 bash scripts/generate-dot4.sh
bash scripts/build-dot4-sw.sh artifacts/dot4-bare-next
# 只验裸机，不必重编 Linux：
VCU_SIM_OBJ=$HOME/.cache/vcu118-build/verilated-dot4-next \
  bash scripts/test-generated-dot4.sh logs/dot4-next artifacts/dot4-bare-next
# 若要验 Linux，再建独立驱动内核；下面最后一项会启动长周期 Linux 验收。
bash scripts/build-dot4-linux.sh "$HOME/.cache/vcu118-build/dot4-linux-next" artifacts/dot4-linux-next
VCU_SIM_OBJ=$HOME/.cache/vcu118-build/verilated-dot4-linux-next \
  bash scripts/test-generated-dot4.sh logs/dot4-linux-next artifacts/dot4-bare-next artifacts/dot4-linux-next
```

打包时逐字节检验 firtool 导出的乘加 RTL（仅允许固定版本生成器的单行注释及文件末尾换行差异），然后从这个包重建模拟器。每例分开记录实际 UART、模型日志和输入哈希；只有进程正常退出且匹配本模式 PASS 才写 `.ok`。Linux 验收另外需要真实设备 ioctl、16 MiB 自检、交互 shell 回答；QEMU virt 打印 `LINUX_DOT4_NO_PLATFORM_DEVICE` 不算通过。

## 观察 Linux 交接后的执行位置

在实际 ChipTop 模型上，`debug-profile-linux` 将完整固件放到模拟外部 RAM，再经 JTAG/DMI 设置 PC 和交接参数。在指定周期停 hart，用调试程序缓冲区读 CSR/GPR，恢复临时借用的 x5，继续执行。它不改变板上配置，也不以 PC 落在内核内当作整机验收。

```bash
# 使用前文生成的 UART5 kit 及其仿真器；按实际解压/编译目录设置这两项。
export VCU_SIM_KIT=$PWD/cache/board5-c VCU_SIM_OBJ=$HOME/.cache/vcu118-build/verilated-uart5-a
bash scripts/test-rtl-boot.sh debug-profile-linux artifacts/linux-compact.img 3000000000 artifacts/fw_payload.bin >logs/linux-profile.txt 2>&1
python3 scripts/symbolize-linux-profile.py logs/linux-profile.txt "$HOME/.cache/vcu118-build/image" artifacts/fw_payload.bin
# 独立诊断配置：同一 Linux Image；对板级 DT 仅增加 /chosen/bootargs，启用早期控制台并限制 Linux 使用 128 MiB。
bash scripts/build-linux-diagnostic.sh "$HOME/.cache/vcu118-build/diag128-next" artifacts/diag128-next artifacts/Image
```

128 MiB 配置将诊断 DTB 嵌入独立 OpenSBI，覆盖 ROM 提供的 DTB；完整硬件地址图仍有 2 GiB。本轮两个新目录重建的载荷 SHA-256 一致：`af9c7b2ae6539e825fe329ca3b739d2f255eb0a46215914dab68aa7d7418b283`。它用于观察早期串口并缩短页描述符初始化；其结果不能代替默认 2 GiB 固件、整段 DDR 自检或实板运行。为防止用错内核，符号化工具核对日志中的固件哈希，从两个 ELF 重新导出二进制，并核对嵌入载荷的位置和内容；不会把无法归属的 PC 自动解释成内核函数。

### JTAG 系统总线读写与 CPU 回包（模拟 TAP）

`bash scripts/test-debug-sba.sh logs/sba-next artifacts/bare-compact.img` 使用 `VCU_SIM_OBJ` 和 `VCU_SIM_KIT` 指向同一套已编译的 ChipTop 和生成清单；脚本核对 Verilator 的原始文件清单路径。不要把来自另一解压目录的清单与旧模型混用。本测试不预装 RAM：通过 SBA 加载一个小程序、写入 32 个输入、检查非对齐错误和清除操作，再让 Rocket 启动并计算。宿主检查 UART 和 SBA 读回的一致性。磁盘仅为仿真器固定输入，没有发起扇区访问。

## 为什么先保留五级：调试时钟的对照实验

ROM4 的 100 MHz 目标未达成，关键建立路径经过控制总线和调试从设备，并非 Rocket 的五级算术流水线。保留原配置，另行生成 `AlwaysClockedDebugRocketVCU118Config`：去掉调试模块的 FPGA fabric 门控时钟，保留调试功能，在生成 RTL 中检查实际连到原始门输入、reset 和 dmactiveAck 保持一致，另比对板级 DTS。

```bash
VCU_GEN_CPUS=2 VCU_GEN_HEAP=3G bash scripts/generate-debug-clock.sh
python3 scripts/package-rtl.py --config AlwaysClockedDebugRocketVCU118Config --out artifacts/clock-test.zip
python3 scripts/prepare-candidate.py artifacts/clock-test.zip artifacts/rom5-next cache/clock-test --boot uart5
export VCU_SIM_KIT=$PWD/cache/clock-test VCU_SIM_OBJ=$HOME/.cache/vcu118-build/verilated-clock-test
bash scripts/build-rtl-sim.sh && bash scripts/test-debug-sba.sh logs/sba-clock-test artifacts/bare-next.img
```

该分支归档还在布线后物理优化前保存一个可恢复的检查点，最终另存各时钟域最差端点。如果最终实现没有同时通过建立、保持、脉宽及 CDC/IO/DRC 人工复核，不把仿真通过当作上板许可。

### 先验 JTAG 和 FPGA 侧 UART（不需要 PMOD 或 SD）

独立探针只连板上 250 MHz 差分时钟和 CP2105 的 FPGA 侧 RX/TX；MMCM 生成 100 MHz，UART 接受 115200 8N1。固件、Rocket 和 DDR 控制器都不在这个 bit 里。下载会替换当前易失配置，但不改写配置 Flash 或卡。关闭占用 FPGA 串口的终端。

```powershell
# PowerShell 7；使用尚不存在的输出目录。
./scripts/test-board-probe-sim.ps1 -Run artifacts/probe-sim-next
./scripts/build-board-probe.ps1 -Run artifacts/probe-route-next
python scripts/review-board-probe.py artifacts/probe-route-next
# 人工检查 impl/ 下的 timing、check、cdc、exceptions、clocks、io、drc、methodology 报告。
# 填入自己审过的 bit 哈希和本地枚举的三个身份值，不要把它们提交到仓库。
./scripts/test-board-probe.ps1 -Run artifacts/probe-route-next -ReviewedBitSha256 '<sha256>' `
  -Bridge '<bridge>' -Cable '<cable>' -Slr0Dna '<0x...>' -Count 260
# 使用刚输出的本地采集目录；复查真实回读及每个请求和响应，不依赖终端回显。
python scripts/verify-probe-capture.py artifacts/probe-route-next logs/probe-hw-<本轮编号>
```

约束只把 UART 异步边界和 MMCM LOCKED 第一级的 D 当作异步；LOCKED 不是时钟发射端，例外报告里该条的已计时端点数为零，不当作额外覆盖。构建脚本检查它是第一级 D 的唯一驱动，以及两条同步链的两级之间都仍有经过 STA 的路径。响应格式是 `56 31 <序号> <ROL8(请求,3) XOR A7>`，主机收完四字节才发下一条。公开验证 JSON 同时记录采集 CSV 和 bit 的 SHA-256，以及构建时原始源文件与 Git 规范化 LF 源文件的摘要；本机串口号、线缆标识、DNA 和原始日志不公开。

### 复现调试从设备缓冲和中断同步器检查

先按上一节生成未门控的对照配置并准备 UART5 ROM。下列命令用独立的生成器 JAR 和目录，不修改上游受版本控制的 Periphery.scala。两个实现并非只差一个因素：缓冲候选另有中断同步属性。不要把最终时序的任何差值都归因于缓冲。

```bash
bash scripts/generate-buffered-debug.sh
python3 scripts/package-rtl.py --config BufferedDebugRocketVCU118Config --out artifacts/buffer-base.zip
python3 scripts/prepare-candidate.py artifacts/buffer-base.zip artifacts/rom5-next cache/buffer5i --boot uart5 --irq-sync
export VCU_SIM_KIT=$PWD/cache/buffer5i VCU_SIM_OBJ=$HOME/.cache/vcu118-build/verilated-buffer5i
bash scripts/build-rtl-sim.sh
bash scripts/test-debug-buffer-stalls.sh logs/buffer-stalls
bash scripts/test-debug-sba.sh logs/buffer-sba artifacts/bare-next.img
bash scripts/test-debug-slave.sh logs/buffer-lanes artifacts/bare-next.img
```

`test-debug-buffer-stalls.sh` 只编译所选 kit 中真实的 A/D 缓冲层次，特意阻塞下游，在装满时复位。`test-debug-slave.sh` 则用整个 ChipTop，经 TAP 停核，用 program buffer 发起 hart 的各宽度访存，并从外部 DMI 交叉读回。测试严格区分取得停核控制前的 ROM 栈填充与停核后的端点测试。`check-model-kit.py` 对照 Verilator 5.022 记录的 `-F` 和每个输入的文件身份、时间戳及当前 kit 校验和；复制、替换或改动生成目录后应重建，不将旧可执行文件冒认为新 RTL。

```bash
# 用所选实现自己的报告，不跨 run 拼接。此命令只列出问题，不豁免任何一项。
python3 scripts/inventory-cdc.py <run>/obj/report/cdc.rpt
# Vivado 打开整个 post_synth.dcp。检查属性、级间扇出、接收时钟，以及第一级的实际驱动与来源。
vivado -mode batch -source scripts/inspect-integrated-irq.tcl -tclargs <run>/obj/post_synth.dcp audit-marked irq-audit.tsv
```

只看到三个真实触发器还不够。`audit-marked` 可报告已识别的跨时钟 OR 门；`require-marked` 会拒绝该结构。两者均不提供整机 CDC 通过结论。板测采集器仅在当前 ROM 完整 `UART5_HANDOFF` 行之后接受客体标记；Linux 还需准确的 16 MiB 自检和本次挑战回复。

### 比较两路停核请求（可选，不改变 CPU 级数）

在生成前述 `buffer-base.zip` 后，从同一输入派生另一个独立目录：

```bash
python3 scripts/prepare-candidate.py artifacts/buffer-base.zip artifacts/rom5-next cache/split-halt --boot uart5 --irq-sync --irq-front-end
VCU_SIM_KIT=$PWD/cache/buffer5i bash scripts/test-debug-halt-sources.sh logs/halt-original
VCU_SIM_KIT=$PWD/cache/split-halt bash scripts/test-debug-halt-sources.sh logs/halt-split
python3 scripts/compare-halt-traces.py logs/halt-original logs/halt-split
# 只对这个候选自己的整机 DCP 核验结构，不能用单模块仿真替代。
vivado -mode batch -source scripts/inspect-integrated-irq.tcl -tclargs <split-run>/obj/post_synth.dcp require-split irq-split.tsv
```

新逻辑针对固定的未门控调试时钟和单 hart。先核对九个已追溯的生成模块摘要；不接受不同版本静默替换。物理审核要求 JTCK 寄存器 Q 到第一级 D 之间无组合逻辑、亚稳态级只驱动第二级、两路在目标域寄存后才进入 OR，并复核原 tile 接收链。测试中 `io_hartIsInReset_0` 是调试模块的状态输入，而不是 VCU118 上可独立复位 hart 的证明。

### 审核外部接口约束

`review-fpga.py` 从同一个 `check_timing -verbose` 报告逐项核对缺少 I/O 延迟的引脚名称、方向和个数。未识别的引脚，或新增的非零豁免类别，会阻止自动下载。`board_io_inventory_known=true` 只表示都能识别，**不表示外部接口时序达标**。下面是 ROM4 的 5 个输入和 6 个输出，不是通用的时序豁免列表：

| 接口 | 报告中的端口 | 还需审什么 |
|---|---|---|
| FPGA 串口 | 输入 `uart_rxd`，输出 `uart_txd` | 两级 RX 的第一级是否直接接引脚、级间有无扇出和实际时序；TX 和波特率须做 J4 双向实板测试。异步串口没有外部同步参考时钟。 |
| 软核调试 TAP | 输入 `jtag_jtag_TDI/TMS`，输出 `jtag_jtag_TDO` | `JTCK` 自身为 100 ns 周期约束；数据的输入建立/保持和 TDO 返回必须按外部调试器、连线和采样边沿预算。J106 配置下载不经过此 TAP。 |
| SPI/SD | 输入 `sdio_spi_dat_0` (MISO)，输出 `sdio_spi_clk`、`sdio_spi_cs` (MOSI)、`sdio_spi_dat_3` (CS_n) | shell 的 `cs` 名称不是 SPI 片选。核对生成 HDL 后再对照 UG1224 表 3-30：J52.1/3/5/7 对应 CS_n/MOSI/MISO/SCLK，U41 在 FPGA 的 1.8 V 和接口的 3.3 V 之间转换。外部卡及连接的发射/返回延迟、选定 SCLK 速率要单独验证；UART 载荷的通过不能验证 SD。 |
| 系统与 DDR 复位 | 输入 `reset`，输出 `ddr_c0_ddr4_reset_n` | 前者进入 POR/PLL/复位整形，需检查断言/释放以及各域复位接收；后者由 MIG 驱动，不是 DDR 数据线。须核查复位保持/释放、校准及真实内存读写，不能用 SoC RTL 的 RAM 模型代替。 |

缺少硬件预算时保留未验证状态，不填零延迟或添加全局假路径来让报告变绿。

对实现所用 kit 的板级复位行为运行 `VCU_SIM_KIT=$PWD/cache/clock5 bash scripts/test-board-wrangler.sh logs/wrangler-new`（替换为实际 kit 路径）。无需连接实板；不能替代 DCP 复位树检查。

### 从板卡参考文件独立审查连线

对一个已完成的实现运行 `python scripts/audit-board-pins.py <run> <Vivado安装目录>/data/xhub/boards/XilinxBoardStore/boards/Xilinx/vcu118/2.4`。输入是该次路由的 `routed-io.rpt` 和生成的 MIG XCI；按逻辑口逐位查 AMD 板数据，而不是按封装位置反查来猜端口名。UART 参考 UG1224 表 3-26，PMOD/FMC 位置参考表 3-30/31。FMC 为单端调试用的标称 1.8 V 配置，程序不测 VADJ、不验证外接探头。正式整机下载前也执行此审查；Vivado 标准安装放在其他目录时可传 `-BoardDefinition`，哈希仍须匹配。单独用 `vivado -mode batch -source scripts/inspect-board-uart.tcl -tclargs <post_route.dcp> <新.tsv>` 追踪真实收发寄存器和级间路径。

DDR 路径分三层检查：

1. 对生成的板级数字适配器：WSL 中 `VCU_SIM_KIT=$PWD/cache/<候选> bash scripts/test-board-mig-adapter.sh logs/<新目录>`。通过标志是 12 个场景及两个故障对照都得到预期结果，脚本正常退出并生成 `test.ok`。
2. 对完整路由 DCP：`vivado -mode batch -source scripts/inspect-mig-crossings.tcl -tclargs <post_route.dcp> <新目录>`，再运行 `python scripts/inventory-mig-crossings.py <新目录>/endpoints.tsv <同次实现>/obj/report/clock-interaction.rpt`。逐方向核对 max/min 集合、总数、端点类型；不能把未设约束的路径改写为时序通过。
3. 对真实物理 DDR：使用易失配置和 UART 载荷，保留本轮握手、内存比较和计时器证据；有物理校准或内存测量后才报告板测结果。
