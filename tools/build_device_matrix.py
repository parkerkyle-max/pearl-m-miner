"""Render the configuration-specific device evidence matrix into four languages.

No network access or mining. Run again after editing docs/device-results.json.
Only the bounded device-results marker blocks are replaced on subsequent runs.
"""
from pathlib import Path
import argparse
import html
import json
import re

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/parkerkyle-max/pearl-m-miner"
START = "<!-- device-results -->"
END = "<!-- /device-results -->"
E = html.escape

COPY = {
    "en": {
        "title": "Device results and testing plans", "requirements": "Requirements",
        "intro": "Expand a family to see exact configurations. Results apply only to configurations marked as measured, never an entire chip family. Published, untested devices are planned tests awaiting hardware, not verified compatibility.",
        "headers": ["Chip / configuration", "Status", "Offline local rate", "Comparison / improvement", "Evidence"],
        "measured": "Measured configuration", "planned": "Planned testing / awaiting hardware", "unmeasured": "Not measured", "other": "other GPU / memory configurations", "unspecified": "GPU / memory configuration not yet tested",
        "best": "best measured within this comparison group", "none": "No measured configuration · planned testing / awaiting hardware",
        "versus": "vs", "means": "matched means", "seconds": "s", "offline": "offline", "our": "our Alpha 2 backend; not upstream",
        "report": "Methods / report", "receipt": "Evidence receipt", "source": "Apple release source", "plan": "device validation plan",
        "future": "No Apple release confirmed as of 2026-10-30: {chips}. Unconfirmed planning slots; not product announcements or compatibility claims.",
        "footnote": "All rates are local offline PRL protocol throughput, not pool hashrate, payouts or wall-power efficiency. M1 Max +7.82% uses matched 60-second means (4.234368 vs 3.927237 TH/s) against this project's Alpha 2; its separate 300-second rate is 4.2347 TH/s. M2 +260.8% / 3.61× uses matched 300-second runs (1.465227 vs 0.406127 TH/s) against pearl-metal-miner 0.2.4 with cert3 compatibility and unchanged upstream GPU kernels. These baselines differ and cannot rank whole families.",
        "thermal": "M2 pool evidence is a separate 600-second test at 80% intensity: 3 accepted / 0 rejected. The 100% live attempt reached an external laboratory 95°C stop guard; that Celsius guard is not a shipped miner feature or an Apple damage threshold. Use --intensity 80 on this tested laptop. Short share counts do not establish sustained pool speed or income.",
        "roadmap": "Next validation work", "roadmap_intro": "Testing priorities, without promised dates or guaranteed support:",
        "steps": ["Expand real-device coverage across released M1–M6 configurations.", "Tune and verify each chip configuration independently.", "Measure longer runs, temperature behavior and stable operation.", "Improve installation, diagnostics and reproducible self-tests.", "Collect community evidence and investigate reproducible discrepancies."],
        "invitation": "Have another Mac configuration? Help test it and contribute your result, including failed builds or self-tests. Include the exact chip, GPU cores, memory, macOS, miner version, intensity, command, test duration and sanitized logs. A failed check must be resolved before mining; never publish wallet secrets.",
        "full_plan": "Full roadmap", "feedback": "Different numbers? Report a problem", "submit": "Contribute a device measurement", "data": "Machine-readable device data",
    },
    "zh": {
        "title": "设备实测与测试计划", "requirements": "运行要求",
        "intro": "展开系列查看具体配置。只有标记为已实测的具体配置有成绩，结果不代表整个芯片系列。已发布但未测的设备列入测试计划、等待设备，不代表已验证兼容。",
        "headers": ["芯片／具体配置", "状态", "离线本地速率", "对照与增幅", "证据"],
        "measured": "该配置已实测", "planned": "计划测试／等待设备", "unmeasured": "未测", "other": "其他 GPU／内存配置", "unspecified": "GPU／内存配置尚未实测",
        "best": "仅同基线／范围已测配置的最高增幅", "none": "暂无实测配置 · 计划测试／等待设备",
        "versus": "对照", "means": "同条件均值", "seconds": "秒", "offline": "离线", "our": "本项目 Alpha 2 后端；不是上游",
        "report": "方法与报告", "receipt": "原始证据", "source": "Apple 发布来源", "plan": "设备验证计划",
        "future": "仅作未来占位，截至 2026-10-30 未确认 Apple 已发布：{chips}。不表示这些设备已经存在或已获兼容支持。",
        "footnote": "以上均为本地离线 PRL 协议吞吐，不是矿池算力、到账收益或插座能效。M1 Max 的 +7.82% 来自同条件 60 秒均值（4.234368 对 3.927237 TH/s），对照本项目 Alpha 2；另一次 300 秒长测为 4.2347 TH/s。M2 的 +260.8%／3.61 倍来自同条件 300 秒测试（1.465227 对 0.406127 TH/s），对照 pearl-metal-miner 0.2.4 加 cert3 兼容补丁，保留原 GPU 内核。两种基线不同，不能据此给整个系列排名。",
        "thermal": "M2 矿池证据另来自 80% 强度、600 秒试跑：3 接受／0 拒绝。100% 强度实挖曾触发外部试验设置的 95°C 停机线；该摄氏温度线不是矿工内置功能，也不是 Apple 损坏阈值。该已测笔记本请使用 --intensity 80。少量份额不能证明长期矿池速度或收益。",
        "roadmap": "接下来的验证工作", "roadmap_intro": "以下为测试优先方向，不承诺日期或保证支持：",
        "steps": ["扩充已发布 M1–M6 各具体配置的真机覆盖。", "逐芯片、逐配置优化并独立验证。", "补充长时间运行、温控与稳定性测量。", "完善安装、诊断和可重复的本机自测。", "收集社区证据，调查可复现的数据差异。"],
        "invitation": "你有其他配置的 Mac 吗？欢迎帮忙测试并贡献实测，构建或自测失败的结果也欢迎。请提供准确芯片、GPU 核数、内存、macOS、矿工版本、强度、命令、测试时长和脱敏日志。自测失败应先解决再挖矿，不要公开钱包恢复资料。",
        "full_plan": "完整路线图", "feedback": "数字有偏差？反馈问题", "submit": "贡献设备实测", "data": "机器可读设备数据",
    },
    "ja": {
        "title": "デバイス実測と検証計画", "requirements": "動作要件",
        "intro": "各シリーズを開くと個別構成を確認できます。結果は実測済みと記した構成のみのもので、シリーズ全体を代表しません。発売済みの未測定機種は実機待ちの検証予定であり、互換性の確認済みを意味しません。",
        "headers": ["チップ／構成", "状態", "オフラインのローカル速度", "比較対象／改善率", "証拠"],
        "measured": "この構成を実測", "planned": "検証予定／実機待ち", "unmeasured": "未測定", "other": "その他の GPU／メモリ構成", "unspecified": "GPU／メモリ構成は未検証",
        "best": "同じ比較条件で実測した構成の最大改善率", "none": "実測構成なし · 検証予定／実機待ち",
        "versus": "比較対象", "means": "同条件の平均", "seconds": "秒", "offline": "オフライン", "our": "本プロジェクトの Alpha 2 バックエンド；上流ではありません",
        "report": "方法・レポート", "receipt": "検証記録", "source": "Apple 発表資料", "plan": "デバイス検証計画",
        "future": "将来の仮枠のみ。2026-10-30 時点で Apple の発売発表を確認できない名称：{chips}。実在や互換性を示すものではありません。",
        "footnote": "速度はローカル・オフラインの PRL プロトコル処理量であり、プール速度、報酬、コンセント電力効率ではありません。M1 Max の +7.82% は本プロジェクトの Alpha 2 を対照とした同条件60秒平均（4.234368 対 3.927237 TH/s）です。別の300秒実測は4.2347 TH/s。M2 の +260.8%／3.61倍は同条件300秒（1.465227 対 0.406127 TH/s）で、元の GPU カーネルを維持した pearl-metal-miner 0.2.4＋cert3 互換修正が対照です。異なる基準でシリーズ全体を順位付けできません。",
        "thermal": "M2 のプール検証は別の80%強度・600秒試験で、受理3／拒否0。100%強度では外部試験の95°C停止基準に達しました。この温度基準は製品内蔵機能でも Apple の損傷限界でもありません。この実測ノートでは --intensity 80 を使用してください。少数のシェアは長期速度や収益を保証しません。",
        "roadmap": "今後の検証", "roadmap_intro": "日程や対応を確約しない検証優先項目：",
        "steps": ["発売済み M1–M6 の個別構成で実機検証を拡大。", "チップ・構成ごとの最適化と独立した検証。", "長時間運転、温度制御と安定性の測定。", "インストール、診断と再現可能なセルフテストの改善。", "コミュニティの実測収集と再現可能な差異の調査。"],
        "invitation": "別の構成の Mac をお持ちですか？実機検証への協力を歓迎します。ビルドやセルフテストの失敗も有用な結果です。正確なチップ、GPU コア数、メモリ、macOS、マイナーバージョン、強度、コマンド、測定時間と匿名化ログを添えてください。失敗を解消してから採掘し、ウォレットの秘密情報は公開しないでください。",
        "full_plan": "ロードマップ全文", "feedback": "数値が違いますか？問題を報告", "submit": "デバイス実測に貢献", "data": "機械可読デバイスデータ",
    },
    "ko": {
        "title": "기기 실측 및 테스트 계획", "requirements": "실행 요구 사항",
        "intro": "각 시리즈를 펼쳐 구체적인 구성을 확인하세요. 결과는 실측으로 표시한 구성에만 적용되며 시리즈 전체를 대표하지 않습니다. 출시됐지만 미측정인 기기는 테스트 계획에 포함되어 기기를 기다리는 상태이며 호환성 검증을 의미하지 않습니다.",
        "headers": ["칩／구체적 구성", "상태", "오프라인 로컬 속도", "비교 기준／향상률", "근거"],
        "measured": "해당 구성 실측", "planned": "테스트 예정／기기 대기", "unmeasured": "미측정", "other": "다른 GPU／메모리 구성", "unspecified": "GPU／메모리 구성 미검증",
        "best": "동일 비교 기준／범위에서 실측한 구성 중 최대 향상률", "none": "실측 구성 없음 · 테스트 예정／기기 대기",
        "versus": "비교 기준", "means": "동일 조건 평균", "seconds": "초", "offline": "오프라인", "our": "본 프로젝트 Alpha 2 백엔드; 업스트림 아님",
        "report": "방법 및 보고서", "receipt": "검증 기록", "source": "Apple 출시 자료", "plan": "기기 검증 계획",
        "future": "미래 자리표시자일 뿐이며 2026-10-30 기준 Apple 출시 발표가 확인되지 않은 이름: {chips}. 실재 기기 또는 호환성 지원을 의미하지 않습니다.",
        "footnote": "모든 속도는 로컬 오프라인 PRL 프로토콜 처리량이며 풀 해시레이트, 지급 수익 또는 벽면 전력 효율이 아닙니다. M1 Max +7.82%는 본 프로젝트 Alpha 2와 동일 조건 60초 평균(4.234368 대 3.927237 TH/s)을 비교합니다. 별도 300초 실측은 4.2347 TH/s입니다. M2 +260.8%／3.61배는 동일 조건 300초 실측(1.465227 대 0.406127 TH/s)이며, 원본 GPU 커널을 유지한 pearl-metal-miner 0.2.4＋cert3 호환 패치가 기준입니다. 비교 기준이 달라 시리즈 전체의 순위로 해석할 수 없습니다.",
        "thermal": "M2 풀 근거는 별도의 강도 80%·600초 테스트에서 수락 3／거절 0입니다. 강도 100% 실채굴은 외부 실험의 95°C 중단 기준에 도달했습니다. 이 섭씨 기준은 내장 기능이나 Apple 손상 한계가 아닙니다. 해당 실측 노트북에서는 --intensity 80을 사용하세요. 적은 셰어 수는 장기 풀 속도나 수익을 입증하지 않습니다.",
        "roadmap": "다음 검증 작업", "roadmap_intro": "일정이나 지원을 보장하지 않는 테스트 우선순위:",
        "steps": ["출시된 M1–M6의 구체적 구성별 실기기 검증 확대.", "칩과 구성별 최적화 및 독립 검증.", "장시간 실행, 온도 제어와 안정성 측정.", "설치, 진단과 재현 가능한 자체 테스트 개선.", "커뮤니티 실측 수집 및 재현 가능한 차이 조사."],
        "invitation": "다른 구성의 Mac이 있나요? 테스트에 참여해 실측을 공유해 주세요. 빌드 또는 자체 테스트 실패도 환영합니다. 정확한 칩, GPU 코어 수, 메모리, macOS, 채굴기 버전, 강도, 명령, 테스트 시간과 민감 정보를 지운 로그를 포함해 주세요. 실패한 검사를 해결한 뒤 채굴하고 지갑 복구 정보는 공개하지 마세요.",
        "full_plan": "전체 로드맵", "feedback": "수치가 다른가요? 문제 보고", "submit": "기기 실측 기여", "data": "기계 판독용 기기 데이터",
    },
}

INTRO_FIXUPS = {
    'en': ('M1 Max: 4.2347 TH/s in a 300-second offline test, +7.82% versus our previous Alpha 2 backend.', 'M1 Max: 4.2347 TH/s in a 300-second offline test. A separate matched comparison of 60-second means showed +7.82% versus our Alpha 2 backend.'),
    'zh': ('M1 Max 在 300 秒离线测试中达到 4.2347 TH/s，相对我们此前 Alpha 2 后端提升 7.82%。', 'M1 Max 在 300 秒离线测试中达到 4.2347 TH/s。另一次同条件 60 秒均值对照，相比本项目 Alpha 2 后端提升 7.82%。'),
    'ja': ('M1 Max の 300 秒オフライン測定で 4.2347 TH/s、従来の Alpha 2 バックエンド比で 7.82% 向上しました。', 'M1 Max の 300 秒オフライン測定は 4.2347 TH/s。別の同条件 60 秒平均の比較では、本プロジェクトの Alpha 2 バックエンド比で 7.82% 向上しました。'),
    'ko': ('M1 Max의 300초 오프라인 측정에서 4.2347 TH/s를 기록했으며, 기존 Alpha 2 백엔드보다 7.82% 빨랐습니다.', 'M1 Max의 300초 오프라인 측정은 4.2347 TH/s입니다. 별도의 동일 조건 60초 평균 비교에서는 본 프로젝트 Alpha 2 백엔드보다 7.82% 향상됐습니다.'),
}


def link(url, label):
    return f'<a href="{E(url, quote=True)}">{E(label)}</a>'


def config(result):
    return f"{result['chip']} · {result['gpu_cores']} GPU cores / {result['memory_gib']} GiB"


def comparison(result, text):
    c = result["comparison"]
    baseline = text["our"] if c["baseline"] == "Pearl M-Miner Alpha 2" else c["baseline"]
    ratio = f" / {c['ratio']:.2f}×" if "ratio" in c else ""
    gain = f"{c['improvement_percent']:.2f}".rstrip("0").rstrip(".")
    return (f"+{gain}%{ratio} · {text['versus']} {baseline} "
            f"({c['duration_seconds']} {text['seconds']} {text['means']}: "
            f"{c['candidate_mean_ths']:.6f} / {c['baseline_mean_ths']:.6f} TH/s)")


def compact_comparison(result, text):
    c = result['comparison']
    # Full baseline values and exact device configuration stay in the table.
    baseline = c['baseline'].replace(' compatibility', '')
    if c['baseline'] == 'Pearl M-Miner Alpha 2':
        baseline = {'en': 'our Alpha 2 (not upstream)', 'zh': '本项目 Alpha 2（非上游）', 'ja': '本プロジェクト Alpha 2（上流ではない）', 'ko': '본 프로젝트 Alpha 2（업스트림 아님）'}[next(lang for lang, value in COPY.items() if value is text)]
    ratio = f" / {c['ratio']:.2f}×" if 'ratio' in c else ''
    gain = f"{c['improvement_percent']:.2f}".rstrip('0').rstrip('.')
    return f"{result['chip']}: +{gain}%{ratio} · {text['versus']} {baseline} · {c['duration_seconds']} {text['seconds']} · {text['best']}"


def validate(data):
    if [f["name"] for f in data["families"]] != [f"M{i}" for i in range(1, 7)]:
        raise ValueError("Expected exactly M1 through M6 in order")
    for family in data["families"]:
        for device in family["devices"]:
            if device["status"] == "measured":
                result = data["results"][device["result"]]
                if result["chip"] != device["chip"]:
                    raise ValueError("Result attached to the wrong chip")
                for evidence in result["evidence"]:
                    if not (ROOT / evidence).is_file():
                        raise ValueError(f"Missing evidence: {evidence}")
            elif device["status"] != "planned" or device.get("rate_ths", "missing") is not None:
                raise ValueError("Unmeasured devices must explicitly have a null rate")


def render(data, lang):
    t = COPY[lang]
    out = [START, '<a id="device-results"></a>', '<section class="device-matrix">', f'<h2>{E(t["title"])}</h2>', f'<p>{E(t["intro"])}</p>']
    for family in data["families"]:
        measured = [data["results"][d["result"]] for d in family["devices"] if d["status"] == "measured"]
        summary = t["none"]
        if measured:
            # Compare gains only inside identical baseline + matched-scope cohorts.
            # New, incomparable baselines get their own summary, never one winner.
            cohorts = {}
            for result in measured:
                c = result["comparison"]
                key = (c["baseline"], c["baseline_is_upstream"], c["duration_seconds"], c["matched_scope"])
                cohorts.setdefault(key, []).append(result)
            summaries = []
            for cohort in cohorts.values():
                best = max(cohort, key=lambda r: r["comparison"]["improvement_percent"])
                summaries.append(compact_comparison(best, t))
            summary = ' ; '.join(summaries)
        out += [f'<details class="device-family" id="device-{family["name"].lower()}">', f'<summary><span class="family-name">{E(family["name"])}</span> <span class="family-result">{E(summary)}</span></summary>', '<div class="table-scroll" tabindex="0" role="region" aria-label="'+E(family["name"]+' '+t["title"], quote=True)+'">', '<table><thead><tr>'+''.join(f'<th scope="col">{E(h)}</th>' for h in t["headers"])+'</tr></thead><tbody>']
        for device in family["devices"]:
            if device["status"] == "measured":
                r = data["results"][device["result"]]
                name = config(r)
                rate_number = f'{r["rate_ths"]:.6f}'.rstrip('0').rstrip('.')
                rate = f'{rate_number} TH/s · {r["duration_seconds"]} {t["seconds"]} · {t["offline"]}'
                status = t["measured"]+' · '+r['measured_on']+' · macOS '+r['macos']
                delta = comparison(r, t)
                evidence = ' · '.join(link(REPO+'/blob/main/'+p, t["report"] if i == 0 else t["receipt"]) for i, p in enumerate(r["evidence"]))
            else:
                name = device["chip"]+' · '+t["other" if device.get("configuration") == "other" else "unspecified"]
                status, rate, delta, evidence = t["planned"], t["unmeasured"], '—', E(t["unmeasured"])
            out.append('<tr><th scope="row">'+E(name)+'</th><td>'+E(status)+'</td><td>'+E(rate)+'</td><td>'+E(delta)+'</td><td>'+evidence+'</td></tr>')
        out += ['</tbody></table></div>']
        sources = [family["release_source"]] + family.get("additional_release_sources", [])
        out.append('<p>'+link(REPO+'/blob/main/docs/ROADMAP.md', family["name"]+' '+t["plan"])+' · '+' · '.join(link(url, t["source"]+(f' {i+1}' if len(sources)>1 else '')) for i,url in enumerate(sources))+'</p>')
        if family["unconfirmed_placeholders"]:
            out.append('<p class="device-note">'+E(t["future"].format(chips=', '.join(family["unconfirmed_placeholders"])))+'</p>')
        out.append('</details>')
    out += [
        '<div class="matrix-notes">',
        '<p>'+E(t["footnote"])+'</p>', '<p>'+E(t["thermal"])+'</p>', '</div>',
        '<p class="matrix-invitation">'+E(t["invitation"])+'</p>',
        '<p class="matrix-feedback">'
        +link(REPO+'/issues/new?template=device-result.yml',t["submit"])+' · '
        +link(REPO+'/issues/new?template=benchmark-discrepancy.yml',t["feedback"])+'</p>',
        '<div class="matrix-roadmap"><h3>'+E(t["roadmap"])+'</h3><p>'
        +E(t["roadmap_intro"])+'</p><ol>'
        +''.join('<li>'+E(step)+'</li>' for step in t["steps"])+'</ol><p>'
        +link(REPO+'/blob/main/docs/ROADMAP.md',t["full_plan"])+' · '
        +link('https://parkerkyle-max.github.io/pearl-m-miner/device-results.json',t["data"])
        +'</p></div>', '</section>', END,
    ]
    return '\n'.join(out)


def update(path, block, anchor, check, lang):
    source = path.read_text(encoding='utf-8')
    if START in source or END in source:
        if source.count(START) != 1 or source.count(END) != 1:
            raise ValueError(f"Ambiguous device matrix markers: {path}")
        updated = re.sub(re.escape(START)+r'.*?'+re.escape(END), lambda _: block, source, flags=re.S)
    else:
        if source.count(anchor) != 1:
            raise ValueError(f"Expected one insertion anchor in {path}: {anchor}")
        updated = source.replace(anchor, block+'\n\n'+anchor, 1)
    updated = updated.replace(*INTRO_FIXUPS[lang])
    # Update only the current requirements; do not change a second range on reruns.
    requirement = re.escape(COPY[lang]['requirements'])
    if path.suffix == '.html':
        pattern = rf'(<h2>{requirement}</h2>)(.*?)(?=<h2>|\Z)'
    else:
        pattern = rf'(## {requirement}\n)(.*?)(?=\n## |\Z)'
    updated = re.sub(pattern, lambda m: m[1]+m[2].replace('M3–M5', 'M3–M6'), updated, flags=re.S)
    updated = updated.replace('vs our Alpha 2 backend</span>', '60 s matched means · vs our Alpha 2</span>')
    if source != updated:
        if check:
            raise ValueError(f"Generated matrix is stale: {path.relative_to(ROOT)}")
        path.write_text(updated, encoding='utf-8', newline='\n')
    print(('checked ' if check else 'rendered ')+str(path.relative_to(ROOT)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify generated blocks without writing')
    args = parser.parse_args()
    data = json.loads((ROOT/'docs/device-results.json').read_text(encoding='utf-8'))
    validate(data)
    paths = {'en': ('README.md','docs/index.html'), 'zh': ('docs/README.zh-CN.md','docs/zh/index.html'), 'ja': ('docs/README.ja.md','docs/ja/index.html'), 'ko': ('docs/README.ko.md','docs/ko/index.html')}
    for lang, (readme, homepage) in paths.items():
        block = render(data, lang)
        update(ROOT/readme, block, '<a id="part-5"></a>', args.check, lang)
        update(ROOT/homepage, block, '<h2>'+COPY[lang]['requirements']+'</h2>', args.check, lang)


if __name__ == '__main__':
    main()
