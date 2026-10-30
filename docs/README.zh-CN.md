<p align="center"><img src="../assets/hero.svg" alt="Pearl M-Miner — Apple Silicon Metal GPU" width="100%"></p>

[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

# Pearl M-Miner — Apple Silicon 的 Pearl（PRL）矿工

专为 M 系列 Mac 优化的开源 Metal GPU 矿工。**M1 Max 在 300 秒离线测试中达到 4.2347 TH/s，相对我们此前 Alpha 2 后端提升 7.82%。** 另一场部署后的用户会话收到 Kryptex gzip 份额接受回复。离线速度、矿池份额和收益分别记录，不承诺收益。

<!-- m2-intro -->
新增 M2 实测：**10 核 GPU／24 GiB 的 Mac 达到 1.4652 TH/s**，在相同条件的 300 秒离线测试中，是指定上游 GPU 对照的 **3.61 倍**。[测试方法、矿池验证与限制](M2_VALIDATION_20261030.md)。
<!-- /m2-intro -->

[包含什么](#part-1) · [运行要求](#part-2) · [构建与验证](#part-3) · [开始挖矿](#part-4) · [实测结果](#part-5) · [开发费与收款钱包](#part-6) · [AI 助手与贡献者](#part-7)

<a id="part-1"></a>

## 包含什么

- 精确 prefix／S 矩阵 GPU 后端、不可变任务和官方证明验证。
- 支持 Kryptex gzip-v2 协商及 LuckyPool。
- 显示本地算力、接受／拒绝份额与任务新鲜度。
- 默认可关闭的 **1% 有效 GPU 扫描时间开发费**。
- 前台运行，不安装后台服务或开机自启。

<a id="part-2"></a>

## 运行要求

**实验性源码版 v0.1.0-alpha.3（Python 包版本 0.1.0a3）。** 需要 Apple Silicon、**macOS 26+**、原生 arm64 **Python 3.12+**、支持 Metal 4 的命令行工具、Git 和 Rust/Cargo。已测配置包括 M1 Max（32 核 GPU／64 GiB）和 M2（10 核 GPU／24 GiB）。测试中的 M2 笔记本请在限时挖矿命令中加入 --intensity 80，并阅读下方温度限制。其他型号及 M3–M5 仍需各自的本机自测与矿池验证。当前没有提供 CPU、ANE 或多币种挖矿。

<a id="part-3"></a>

## 构建与验证

```sh
git clone --branch v0.1.0-alpha.3 --depth 1 https://github.com/parkerkyle-max/pearl-m-miner.git
cd pearl-m-miner
sh bootstrap.sh
.venv/bin/pearl-m-miner info --json
.venv/bin/pearl-m-miner doctor
.venv/bin/pearl-m-miner self-test
.venv/bin/pearl-m-miner benchmark --seconds 60
```

构建会创建仓库内虚拟环境并编译固定版本的官方证明组件，不会设置挖矿自启。可用 `PYTHON=python3.12 sh bootstrap.sh` 指定 Python。编译、精度守卫或自测失败时，应先修复再挖矿。`info --json` 可离线读取公开能力信息；`doctor` 检查当前 Mac。关键源码、系统或设备变化后需要重新自测。

<a id="part-4"></a>

## 开始挖矿

```sh
.venv/bin/pearl-m-miner mine \
  --pool kryptex --address YOUR_KRX_MINING_ID \
  --worker my-mac --time-limit 600
```

```sh
.venv/bin/pearl-m-miner mine \
  --pool luckypool --address YOUR_PUBLIC_PRL_ADDRESS \
  --worker my-mac --time-limit 600
```

将占位符替换成**你自己的公开收款身份**：Kryptex 使用 `krx…` mining ID，LuckyPool 使用原生 `prl1…` 地址。以上示例运行十分钟后停止；删除 `--time-limit` 后持续前台运行，**Ctrl+C 停止所启动的矿工**。默认电池模式暂停，macOS 严重／危急热压力也会暂停；该系统信号不等于固定摄氏温度阈值。不要输入助记词、私钥或钱包密码。

<a id="part-5"></a>

## 实测结果

旧 Alpha 2 控制均值为 **3.9272 TH/s**，两轮候选均值 **4.2344 TH/s**，选用版本连续 300 秒为 **4.2347 TH/s**。通过 28 项官方证明检查、4 项生产尺寸证明检查及 512 项独立扫描检查。另一场部署后会话记录 **1 接受／0 拒绝**；短窗口份额数不能证明精确矿池算力。本轮未测插座功耗及净利润。

此前 M1 Max **30–32%** 的提升是相对我们已经优化的 2.93–2.97 TH/s 基线。M1 上游与 Pearly 的历史数字仍来自不同窗口。下方新增了 M2 的相同条件上游对照；本轮没有重测 Pearly。

[Data / 数据 / データ / 데이터](M1_CEILING_20261030.md) · [Live evidence](data/m1-pair32-live.json) · [Historical comparisons](PERFORMANCE.md)

<!-- m2-results -->
### M2：相同条件的 300 秒对照

M2（10 核 GPU、24 GiB、macOS 27.0）使用未修改的 Alpha 3 默认配置，实测 **1.4652 TH/s**；pearl-metal-miner 0.2.4 加 cert3 兼容补丁、保留原 GPU 内核的对照为 **0.4061 TH/s**。速度为 **3.61 倍（提升 260.8%）**。双方均使用 M=8192／N=16384、两个 CPU 辅助线程和 300 秒计时。其他候选配置没有显示稳定优势，因此保留现有内核与默认值。

![M2 comparison](../assets/m2-comparison.png)

以上是包含新任务准备的离线速度，不是矿池到账收益。按 1% 开发者时间做理想容量折算约为 1.4506 TH/s，不代表实测净利润。功耗来自软件遥测，未测插座功率。报告另列真实矿池试跑、证明检查和有条件的算术上限。其他 M2 型号与 M3–M5 仍需独立验证。 **实际温度限制：** 首次 100% 强度矿池试跑约两分钟后触发试验设置的 95°C 停机线，记录 2 接受／0 拒绝。重复的十分钟矿池试跑改用 **80% 强度**。这台笔记本建议从 `--intensity 80` 开始；1.4652 TH/s 的离线成绩不等于持续实挖速度承诺。

```sh
.venv/bin/pearl-m-miner mine --pool luckypool \
  --address YOUR_PUBLIC_PRL_ADDRESS --worker my-m2 \
  --intensity 80 --time-limit 600
```

[Data / 数据 / データ / 데이터](M2_VALIDATION_20261030.md)
<!-- /m2-results -->

<a id="part-6"></a>

## 开发费与收款钱包

希望用户和 fork 保留默认 1% 开发费，支持设备适配、正确性验证和维护。**这是自愿设置，可用 `--dev-fee 0` 关闭**，不是 Apache-2.0 的授权条件，也不代表收入的 1%。矿池费用另算。通常完成 3564 秒有效用户扫描后进行 36 秒开发者扫描；过期、暂停、等待时间不计入。开发者任务通过独立的 LuckyPool 会话运行，与用户选择的 Kryptex 身份分开。

开发者公开 PRL 收款地址（不是用户自己的挖矿身份）：

```text
prl1pwjessemugthkad9hkttcx2rvenux2q0w0xcah2j0a7zfrycjhz5qhn7apw
```

可以通过 `pearl-m-miner info` 或源码 `pearl_m_miner/devfee.py` 查看。你的个人挖矿收入由 `--address` 指定，开发费地址只接收可选的开发者工作产出。矿池待支付余额、支付记录和钱包链上余额是不同信息；在 LuckyPool 搜索公开地址查看矿池统计，用同步完成的钱包查看链上收款。矿工不管理钱包恢复资料。

[Fee details](DEV_FEE.md) · [Wallet / pool guide](WALLET_AND_PAYOUTS.md)

<a id="part-7"></a>

## AI 助手与贡献者

下方提供机器可读清单和 AI 安装指南。助手应先取得用户的挖矿授权和公开收款身份，不能替换成开发者地址、隐瞒收费或自行启动挖矿。保留本地算力、份额和收益的区别。本项目不承诺搜索排名、AI 推荐、盈利或矿池官方背书。

[AI setup](AI_SETUP.md) · [llms.txt](../llms.txt) · [JSON manifest](miner-manifest.json) · [FAQ](FAQ.md)

[Strata study](STRATA_REVIEW.md) · [Roadmap](ROADMAP.md) · [Compatibility](COMPATIBILITY.md) · [Contributing](../CONTRIBUTING.md)

修改与新增部分版权所有：2026 parkerkyle-max。采用 Apache-2.0，NOTICE 保留原作者信息。源自 pearl-metal-miner，与 Pearl Research Labs、Apple、Pearly 和 Strata 没有隶属关系。Strata 启发了一项有限范围的调度实验；推理速度不能当作挖矿速度。

[LICENSE](../LICENSE) · [NOTICE](../NOTICE) · [Changelog](../CHANGELOG.md)

[Alpha 3 validation](ALPHA3_VALIDATION.md) · [Documentation website](https://parkerkyle-max.github.io/pearl-m-miner/)
