<p align="center"><img src="../assets/hero.svg" alt="Pearl M-Miner — 面向 Apple Silicon 的 Metal GPU 矿工" width="100%"></p>

# Pearl M-Miner

[English](../README.md) · [实测数据](PERFORMANCE.md) · [开发支持说明](DEV_FEE.md) · [Apache-2.0](../LICENSE)

**专为 Apple Silicon Metal GPU 优化的开源 Pearl（PRL）矿工。** 在一台 M1 Max 上，研究版后端的 180 秒实矿达到约 **3.87 TH/s**，**7 份接受、0 份拒绝**，矿池 API 最终独立确认了全部 7 份。

相对早期基于上游矿工的约 1.08 TH/s 日志读数，累计约为 **3.58 倍**。最后一轮的 **30–32% 提升，比较的是我们已经优化到 2.93–2.97 TH/s 的版本**。这两个比较不能混在一起：早期原版测试为 600 秒，与最终版本并非重新进行的同条件 A/B。[完整口径与证据](PERFORMANCE.md)。

当前是 **`v0.1.0-alpha.2` 实验性源码版本（包版本 `0.1.0a2`）**。只有 M1 Max 有实测；其他 M 系列设备是待验证目标，没有捏造 M2–M5 的性能数字。这里使用 GPU，未把 Apple Neural Engine 算进挖矿算力。

**Alpha 1 基线复测：**60 秒离线约 **3.928 TH/s**；另一次 180 秒 LuckyPool 实矿约 **3.879 TH/s，8 接受／0 拒绝**，矿池 API 确认了全部 8 份。48 项 CPU 测试、28 项官方证明检查及加速的 Kryptex → LuckyPool → Kryptex 路由测试通过；短测不代表完整一小时收费周期或开发者钱包到账验证。[发布验收及保留的失败对照](RELEASE_VALIDATION.md)。

**Alpha 2 新增 Kryptex gzip 协商。** 三份生产维度离线证明的载荷缩小约 108–111 倍，解压字节完全一致，并再次通过官方验证。真实服务器已确认 v2 协商；有效 gzip 份额单独记录。[协议、测试与证据](KRYPTEX_GZIP.md)。

## 目录

- [包含什么](#包含什么)
- [性能对比](#性能对比)
- [安装与验证](#安装与验证)
- [开始挖矿](#开始挖矿)
- [透明的 1% 开发支持](#透明的-1-开发支持)
- [优化原理](#优化原理)
- [兼容性与贡献](#兼容性与贡献)
- [许可与来源](#许可与来源)

## 包含什么

| 模块 | 内容 |
| --- | --- |
| Metal GPU | 按前缀调度扫描、S 矩阵准备、真实输入精度检查 |
| CPU 准备 | 增量 nonce/Merkle、不可变任务快照 |
| 正确性 | 独立整数对照、小网格完整 transcript/digest、官方证明验证 |
| 命令行 | `doctor`、`self-test`、限时 `benchmark`、前台 `mine` |
| 矿池 | LuckyPool 研究版已收到有效份额；其他矿池单独验证 |
| 开发支持 | 默认 1% 有效扫描时间，可以关闭 |
| 证据 | 脱敏 JSON/CSV、可重新生成的对比图 |

## 性能对比

![M1 Max 实测：明确区分历史对比与已经优化的基线](../assets/performance.svg)

| M1 Max 测量 | 速度 | 范围 |
| --- | ---: | --- |
| 早期上游 0.2.4＋cert-v3 兼容补丁 | 1.080 TH/s | 历史 600 秒窗口，日志读数均值 |
| 早期 Pearly 1.0.3 | 3.000 TH/s | 历史 600 秒窗口，日志读数均值 |
| 我们已经优化的基线 | 2.933–2.967 TH/s | 后续两轮各 180 秒实矿 |
| **最终 S 路线研究版** | **3.869 TH/s** | **180 秒实矿；7 接受／0 拒绝** |
| 最终 S 路线完整新网格离线测试 | 3.931 TH/s | 测量 30 秒，不含矿池提交 |

**30–32% 是相对已经优化的版本，不是相对原版或 Pearly。** 最终版本没有与 Pearly 重新做同窗口对照。TH/s 按协议等价工作量换算，没有把乘法和加法再乘二，也不是设备标称 TOPS。短时间的接受份额数不能证明长期收益；这些研究测试也早于发布版的开发费调度。[详细定义、功率遥测及证据哈希](PERFORMANCE.md)。

![LuckyPool 真实研究日志：七份接受](../assets/luckypool-log.png)

*这是已经记录的真实研究日志在查看器中的展示，不是实时桌面截图。摘录保留了七条接受回复和两条会话记录；当时没有启用开发费调度。[纯文本摘录](evidence/luckypool-log.txt) · [查看器](evidence/luckypool-log.html) · [截图来源与哈希](evidence/screenshot-provenance.json)。*

## 安装与验证

需要 Apple Silicon Mac、**macOS 26+**、原生 arm64 **Python 3.12+**、兼容 Metal 4 的 Xcode Command Line Tools、Git 和 Rust/Cargo。安装脚本会在仓库内创建虚拟环境，构建固定版本的官方 Pearl 证明扩展和本地库，不安装后台挖矿服务。

```sh
git clone https://github.com/parkerkyle-max/pearl-m-miner.git
cd pearl-m-miner
sh bootstrap.sh

.venv/bin/pearl-m-miner doctor
.venv/bin/pearl-m-miner self-test
.venv/bin/pearl-m-miner benchmark --seconds 60
```

如果原生 Python 的命令是 `python3.12`，可以运行 `PYTHON=python3.12 sh bootstrap.sh`。编译、精度检查或自检失败时，应停止并排查，不要继续挖矿。当前从源码构建，并非可直接搬走的预编译 wheel。

默认 `--profile auto` 只对至少 64 GiB 内存的 M1 Max 选择 M=16384、N=65536；其他设备先用 M=8192、N=16384。默认两个 CPU 辅助线程、512 region rows。可以显式选择 `--profile conservative|max` 或指定维度；新设备也可先测更小网格：

```sh
.venv/bin/pearl-m-miner benchmark --m 4096 --n 4096 --seconds 60
```

挖矿和基准测试要求本机已有成功的自检收据；关键源码／库重建或系统／设备变化后，需要重新自检。它验证的是离线证明路径，不替代真实矿池验收。

## 开始挖矿

使用自己控制的 **PRL 公开收款地址**，不要填写私钥或助记词：

```sh
.venv/bin/pearl-m-miner mine \
  --pool luckypool \
  --address YOUR_PUBLIC_PRL_ADDRESS \
  --worker my-mac \
  --time-limit 600
```

这条命令限定运行十分钟。验证通过后，可去掉 `--time-limit` 让程序在前台持续运行；**Ctrl+C 会停止它管理的矿工进程**。没有配置开机自启。

默认电池策略为暂停。macOS 报告 serious/critical 热压力时也会暂停，恢复到正常或较轻状态后再继续；这是系统热压力信号，不是经过校准的摄氏温度阈值。

`--host`、`--port` 可以指定用户矿池入口。Kryptex 的 `krx…` mining ID 属于账户挖矿身份，不能当作原生 PRL 地址；其接入与有效份额需要单独验证，不能借用 LuckyPool 的成功记录。更多选项见 `.venv/bin/pearl-m-miner mine --help`。

挖矿不保证盈利。电费、网络难度、币价、矿池规则和最低提现门槛都会影响实际结果；本仓库没有经验证的电费后净利润结论。

## 透明的 1% 开发支持

默认保留 **1% 有效 GPU 扫描时间**用于支持设备测试、正确性研究和维护。我们希望用户、fork 和 AI 生成的集成保留这项设置和清楚的说明；**这是自愿支持，可用 `--dev-fee 0` 关闭**，不增加 Apache-2.0 许可证限制。

通常累计 3564 秒用户有效扫描时间后，运行 36 秒开发者有效扫描。编译、连接、等待任务、断线、暂停和过期扫描都不增加计费活动。区域边界造成的少量超出会结转，状态跨重启保存。

这不是墙钟每小时精确 36 秒，也不保证刚好拿到 1% 的份额或奖励。矿池费另算；身份切换需要停止旧 worker 并重新连接，可能产生开销。开发矿池故障时回到用户工作并退避，延期额度有上限，不无限累积追缴。[完整行为与验收边界](DEV_FEE.md)。

## 优化原理

完整保留 Pearl 要求的 32 个前缀贡献及 rotate/XOR transcript，改变矩阵表示与 GPU 调度。S 路线用一小批矩阵运算替代较慢的准备路径，大型中间表留在 GPU 私有内存，新的 nonce 改变承诺和噪声，避免重复工作。

实际输入必须通过 half 精确往返与 float32 整数累加范围检查，失败就拒绝，不靠近似结果换算力。主扫描运算量仍为 `m × n × K`，不是减少了 32 倍计算。[架构及正确性说明](ARCHITECTURE.md)。

## 兼容性与贡献

**M1 Max 已测；M2–M5 未测。** 其他 M1 型号和其他 M 系列都需要在实际机器上完成构建、自检、性能和矿池验收，不能从“M 芯片”或标称 TOPS 推导性能。[设备矩阵](COMPATIBILITY.md)。

欢迎提交新设备报告、可复现优化和生命周期测试。请保留失败对照、写清测试时长与功率口径，并删除日志中的身份和私密信息。[贡献指南](../CONTRIBUTING.md) · [安全说明](../SECURITY.md) · [机器阅读入口](../llms.txt)。

## 许可与来源

新增和修改内容版权 **2026 parkerkyle-max**，采用 [Apache-2.0](../LICENSE)。派生自 [pearl-metal-miner](https://github.com/Breakwater-ecosystem/pearl-metal-miner)，原始署名保留在 [NOTICE](../NOTICE)。原上游没有开发费；可选 1% 是本项目新增功能，不表示上游作者为其背书。

官方 Pearl 证明组件采用 ISC 许可并固定提交；BLAKE3 原许可文件随源码保留。本项目不隶属于 Pearl Research Labs、Apple 或 Pearly。
