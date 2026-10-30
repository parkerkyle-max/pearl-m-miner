<p align="center"><img src="../assets/hero.svg" alt="Pearl M-Miner — Apple Silicon Metal GPU" width="100%"></p>

[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

# Pearl M-Miner — Apple Silicon 的 Pearl（PRL）矿工

专为 M 系列 Mac 优化的开源 Metal GPU 矿工。**M1 Max 在 300 秒离线测试中达到 4.2347 TH/s。另一次同条件 60 秒均值对照，相比本项目 Alpha 2 后端提升 7.82%。** 另一场部署后的用户会话收到 Kryptex gzip 份额接受回复。离线速度、矿池份额和收益分别记录，不承诺收益。

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

**实验性源码版 v0.1.0-alpha.3（Python 包版本 0.1.0a3）。** 需要 Apple Silicon、**macOS 26+**、原生 arm64 **Python 3.12+**、支持 Metal 4 的命令行工具、Git 和 Rust/Cargo。已测配置包括 M1 Max（32 核 GPU／64 GiB）和 M2（10 核 GPU／24 GiB）。测试中的 M2 笔记本请在限时挖矿命令中加入 --intensity 80，并阅读下方温度限制。其他型号及 M3–M6 仍需各自的本机自测与矿池验证。当前没有提供 CPU、ANE 或多币种挖矿。

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

<!-- device-results -->
<a id="device-results"></a>
<section class="device-matrix">
<h2>设备实测与测试计划</h2>
<p>展开系列查看具体配置。只有标记为已实测的具体配置有成绩，结果不代表整个芯片系列。已发布但未测的设备列入测试计划、等待设备，不代表已验证兼容。</p>
<details class="device-family" id="device-m1">
<summary><span class="family-name">M1</span> <span class="family-result">M1 Max: +7.82% · 对照 本项目 Alpha 2（非上游） · 60 秒 · 仅同基线／范围已测配置的最高增幅</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M1 设备实测与测试计划">
<table><thead><tr><th scope="col">芯片／具体配置</th><th scope="col">状态</th><th scope="col">离线本地速率</th><th scope="col">对照与增幅</th><th scope="col">证据</th></tr></thead><tbody>
<tr><th scope="row">M1 · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M1 Pro · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M1 Max · 32 GPU cores / 64 GiB</th><td>该配置已实测 · 2026-10-30 · macOS 26.6.1</td><td>4.2347 TH/s · 300 秒 · 离线</td><td>+7.82% · 对照 本项目 Alpha 2 后端；不是上游 (60 秒 同条件均值: 4.234368 / 3.927237 TH/s)</td><td><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/M1_CEILING_20261030.md">方法与报告</a> · <a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/data/m1-pair32-live.json">原始证据</a></td></tr>
<tr><th scope="row">M1 Max · 其他 GPU／内存配置</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M1 Ultra · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M1 设备验证计划</a> · <a href="https://www.apple.com/newsroom/2022/03/apple-unveils-m1-ultra-the-worlds-most-powerful-chip-for-a-personal-computer/">Apple 发布来源</a></p>
</details>
<details class="device-family" id="device-m2">
<summary><span class="family-name">M2</span> <span class="family-result">M2: +260.8% / 3.61× · 对照 pearl-metal-miner 0.2.4 + cert3 · 300 秒 · 仅同基线／范围已测配置的最高增幅</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M2 设备实测与测试计划">
<table><thead><tr><th scope="col">芯片／具体配置</th><th scope="col">状态</th><th scope="col">离线本地速率</th><th scope="col">对照与增幅</th><th scope="col">证据</th></tr></thead><tbody>
<tr><th scope="row">M2 · 10 GPU cores / 24 GiB</th><td>该配置已实测 · 2026-10-30 · macOS 27.0</td><td>1.465227 TH/s · 300 秒 · 离线</td><td>+260.8% / 3.61× · 对照 pearl-metal-miner 0.2.4 + cert3 compatibility (300 秒 同条件均值: 1.465227 / 0.406127 TH/s)</td><td><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/M2_VALIDATION_20261030.md">方法与报告</a> · <a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/data/m2-validation-20261030.json">原始证据</a></td></tr>
<tr><th scope="row">M2 · 其他 GPU／内存配置</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M2 Pro · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M2 Max · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M2 Ultra · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M2 设备验证计划</a> · <a href="https://www.apple.com/newsroom/2023/06/apple-introduces-m2-ultra/">Apple 发布来源</a></p>
</details>
<details class="device-family" id="device-m3">
<summary><span class="family-name">M3</span> <span class="family-result">暂无实测配置 · 计划测试／等待设备</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M3 设备实测与测试计划">
<table><thead><tr><th scope="col">芯片／具体配置</th><th scope="col">状态</th><th scope="col">离线本地速率</th><th scope="col">对照与增幅</th><th scope="col">证据</th></tr></thead><tbody>
<tr><th scope="row">M3 · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M3 Pro · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M3 Max · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M3 Ultra · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M3 设备验证计划</a> · <a href="https://www.apple.com/newsroom/2025/03/apple-reveals-m3-ultra-taking-apple-silicon-to-a-new-extreme/">Apple 发布来源</a></p>
</details>
<details class="device-family" id="device-m4">
<summary><span class="family-name">M4</span> <span class="family-result">暂无实测配置 · 计划测试／等待设备</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M4 设备实测与测试计划">
<table><thead><tr><th scope="col">芯片／具体配置</th><th scope="col">状态</th><th scope="col">离线本地速率</th><th scope="col">对照与增幅</th><th scope="col">证据</th></tr></thead><tbody>
<tr><th scope="row">M4 · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M4 Pro · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M4 Max · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M4 设备验证计划</a> · <a href="https://www.apple.com/newsroom/2024/10/apple-introduces-m4-pro-and-m4-max/">Apple 发布来源</a></p>
<p class="device-note">仅作未来占位，截至 2026-10-30 未确认 Apple 已发布：M4 Ultra。不表示这些设备已经存在或已获兼容支持。</p>
</details>
<details class="device-family" id="device-m5">
<summary><span class="family-name">M5</span> <span class="family-result">暂无实测配置 · 计划测试／等待设备</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M5 设备实测与测试计划">
<table><thead><tr><th scope="col">芯片／具体配置</th><th scope="col">状态</th><th scope="col">离线本地速率</th><th scope="col">对照与增幅</th><th scope="col">证据</th></tr></thead><tbody>
<tr><th scope="row">M5 · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M5 Pro · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M5 Max · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
<tr><th scope="row">M5 Ultra · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M5 设备验证计划</a> · <a href="https://www.apple.com/newsroom/2026/08/apple-introduces-new-mac-studio-with-m5-max-and-m5-ultra/">Apple 发布来源 1</a> · <a href="https://www.apple.com/newsroom/2025/10/apple-unleashes-m5-the-next-big-leap-in-ai-performance-for-apple-silicon/">Apple 发布来源 2</a> · <a href="https://www.apple.com/newsroom/2026/03/apple-debuts-m5-pro-and-m5-max-to-supercharge-the-most-demanding-pro-workflows/">Apple 发布来源 3</a></p>
</details>
<details class="device-family" id="device-m6">
<summary><span class="family-name">M6</span> <span class="family-result">暂无实测配置 · 计划测试／等待设备</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M6 设备实测与测试计划">
<table><thead><tr><th scope="col">芯片／具体配置</th><th scope="col">状态</th><th scope="col">离线本地速率</th><th scope="col">对照与增幅</th><th scope="col">证据</th></tr></thead><tbody>
<tr><th scope="row">M6 · GPU／内存配置尚未实测</th><td>计划测试／等待设备</td><td>未测</td><td>—</td><td>未测</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M6 设备验证计划</a> · <a href="https://www.apple.com/newsroom/2026/08/apple-introduces-m6-and-m5-ultra-for-a-big-leap-in-performance-and-ai-compute/">Apple 发布来源</a></p>
<p class="device-note">仅作未来占位，截至 2026-10-30 未确认 Apple 已发布：M6 Pro, M6 Max, M6 Ultra。不表示这些设备已经存在或已获兼容支持。</p>
</details>
<div class="matrix-notes">
<p>以上均为本地离线 PRL 协议吞吐，不是矿池算力、到账收益或插座能效。M1 Max 的 +7.82% 来自同条件 60 秒均值（4.234368 对 3.927237 TH/s），对照本项目 Alpha 2；另一次 300 秒长测为 4.2347 TH/s。M2 的 +260.8%／3.61 倍来自同条件 300 秒测试（1.465227 对 0.406127 TH/s），对照 pearl-metal-miner 0.2.4 加 cert3 兼容补丁，保留原 GPU 内核。两种基线不同，不能据此给整个系列排名。</p>
<p>M2 矿池证据另来自 80% 强度、600 秒试跑：3 接受／0 拒绝。100% 强度实挖曾触发外部试验设置的 95°C 停机线；该摄氏温度线不是矿工内置功能，也不是 Apple 损坏阈值。该已测笔记本请使用 --intensity 80。少量份额不能证明长期矿池速度或收益。</p>
</div>
<p class="matrix-invitation">你有其他配置的 Mac 吗？欢迎帮忙测试并贡献实测，构建或自测失败的结果也欢迎。请提供准确芯片、GPU 核数、内存、macOS、矿工版本、强度、命令、测试时长和脱敏日志。自测失败应先解决再挖矿，不要公开钱包恢复资料。</p>
<p class="matrix-feedback"><a href="https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=device-result.yml">贡献设备实测</a> · <a href="https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=benchmark-discrepancy.yml">数字有偏差？反馈问题</a></p>
<div id="community-testing" class="matrix-roadmap community-testing"><h3>愿意帮忙测试你的 Mac 吗？</h3><p>实验对比工具位于 main 开发预览版（0.1.0a4.dev1），Alpha 3 发布标签不含此命令。请另建目录克隆 main 并运行 sh bootstrap.sh，完整步骤见指南。</p><pre><code>.venv/bin/pearl-m-miner compare --plan
.venv/bin/pearl-m-miner compare --against pearl-metal-miner --output ./my-comparison</code></pre><p>先看计划，再确认开始：每轮 60 秒，每个后端两轮，顺序 A/B/B/A；每轮前冷却 30 秒，另需编译、预热和正确性检查。对照固定版本 pearl-metal-miner 0.2.4 加 cert3 兼容补丁，测量离线新工作准备与扫描。不使用钱包、矿池或自动上传。更慢与失败的结果也欢迎，报告需审核后才可能进入设备表。</p><p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/COMMUNITY_TESTING.md">安装、对比与分享前复核指南</a> · <a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/COMPARATORS.md">对照项目调查与比较限制</a></p></div>
<div class="matrix-roadmap"><h3>接下来的验证工作</h3><p>以下为测试优先方向，不承诺日期或保证支持：</p><ol><li>扩充已发布 M1–M6 各具体配置的真机覆盖。</li><li>逐芯片、逐配置优化并独立验证。</li><li>补充长时间运行、温控与稳定性测量。</li><li>完善安装、诊断和可重复的本机自测。</li><li>收集并审核社区 A/B 实测，包括更慢和失败的结果，调查数据差异。</li></ol><p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">完整路线图</a> · <a href="https://parkerkyle-max.github.io/pearl-m-miner/device-results.json">机器可读设备数据</a></p></div>
</section>
<!-- /device-results -->

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
