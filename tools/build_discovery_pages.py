"""Build static, readable discovery pages; no analytics, network or mining."""
from pathlib import Path
import html
import json
import re
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
SITE = 'https://parkerkyle-max.github.io/pearl-m-miner/'
REPO = 'https://github.com/parkerkyle-max/pearl-m-miner'
escape = html.escape

def inline(text):
    text = escape(text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', lambda m: '<a href="' + (m[2] if m[2].startswith('https://') else REPO+'/blob/main/docs/'+m[2]) + '">' + m[1] + '</a>', text)
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

def page(slug, title, description, body):
    url = SITE + slug + '/'
    schema = {'@context':'https://schema.org', '@type':'WebPage', 'name':title,
              'url':url, 'description':description, 'isPartOf':{'@type':'WebSite','name':'Pearl M-Miner','url':SITE}}
    output = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} | Pearl M-Miner</title><meta name="description" content="{escape(description)}">
<link rel="canonical" href="{url}"><meta property="og:type" content="website"><meta property="og:title" content="{escape(title)}">
<meta property="og:url" content="{url}"><meta property="og:image" content="{SITE}site-assets/social.png">
<meta name="twitter:card" content="summary_large_image"><link rel="stylesheet" href="../site-assets/site.css">
<script type="application/ld+json">{json.dumps(schema)}</script></head>
<body><main><nav aria-label="Project"><a href="{SITE}">Home</a><a href="{SITE}faq/">FAQ</a><a href="{SITE}about/">About &amp; support</a><a href="{SITE}privacy/">Privacy</a><a href="{REPO}">Source code</a></nav>
<h1>{escape(title)}</h1>{body}<footer>Independent Apache-2.0 project by parkerkyle-max. Optional 1% valid GPU scan-time support. No affiliation with Apple, Pearl Research Labs or mining pools.</footer></main></body></html>
'''
    target = DOCS/slug/'index.html';target.parent.mkdir(exist_ok=True);target.write_text(output,encoding='utf-8',newline='\n')

faq=(DOCS/'FAQ.md').read_text(encoding='utf-8')
sections=re.split(r'^## ',faq,flags=re.M)[1:]
body=''
for section in sections:
    question,answer=section.split('\n',1)
    body+='<section><h2>'+escape(question)+'</h2>'
    for paragraph in answer.strip().split('\n\n'):
        body+='<p>'+inline(' '.join(paragraph.splitlines()))+'</p>'
    body+='</section>'
page('faq','Apple Silicon PRL mining: questions and answers',
     'Pearl M-Miner requirements, measured performance, wallets, optional developer fee, stopping and supported hardware.',body)

page('about','About Pearl M-Miner and project support',
     'Who maintains Pearl M-Miner, where to verify its source and benchmarks, and how to report a reproducible problem.',f'''
<p>Pearl M-Miner is an independent open-source Pearl (PRL) GPU miner maintained under the GitHub account <a href="https://github.com/parkerkyle-max">parkerkyle-max</a>. It focuses on exact Metal computation on Apple Silicon. Its implementation is derived from pearl-metal-miner; the repository preserves upstream attribution and license notices.</p>
<p>The source is Apache-2.0. The default developer contribution is optional and uses 1% of completed valid GPU scan time. It is disclosed in the CLI and source, can be disabled with <code>--dev-fee 0</code>, and is not a condition of the license. Support helps fund testing on real hardware, correctness checks and maintenance.</p>
<h2>Evidence before performance claims</h2><p>Read the <a href="{REPO}/blob/main/docs/COMPATIBILITY.md">device qualification table</a> and <a href="{REPO}/blob/main/docs/PERFORMANCE.md">benchmark methods</a>. An offline speed test, an accepted pool share and realized income are different measurements. We do not claim that every M-series chip has been tested.</p>
<h2>Contact and bug reports</h2><p>The public support channel is <a href="{REPO}/issues">GitHub Issues</a>. Include the release, chip/GPU cores, memory, macOS version, exact command with your account removed, and the failing self-test or sanitized log. Do not post wallet recovery material, API credentials, private keys or unrelated process inventories. For sensitive reports, see <a href="{REPO}/blob/main/SECURITY.md">SECURITY.md</a> before posting.</p>
<p>There is no guaranteed support response time, profitability promise, Apple endorsement or mining-pool listing implied by this website.</p>''')

page('privacy','Privacy and network activity',
     'What this static website and the PRL miner do, which commands contact mining pools, and what not to include in public reports.',f'''
<p>This documentation website is static HTML hosted by GitHub Pages. It does not add advertising pixels, analytics scripts, a registration form or an application database. GitHub operates the hosting infrastructure and may process request information under its own policies; this project cannot make promises on GitHub’s behalf.</p>
<h2>Miner commands and network access</h2><p><code>info --json</code> reads public capabilities locally. A benchmark performs local synthetic work; it does not earn coins. The build process downloads dependencies from their documented sources. An explicitly launched <code>mine</code> command connects to the selected mining pool, sends the public mining identity and protocol work, and receives jobs and share responses. The pool sees the connection’s network address.</p>
<p>When the optional developer contribution is enabled, developer work uses a separate, disclosed LuckyPool connection. It does not require your wallet seed, private key or wallet password. The miner does not manage wallet recovery or exchange withdrawals. Pool operators have their own retention and payment rules.</p>
<h2>Local and public records</h2><p>Self-test and fee-accounting records are local. Console logs may contain public payout identities and worker names. Remove those and local filesystem paths before sharing logs. Published performance evidence is sanitized and does not include private host inventories or reusable access credentials. See the <a href="{REPO}/blob/main/docs/AI_SETUP.md">AI installation guide</a> for the authorized setup sequence.</p>''')

shutil.copyfile(ROOT/'assets/hero-preview.png',DOCS/'site-assets/social.png')
m2_path=DOCS/'data/m2-validation-20261030.json'
if m2_path.exists():
    m2_data=json.loads(m2_path.read_text(encoding='utf-8'));m2=m2_data['headline']
    live_rows=''.join('<tr><th scope="row">'+escape(t['label'])+'</th><td>'+f"{t['final_session']['rounded_local_ths']:.4f} TH/s"+'</td><td>'+f"{t['software_telemetry']['mean_sys_w']:.2f} W"+'</td><td>'+f"{t['accepted']} / {t['rejected']}"+'</td></tr>' for t in m2_data['pool_trials']['trials'])
    page('m2','M2 Mac PRL mining benchmark: Pearl M-Miner versus pearl-metal-miner',
         'Measured PRL GPU mining on a 10-core Apple M2 with 24 GiB memory: matched tests, arithmetic limits, software power and pool checks.',f'''
<p>On 2026-10-30, a MacBook Pro with a 10-core Apple M2 GPU, 24 GiB unified memory and macOS 27.0 built the unchanged <strong>v0.1.0-alpha.3</strong> source release and passed its official-proof self-test. The following comparison uses the same device, certificate version, matrix dimensions, CPU-helper count and 300-second measurement duration.</p>
<table><caption>Fresh-work offline rate; not a paid or pool-effective rate</caption><thead><tr><th scope="col">Miner</th><th scope="col">Local PRL work</th><th scope="col">Software power</th></tr></thead><tbody>
<tr><th scope="row">pearl-metal-miner 0.2.4 + cert3 compatibility</th><td>{m2['upstream_ths']:.4f} TH/s</td><td>{m2['upstream_software_w']:.2f} W</td></tr>
<tr><th scope="row">Pearl M-Miner Alpha 3, default M2 profile</th><td>{m2['default_ths']:.4f} TH/s</td><td>{m2['default_software_w']:.2f} W</td></tr></tbody></table>
<p>The ratio is <strong>{m2['ratio']:.2f}×</strong>, or {m2['gain_percent']:.1f}% higher local throughput. The control preserves the upstream GPU kernels and adds documented certificate-v3 compatibility. This is not a Pearly comparison. Power comes from macmon software telemetry, not an AC outlet meter; it does not establish electricity cost or net profit.</p>
<p><strong>Observed operating limit:</strong> an initial full-duty pool trial stopped at the lab’s 95°C average-sensor guard after about two minutes, with two accepted and zero rejected shares. Repeated ten-minute live trials use <strong>80% intensity</strong> for both miners. On this laptop, begin with <code>--intensity 80</code>; the full-duty offline headline is not a sustained live-rate promise. This Celsius guard belonged to the test supervisor, not a newly shipped miner feature.</p>
<p><img class="hero" src="../site-assets/m2-comparison.png" alt="Matched 300-second M2 offline throughput and software power comparison"></p>
<h2>Ten-minute live trials at intensity 80</h2><table><caption>Same pool and requested duration; rounded cumulative local rates</caption><thead><tr><th scope="col">Miner</th><th scope="col">Local PRL work</th><th scope="col">Software power</th><th scope="col">Accepted / rejected</th></tr></thead><tbody>{live_rows}</tbody></table><p>These sessions include real job changes, proof preparation and network interruptions. Power covers the full process phase. Small share counts do not measure precise pool hashrate, paid income or overnight reliability. Intensity is a scheduling control, not a proportional hashrate guarantee.</p>
<h2>How close is M2 to its arithmetic limit?</h2><p>A model using 10 GPU cores, 128 lanes, two operations per FMA and 1.398 GHz gives approximately 3.579 TFLOP/s. For this direct scan algorithm, two floating-point operations correspond to one reported PRL work unit, giving about 1.789 TH/s before overhead. Our 300-second matrix microbenchmark measured {m2['peak_gpu_tflops']:.3f} GPU TFLOP/s. This is a workload-specific reference, not a universal upper bound on every possible PRL algorithm.</p>
<h2>Correctness, mining pools and fee</h2><p>The detailed report separates offline proof checks from bounded same-pool trials. The optional default developer contribution uses 1% of completed valid GPU scan time, not 1% of income. Multiplying the local rate by 0.99 is only a capacity model; it does not measure pool revenue. M2 Pro, Max, Ultra, other GPU-core counts and other operating-system versions still need their own tests.</p>
<p>Read the <a href="{REPO}/blob/main/docs/M2_VALIDATION_20261030.md">full M2 report</a>, <a href="{REPO}/blob/main/docs/data/m2-validation-20261030.json">machine-readable evidence</a> and <a href="{REPO}/tree/main/research/2026-10-30/m2">reproduction materials</a>. Follow the <a href="{SITE}">versioned setup guide</a>, run the local self-test, and use your own public payout identity for an authorized pool trial.</p>''')
for lang in ('','zh/','ja/','ko/'):
    p=DOCS/lang/'index.html';text=p.read_text(encoding='utf-8')
    text=text.replace(SITE+'site-assets/hero.svg',SITE+'site-assets/social.png')
    text=re.sub(r'<!-- discovery-links -->.*?<!-- /discovery-links -->','',text,flags=re.S)
    m2_link=f'<a href="{SITE}m2/">M2 benchmark</a>' if m2_path.exists() else ''
    links=f'<!-- discovery-links --><nav aria-label="Project information">{m2_link}<a href="{SITE}faq/">FAQ</a><a href="{SITE}about/">About / Support</a><a href="{SITE}privacy/">Privacy</a><a href="{SITE}llms.txt">AI-readable guide</a></nav><!-- /discovery-links -->'
    text=text.replace('<footer>',links+'<footer>')
    if 'name="twitter:card"' not in text:
        text=text.replace('</head>',f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{SITE}site-assets/social.png"></head>')
    p.write_text(text,encoding='utf-8',newline='\n')

urls=['','zh/','ja/','ko/','faq/','about/','privacy/']
if m2_path.exists():urls.append('m2/')
xml='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
for slug in urls:xml+='  <url><loc>'+SITE+slug+'</loc><lastmod>2026-10-30</lastmod></url>\n'
xml+='</urlset>\n';ET.fromstring(xml);(DOCS/'sitemap.xml').write_text(xml,encoding='utf-8',newline='\n')
(DOCS/'404.html').write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Page not found — Pearl M-Miner</title><main><h1>Page not found</h1><p>Return to the <a href="{SITE}">project homepage</a>, <a href="{SITE}faq/">FAQ</a> or <a href="{SITE}llms.txt">AI-readable guide</a>.</p></main></html>\n',encoding='utf-8',newline='\n')
print('Built FAQ, about, privacy, social metadata, sitemap and 404 pages.')
