"""Review-first community reports; publishing requires an explicit --submit."""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlencode
import webbrowser

from .comparison import (SCHEMA, UPSTREAM_COMMIT, UPSTREAM_REPO, FAILURES,
                         WORK_PER_TILE, aggregate, exclusive_write, numeric,
                         parse_benchmark, trial_order, utc_now, validate_context)

REPO = 'parkerkyle-max/pearl-m-miner'
ISSUES = 'https://github.com/' + REPO + '/issues/new'


def safe_text(value, limit=160):
    if not isinstance(value, str) or len(value) > limit or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._()+:/;=\-]*', value):
        raise ValueError('Invalid public metadata text')
    return value


def optional_text(value, limit=160):
    return None if value is None else safe_text(value, limit)


def matched_text(value, pattern):
    if not isinstance(value, str) or len(value) > 96 or not re.fullmatch(pattern, value):
        raise ValueError('Invalid public hardware or version identifier')
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid report integer')
    return value


def public_report(raw):
    """Construct an allowlisted view; never upload the input JSON verbatim."""
    try:
        return _public_report(raw)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError('Incomplete or malformed comparison report') from error


def _public_report(raw):
    if not isinstance(raw, dict) or raw.get('schema') != SCHEMA:
        raise ValueError('Unsupported comparison report')
    if not re.fullmatch('[0-9a-f]{32}', str(raw.get('report_id', ''))):
        raise ValueError('Invalid report identity')
    status = raw.get('status')
    if status not in ('complete', 'failed', 'interrupted'):
        raise ValueError('Only finished or interrupted reports can be shared')
    cfg = raw['configuration']
    config = {'m': integer(cfg['m'], 64, 16384), 'n': integer(cfg['n'], 64, 65536),
              'k': integer(cfg['k'], 4096, 4096), 'rank': integer(cfg['rank'], 128, 128),
              'cert_version': integer(cfg['cert_version'], 3, 3),
              'cpu_threads': integer(cfg['cpu_threads'], 1, 64),
              'region_rows': integer(cfg['region_rows'], 32, 8192),
              'seconds': integer(cfg['seconds'], 60, 600),
              'rounds': integer(cfg['rounds'], 2, 6),
              'cooldown_seconds': integer(cfg['cooldown_seconds'], 10, 300),
              'intensity': integer(cfg['intensity'], 100, 100),
              'work_per_tile': integer(cfg['work_per_tile'], WORK_PER_TILE, WORK_PER_TILE)}
    if config['m'] % 64 or config['n'] % 64 or config['region_rows'] % 32:
        raise ValueError('Invalid matrix dimensions')
    config['order'] = trial_order(config['rounds'])
    if cfg.get('order') != config['order']:
        raise ValueError('Trial order does not match the plan')
    result = {'schema': SCHEMA, 'report_id': raw['report_id'], 'status': status,
              'created_utc': datetime.fromisoformat(raw['created_utc']).isoformat(),
              'completed_utc': datetime.fromisoformat(raw['completed_utc']).isoformat(),
              'review_status': 'self-reported community evidence; not independently hardware-verified',
              'configuration': config, 'hardware': None, 'software': None, 'gates': [], 'trials': [],
              'comparison': None, 'failure_code': None,
              'scope': 'Offline fresh preparation and scan; excludes pool/network and hit-triggered proofs. No income or outlet-power claim.'}
    if raw.get('hardware') is not None:
        h = raw['hardware']
        if not numeric(h['memory_gib']) or h['memory_gib'] > 16384:
            raise ValueError('Invalid memory value')
        result['hardware'] = {'chip': matched_text(h['chip'], r'Apple M[1-9][0-9]*(?: (?:Pro|Max|Ultra))?'), 'gpu_cores': None if h['gpu_cores'] is None else integer(h['gpu_cores'], 1, 512),
                              'memory_gib': h['memory_gib'], 'os': matched_text(h['os'], r'macOS [0-9]+(?:\.[0-9]+){0,2}'),
                              'architecture': matched_text(h['architecture'], 'arm64'), 'python': matched_text(h['python'], r'[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?')}
    if raw.get('software') is not None:
        s = raw['software']
        if s['upstream_commit'] != UPSTREAM_COMMIT or s['upstream_repository'] != UPSTREAM_REPO:
            raise ValueError('Unknown comparison control')
        commit = s['commit']
        if commit is not None and not re.fullmatch('[0-9a-f]{40}', commit):
            raise ValueError('Invalid source commit')
        if s['tracked_changes'] is not None and type(s['tracked_changes']) is not bool:
            raise ValueError('Invalid source state')
        hashes = {}
        allowed = ('pearl_m_miner/', 'pearl_metal_miner/', 'tools/prefix_s_miner/', 'tools/prefix_sparse_host/',
                   'tools/merkle_overlay/', 'csrc/metal/', 'comparators/pearl-metal-miner/', 'build/', 'packaging/')
        for name, digest in s['source_and_build_sha256'].items():
            if (not isinstance(name, str) or len(name) > 240 or '..' in name or '\\' in name
                    or not re.fullmatch(r'[A-Za-z0-9_./-]+', name)
                    or not (name.startswith(allowed) or name == 'PINNED_PEARL_COMMIT.txt')
                    or not re.fullmatch('[0-9a-f]{64}', str(digest))):
                raise ValueError('Invalid source fingerprint')
            hashes[name] = digest
        result['software'] = {'version': matched_text(s['version'], r'[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?(?:\.dev[0-9]+)?'), 'commit': commit, 'tracked_changes': s['tracked_changes'],
                              'upstream_repository': UPSTREAM_REPO, 'upstream_commit': UPSTREAM_COMMIT,
                              'baseline': 'pearl-metal-miner 0.2.4 + cert3 compatibility; original pinned GPU kernels',
                              'source_and_build_sha256': hashes}
    proof_identity = None
    def bound_context(item, phase):
        nonlocal proof_identity
        context = validate_context(item.get('context'), phase, config, item['backend'])
        if proof_identity is None:
            proof_identity = context['proof_extension_sha256']
        elif context['proof_extension_sha256'] != proof_identity:
            raise ValueError('Mixed official proof extensions')
        return context
    for gate in raw.get('gates', []):
        if gate['backend'] not in ('upstream', 'candidate') or gate['moment'] not in ('before', 'after') or gate['status'] != 'passed':
            raise ValueError('Invalid correctness gate')
        if gate.get('owned_process_reaped') is not True:
            raise ValueError('Unconfirmed worker cleanup')
        result['gates'].append({'backend': gate['backend'], 'moment': gate['moment'], 'status': 'passed',
                               'official_proof_checks': integer(gate['official_proof_checks'], 1, 1000000),
                               'condition_samples': integer(gate['condition_samples'], 1, 1000000),
                               'max_thermal_pressure': integer(gate['max_thermal_pressure'], 0, 1),
                               'owned_process_reaped': True, 'context': bound_context(gate, 'gate')})
    for i, trial in enumerate(raw.get('trials', [])):
        if i >= len(config['order']) or trial['index'] != i + 1 or trial['backend'] != config['order'][i]:
            raise ValueError('Invalid trial sequence')
        if trial.get('owned_process_reaped') is not True:
            raise ValueError('Unconfirmed worker cleanup')
        result['trials'].append({'index': i + 1, 'backend': trial['backend'], **parse_benchmark(trial, config),
                                 'condition_samples': integer(trial['condition_samples'], 1, 1000000),
                                 'max_thermal_pressure': integer(trial['max_thermal_pressure'], 0, 1),
                                 'owned_process_reaped': True, 'context': bound_context(trial, 'benchmark')})
    if status == 'complete':
        expected = [(b, m) for m in ('before', 'after') for b in ('upstream', 'candidate')]
        if [(g['backend'], g['moment']) for g in result['gates']] != expected or result['software'] is None or result['hardware'] is None:
            raise ValueError('Complete comparison lacks hardware, identity or correctness evidence')
        result['comparison'] = aggregate(result['trials'], config)
        if raw.get('comparison') != result['comparison'] or raw.get('failure_code') is not None:
            raise ValueError('Comparison summary does not match its measured records')
    else:
        if raw.get('comparison') is not None or raw.get('failure_code') not in FAILURES:
            raise ValueError('Failed comparisons must not advertise an improvement')
        result['failure_code'] = raw['failure_code']
    return result


def render_report(raw, *, include_json=False):
    r = public_report(raw)
    h = r['hardware']
    lines = ['# Pearl M-Miner community comparison', '',
             'Participant-submitted evidence; pending maintainer review. This is an offline throughput comparison, not pool speed or income.', '',
             f"Report: `{r['report_id']}` · Status: **{r['status']}**", '']
    if h:
        lines += [f"Device: {h['chip']} · GPU cores: {h['gpu_cores'] if h['gpu_cores'] is not None else 'unconfirmed'} · {h['memory_gib']:g} GiB · {h['os']}", '']
    c = r['configuration']
    lines += [f"Control: pearl-metal-miner 0.2.4 + cert3 compatibility, `{UPSTREAM_COMMIT}`; original pinned GPU kernels.",
              f"M={c['m']}, N={c['n']}, K=4096, rank=128, cert3; {c['cpu_threads']} CPU helpers; region={c['region_rows']}; intensity=100.",
              f"Each run requests {c['seconds']} measured seconds; order: {', '.join(c['order'])}; {c['cooldown_seconds']} s cooldown before each run.",
              'AC and public OS thermal-pressure checks apply to both backends. Warmup is excluded; fresh preparation is included.', '',
              '| Run | Backend | Seconds | Local PRL TH/s |', '| --- | --- | ---: | ---: |']
    lines += [f"| {t['index']} | {t['backend']} | {t['measured_seconds']:.3f} | {t['local_prl_ths']:.6f} |" for t in r['trials']]
    if r['comparison']:
        a = r['comparison']
        lines += ['', f"Median ratio: **{a['ratio']:.3f}x ({a['improvement_percent']:+.2f}%)**. Every completed run is included; slower results are retained.",
                  'This small repeated test does not establish long-term reliability or an entire chip family’s performance.']
    else:
        lines += ['', 'No accepted improvement: ' + FAILURES[r['failure_code']]]
    if include_json:
        lines += ['', '<details><summary>Sanitized comparison evidence</summary>', '', '```json',
                  json.dumps(r, indent=2, allow_nan=False), '```', '', '</details>']
    return '\n'.join(lines) + '\n'


def share(path, *, open_browser=False, submit=False):
    source = Path(path)
    if any(p.is_symlink() for p in (source.absolute(), *source.absolute().parents)):
        raise ValueError('Choose a regular report path without symbolic-link parents')
    if source.stat().st_size > 2_000_000:
        raise ValueError('Report is too large')
    raw = json.loads(source.read_text(encoding='utf-8'))
    clean = public_report(raw)
    title = '[Community comparison] ' + (clean['hardware']['chip'] if clean['hardware'] else 'incomplete test') + ' / ' + clean['report_id'][:8]
    body = render_report(raw, include_json=True)
    if len(body.encode('utf-8')) > 60000:
        raise ValueError('Report is too large for an issue; use the device-result form and attach the reviewed report manually')
    if not submit:
        print(render_report(raw))
        print('Review report.json before sharing. The project does not upload it automatically.')
        if open_browser:
            # Keep browser URLs small. The user attaches the reviewed JSON and
            # presses Submit in their own logged-in GitHub session.
            short = render_report(raw) + '\nAttach the reviewed report.json before submitting this issue.\n'
            url = ISSUES + '?' + urlencode({'title': title, 'body': short})
            if not webbrowser.open(url):
                print('Open manually: ' + url)
            print('Opened a draft only; GitHub submission is still your action.')
        return 0
    gh = shutil.which('gh')
    if gh is None:
        raise RuntimeError('Direct submission requires the optional GitHub CLI and your own gh auth login. Use --open instead.')
    payload = json.dumps(clean, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    receipt_path = source.parent / ('submission-' + clean['report_id'] + '.json')
    attempt = {'report_id': clean['report_id'], 'report_sha256': hashlib.sha256(payload).hexdigest(),
               'attempted_utc': utc_now(), 'status': 'pending', 'issue_url': None}
    exclusive_write(receipt_path, json.dumps(attempt, indent=2) + '\n')
    try:
        with tempfile.TemporaryDirectory(prefix='pearl-comparison-share-') as temporary:
            body_path = Path(temporary) / 'body.md'
            body_path.write_text(body, encoding='utf-8')
            response = subprocess.run([gh, 'issue', 'create', '--repo', REPO, '--title', title,
                                       '--body-file', str(body_path)], capture_output=True, text=True, timeout=60)
        url = response.stdout.strip()
        if response.returncode or not re.fullmatch(r'https://github\.com/parkerkyle-max/pearl-m-miner/issues/[0-9]+', url):
            raise RuntimeError('Submission outcome is unknown. Check your GitHub issues before retrying; this command will not post twice automatically.')
        attempt.update(status='submitted', issue_url=url)
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        attempt['status'] = 'unknown'
        raise RuntimeError('Submission outcome is unknown. Check your GitHub issues before retrying; this command will not post twice automatically.') from error
    finally:
        # This receipt was created exclusively by this invocation. A subsequent
        # invocation refuses it, including ambiguous network-failure outcomes.
        receipt_path.write_text(json.dumps(attempt, indent=2) + '\n', encoding='utf-8')
    print('Submitted: ' + attempt['issue_url'])
    return 0
