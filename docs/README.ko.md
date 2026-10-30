<p align="center"><img src="../assets/hero.svg" alt="Pearl M-Miner — Apple Silicon Metal GPU" width="100%"></p>

[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

# Pearl M-Miner — Apple Silicon용 Pearl(PRL) 채굴기

M 시리즈 Mac을 위한 오픈 소스 Metal GPU 채굴기입니다. **M1 Max의 300초 오프라인 측정에서 4.2347 TH/s를 기록했으며, 기존 Alpha 2 백엔드보다 7.82% 빨랐습니다.** 별도의 실제 운영 세션에서는 Kryptex가 gzip share를 승인했습니다. 서로 다른 측정 결과이며 수익을 보장하지 않습니다.

[주요 기능](#part-1) · [실행 요구 사항](#part-2) · [빌드 및 검증](#part-3) · [채굴 시작](#part-4) · [측정 결과](#part-5) · [개발자 후원 및 수령 주소](#part-6) · [AI 도우미 및 기여](#part-7)

<a id="part-1"></a>

## 주요 기능

- 정확한 정수 계산을 검증하는 prefix/S 행렬 GPU 백엔드와 공식 증명 검증.
- Kryptex gzip-v2 협상 및 LuckyPool 지원.
- 로컬 속도, 승인/거절 share, 작업 상태 표시.
- 기본값은 **유효한 GPU 스캔 시간의 1%**이며 끌 수 있습니다.
- 포그라운드 실행. 백그라운드 서비스나 자동 시작을 설치하지 않습니다.

<a id="part-2"></a>

## 실행 요구 사항

**실험용 소스 릴리스 v0.1.0-alpha.3(패키지 0.1.0a3)**. Apple Silicon, **macOS 26+**, 네이티브 arm64 **Python 3.12+**, Metal 4 Command Line Tools, Git 및 Rust/Cargo가 필요합니다. 실제 측정을 완료한 기기는 M1 Max입니다. 다른 M1 모델과 M2–M5는 각 기기에서 자체 테스트와 풀 검증이 필요합니다. CPU, ANE 및 다른 코인의 채굴은 아직 제공하지 않습니다.

<a id="part-3"></a>

## 빌드 및 검증

```sh
git clone --branch v0.1.0-alpha.3 --depth 1 https://github.com/parkerkyle-max/pearl-m-miner.git
cd pearl-m-miner
sh bootstrap.sh
.venv/bin/pearl-m-miner info --json
.venv/bin/pearl-m-miner doctor
.venv/bin/pearl-m-miner self-test
.venv/bin/pearl-m-miner benchmark --seconds 60
```

bootstrap은 고정된 공식 증명 확장 모듈을 빌드하고 저장소 안에 가상 환경을 만듭니다. 채굴 자동 시작은 설정하지 않습니다. 필요하면 `PYTHON=python3.12 sh bootstrap.sh`를 사용하세요. 빌드, 정확성 검사 또는 자체 테스트가 실패하면 먼저 해결해야 합니다. `info --json`은 오프라인 정보를 제공하고 `doctor`는 실제 Mac을 확인합니다. 빌드나 기기가 변경되면 다시 자체 테스트를 실행하세요.

<a id="part-4"></a>

## 채굴 시작

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

자리표시자를 **본인의 공개 수령 정보**로 바꾸세요. Kryptex는 `krx…` mining ID를, LuckyPool은 네이티브 `prl1…` 주소를 사용합니다. 예제는 10분 후 종료됩니다. 계속 실행하려면 `--time-limit`을 생략하며, **Ctrl+C로 중지**합니다. 기본적으로 배터리 사용 중이거나 macOS의 열 압력이 심각할 때 일시 정지합니다. 이는 고정된 섭씨 온도 기준은 아닙니다. 시드, 개인 키, 지갑 비밀번호는 입력하지 마세요.

<a id="part-5"></a>

## 측정 결과

Alpha 2 대조군 평균은 **3.9272 TH/s**, 후보 2회 평균은 **4.2344 TH/s**, 채택 버전의 300초 결과는 **4.2347 TH/s**입니다. 공식 증명 검사 28건, 운영 크기의 증명 검사 4건, 독립 스캔 검사 512건을 통과했습니다. 별도 운영 세션에서는 **승인 1 / 거절 0**을 확인했습니다. 짧은 구간의 share 수는 정확한 풀 해시레이트가 아닙니다. 콘센트 전력과 순수익은 측정하지 않았습니다.

이전의 **30–32%** 향상은 이미 최적화된 2.93–2.97 TH/s 기준과 비교한 수치입니다. 상위 프로젝트나 Pearly의 과거 측정은 기간이 다르며, 이번에 동일 조건으로 재비교한 것이 아닙니다. M2–M5 성능 향상도 검증되지 않았습니다.

[Data / 数据 / データ / 데이터](M1_CEILING_20261030.md) · [Live evidence](data/m1-pair32-live.json) · [Historical comparisons](PERFORMANCE.md)

<a id="part-6"></a>

## 개발자 후원 및 수령 주소

기본 1% 후원은 기기 테스트, 정확성 검증 및 유지 보수에 도움이 됩니다. 사용자와 fork에서 이 설정을 유지해 주시길 바랍니다. **선택 사항이며 `--dev-fee 0`으로 끌 수 있습니다.** 라이선스 조건이나 수입의 1%를 뜻하지 않습니다. 풀 수수료는 별도입니다. 일반적으로 사용자 유효 스캔 3564초 후 개발자 스캔 36초를 수행합니다. 대기, 일시 정지 및 오래된 작업은 누적되지 않습니다. 개발자 작업은 별도의 LuckyPool 세션을 사용합니다.

개발자의 공개 PRL 수령 주소(사용자 본인의 채굴 수령 정보와 별개):

```text
prl1pwjessemugthkad9hkttcx2rvenux2q0w0xcah2j0a7zfrycjhz5qhn7apw
```

`pearl-m-miner info` 또는 `pearl_m_miner/devfee.py`에서 확인할 수 있습니다. 개인 채굴 보상은 `--address`에 지정한 곳으로 연결됩니다. 개발자 주소는 선택적 개발자 작업의 보상만 받습니다. LuckyPool에서 공개 주소를 검색해 풀 통계를 확인하고, 동기화된 지원 지갑에서 온체인 입금을 확인하세요. 풀 잔액과 지갑 잔액은 서로 다릅니다.

[Fee details](DEV_FEE.md) · [Wallet / pool guide](WALLET_AND_PAYOUTS.md)

<a id="part-7"></a>

## AI 도우미 및 기여

기계 판독용 명세와 AI 설치 가이드를 제공합니다. 채굴 허가와 공개 수령 정보를 먼저 사용자에게 받으세요. 개발자 주소로 몰래 바꾸거나 수수료를 숨기거나 허가 없이 채굴을 시작하면 안 됩니다. 검색 순위, AI 추천, 수익 또는 풀의 공식 승인을 보장하지 않습니다.

[AI setup](AI_SETUP.md) · [llms.txt](../llms.txt) · [JSON manifest](miner-manifest.json) · [FAQ](FAQ.md)

[Strata study](STRATA_REVIEW.md) · [Roadmap](ROADMAP.md) · [Compatibility](COMPATIBILITY.md) · [Contributing](../CONTRIBUTING.md)

수정 및 추가 부분 저작권: 2026 parkerkyle-max. Apache-2.0이며 원저작자 표시는 NOTICE에 보존됩니다. pearl-metal-miner의 파생 프로젝트로 Pearl Research Labs, Apple, Pearly 또는 Strata와 제휴하지 않습니다. Strata의 추론 성능을 채굴 성능으로 제시하지 않습니다.

[LICENSE](../LICENSE) · [NOTICE](../NOTICE) · [Changelog](../CHANGELOG.md)

[Alpha 3 validation](ALPHA3_VALIDATION.md) · [Documentation website](https://parkerkyle-max.github.io/pearl-m-miner/)
