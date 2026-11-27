# 四路 BOOM 开始布线（北京时间 2026-11-28 00:01）

这是 [11 月 27 日 18:00 截止报告](status-2026-11-27-1800.md)之后的进展。单 hart，四路译码/提交；175 MHz 是请求频率。本版尚未上板：性能种子 0/3 次、验证种子 0/3 次完成，无实测分数。

同一 Vivado 2024.2 构建完成布局后物理优化和功耗优化，写出完整 `post_place.dcp`，随后进入 `route_design -directive Explore`。布局后物理优化给出的 WNS 是 **−8.258 ns**，不是布线后时序，不能据此报告工作频率。

| 同一构建的证据 | 值 |
| --- | --- |
| [实现输入清单](perf-mega175-implementation-inputs.json) SHA-256 | `b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959` |
| `post_opt.dcp` SHA-256 | `98e6d4f6c545a4f0f07c0618dad28e5de23dc9330ff98bc2cc81d2038a54db5f` |
| `post_place.dcp` 字节数 / SHA-256 | 464,636,777 / `e5be273c5dae935df5b0e114a94b7c55ee1825bd7dedad2f2ec63ae4fdf3858e` |

从两份检查点的 `dcp.xml` 核对顶层、器件、工具版本后，逐项读取四份 XDC。主、板级、early、late XDC 的原始内容分别相同，命令数分别为 552、16、1,729、66。这里只核对约束文件：命令相同不保证约束命中相同的端点，也不证明 CDC、时序或 DRC 通过。

下一次判断以本次布线后的慢路径、setup/hold/脉宽、约束覆盖、CDC 和 DRC 等报告为准。板卡接回且签核通过后，才易失配置并记录 Linux CoreMark 六次实测。

后续：[初次布线的北向长线拥塞和全部 26 个紧约束引脚](perf-mega175-initial-congestion.md)。
