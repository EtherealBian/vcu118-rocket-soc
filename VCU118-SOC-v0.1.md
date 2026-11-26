# VCU118 上的 Linux RISC-V SoC：初始需求 v0.1

本文是初始需求快照，不是测试结果；当前交付与证据见 README.md。假设目标是做整颗可扩展 SoC，允许复用开源 CPU，而非从零验证自研指令流水线。

## 基线决策

| 项 | v1 决策 | 如何确认 |
| --- | --- | --- |
| CPU | 1 个 64 位 Rocket 核，五级顺序、单发射；RV64GC，M/S/U 特权级、Sv39 MMU、分离的 L1 指令和数据缓存 | 检查生成配置、设备树及指令/虚存测试；用户程序能在 Linux 上运行 |
| 时钟 | CPU/主总线目标 100 MHz（10 ns），先复现原版，不改流水级数。50 MHz 是独立的诊断配置，不代替正式验收 | 保存布线后的时钟、时序、未约束路径和 CDC 报告；检查 setup、hold 及脉宽。DDR4 物理层/用户接口按板级控制器配置，不套用 CPU 时钟 |
| 存储 | 沿用板级参考设计的一路 DDR4；独立 Boot ROM；保留原版内存映射及缓存配置 | DDR 校准完成，裸机在保留的测试区跨多地址读写不同数据模式；系统软件与硬件依据同一内存映射 |
| 外设 | UART 控制台、机器定时器/软件中断、PLIC 外部中断、SPI SD、CPU 调试接口 | 串口双向、定时器计数、中断计数、SD 读回、调试停机/继续分别测试 |
| 启动 | 首版用 JTAG 配置 FPGA；软核从 Boot ROM 经 SPI SD 装入含 OpenSBI、Linux 和内置根文件系统的启动载荷（板级设备树由 Rocket 生成并附加在 Boot ROM 中） | 记录 bitstream 和镜像版本；复位后无调试器手动加载 Linux 即可进入 shell。注意板载管理 SD 卡槽不是软核的启动口；参考连接使用 PMOD 转 SPI SD |
| 工具 | 参考 Chipyard 1.13.0 的 RocketVCU118Config，固定 tag 和子模块，Vivado 2024.2 为拟用版本，不提前声明已验证兼容 | 归档生成命令、Vivado 版本、约束、硬件和软件产物标识 |

## 分阶段验收

1. **参考系统**：不加自定义 IP。通过裸机串口、DDR 和定时器测试；完成 100 MHz 布线后时序签核。重点检查生成时钟和 DDR 跨域复位释放，不能用大范围 false path 消除告警。
2. **Linux 基线**：从外接 SD 进入 shell，运行 integer 与 double 精度测试、SD 文件读写比对和内存压力测试。建议连续 10 次复位启动均成功、运行内存测试一小时无错；记录内存工作集、日志与时序报告。
3. **第一项加速功能**：建议实现由 Linux 调度的矩阵乘单元。数据流：DDR → DMA → 计算阵列 → DMA → DDR，寄存器下发任务，中断报告完成。设计前确定 DMA 一致性策略和内存所有权。以同一尺寸/精度的 CPU 软件结果为基准，报告结果误差、含数据搬移的端到端延迟、吞吐和 FPGA 资源。不要把阵列理论峰值当应用性能。
4. **按瓶颈扩展**：多任务吞吐不足时做双核 SMP 及一致性测试；主机传输不足时加 PCIe DMA；远程服务有需求时加以太网。每次只引入一个子系统，保留上一版通过的配置与镜像。

## 依据

- Chipyard 1.13.0 上游 VCU118 配置：`https://github.com/ucb-bar/chipyard/blob/1.13.0/fpga/src/main/scala/vcu118/Configs.scala`
- Chipyard 上游板级与 Linux 启动说明：`https://github.com/ucb-bar/chipyard/blob/1.13.0/docs/Prototyping/VCU118.rst`
- Chipyard Rocket 核说明：`https://chipyard.readthedocs.io/en/latest/generators/rocket/`
- VCU118 板级手册：AMD UG1224；Vivado 布线后时序签核：AMD UG906。
- Chipyard 团队对 SD 转接方式的说明：`https://groups.google.com/g/chipyard/c/7nlv78HTJvE`
