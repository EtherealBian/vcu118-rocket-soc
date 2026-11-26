# 四核、150 MHz、九级 Rocket 对照

[性能主线](performance-first.md)先评估单核三路 BOOM；本文记录独立的四核九级设计及其验证。两者不共用成绩。

目标板为 VCU118。四核运行同一个 RV64GC/Sv39 Linux；性能验收只让一个进程、一个上下文固定在一个 hart 上。150 MHz 意味着每轮总预算 150,000 周期，至少需要 6.667 次/秒/MHz。其余三核的成绩不能相加。另行报告并发吞吐。

## 谁做到了什么？

| 原始出处 | 可借鉴的具体设计 | 不可照搬的结论 |
|---|---|---|
| [VeeR EH1 参考手册](https://chipsalliance.github.io/Cores-VeeR-EH1/html/core-overview.html)、[RTL](https://github.com/chipsalliance/Cores-VeeR-EH1)、[WD 公布值](https://www.westerndigital.com/company/newsroom/press-releases/2018/2018-12-04-western-digital-delivers-new-innovations-to-drive-open-standard-interfaces-and-risc-v-processor-development) | 九级、双发射，观察配对规则、旁路与 load-to-use；厂商报 4.9 CoreMark/MHz | RV32、仅 M 模式，不能替换本工程的 RV64 Linux 核。该数字也低于 6.667。 |
| Zhao 等，[SonicBOOM，CARRV 2020](https://people.eecs.berkeley.edu/~krste/papers/SonicBOOM-CARRV2020.pdf)、[BOOM 源码](https://github.com/riscv-boom/riscv-boom) | RV64 乱序；重做取指、TAGE 分支预测、支持多加载，项目报 6.2 CoreMark/MHz | 6.2 × 150 = 930 只是比例尺，不是这块板的成绩，也不是所有 BOOM 配置的 IPC。 |
| Chen 等，[Xuantie-910，ISCA 2020](https://doi.org/10.1109/ISCA45697.2020.00016)、[论文全文](https://ftp.libre-soc.org/466100a052.pdf)、[openC910](https://github.com/XUANTIE-RV/openc910) | 64 位、三路译码、乱序。论文第 2 页（页码 53）报 7.1 CoreMark/MHz，说明每 MHz 门槛有先例 | 原设计为十二级，有自定义指令和配套编译优化。不可用其成绩替代九级标准软件的实测。 |

## 架构选择

先保留单发射九级核作**时序和正确性对照**，不把它当作单核冲分保证。我们的裸机诊断中，通用 ELF 在 Rocket 与两路 BOOM 上执行相同指令，性能种子每轮从 445,246.5 降到 223,562 周期，IPC 从 0.806 到 1.605；这组数据来自 RTL，不是 Linux 的 CoreMark 分数。[模型与输入身份](coremark-1000-rtl.json)。按该 ELF 每轮约 358,882 条指令估算，150,000 周期至少要持续退休 2.39 条/周期。双发射的理论峰值都不够。主攻方向是用同一 ELF 比较三/四宽取指、译码及提交；允许重叠独立的加载，记录分支失败、加载停顿、每轮指令数。若更换编译器或指令集，固定并公开新的二进制并从头复测。宽发射对照未证明九级，不能把一个实现的深度与另一实现的分数拼接。

## 九级到底怎么数

短路径：普通整数指令，I$、ITLB 命中，取指队列没有积压，不停顿、不重放。顺序为 **F0 发取指 → F1 地址翻译/预测 → F2 接收 I$ 结果 → A 对齐/压缩指令展开 → D 静态译码 → I 读寄存器/冒险/发射 → X 执行 → M 访存/分支校正 → W 写回/退休**。前端原本为 flow-through 的 fetch queue 改为不可旁路；主核在对齐后、静态译码后各有一组带 valid、反压和重定向清空的寄存器。队列深度 5 不是五级，访存 miss 的等待周期也不是流水级。这是短路径口径。对每个 hart 分别核验同一 PC 在九个相邻时钟上的有效位及写回退休，另查 RVC、异常返回和错误路径；不能把有停顿的所有指令都说成九拍。

## 已验证与未验证

- 已上板：100 MHz 旧单核 Linux，第一轮编译对照最快配置的三次性能种子为 **246.654745 / 246.720671 / 246.654745**。[物理测量与 CRC](coremark-1000-board.json)。第二轮的 GCC 15.1 + LTO 中位数为 **254.232**，仍是同一个旧核，详见[逐次记录](coremark-1000-compilers-board.json)。
- 已生成：100 MHz 四核参考 RTL。逐层查到四个独立核实例；生成的设备树检查四个 hart、每 hart 的 CLINT/PLIC、中断与共享 L2。不是上板验证。
- 已通过软件仿真：同一 OpenSBI/Linux 镜像在 QEMU virt `-smp 4` 上有 0–3 四个在线 CPU，四个固定线程做 4096 次共享交接；`-smp 1` 反例按预期拒绝。[软件验收摘要](quad-linux-qemu.json)。QEMU 不使用本板的 UART ROM，也不证明 Rocket 的一致性或频率。
- 九级候选已生成：首版因 `vec` 未驱动而失败；修复后，RTL 中有四个独立 hart，712 字节 UART ROM 和 5,704 字节 DTB 与生成的 ROM 内容一致。150 MHz 是设计请求，未做整机布线签核。
- 串口引脚仿真：首版探针能走完 ROM 交接，却没有四核成功回执；反汇编查到直接模式 `mtvec` 地址未按 4 字节对齐。把陷阱入口移入单独对齐节，并在写 CSR 后读回校验。同一 RTL 和行为存储器上，修复后的 548 字节帧收到了 `QUAD_ROM_PASS`：四核到齐，64 次共享交接求和 2,080，四次陷入返回。首字节测到 1,302 拍/bit，错钟和 CRC 负控均通过。
- 四核九级的[逐拍记录及引脚正负控](quad-nine-rom-link.json)已通过独立复核：每个 hart 退休 256 条对齐整数指令，其中各有 **251 条**在同一 PC、九个连续时钟上逐级出现。首次分析拒绝了 16 条半字地址记录；补录真实发射取消信号后，证实是 8 次译码、8 次对应的发射前取消，下一拍均无有效 X，亦无这类地址退休。两次使用同一封存 RTL 与探针。以上只证明该热循环和裸机探针；尚未在该硬件上验收 Linux、物理 150 MHz 或多核吞吐。

重建（WSL，前置工具和锁定的源码见 [bring-up](bring-up.md)，两个生成器顺序运行，不共享输出）：

```bash
bash scripts/generate-quad-rocket.sh
bash scripts/generate-quad150-nine.sh
kit="$HOME/.cache/vcu118-build/quad-nine-kit"; obj="$HOME/.cache/vcu118-build/quad-nine-obj"
bash scripts/build-clocked-rom-model.sh quad150 "$kit" "$obj"
bash scripts/test-clocked-rom-link.sh "$kit" "$obj" 150 quad logs/quad-nine-new
python3 scripts/review-clocked-rom-link.py logs/quad-nine-new "$kit" 150 quad
bash scripts/build-quad-linux.sh "$HOME/.cache/vcu118-build/quad-new" artifacts/quad-new
python3 scripts/test-quad-linux.py artifacts/quad-new logs/quad-new-qemu
```

正式计时：使用未改算法、标准 POSIX 计时、2,000 B、每套种子每次 ≥10 s，核验实际墙钟、输入镜像/ELF 与 CRC。至少三次有效性能种子**每次** ≥1,000；另做三次验证种子。四核镜像需要在运行前固定单 CPU 亲和性，同时记录其他 hart 的负载。
