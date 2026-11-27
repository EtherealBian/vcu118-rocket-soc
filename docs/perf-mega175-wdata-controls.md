# 四个 WDATA 紧约束引脚，是四条独立的数据通路吗？

**先查写数据选择器的两侧，不先改异步 FIFO 的选槽使能。** 四路设计[初布线的 26 个引脚](perf-mega175-initial-congestion.md)中，MIG 写数据通道的四个引脚都是 `mem_{1,3,6,7}_data_reg[5]/D`：同一个数据位，四个存储槽，不是四个地址位或四个 `CE`。在两份已经布线的 100 MHz 对照里，同名四个引脚确实由**同一颗 LUT3 的同一输出**驱动，另外四个槽也接这个输出。四路自身的最终布线仍须单独检查。

## 逐位追线，而非从名字猜扇出

两个对照与本次四路构建的 MIG 外壳、TileLink 转 AXI、单项 W 队列、异步源桥及 W 源队列这五份 RTL 均逐字节相同。`Queue1_AXI4BundleW` 有数据时返回先前存入的字；空时直接旁路当前输入。在两份历史整机 timesim 网表中，64 位各自用一颗 `LUT3`；逐颗检查初值的八个真值，确认 `I1 ? I0 : I2`。SDF 显示 `I0` 来自该位的存储寄存器，`I1` 来自 `full_reg/Q`，`I2` 来自上游 TileLink A 缓冲 RAM；每个输出恰好驱动 8 个 FDRE 的 `D`，合计 512 个。网表也独立核对这 512 个数据引脚按位共享，而不是误取 `CE` 或 `Q`。

| 匹配的物理导线（ps） | 单核 Rocket，100 MHz | 单核双路 BOOM，100 MHz，未上板 |
|---|---:|---:|
| bit 5：存储寄存器 → 选择器 | 178.0 | 154.0 |
| bit 5：`full` → 选择器 | 244.1 | 482.8 |
| bit 5：上游 RAM 旁路 → 选择器 | 221.2 | 1,339.9 |
| bit 5：选择器 → 八槽 `D`（最小至最大） | 308.8–497.0 | 495.5–870.4 |
| 全部 64 位中，旁路输入线比**同一位最长输出线**更长的位数 | **4/64** | **63/64** |

数值为同一份 SDF 每条 `INTERCONNECT` 的上升、下降两个 MAX 的较大者，单位为 ps。没有把不同路径或不同沿相加，也没有计入单元延迟、时钟和余量。按每位八条输出线的最大值比较，历史 Rocket 还有 57 位、双路 BOOM 还有 23 位比 bit 5 更长。因此，四路报告中 bit 5 出现四次，并不能证明只有该位有问题，更不能证明换成复制选择器或加流水级会改善时序。

**下一步如何区分。** 若本次最终慢路径确实到达这些 `D`，区分经过上游 RAM 旁路、`full` 选择线还是八槽中的某条出线，再比较其实际逻辑/布线延迟；若最终慢路径不经过这里，就按实际路径排序。该判断不改变正在运行的 RTL、物理约束或上板条件。

[去敏数值及构建指纹](perf-mega175-wdata-controls.json)。复算使用四路原始引脚表及[两份归档的同构建网表、SDF 和 bitstream](perf-aw-routed-controls.json)，不运行 Vivado，不连接板卡：

```sh
python3 scripts/review-wdata-pin-controls.py "$FOUR_KIT" "$FOUR_RUN/tight_setup_hold_pins.txt" \
  "$ROCKET_RUN" "$ROCKET_KIT" "$MEDIUM_RUN" "$MEDIUM_KIT" > wdata.json
cmp wdata.json docs/perf-mega175-wdata-controls.json
```
