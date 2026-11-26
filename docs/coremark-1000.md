# 单核 CoreMark 1,000 次/秒

**目标，未达标。** 评估对象是 VCU118 上的一个物理 hart，在 Linux 用户态运行一个 CoreMark 上下文。起点是五级 Rocket、100 MHz、`-O2`，三次性能种子为 216.888375、216.990344、217.045290 次/秒。中位数 216.990344；到 1,000 需要 4.61 倍。部署同一套测试时，不把多核并行、Dot4、宿主机或仿真结果计入。

| 验收项 | 项目口径 |
|---|---|
| 原始输入 | EEMBC `9d07b05523c16754a214a40224018a4ee908e091`，未改算法和 POSIX port；2,000 字节、heap、一个执行上下文、两套标准种子 |
| 时长与复测 | 每套种子固定 12,000 次；若未来快到不足 10 秒，整组预先提高相同迭代数重测。每个配置三遍，保留每次原值、最小值/最大值和中位数 |
| 判定 | 三次性能种子**各自** ≥ 1,000 次/秒；三次验证种子通过。两套种子的各项 CRC、退出状态、ELF 身份、编译选项及主机墙钟全部复核 |
| 实现 | 报告真实使用的 bitstream、系统时钟配置、时序/CDC/DRC 评审和 Linux 启动记录。若更换核/频率，先重新评审并验板；不得修改计时基准制造提速 |

## 可复现的第一组对照

使用已通过的 `split5h`，不改 FPGA 时钟或 CPU。在同一 initramfs 中放入三份程序：`baseline`（`-O2`）、`o3`（只改到 `-O3`）、`o3-zb`（在 `-O3` 上只扩展 `-march` 至 `rv64gc_zba_zbb`）。均为同一 GCC 13.3.0、`lp64d`、静态链接、无 PGO。前两组隔离优化级别的影响；后两组隔离允许发出 Zba/Zbb 指令的影响。三轮顺序 ABC / BCA / CAB，九次调用不重启。会话标记只存在 shell 内存中。

```bash
# WSL；依赖与工具链准备见 bring-up.md，使用全新目录
VCU_COREMARK_AB=1 bash scripts/build-lab-linux.sh "$HOME/.cache/vcu118-build/cm-ab" artifacts/cm-ab
bash scripts/build-packed-boot.sh artifacts/cm-ab/fw_payload.bin artifacts/cm-pack
python3 scripts/test-coremark-qemu.py artifacts/cm-ab/fw_payload.bin artifacts/cm-ab/coremark-o3.elf logs/cm-qemu --profile o3
```

固定的 QEMU 4.2.1 `virt` 能用于普通 RV64GC 的软件正确性测试，不能运行本次扩展 ELF（在第一条 `sh3add` 上 SIGILL，两个种子的退出码均为 132）。保留此失败；不把它当作板卡的结论。实板另行核对 ELF、Linux 可用扩展和完整输出。

```powershell
# 先依 bring-up.md 将已评审 bit 和 cm-pack/stage.bin 易失启动为 linux-oscheck；
# $capture 是本次启动的实板证据目录，$bridge 为本机核对过的 FPGA 侧串口桥。
./scripts/test-board-coremark-matrix.ps1 -Run artifacts/split5h-impl-a -Capture $capture -Payload artifacts/cm-pack/stage.bin -Release artifacts/cm-ab -Out logs/cm-ab-board -Bridge $bridge
python scripts/review-coremark-matrix.py artifacts/split5h-impl-a $capture artifacts/cm-pack/stage.bin artifacts/cm-ab logs/cm-ab-board
```

### 同一块板、同一次启动的结果

| 配置 | 性能种子中位数（次/秒） | 验证种子中位数 | 性能相对对照 |
|---|---:|---:|---:|
| `-O2` | 216.974650 | 215.683808 | — |
| `-O3` | 223.738673 | 222.758493 | +3.117% |
| `-O3 -march=rv64gc_zba_zbb` | **246.654745** | **244.992956** | **+13.679%** |

每份程序三轮，每轮两套种子，各 12,000 次；所有 CRC 通过。距目标仍差 4.05 倍。[逐次实板记录](coremark-1000-board.json)。

## 第二组实板对照：编译器和链接优化

同一块 VCU118、同一 100 MHz Rocket bitstream。新镜像中保留字节相同的 GCC 13.3 对照 ELF；同一次 Linux 启动按 ABC / BCA / CAB 交错执行九次。每次都是一个上下文、性能与验证种子各 12,000 轮。

| 配置 | 性能种子中位数（次/秒） | 验证中位数 | 相对本次对照 |
|---|---:|---:|---:|
| o3-zb | 246.715599 | 244.992956 | +0.000% |
| g15-zb-lto | 254.231902 | 252.812540 | +3.047% |
| o3-zb-lto-unroll | 251.366807 | 250.579465 | +1.885% |

最快配置的三次性能种子：**254.285775 / 254.215744 / 254.231902** 次/秒，非认证成绩。三次验证种子均通过，所有 18 次计时均超过 10 秒，主机墙钟与客机相符。对同批次对照快 3.047%，还需 3.93 倍才到单核 1,000。参见[完整记录](coremark-1000-compilers-board.json)和[复现命令](performance-first.md#复现实验)。本实验比较组合，不把收益全部归给 GCC 版本或 LTO。

## 硬件候选和预算

第一个对照是单 hart 的 BOOM v3 Medium（两路译码、乱序），板级时钟目标仍为 100 MHz；用 `bash scripts/generate-perf-boom.sh` 独立生成。即使生成 RTL 也不是实板成绩。优先比较同一通用 `rv64gc` ELF，再做专门优化；不假设该核也支持 Rocket 的 Zba/Zbb。

达到 1,000 的频率–效率预算举例：100 MHz 需要 10.00 次/秒/MHz；150 MHz 需要 6.67；200 MHz 需要 5.00。它们是算术门槛，不是 FPGA 时序或性能预测。[性能主线](performance-first.md)先比较双路与三路乱序单核的每轮周期，再用实际通过布线的时钟决定取舍。[四核、150 MHz、九级](quad-nine.md)保留为独立对照。无论整机有几个核，单核验收始终只用一个物理 hart。
