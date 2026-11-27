# 相邻复制到加载：四路 BOOM 的重命名单元实验

原版的[指针逐次跟踪](perf-strict-reversal.md)显示，下一次 `ld` 常在 `mv` 执行后一拍才发出地址。这个实验改变的是**加载等待哪一个物理寄存器**，不删除复制指令，也不增加流水级。原版和候选在同一测试台上，**22 个定向用例通过，3 个故意写错的版本均被指定用例检出**。[模块指纹与各项判定](perf-copy-load-rename.json)。尚未测到整核周期减少或 FPGA 分数变化。

- 当同一译码沿的相邻两路是 `add rd,x0,rs2`（包括展开后的 `c.mv`）和以 `rd` 为基址的普通整数加载时，加载查 `rs2` 的物理映射。不按 PC 或指定寄存器号匹配；排除零寄存器、自复制、异常、SFB 标记、浮点和原子访问。查表、同包旁路和停顿保持使用同一个有效源。向下游输出的原始逻辑基址仍为 `rd`，复制仍分配新物理目的，加载也仍按原指令分配并保留旧映射。
- 同一份真实 RVC 展开与译码结果送进两套 `RenameStage`，每套都实例化真实的映射表、空闲表、忙表。测试先给源分配非零的物理寄存器，再看加载实际拿到的是原生产者还是复制的目的，同时看就绪位。三对相邻槽均测试；包括原生产者尚未唤醒、同包更老的生产者、加载覆盖原源、复制先派发而加载留下、停顿、取消、跨包及负例。其余有效槽输出在相同输入下逐项对照。
- 三个反例各自只改一处：禁掉第 1 路替换、放过带 SFB 标记的复制、让查表仍用旧基址。三个变体必须以预期的源不匹配退出；只编译成功不算通过。这是定向仿真，不是所有程序、异常和恢复序列的形式证明。

已单独封存[候选整核功能模型的输入](perf-copy-load-model.json)：原版的 549 个有序 HDL 文件中仅 `rtl/RenameStage.sv` 不同；完整清单 554 项，源目录重新验签未变。**未修改在跑的 175 MHz 原版物理工程，未启动候选实现。** 下一步是相同快照、相同 ELF 的两种种子整核 A/B：退休 PC 顺序、最终寄存器和内存必须保持，周期允许改变，分别比较四轮边界。只有这些检查通过才讨论收益。

```sh
python3 scripts/test-copy-load-rename.py "$STOCK_MODEL_KIT/rtl" "$FRESH_PAIRED"  # Icarus Verilog + vvp
python3 scripts/derive-copy-load-model.py "$STOCK_MODEL_KIT" "$FRESH_PAIRED" "$FRESH_FUNCTIONAL_KIT"
```

整核比较入口（Linux，Verilator 与原归档一致；不连接硬件）：

```bash
inputs=("$STOCK_MODEL_KIT" "$STOCK_OBJ" "$STOCK_REPLAY" "$FRESH_FUNCTIONAL_KIT" "$GUEST_PAIR" "$STRICT_ELF" "$VERILATOR_PREFIX")
python3 scripts/test-copy-load-fullcore.py preflight "${inputs[@]}"
# 以下两步在主机资源允许时执行；输出必须是私有候选 kit 的全新同级目录。
python3 scripts/test-copy-load-fullcore.py run "${inputs[@]}" --out "$FRESH_RUN"
python3 scripts/test-copy-load-fullcore.py review "${inputs[@]}" --out "$FRESH_RUN"
```

`preflight` 已在原版两份真实归档上作零差对照：两种种子的四轮逐项均为零。这是比较工具的对照，不是候选的结果。`run` 从封存源码重新翻译、单线程编译并独立链接，再记录原始 PC、UART 和事件。`review` 从原始文件重算，与已存摘要逐项核对，不重编模型。周期差按“候选减原版”保留正负号，不能把退步算成加速。

## 译码同拍和派发同拍，是同一批指令吗？

在同一份严格对齐 ELF 的原版四轮用户态 RTL 窗口中，逐个退休票据回查 `c.mv x8,x14` 和下一条 `c.ld x14,0(x8)` 的真实译码沿。每种种子有 23,664 对；另有 816 次从循环入口直接执行加载，没有前驱复制，不进分母。下表的“同拍”均要求占相邻两路。[计数、各槽位命中数与输入指纹](perf-strict-copy-decode.json)。

| 原版出现的情况（对） | 性能种子 | 验证种子 |
|---|---:|---:|
| 同拍译码、同拍派发 | 16,620 | 16,735 |
| 同拍译码、分开派发 | 1,213 | 1,107 |
| 未同拍相邻译码、同拍相邻派发 | 0 | 0 |
| 两处均未同拍相邻 | 5,831 | 5,822 |
| **满足全部旁路条件** | **17,833（75.36%）** | **17,842（75.40%）** |

只看派发会漏掉第二行。当前候选必须在复制已派发、加载仍停顿时保留所选源；这个单元测试场景在两个原版窗口中都实际出现了。覆盖率只针对这个循环，不能换算为少用多少周期。收益仍要看候选整核四轮周期差，以及布线后的时序是否允许采用该修改。

复核时，探针逐拍对照真实重命名有效位，用派发沿和 ROB 槽连接原始译码沿与退休指令。审核器核对锁定 ELF 的压缩编码、展开指令、寄存器及控制字段；有序退休 PC、票据、重定向、UART 和退出事件须保持原版指纹。要复算表格：

```bash
inputs=("$STOCK_MODEL_KIT" "$STOCK_OBJ" "$GUEST_PAIR" "$PREVIOUS_REDIRECT_CAPTURE" "$FRESH_DECODE_RUN")
python3 scripts/test-strict-copy-decode.py "${inputs[@]}" "$VERILATOR_INCLUDE"
python3 scripts/review-strict-copy-decode.py "${inputs[@]}" "$STRICT_ELF" --expect docs/perf-strict-copy-decode.json
```

## 缩短判定条件，是否值得替换当前候选？

**暂不替换。** 如果只观察旁路是否命中和加载选中的源寄存器，短版看起来少用近一半原语；把译码器仍须为其他逻辑提供的字段一起保留，结论反转。两组用同一版 Yosys/ABC、同一 `xcup` 映射流程，各自比较相同输入和输出。表中数量是组合原语个数，深度是三个有效源输出中最长的原语链；二者都不是布局后延迟或整核资源。

| 保留的输出 | 版本 | LUT | 宽 MUX | 有效源最长原语链 |
|---|---|---:|---:|---:|
| 三个命中位及三个 6 位源索引 | 完整条件 | 864 | 213 | 13 |
| 同上 | 短条件 | 436 | 109 | 12 |
| 上述输出 + 每路 15 个译码字段（共 272 位） | 完整条件 | 1,036 | 184 | 11 |
| 同上 | 短条件 | 1,125 | 227 | 11 |

短版只改三处命中判定，保留异常、SFB、寄存器和相邻有效指令检查。四个真实译码器的输入和四路握手分别放开，不用 CoreMark 轨迹限制输入：两版 **21 位**命中与有效源输出的二值组合等价证明通过，三对相邻路各有命中和不命中的可达解。三个有意破坏的版本均得到预期方向的反例；短版在原来的真实重命名流水线上也通过同一套 **22 个定向用例**。四份映射后网表各自对映射前 RTL 再做等价检查，通过。详见[每路深度、原语分类、测试与模块指纹](perf-copy-load-guard.json)。

保留全部字段时短版多用 89 个 LUT、43 个宽 MUX，最长有效源链没有缩短，第 3 路还由 10 层变为 11 层。因此**整核双种子 A/B 仍使用已封存的完整条件候选**，不因孤立电路变小而换版。这组对照保留的是译码输出，不包含真实映射表、其他负载的扇出和物理连线；不能据此认定两种写法的上板频率或 CoreMark 分数。

```sh
python3 scripts/prove-copy-load-guard.py "$STOCK_MODEL_KIT" "$FULL_GUARD_MODEL_KIT" "$FRESH_GUARD_CHECK" "$(command -v yosys)"
# 需要归档版本的 Yosys 和 berkeley-abc，以及 Icarus Verilog/vvp。
# 私有结果保存在新目录内；只有汇总应与公开记录一致。
diff -u docs/perf-copy-load-guard.json "$FRESH_GUARD_CHECK/result.json"
```
