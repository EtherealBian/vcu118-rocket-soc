# VCU118 性能主线：先做快一个 hart

验收指标只有一个：在 VCU118 上启动 Linux，以一个上下文运行标准 2 kB CoreMark，三次性能种子**每次**达到 1,000 次/秒；另三次验证种子与 CRC 通过。多核并发另报总吞吐。旧版 [100 MHz 单核 Rocket 实板记录](coremark-1000-board.json)中，最佳配置中位数为 246.655 次/秒。继续在同一块板、同一 100 MHz bitstream 上测试，GCC 15.1、`-O3 -flto`、Zba/Zbb 已把中位数提高到 **254.232**。距目标还需 3.93 倍。[新一轮实板记录](coremark-1000-compilers-board.json)与新核的进度分开报告。

| 配置 | 本轮要回答的问题 | 时钟和结果的边界 |
|---|---|---|
| 单核 Rocket，顺序单发射 | 只换编译器、LTO 或循环展开，实板速度会变多少？ | 使用已验证的 100 MHz 系统；同一次 Linux 启动交错测量 |
| 单核 BOOM v3 Medium，双路 | 在不改变 ELF 时，乱序执行能省多少周期？ | 已有 RTL 计数，100 MHz 整机实现尚未经布线签核 |
| **单核 BOOM v3 Large，三路译码/提交，96 项 ROB** | 和双路相比，省下的周期能否抵消更宽设计的频率损失？ | 同一 `-O3` ELF 在 100 MHz 对照 RTL 中的六个窗口均比双路快；已启动独立的 175 MHz 候选生成。175 MHz 不是已实现频率 |
| 四核九级 Rocket | 九级短路径是否正确？多核 Linux 和共享内存是否正确？ | [SMP 与九级验证](quad-nine.md)独立推进，不把总吞吐计为单核成绩 |

## 为什么从三路开始

在[同一 `rv64gc` ELF 的裸机热区](coremark-1000-rtl.json)中，性能种子每轮退休 358,881.75 条指令。单发射 Rocket 用 445,246.5 周期，双路 BOOM 用 223,562 周期。若这个窗口要在 **175 MHz** 达到每秒 1,000 轮，预算是 **175,000 周期/轮**：双路的周期数还须下降 **21.72%**，且平均须退休 **2.051 条/拍**，超过两路提交的理论上限。改进编译器可能减少指令数，所以软件对照也保留。这是 M 模式行为内存窗口的预算，不是 Linux 分数预测。

换成第二份通用 `rv64gc -O3` ELF 后，两颗核在性能种子每轮均退休 344,107.25 条指令。Rocket 用 **439,168.5** 周期，双路 BOOM 用 **226,170.25** 周期；验证种子分别为 441,272 和 228,018.5 周期。[两种子的原始计数及 ELF 身份](coremark-1000-rtl-o3.json)。相对各自 `-O2`，指令少 4.12%，Rocket 周期少 1.37%，双路 BOOM 却多用 1.17%。因此按每轮时间选编译配置，不能只看指令数量或选项等级。

### 双路与三路：同一程序的实际差距

| `-O3`，两次比较均用同一份 ELF | 双路周期/轮 | 三路周期/轮 | 周期降幅 | 双路 → 三路 IPC |
|---|---:|---:|---:|---:|
| 性能种子，三次中位数 | 226,170.25 | **178,976** | 20.87% | 1.521 → 1.923 |
| 验证种子，三次中位数 | 228,018.5 | **179,914.25** | 21.10% | 1.512 → 1.916 |

[逐次周期、退休数和 ELF 哈希](perf-wide-o3.json)。每个窗口四轮；同种子的退休指令数逐次相同，三路在六对窗口中全部领先。三路和双路也有缓存、预测器及发射组织的差别，不能把收益全部归因于多一路提交。以性能种子计，如果三路布线后的工作频率低于双路的 79.13%，这个周期优势就不够。按 175,000 周期/轮筛选，**六个窗口都没有通过**；性能中位差 3,976 周期，验证中位差 4,914.25 周期。均非 Linux 实板成绩。

换成通用 `-O2` 后，严格按 ELF 哈希给双路重跑：性能种子 **223,562 → 177,191.75 周期/轮**（−20.74%，IPC 1.605 → 2.025），验证种子 224,820.25 → 178,005（−20.82%）。[独立的六对采样](perf-wide-o2.json)也全部更快，但仍无一个三路窗口进入预算；较好的 `-O2` 性能中位仍差 **2,191.75 拍**。第一次对照虽有相同裸机载荷，却因 ELF 不同被拒；本表用的是重跑后的配对数据。

选择实现按 `通过时序且经核对的时钟频率 / 每轮周期数` 比较：三路若只用双路周期数的 85%，它的时钟就必须**高于**双路的 85% 才能更快。先用同一二进制比较两套种子，再审查整机时序、CDC、DRC、时钟、管脚及 ROM；过关才通过 JTAG 易失配置，最后以 Linux 板测为准。若新增一个核能提高并发吞吐但降低单核频率，报告两项，不用核数弥补单核差距。

**为什么不固定流水级数？** Celio 等在 [BOOM v2 的物理设计报告（UC Berkeley，2017）](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2017/EECS-2017-157.html)中记录过：换代后，每拍完成的指令数最多下降约 20%，作者将主要损失归因于加载到依赖指令的延迟增加。这不是 VCU118 的测量，但给出了具体的检查点：若为布线多加一级，必须用依赖加载链和同 ELF 热区复测它是否真的省时间。BOOM 团队[公开的另一 FPGA 实现](https://boom-core.org/)是 EC2 F1 上的 FireSim 流程，不能用它或 ASIC 时钟为本板 175 MHz 签核。

## 复现实验

- 三路配置来自锁定的 [BOOM v3 `WithNLargeBooms`](https://github.com/riscv-boom/riscv-boom/blob/d2a64f7ca9fd914d9c686cb23edcd32d3465a02e/src/main/scala/v3/common/config-mixins.scala)：TAGE-L 预测器，整数/访存/浮点发射队列分别最多 3/1/1 路。不是任何三条指令都能同时发射。对比 [SonicBOOM 论文和另外两个开源内核](quad-nine.md#谁做到了什么)时，引用值都不作为本板数据。
- WSL 按 [bring-up](bring-up.md)准备工具。依次运行 `bash scripts/generate-perf-boom.sh`（双路）、`bash scripts/generate-perf-wide.sh control`（三路 100 MHz）；对同一窗口用 `scripts/compare-cpu-window.py` 复核两份模型、ELF、阶段计数及逐轮退休数。不要并行改写同一 Chipyard 生成目录。三路周期有收益，再运行 `bash scripts/generate-perf-wide.sh perf175`；该目标使用独立的类、生成目录、ROM 与时间基准。
- `scripts/check-boom-shape.py` 从 ChipTop 逐层定位唯一 BOOM 核，在生成的 RTL 里数译码单元、检查 ROB 各提交端口、各 bank 的有效位及驱动。100 MHz Large 的[生成结构与 RTL 摘要](perf-large-structure.json)已核对：1 个 hart、3 个译码单元、3 路提交、3 × 32 个有效项。设备树、ROM 字节和板级 PLL 请求亦通过静态检查。它不测持续 IPC，也不认定 BOOM 是九级。
- 编译器实验镜像：`VCU_COREMARK_COMPILERS=1 VCU_COREMARK_AB=1 bash scripts/build-lab-linux.sh "$HOME/.cache/vcu118-build/compiler-test" artifacts/compiler-test`。先打包、验证镜像并启动。已评审的 100 MHz Rocket 上，用 `test-board-coremark-matrix.ps1 -Experiment compilers`（其余参数见[实板步骤](coremark-1000.md)），交错比较 GCC 13.3 的 `-O3 + Zba/Zbb`、GCC 15.1 的 `-O3 + LTO + Zba/Zbb` 与 GCC 13.3 的 `-O3 + LTO + unroll + Zba/Zbb`。每种配置三次、每次两套种子各 12,000 轮；复核 SHA、版本、flags、Linux 报告的 ISA 扩展、CRC 和主机墙钟。固定同一份对照 ELF。编译器和编译选项组合的差值不能归因于其中的某一项。

### 定位瓶颈，而不是猜

`bash scripts/build-cpu-window.sh <新目录> boom-events` 构建独立的 M 模式诊断程序；运行 `scripts/run-cpu-window.sh` 时在五个常规参数后加 `--boom-events`。只接受带匹配配置的 BOOM v3 Medium 模型，读回五个硬件事件选择器。报告分支误预测、间接跳转误预测、ROB 清空、L1 指令/数据缓存 acquire 的事件周期数及每千条退休指令的中位数。它们不能直接相加为停顿，也不提供“分支预测命中率”的分母。带计数器的 ELF 不参与上述同 ELF 架构比较。

双路的两次独立计数器实验已完成：[GCC 13.3 `-O2`](perf-medium-events.json) 与 [`-O3`](perf-medium-events-o3.json)。性能种子的分支误预测事件周期/千条退休指令分别为 1.202 与 1.258；`-O2` 后两个性能窗口的 I$/D$ acquire 均为零。这只描述这些热窗口，不证明扩大缓存没有价值，也不等于误预测率。

175 MHz 的串口链路须两端匹配。[100 MHz 引脚对照](rom-link-100-control.json)已测到首字节 9 个相邻跳变均为 868 拍；误设为 175 MHz（1,519 拍）时按预期拒绝。20 字节错误 CRC 帧停在 ROM，64 字节正确帧经 ROM 交给载荷并收到 `K`。这次测试模拟外部存储器；不能替代板上 UART 或 DDR。现有 100 MHz 诊断程序会重写 UART 分频，旧模拟器也按 100 MHz 接收；不能只替换 PLL、复用旧模拟器或固件，就把输出算作 175 MHz 的验证。Linux 板测仍须检查匹配的时钟设备树、独立的时基和主机墙钟。

**二进制复现说明。** 两个全新目录独立重建默认 `-O2` 窗口后，裸机载荷保持既有的 `2d2525c7…`，两份 ELF 逐字节相同（`ca2072e2…`）。早期 GCC 为入口汇编产生随机的临时对象文件名，导致其名字留在 ELF 符号表中，现已改为固定 `entry.o`。历史对照使用各自封存的原 ELF，不倒改旧哈希。

### 新核的 Linux 软件对照

三路候选报告的 ISA 不含 Zba/Zbb，不能直接部署 Rocket 上得分最高的二进制。用 `VCU_COREMARK_AB=portable bash scripts/build-lab-linux.sh <新构建目录> <新产物目录>` 可构建三份标准 RV64GC 用户程序（GCC 13.3 `-O2` / `-O3`、GCC 15.1 `-O3 -flto`）。新镜像已在 QEMU 单核 Linux 启动并验证 GCC 15.1 版本的两套种子与 CRC；同一模拟器、同一 CPU 型号另测普通 `addi` 正常，`sh1add` 和 `andn` 分别触发非法指令陷阱。[固件、ELF、ISA 与 CRC 记录](portable-linux-qemu.json)不含 QEMU 性能数字，不代替新核板测。

```bash
python3 scripts/test-coremark-qemu.py <产物>/fw_payload.bin <产物>/coremark-g15-gc-lto.elf logs/qemu-portable-new --profile g15-gc-lto
```
