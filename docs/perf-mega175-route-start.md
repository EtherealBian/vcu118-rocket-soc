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

## 03:44：布线完成，175 MHz 的建立时序仍未达到

北京时间 2026-11-28 03:44，同一次 Vivado 运行写完 `routed_before_physopt.dcp`。路由器完成了网络连接；它同时明确报告 `Route 35-39`（时序未达）。下表是**独立执行布线后物理优化之前**的全设计工具估计，不是最终静态时序签核，也不是板测时钟。

| 布线过程中 Vivado 报告的时点 | 最差建立余量 WNS | 总负建立余量 TNS | 最差保持余量 WHS | 总负保持余量 THS |
|---|---:|---:|---:|---:|
| Phase 15，路由器更新时序 | −9.283 ns | −753,824.949 ns | +0.010 ns | 0.000 ns |
| Phase 16，路由器内部物理优化结束；与检查点内 `route_design` 行相同 | **−9.237 ns** | **−747,889.862 ns** | **+0.010 ns** | **0.000 ns** |

**下一步先查整数发射槽和分支更新。** 在 Phase 16.2，工具对 CPU 时钟组的三根具名网络尝试优化：槽 8 的 `p2`、核心的 `brinfos_0_valid`、槽 12 的 `slot_uop_prs2_reg[4]_20`。三次都报告该组 WNS 未改善。封存 RTL 中，`p2` 参与槽就绪判断，`brinfos_0_valid` 参与分支解决及误判逻辑；第三项是实现后的网名。这三项不是三条已定位的最差路径，不能据此断言慢在仲裁还是广播。待同一构建给出最终端点及逐段延时，再决定是否试[整数发射选择器](perf-mega175-issue.md)或[分支掩码候选](perf-mega175-branch-mask.md)。

[去敏证据与 SHA-256](perf-mega175-routed-checkpoint.json)：布线检查点 537,529,878 字节；其内 `Design State` 为 `Routed`，前五条阶段记录与布局检查点一致，新增 `route_design -directive Explore`。四份 XDC 在布局与布线检查点间逐字节不变，这不证明覆盖或例外正确。Phase 8 的失败、未布、部分布线网络和节点重叠计数均为 0，Phase 9 网络连接核验通过。日志前缀的指纹取到 Vivado 确认**完整写出检查点**的行末。

该运行随后进入单独的 `phys_opt_design -directive Explore`。发布此截点时尚无最终 `post_route.dcp`、同版完整 STA/CDC/DRC 签核及可上板 bitstream。没有配置 VCU118；BOOM 的性能和验证种子仍各 **0/3 次完成**，没有可登记的分数。
