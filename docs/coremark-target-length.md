# 单核 CoreMark 验收：固定迭代数

在已完成时序、CDC、DRC、约束审查并登记的硬件上，运行 `test-board-coremark-matrix.ps1 -Experiment target`。默认保持每个种子 12,000 轮；如预期单核超过 1,200 次/秒，可在**开始采集前**选择 `-Iterations 24000`。对应离线命令使用 `review-coremark-matrix.py --experiment target --iterations 24000`，其余参数与 12,000 轮相同。不混用两种长度，也不把短运行外推为有效成绩。

三对运行均使用同一次易失启动、同一严格对齐 RV64GC Linux ELF、单 hart、单上下文和总计 2,000 字节。每个种子都必须运行至少 10 秒、与主机墙钟一致，并通过种子、三个内核和最终 CRC；三次性能种子必须**各自**达到 1,000 次/秒。24,000 轮并不豁免用时限制：例如快于 2,400 次/秒时仍会被拒绝。任何模型或主机 CRC 结果均不能替代实板的六次运行。

| 每个种子迭代数 | 性能 final CRC | 验证 final CRC |
| ---: | --- | --- |
| 12,000 | `0xd340` | `0xbc68` |
| 24,000 | `0x4983` | `0xeb93` |

生成方法：`python3 scripts/derive-target-length-crcs.py <sources.sha256 中固定的 CoreMark 源码压缩包>`。原版 POSIX 源码以 GCC `-O0` 和 `-O2` 独立编译；[结果](coremark-target-length-crcs.json)仅包含 CRC。再以 `test-coremark-qemu.py <解包固件> <严格对齐的 ELF> <新目录> --profile g15-gc-lto-ooo-strict --target-crc-only` 检查 RISC-V Linux ELF 的 24,000 轮 [交叉验证记录](coremark-target-length-guest.json)。这次 QEMU 两个种子均短于 10 秒，**不是有效跑分**。

[12,000 轮的 Rocket 实板对照](coremark-target-rocket-control.json)是板上测量；这里增加的 24,000 轮流程本身没有产生新的 BOOM 或 Rocket 板分。
