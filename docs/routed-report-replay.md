# 最终布线复核：工程报告和重新打开的 DCP 是否相符？

`scripts/inspect-mega-postroute.py` 先核对四路 BOOM 的输入封存、原实现日志、最终 DCP 和 CPU 端点。在第一次只读打开该 DCP 时，用原实现的命令重出下列六份报告，然后才查询 waiver 或运行独立的 DDR Gray 偏斜实验。此流程不改约束；主实现未退出、报告不全时不要启动。

| 对照 | 必须吻合的内容 |
| --- | --- |
| 布线状态 | 报告中的全部状态计数，包括需要布线的网、已完全布线的网及布线错误；这份报告没有命令头，不能独立证明来源。 |
| 全局时序 | timer settings 和分析角；setup、hold、pulse width 各自的最差余量、总负余量、失败和分析端点数。并不比较所有详细路径；CPU 的 40 条 setup 和 40 条 hold 另行核对。 |
| 约束覆盖 | `check_timing -verbose` 全文，包括实际缺少延时约束的 I/O 名称、豁免和其他检查。 |
| CDC、DRC、时钟 | 默认 CDC 的每条跨域记录；默认 DRC 报告中实际列出的规则、严重性和对象；时钟源、周期、波形等完整报告正文。被工具截断的对象名单不代表已逐项核验。 |

两份报告各自的命令必须指向实际文件，工具版本、设计、器件和实现状态也要一致（无报告头的布线状态除外）。`replay.json` 在本地保存 DCP、原始文件和被比较内容的 SHA-256；逐项记下缺失、解析错误或不匹配。若正文顺序变化，保守地标为不匹配，保留两份原文查明原因。**两边同样时序违例也会匹配**，并不批准上板。方法学、clock interaction、单独的 pulse width 明细、利用率以及约束例外仍要审查；本检查不能替代工程签核。

**离线核验（非本轮四路结果）。** 对历史 Rocket 实现中两次独立打印的时钟和 DRC 报告，两个原始文件对均不同、比较内容均一致。再将该 Rocket 的报告与另一份历史 BOOM 实现对照：时钟和 I/O 覆盖内容相同，而布线状态、全局时序、CDC、DRC 均不同。故不能仅凭同板、同顶层、相同 I/O 和时钟判定是同一实现。这里没有重新运行历史实现，也没有任何新的实板成绩。

## 哪些时钟方向真的检查了建立时间？

四路 BOOM 当前的 post-opt 检查点有一条异步时钟组声明，把 CPU、DDR4 用户时钟和 JTCK 分为三组。**这只确定了约束的写法，不确定布线后的端点、CDC 严重性或同步器是否可靠。** 新的[逐方向对照](perf-mega175-clock-scope.json)把本次声明与两份历史样本分开，不为四路 BOOM 填入历史数字。

下表是两个 **100 MHz 历史布线样本**。每份样本均比对同一次实现的时钟表、clock interaction、全局时序和默认 CDC 明细，并独立锁定输入哈希。端点数与 CDC 结构报告行数不是同一个量。

| 方向 | Interaction 端点 / 默认 CDC 行数（两版相同） | 其中 Critical 行：Rocket / 旧 BOOM |
| --- | ---: | ---: |
| JTCK → CPU | 61 / 51 | 1 / 2 |
| CPU → JTCK | 49 / 39 | 1 / 1 |
| CPU → DDR4 UI | 188 / 178 | 1 / 1 |
| DDR4 UI → CPU | 118 / 110 | 2 / 2 |
| JTCK ↔ DDR4 UI | 两方向均没有对应报告条目 | 不能据此判为安全 |

前四个方向在 `User Ignored Path Table` 中出现，没有普通 setup 数值，CDC 行的例外均为异步时钟组。相反，两个历史样本中的 `mmcm_clkout0 → mmcm_clkout5` 虽被标为 `Ignored`，仍有最大数据延时检查（10 个 setup 端点）；`sys_clock → sys_clock` 标为 `Clean / Partial False Path`，既有 23 个 setup 端点，也出现于用户忽略表。只按 `Clean` 或 `Ignored` 字样计数会漏审。还有一条输入端口至 `sys_clock` 的 CDC 记录，interaction 无对应行，已单列保留。

```sh
# 本机归档：产生历史对照与本次 post-opt 的声明；不打开 Vivado。
python3 scripts/review-clock-domain-coverage.py controls "$ARTIFACTS"
# 只在本次最终 DCP 和只读重放完成后：从同一构建重算，不沿用上表。
python3 scripts/review-clock-domain-coverage.py routed "$RUN" "$BOARD_KIT" "$IMPLEMENTATION_LOG" "$POSTROUTE_DIAGNOSTICS"
```

后者核对四路输入与最终 DCP，重新校验六份重放报告及其哈希。原实现的 clock interaction **没有独立重打**：校验命令来源、列和上述方向的时序/CDC 交叉证据，不宣称所有方向或每个端点均已覆盖。标签、方向或报告格式与预期不符时应审查原件，不增设豁免、不批准上板。
