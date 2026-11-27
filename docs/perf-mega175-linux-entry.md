# 四路 BOOM：从 OpenSBI 进入 Linux 的第一段指令

在单 hart 四路 BOOM 原版和替换寄存器堆的 LVT 候选上，用同一份 OpenSBI/Linux 固件检查启动交接。两套整核 RTL 模型的串口字节和事件记录相同。**两者都执行到了内核入口之后；实验在用户态之前主动停止，没有运行 CoreMark。** [输入指纹及逐项记录](perf-mega175-linux-entry.json)。

| 同一测试点 | 原版与 LVT 各自的结果（模型周期） |
| --- | ---: |
| 只翻转帧 CRC 一位的独立复位用例：ROM 报错，再观察 20 位静默 | 883,890 |
| 正常帧：ROM 输出 `HANDOFF` | 838,329 |
| 外部 TileLink 接受对 `0x80200000` 的 64 字节读请求 | 30,779,723 |
| `mret`：`mepc=0x80200000`，`MPP=S`，时钟沿前后特权级从 M 变为 S | 40,822,114 |
| 最后观测点：四路 ROB 合计已报告 258 条 S 模式架构提交 | 40,822,448 |

读内核入口地址比真正切换特权级早 **10,042,391 拍**，不能用那次读代替启动成功。计数器只累计已切到 S 模式后的架构提交，不是逐条 PC 跟踪，也不证明两种寄存器堆全程等价。CRC 错误用例从独立复位开始，不与正常帧共用一条时间线。

**哪些字节真的经过了串口？** 固件前 8 字节在复位时刻意留空，经 ROM 的串口引脚接收 24 字节帧后补上；其余 5,604,352 字节预置于外部行为内存。此实验未串行上传完整压缩载荷、未测试解压与物理 DDR，也没有 Linux shell、板上频率或计时成绩。

**模型中是哪份软件？** 从同份 `vmlinux` 用原构建的 `objcopy` 重建裸 `Image`，与固件偏移 `0x200000` 处的发行镜像逐字节相同。按其链接符号，gzip 始于 `Image + 0x1b2b48`；`Image + 0x2182d8` 保存的是 8 字节小端长度 **415,629**。复核脚本展开该单个 gzip，解析 `newc` 的 38 项，核对 `bin/coremark-g15-gc-lto-ooo-strict` 是独立的可执行普通文件，67,008 字节与已在 Rocket 实测的目标 ELF 完全相同。旁边三个 GCC 15 配置不能代替它。**在镜像里找到 ELF，并不表示执行了它。**

## 复现

准备[原版和 LVT 输入及独立串口对照](perf-mega175-regfile-chiptop.json)对应的两套模型对象、引脚测试目录，以及同一份 Linux 发行目录；使用仓库固定的 Verilator 版本。每个运行目录必须是新目录。下面两次运行会各自链接观测程序、分别执行 CRC 错误帧和正常帧，最后再次核验输入。

```sh
bash scripts/test-mega-linux-entry.sh stock "$STOCK_KIT" "$STOCK_OBJ" "$STOCK_PINS" "$RELEASE" "$STOCK_RUN"
bash scripts/test-mega-linux-entry.sh lvt   "$LVT_KIT"   "$LVT_OBJ"   "$LVT_PINS"   "$RELEASE" "$LVT_RUN"
python3 scripts/review-mega-linux-entry.py "$STOCK_KIT" "$STOCK_PINS" "$STOCK_RUN" \
    "$LVT_KIT" "$LVT_PINS" "$LVT_RUN" "$RELEASE"
```

从 Git 的干净导出复核历史字节时有一处差别：当次编译的两个既有头文件只在**最后一行**使用 CRLF，Git 将其规范为 LF。仅在一次性导出目录中运行下面的准备步骤，然后执行上面的命令；它先由旧串口实验的既有哈希核定转换后的字节，其余任何差异都会失败。已用这种方式在独立导出目录复核出相同的 JSON，再分别用原模型归档重编译并链接观测程序，两个可执行文件均与各自当次运行的文件逐字节相同。不要修改工作仓库或原捕获。

```sh
tmp=$(mktemp -d); git archive HEAD | tar -x -C "$tmp"; cd "$tmp"
python3 - <<'PY'
from hashlib import sha256
import json
from pathlib import Path
wanted = json.loads(Path('docs/perf-mega175-fixed-rom-link.json').read_bytes())['inputs']
for name in ('chiptop_address.hpp', 'chiptop_sd.hpp'):
    p = Path('tests') / name
    b = p.read_bytes()
    if sha256(b).hexdigest() != wanted[name]:
        changed = b[:-1] + b'\r\n'
        if not b.endswith(b'};\n') or sha256(changed).hexdigest() != wanted[name]:
            raise ValueError('unexpected source: ' + name)
        p.write_bytes(changed)
PY
```

如需独立定位此发行的两个链接符号，用同一工具链的 `nm -n vmlinux` 查 `_start`、`__initramfs_start` 和 `__initramfs_size`，后两者各减 `_start` 得到上面的偏移。对应 `vmlinux` 的 SHA-256 为 `9d66a82b453123e893ee82e4c0ca090b6401a317ccd97519d033088a0e5c0d7f`。离线程序均不连接 JTAG 或串口。
