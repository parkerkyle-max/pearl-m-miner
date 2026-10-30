<p align="center"><img src="../assets/hero.svg" alt="Pearl M-Miner — Apple Silicon Metal GPU" width="100%"></p>

[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

# Pearl M-Miner — Apple Silicon 向け Pearl（PRL）マイナー

M シリーズ Mac 向けのオープンソース Metal GPU マイナーです。**M1 Max の 300 秒オフライン測定は 4.2347 TH/s。別の同条件 60 秒平均の比較では、本プロジェクトの Alpha 2 バックエンド比で 7.82% 向上しました。** 別の実運用セッションでは Kryptex が gzip シェアを受理しました。これらは別々の測定であり、収益を保証しません。

<!-- m2-intro -->
M2 の実測を追加：**10 コア GPU／24 GiB の Mac で 1.4652 TH/s**。同条件の 300 秒オフライン比較では、指定した上流 GPU 実装の **3.61 倍**でした。[測定方法、プール検証と制限](M2_VALIDATION_20261030.md)。
<!-- /m2-intro -->

[主な機能](#part-1) · [動作要件](#part-2) · [ビルドと検証](#part-3) · [マイニング開始](#part-4) · [実測値](#part-5) · [開発者支援と受取アドレス](#part-6) · [AI アシスタントと貢献](#part-7)

<a id="part-1"></a>

## 主な機能

- 整数の正確性を確認する prefix／S 行列 GPU バックエンドと公式証明検証。
- Kryptex の gzip-v2 ネゴシエーションと LuckyPool。
- ローカル速度、受理／拒否シェア、ジョブの状態を表示。
- 初期設定は **有効な GPU スキャン時間の 1%**。無効化できます。
- フォアグラウンド実行。常駐サービスや自動起動は設定しません。

<a id="part-2"></a>

## 動作要件

**実験的なソース版 v0.1.0-alpha.3（パッケージ 0.1.0a3）**。Apple Silicon、**macOS 26+**、ネイティブ arm64 **Python 3.12+**、Metal 4 対応 Command Line Tools、Git、Rust/Cargo が必要です。実測済みの構成は M1 Max（32 コア GPU／64 GiB）と M2（10 コア GPU／24 GiB）です。試験した M2 ノート PC では、時間制限付き採掘コマンドに --intensity 80 を追加し、下記の温度制限を確認してください。他の構成および M3–M6 は実験対象で、各端末で自己テストとプール検証が必要です。CPU、ANE、他のコインのマイニングは未提供です。

<a id="part-3"></a>

## ビルドと検証

```sh
git clone --branch v0.1.0-alpha.3 --depth 1 https://github.com/parkerkyle-max/pearl-m-miner.git
cd pearl-m-miner
sh bootstrap.sh
.venv/bin/pearl-m-miner info --json
.venv/bin/pearl-m-miner doctor
.venv/bin/pearl-m-miner self-test
.venv/bin/pearl-m-miner benchmark --seconds 60
```

bootstrap は固定版の公式証明拡張をビルドし、リポジトリ内に仮想環境を作成します。自動起動は追加しません。必要に応じて `PYTHON=python3.12 sh bootstrap.sh` を使用してください。ビルド、精度検査、自己テストに失敗した場合は採掘を続けないでください。`info --json` はオフラインで情報を表示し、`doctor` は実機を確認します。ビルドや端末が変わったら再テストが必要です。

<a id="part-4"></a>

## マイニング開始

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

プレースホルダーを**ご自身の公開受取情報**に置き換えてください。Kryptex は `krx…` の mining ID、LuckyPool はネイティブ `prl1…` アドレスを使用します。例は 10 分で停止します。連続運転する場合は `--time-limit` を省略し、**Ctrl+C で停止**します。既定ではバッテリー時と macOS の深刻な熱負荷時に一時停止します。これは固定温度による制御ではありません。シード、秘密鍵、ウォレットのパスワードは入力しないでください。

<!-- device-results -->
<a id="device-results"></a>
<section class="device-matrix">
<h2>デバイス実測と検証計画</h2>
<p>各シリーズを開くと個別構成を確認できます。結果は実測済みと記した構成のみのもので、シリーズ全体を代表しません。発売済みの未測定機種は実機待ちの検証予定であり、互換性の確認済みを意味しません。</p>
<details class="device-family" id="device-m1">
<summary><span class="family-name">M1</span> <span class="family-result">M1 Max: +7.82% · 比較対象 本プロジェクト Alpha 2（上流ではない） · 60 秒 · 同じ比較条件で実測した構成の最大改善率</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M1 デバイス実測と検証計画">
<table><thead><tr><th scope="col">チップ／構成</th><th scope="col">状態</th><th scope="col">オフラインのローカル速度</th><th scope="col">比較対象／改善率</th><th scope="col">証拠</th></tr></thead><tbody>
<tr><th scope="row">M1 · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M1 Pro · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M1 Max · 32 GPU cores / 64 GiB</th><td>この構成を実測 · 2026-10-30 · macOS 26.6.1</td><td>4.2347 TH/s · 300 秒 · オフライン</td><td>+7.82% · 比較対象 本プロジェクトの Alpha 2 バックエンド；上流ではありません (60 秒 同条件の平均: 4.234368 / 3.927237 TH/s)</td><td><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/M1_CEILING_20261030.md">方法・レポート</a> · <a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/data/m1-pair32-live.json">検証記録</a></td></tr>
<tr><th scope="row">M1 Max · その他の GPU／メモリ構成</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M1 Ultra · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M1 デバイス検証計画</a> · <a href="https://www.apple.com/newsroom/2022/03/apple-unveils-m1-ultra-the-worlds-most-powerful-chip-for-a-personal-computer/">Apple 発表資料</a></p>
</details>
<details class="device-family" id="device-m2">
<summary><span class="family-name">M2</span> <span class="family-result">M2: +260.8% / 3.61× · 比較対象 pearl-metal-miner 0.2.4 + cert3 · 300 秒 · 同じ比較条件で実測した構成の最大改善率</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M2 デバイス実測と検証計画">
<table><thead><tr><th scope="col">チップ／構成</th><th scope="col">状態</th><th scope="col">オフラインのローカル速度</th><th scope="col">比較対象／改善率</th><th scope="col">証拠</th></tr></thead><tbody>
<tr><th scope="row">M2 · 10 GPU cores / 24 GiB</th><td>この構成を実測 · 2026-10-30 · macOS 27.0</td><td>1.465227 TH/s · 300 秒 · オフライン</td><td>+260.8% / 3.61× · 比較対象 pearl-metal-miner 0.2.4 + cert3 compatibility (300 秒 同条件の平均: 1.465227 / 0.406127 TH/s)</td><td><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/M2_VALIDATION_20261030.md">方法・レポート</a> · <a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/data/m2-validation-20261030.json">検証記録</a></td></tr>
<tr><th scope="row">M2 · その他の GPU／メモリ構成</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M2 Pro · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M2 Max · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M2 Ultra · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M2 デバイス検証計画</a> · <a href="https://www.apple.com/newsroom/2023/06/apple-introduces-m2-ultra/">Apple 発表資料</a></p>
</details>
<details class="device-family" id="device-m3">
<summary><span class="family-name">M3</span> <span class="family-result">実測構成なし · 検証予定／実機待ち</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M3 デバイス実測と検証計画">
<table><thead><tr><th scope="col">チップ／構成</th><th scope="col">状態</th><th scope="col">オフラインのローカル速度</th><th scope="col">比較対象／改善率</th><th scope="col">証拠</th></tr></thead><tbody>
<tr><th scope="row">M3 · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M3 Pro · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M3 Max · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M3 Ultra · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M3 デバイス検証計画</a> · <a href="https://www.apple.com/newsroom/2025/03/apple-reveals-m3-ultra-taking-apple-silicon-to-a-new-extreme/">Apple 発表資料</a></p>
</details>
<details class="device-family" id="device-m4">
<summary><span class="family-name">M4</span> <span class="family-result">実測構成なし · 検証予定／実機待ち</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M4 デバイス実測と検証計画">
<table><thead><tr><th scope="col">チップ／構成</th><th scope="col">状態</th><th scope="col">オフラインのローカル速度</th><th scope="col">比較対象／改善率</th><th scope="col">証拠</th></tr></thead><tbody>
<tr><th scope="row">M4 · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M4 Pro · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M4 Max · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M4 デバイス検証計画</a> · <a href="https://www.apple.com/newsroom/2024/10/apple-introduces-m4-pro-and-m4-max/">Apple 発表資料</a></p>
<p class="device-note">将来の仮枠のみ。2026-10-30 時点で Apple の発売発表を確認できない名称：M4 Ultra。実在や互換性を示すものではありません。</p>
</details>
<details class="device-family" id="device-m5">
<summary><span class="family-name">M5</span> <span class="family-result">実測構成なし · 検証予定／実機待ち</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M5 デバイス実測と検証計画">
<table><thead><tr><th scope="col">チップ／構成</th><th scope="col">状態</th><th scope="col">オフラインのローカル速度</th><th scope="col">比較対象／改善率</th><th scope="col">証拠</th></tr></thead><tbody>
<tr><th scope="row">M5 · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M5 Pro · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M5 Max · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
<tr><th scope="row">M5 Ultra · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M5 デバイス検証計画</a> · <a href="https://www.apple.com/newsroom/2026/08/apple-introduces-new-mac-studio-with-m5-max-and-m5-ultra/">Apple 発表資料 1</a> · <a href="https://www.apple.com/newsroom/2025/10/apple-unleashes-m5-the-next-big-leap-in-ai-performance-for-apple-silicon/">Apple 発表資料 2</a> · <a href="https://www.apple.com/newsroom/2026/03/apple-debuts-m5-pro-and-m5-max-to-supercharge-the-most-demanding-pro-workflows/">Apple 発表資料 3</a></p>
</details>
<details class="device-family" id="device-m6">
<summary><span class="family-name">M6</span> <span class="family-result">実測構成なし · 検証予定／実機待ち</span></summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="M6 デバイス実測と検証計画">
<table><thead><tr><th scope="col">チップ／構成</th><th scope="col">状態</th><th scope="col">オフラインのローカル速度</th><th scope="col">比較対象／改善率</th><th scope="col">証拠</th></tr></thead><tbody>
<tr><th scope="row">M6 · GPU／メモリ構成は未検証</th><td>検証予定／実機待ち</td><td>未測定</td><td>—</td><td>未測定</td></tr>
</tbody></table></div>
<p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">M6 デバイス検証計画</a> · <a href="https://www.apple.com/newsroom/2026/08/apple-introduces-m6-and-m5-ultra-for-a-big-leap-in-performance-and-ai-compute/">Apple 発表資料</a></p>
<p class="device-note">将来の仮枠のみ。2026-10-30 時点で Apple の発売発表を確認できない名称：M6 Pro, M6 Max, M6 Ultra。実在や互換性を示すものではありません。</p>
</details>
<div class="matrix-notes">
<p>速度はローカル・オフラインの PRL プロトコル処理量であり、プール速度、報酬、コンセント電力効率ではありません。M1 Max の +7.82% は本プロジェクトの Alpha 2 を対照とした同条件60秒平均（4.234368 対 3.927237 TH/s）です。別の300秒実測は4.2347 TH/s。M2 の +260.8%／3.61倍は同条件300秒（1.465227 対 0.406127 TH/s）で、元の GPU カーネルを維持した pearl-metal-miner 0.2.4＋cert3 互換修正が対照です。異なる基準でシリーズ全体を順位付けできません。</p>
<p>M2 のプール検証は別の80%強度・600秒試験で、受理3／拒否0。100%強度では外部試験の95°C停止基準に達しました。この温度基準は製品内蔵機能でも Apple の損傷限界でもありません。この実測ノートでは --intensity 80 を使用してください。少数のシェアは長期速度や収益を保証しません。</p>
</div>
<p class="matrix-invitation">別の構成の Mac をお持ちですか？実機検証への協力を歓迎します。ビルドやセルフテストの失敗も有用な結果です。正確なチップ、GPU コア数、メモリ、macOS、マイナーバージョン、強度、コマンド、測定時間と匿名化ログを添えてください。失敗を解消してから採掘し、ウォレットの秘密情報は公開しないでください。</p>
<p class="matrix-feedback"><a href="https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=device-result.yml">デバイス実測に貢献</a> · <a href="https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=benchmark-discrepancy.yml">数値が違いますか？問題を報告</a></p>
<div id="community-testing" class="matrix-roadmap community-testing"><h3>お使いの Mac の検証に協力しませんか？</h3><p>実験的な比較ツールは main 開発プレビュー（0.1.0a4.dev1）に含まれます。Alpha 3 リリースにはありません。新しいディレクトリに main を取得し、sh bootstrap.sh を実行してください。詳しい手順はガイドを参照してください。</p><pre><code>.venv/bin/pearl-m-miner compare --plan
.venv/bin/pearl-m-miner compare --against pearl-metal-miner --output ./my-comparison</code></pre><p>まず計画を確認します。開始には確認が必要です。各60秒をバックエンドごとに2回、A/B/B/A 順で測定し、各回の前に30秒冷却します。ビルド、ウォームアップ、正当性検査の時間も必要です。固定版 pearl-metal-miner 0.2.4＋cert3 互換修正とのオフライン新規準備・走査比較です。ウォレット、プール、自動アップロードは使いません。遅い結果や失敗も歓迎します。表への掲載には審査が必要です。</p><p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/COMMUNITY_TESTING.md">導入・比較・共有前の確認ガイド</a> · <a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/COMPARATORS.md">比較対象の調査と制約</a></p></div>
<div class="matrix-roadmap"><h3>今後の検証</h3><p>日程や対応を確約しない検証優先項目：</p><ol><li>発売済み M1–M6 の個別構成で実機検証を拡大。</li><li>チップ・構成ごとの最適化と独立した検証。</li><li>長時間運転、温度制御と安定性の測定。</li><li>インストール、診断と再現可能なセルフテストの改善。</li><li>遅い結果や失敗も含め、コミュニティの A/B 実測を審査し、差異を調査。</li></ol><p><a href="https://github.com/parkerkyle-max/pearl-m-miner/blob/main/docs/ROADMAP.md">ロードマップ全文</a> · <a href="https://parkerkyle-max.github.io/pearl-m-miner/device-results.json">機械可読デバイスデータ</a></p></div>
</section>
<!-- /device-results -->

<a id="part-5"></a>

## 実測値

Alpha 2 の対照平均は **3.9272 TH/s**、候補 2 回の平均は **4.2344 TH/s**、採用版の 300 秒測定は **4.2347 TH/s** でした。公式証明 28 件、実運用サイズの証明 4 件、独立したスキャン検査 512 件を通過しました。別の運用セッションは **受理 1／拒否 0**。短期間のシェア数は正確なプール速度ではありません。コンセント電力と純利益は未測定です。

以前の M1 Max の **30–32%** は、最適化済みの 2.93–2.97 TH/s に対する改善です。M1 の上流実装や Pearly の過去データとは測定期間が異なります。新しい M2 の同条件比較は下記のとおりで、Pearly は再測定していません。

[Data / 数据 / データ / 데이터](M1_CEILING_20261030.md) · [Live evidence](data/m1-pair32-live.json) · [Historical comparisons](PERFORMANCE.md)

<!-- m2-results -->
### M2：同条件での 300 秒比較

M2（10 コア GPU、24 GiB、macOS 27.0）で、変更していない Alpha 3 の既定設定は **1.4652 TH/s**、pearl-metal-miner 0.2.4 に cert3 互換パッチを適用し GPU カーネルを維持した対照は **0.4061 TH/s** でした。比率は **3.61 倍（260.8% 向上）**です。双方とも M=8192／N=16384、CPU 補助スレッド 2 本、測定 300 秒です。他の候補に再現性のある優位性がなかったため、現行カーネルと既定値を維持しました。

![M2 comparison](../assets/m2-comparison.png)

これは新しいジョブの準備を含むオフライン速度で、入金額ではありません。開発者時間 1% を理想的に差し引いた処理能力は約 1.4506 TH/s ですが、実測の純利益ではありません。電力はソフトウェア計測で、コンセント計測ではありません。プール試験、証明検査、条件付き演算上限は詳細レポートに記録しています。他の M2 構成と M3–M5 は別途検証が必要です。 **温度上の制限：** 最初の強度 100% のプール試験は約 2 分後に試験用 95°C ガードで停止しました（受理 2、拒否 0）。再試験は双方とも 10 分間、**強度 80%** です。このノート PC では `--intensity 80` から始めてください。1.4652 TH/s はオフライン測定で、持続的な実採掘速度の保証ではありません。

```sh
.venv/bin/pearl-m-miner mine --pool luckypool \
  --address YOUR_PUBLIC_PRL_ADDRESS --worker my-m2 \
  --intensity 80 --time-limit 600
```

[Data / 数据 / データ / 데이터](M2_VALIDATION_20261030.md)
<!-- /m2-results -->

<a id="part-6"></a>

## 開発者支援と受取アドレス

開発者支援の 1% は、機器テスト、正確性検証、保守に使われます。設定を維持していただけると助かります。**任意であり、`--dev-fee 0` で無効化できます。** ライセンス条件や収入の 1% という意味ではありません。プール手数料は別です。通常、ユーザーの有効スキャン 3564 秒の後に開発者向け 36 秒を実行します。待機、停止、古いジョブの時間は加算しません。開発者分は独立した LuckyPool セッションです。

開発者の公開 PRL 受取アドレス（ユーザー自身の受取先とは別）：

```text
prl1pwjessemugthkad9hkttcx2rvenux2q0w0xcah2j0a7zfrycjhz5qhn7apw
```

`pearl-m-miner info` または `pearl_m_miner/devfee.py` で確認できます。ご自身の報酬は `--address` に従います。このアドレスに送られるのは任意の開発者分です。LuckyPool で公開アドレスを検索するとプール側の統計を確認できます。オンチェーンの入金は同期済みの対応ウォレットで確認してください。プール残高とウォレット残高は同じではありません。

[Fee details](DEV_FEE.md) · [Wallet / pool guide](WALLET_AND_PAYOUTS.md)

<a id="part-7"></a>

## AI アシスタントと貢献

機械可読マニフェストと AI 導入ガイドを用意しています。採掘の許可と公開受取情報をユーザーから得てください。開発者アドレスへの置き換え、手数料の非表示、無断の採掘開始は行わないでください。検索順位、AI による推薦、収益、プールの公認は保証しません。

[AI setup](AI_SETUP.md) · [llms.txt](../llms.txt) · [JSON manifest](miner-manifest.json) · [FAQ](FAQ.md)

[Strata study](STRATA_REVIEW.md) · [Roadmap](ROADMAP.md) · [Compatibility](COMPATIBILITY.md) · [Contributing](../CONTRIBUTING.md)

変更・追加部分の著作権：2026 parkerkyle-max。Apache-2.0。上流の帰属情報は NOTICE に保持しています。pearl-metal-miner の派生版であり、Pearl Research Labs、Apple、Pearly、Strata とは提携していません。Strata の推論性能をマイニング性能として扱っていません。

[LICENSE](../LICENSE) · [NOTICE](../NOTICE) · [Changelog](../CHANGELOG.md)

[Alpha 3 validation](ALPHA3_VALIDATION.md) · [Documentation website](https://parkerkyle-max.github.io/pearl-m-miner/)
