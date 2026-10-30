<p align="center"><img src="../assets/hero.svg" alt="Pearl M-Miner — Apple Silicon Metal GPU" width="100%"></p>

[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

# Pearl M-Miner — Apple Silicon 向け Pearl（PRL）マイナー

M シリーズ Mac 向けのオープンソース Metal GPU マイナーです。**M1 Max の 300 秒オフライン測定で 4.2347 TH/s、従来の Alpha 2 バックエンド比で 7.82% 向上しました。** 別の実運用セッションでは Kryptex が gzip シェアを受理しました。これらは別々の測定であり、収益を保証しません。

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

**実験的なソース版 v0.1.0-alpha.3（パッケージ 0.1.0a3）**。Apple Silicon、**macOS 26+**、ネイティブ arm64 **Python 3.12+**、Metal 4 対応 Command Line Tools、Git、Rust/Cargo が必要です。実測済みは M1 Max のみです。他の M1 モデルおよび M2–M5 は実験対象で、各端末で自己テストとプール検証が必要です。CPU、ANE、他のコインのマイニングは未提供です。

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

<a id="part-5"></a>

## 実測値

Alpha 2 の対照平均は **3.9272 TH/s**、候補 2 回の平均は **4.2344 TH/s**、採用版の 300 秒測定は **4.2347 TH/s** でした。公式証明 28 件、実運用サイズの証明 4 件、独立したスキャン検査 512 件を通過しました。別の運用セッションは **受理 1／拒否 0**。短期間のシェア数は正確なプール速度ではありません。コンセント電力と純利益は未測定です。

以前の **30–32%** は、すでに最適化した 2.93–2.97 TH/s に対する改善です。上流や Pearly の過去データとは測定期間が異なります。本版での同条件比較や M2–M5 の性能向上は確認していません。

[Data / 数据 / データ / 데이터](M1_CEILING_20261030.md) · [Live evidence](data/m1-pair32-live.json) · [Historical comparisons](PERFORMANCE.md)

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
