# 把八个 MSHR 的 ready 接回 D-cache 和 LSU 后，哪里有希望缩短？

目标是[旧版布线](perf-mega175-routed-recovery.md)中分支撤销经过缓存到整数发射队列的慢路径。下面只比较恢复版组合逻辑；**没有改动正在综合的物理输入，没有新的布线时序或实板成绩。**

## 从两路 ready 看：优化了选择信号，却没有优化整体最深路径

从物理包的 `BoomMSHRFile`、八个 `BoomMSHR` 及其 RPQ 逐项核对接线。RPQ 的入队空间由两个寄存指针是否相等及 `maybe_full` 决定，不依赖本拍出队或队首的分支撤销。D-cache 的分支掩码仍可通过两路 S2 请求有效位改变 MSHR 仲裁。不能仅凭时序报告里含 `rpq` 的网络名解释因果。

保留原优先级、主/次请求语义和同拍握手。第一种改法按请求通道预计算地址、标签/索引命中；第二种还区分新请求的命令类别，各个子 MSHR 分别给出开放条件及要求更高权限时的条件。没有新增寄存器，也没有把 lane 0 空闲时的 ready 强行置零。在 490 个自由二态输入上，两个 ready 对所有输入组合与封存基准等价；两个派生父/子模块组合也都通过了完整父模块的 Verilator lint。

| XCUP 未布局结构，斜线左右为 ready 0 / 1 | 基准 | 按通道 | 按通道及命令类别 |
|---|---:|---:|---:|
| 任意输入最长原语层数 | 11 / 12 | 12 / 11 | 12 / 9 |
| 通道 1 的 valid 到 ready | 7 / 8 | 10 / 9 | 1 / 2 |
| RPQ 空间到 ready | 7 / 8 | 11 / 10 | 11 / 8 |

两个输出的整体最深值始终是 12。误将 lane 0 的主请求 ready 用本路 valid 门控、漏掉通道 1 的命令 6、把第 7 项开放条件接到第 6 项，都被 SAT 找到反例。[局部结果](perf-mega175-mshr-ready.json)。

## 看消费者：接到真正的 LSU miss，单项改善不保证组合改善

上轮实验把 [MSHR ready 当作自由输入](perf-mega175-dcache-response.md)。这次将两路请求的 valid、命令、地址、probe 限定、选 way 的表达式、ready 和次级 miss 都按物理包中的实际实例连起来。每个子项展开到 MSHR 状态、地址、way 与 RPQ 读写指针及满位；LSU 的五张队列表沿用原顺序和索引。共 1,891 个不加可达性假设的输入位，包含两路 S2 hit 等尚未展开的边界。检查输出为 D-cache 两路响应 valid 和 LSU 的 `io_core_ld_miss`；不包括下游整数发射器和真实布线。三个候选的三个输出都通过同拍二态等价检查。

| 映射后原语层数，终点均为 LSU miss | 基准 | 只改 MSHR 类别选择 | 只拆 D-cache 响应和 S2 | 两者同时改 |
|---|---:|---:|---:|---:|
| 任意输入最长 | 29 | 28 | **26** | 28 |
| 分支误判掩码 | 27 | 23 | 26 | **22** |
| 通道 1 地址 | 29 | 26 | 25 | **24** |
| RPQ 指针/满位 | 23 | 24 | **21** | 26 |
| LUT / MUXF 数 | 2,419 / 700 | 2,197 / 484 | 2,413 / 410 | 2,509 / 657 |

错接第 7 项的**开放**条件会改变独立 ready，却不改变这三个消费者输出：MSHR miss 生成本地响应时只接受命令 1 或 17，两者读取的是要求权限的条件。这是局部观测盲区，不是允许合入的理由。改错第 7 项的**权限**条件或交换两路 ready，则三个输出组成的向量均有反例。[组合实验与反例](perf-mega175-mshr-connected.json)。

**决策：** 后续物理比较分别保留“只改 MSHR”和“只拆响应”，以未改版为基准；不因为组合方案的分支路径最浅就采用它。早先一旦把 ready 当作自由输入，甚至会得到拆分响应使 LSU 最深路径变长的相反结论。以上是不同组合网表的原语图深度，不是关键路径延迟；尤其不能证明跨 SLR 的网络或发射槽已经变快。

复现需要封存恢复版物理包、固定 Yosys 和可执行的 `berkeley-abc`。为两次实验分别指定尚不存在的私有输出目录。不公开派生的生成 RTL、网表或日志。

```sh
python3 -B scripts/test-mega-mshr-ready.py "$PHYSICAL" "$YOSYS" "$READY_OUT"
python3 -B scripts/test-mega-mshr-connected.py "$PHYSICAL" "$YOSYS" "$CONNECTED_OUT"
diff -u docs/perf-mega175-mshr-ready.json "$READY_OUT/result.json"
diff -u docs/perf-mega175-mshr-connected.json "$CONNECTED_OUT/result.json"
```

## 物理比较的输入

为基准、只改 MSHR、只拆响应三种情况，已生成相同的单时钟寄存边界并统一物理实验内部的实例名，以免把形式验证所需的不同命名带进布局。独立从 Yosys 展开后的边界模块检查：三者均有 1,891 位由上升沿锁存的输入，逐总线对应组合逻辑输入；三个输出经同一时钟捕获，不另加其他寄存延迟。这些寄存器只属于局部实验，不是新增的 CPU 流水级。已准备 5.714 ns 的 VCU118 器件对照，但上述结果中**没有**此对照的布局布线数据。主整机实现优先。

```sh
python3 -B scripts/prepare-mega-mshr-ooc.py "$CONNECTED_OUT" "$PREPARED"
# Vivado 2024.2；各 CASE 单独运行，使用互不相同的新目录；不并行争用主实现资源。
for CASE in stock class_local split_rsp; do
  vivado -mode batch -source scripts/implement-mega-mshr-ooc.tcl \
    -tclargs "$PREPARED" "$OUT_BASE/$CASE" "$CASE" || exit 1
done
```

## 同一个寄存边界进 Vivado 之后

三案都在 VCU118 器件、5.714 ns 约束下分别完成综合和 `opt_design`，保存了可继续布局的 DCP。[去敏记录](perf-mega175-mshr-preplace.json)按案核对了三个独立捕获端、四组到 LSU miss 的启动端、每条报告的查询与实际引脚。下表是 **Vivado 按估算时序选中的路径**的逻辑级数，并非所有路径的最大结构深度；CLB LUT 为布局前资源估计。

| 方案 | 响应 0 / 响应 1 / LSU miss 的级数 | 分支掩码 / 通道 1 地址 / MSHR 状态 / RPQ 至 miss 的级数 | CLB LUT / 寄存器 |
|---|---:|---:|---:|
| 不改写 | 14 / 15 / 19 | 17 / 19 / 19 / 14 | 1384 / 1838 |
| 只改 MSHR 命令分类 | 11 / 12 / 16 | 14 / 16 / 16 / 14 | 1462 / 1838 |
| 只拆两路 D-cache 响应 | 13 / 13 / 20 | 17 / 20 / 20 / 15 | 1460 / 1840 |

以基准为对照，改命令分类后，三个输出的所选路径各少 3 级；寄存器数不变，局部 CLB LUT 由 1,384 增至 1,462（多 78 个）。拆响应后的 miss 路径反而从 19 级变为 20 级。只看两个候选，Vivado 选出的 miss 路径是命令分类 16 级、拆响应 20 级；上面的 Yosys 最长结构路径却分别是 28 和 26 级。两者的映射和选路准则不同。优先对命令分类和基准做同约束布线，再测拆响应；不能把级数差当作时序收益。三个优化后检查点均未用于正在综合的整机。一次独立的基准布局在触发主机内存保护线时提前停止，未得到任何布线余量；因此不发布估算延时或跑分。

复核命令（Windows、Vivado 2024.2；占位符均用绝对路径）：每案从单独的 `RUNS/CASE-driver` 工作目录启动，`RUNS/CASE` 尚不存在。这里的 `CONNECTED` 是已通过独立等价检查的实验输出。

```text
vivado -mode batch -log vivado.log -nojournal -source SCRIPT_DIR/implement-mega-mshr-ooc.tcl -tclargs PREPARED RUNS/CASE CASE opt-only
python -B SCRIPT_DIR/review-mega-mshr-ooc.py CONNECTED PREPARED RUNS stock class_local split_rsp --opt-only
```
