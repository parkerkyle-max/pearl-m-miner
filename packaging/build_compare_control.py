"""Verify and build the vendored upstream control, offline and only on request."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_COMMIT = '3d4cc7dadbd1de98ba20e9beb162806a0e70266b'
PROOF_COMMIT = '3c84be9fb4b2b279967ad3f9f74e67fb8c9cce30'
VENDOR_RELATIVE = Path('comparators/pearl-metal-miner')
LIBRARY_RELATIVE = Path('build/runtime/build/libpearlmetal.dylib')
RUNTIME_BUILD_FILES = frozenset({
    'build/libpearlmetal.dylib', 'csrc/metal/kernels_embedded.h',
})
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(name: str) -> Path:
    value = PurePosixPath(name)
    if (not isinstance(name, str) or not name or '\\' in name
            or value.is_absolute() or '..' in value.parts or ':' in name):
        raise RuntimeError('invalid relative source path')
    return Path(*value.parts)


def _read_file(base: Path, name: str) -> bytes:
    path = base / _safe_relative(name)
    if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
        raise RuntimeError('source path escapes its expected directory: ' + name)
    return path.read_bytes()


def runtime_files(runtime: Path) -> set[str]:
    """Inventory regular files without following links or reparse directories."""
    runtime = Path(runtime)
    found = set()
    if not runtime.exists():
        return found
    root_status = runtime.lstat()
    if (stat.S_ISLNK(root_status.st_mode)
            or getattr(root_status, 'st_file_attributes', 0) & 0x400):
        raise RuntimeError('comparison runtime root must not be a link or reparse entry')
    for directory, directories, filenames in os.walk(runtime, followlinks=False):
        for name in [*directories, *filenames]:
            path = Path(directory) / name
            status = path.lstat()
            if (stat.S_ISLNK(status.st_mode)
                    or getattr(status, 'st_file_attributes', 0) & 0x400):
                raise RuntimeError('link or reparse entry in comparison runtime: '
                                   + path.relative_to(runtime).as_posix())
            if name in filenames:
                if not stat.S_ISREG(status.st_mode):
                    raise RuntimeError('non-regular file in comparison runtime')
                found.add(path.relative_to(runtime).as_posix())
    return found


def validate_runtime_inventory(runtime: Path, allowed: set[str], *,
                               require_complete: bool = True) -> None:
    actual = runtime_files(runtime)
    unexpected = actual - set(allowed)
    if unexpected:
        raise RuntimeError('unexpected files in comparison runtime: '
                           + ', '.join(sorted(unexpected)))
    if require_complete and actual != set(allowed):
        raise RuntimeError('missing files in comparison runtime: '
                           + ', '.join(sorted(set(allowed) - actual)))


def load_manifest(root: Path = ROOT) -> dict:
    manifest = json.loads((root / VENDOR_RELATIVE / 'source-manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('schema') != 'pearl-m-compare-source-v1'
            or manifest.get('upstream_commit') != UPSTREAM_COMMIT
            or manifest.get('official_proof_commit') != PROOF_COMMIT):
        raise RuntimeError('comparison control has an unknown source identity')
    if (root / 'PINNED_PEARL_COMMIT.txt').read_text().strip() != PROOF_COMMIT:
        raise RuntimeError('project proof pin differs from the comparison protocol pin')
    return manifest


def verify_sources(root: Path = ROOT) -> dict:
    root = Path(root)
    vendor = root / VENDOR_RELATIVE
    manifest = load_manifest(root)
    expected = manifest['upstream_files_sha256']
    if not expected or not {'LICENSE', 'NOTICE', 'pearl_metal_miner/miner.py',
                            'csrc/metal/pearl_metal.mm',
                            'csrc/metal/kernels/pearl_kernels.metal'} <= expected.keys():
        raise RuntimeError('comparison source manifest is incomplete')
    for name, wanted in expected.items():
        if digest(_read_file(vendor / 'upstream', name)) != wanted:
            raise RuntimeError('pinned upstream source changed: ' + name)
    actual = {p.relative_to(vendor / 'upstream').as_posix()
              for p in (vendor / 'upstream').rglob('*') if p.is_file()}
    if actual != set(expected):
        raise RuntimeError('unexpected or missing files in the pinned upstream source tree')
    patch = manifest['patch']
    if digest(_read_file(vendor, patch['path'])) != patch['sha256']:
        raise RuntimeError('the disclosed cert3 compatibility patch changed')
    return {
        'upstream_commit': UPSTREAM_COMMIT,
        'official_proof_commit': PROOF_COMMIT,
        'source_manifest_sha256': digest((vendor / 'source-manifest.json').read_bytes()),
        'patch_sha256': patch['sha256'],
        'upstream_files_sha256': expected,
        'patched_files_sha256': manifest['patched_files_sha256'],
    }


def apply_patch_exact(files: dict[str, bytes], patch: bytes) -> dict[str, bytes]:
    """Apply this disclosed unified diff without Git, fuzz or shell commands."""
    result = dict(files)
    lines = patch.decode('utf-8').splitlines(keepends=True)
    index = 0
    changed = set()
    while index < len(lines):
        if not lines[index].startswith('diff --git '):
            raise RuntimeError('unexpected compatibility patch preamble')
        match = re.fullmatch(r'diff --git a/(\S+) b/(\S+)\n?', lines[index])
        if not match or match[1] != match[2]:
            raise RuntimeError('patch must update existing files without renames')
        name = match[1]
        _safe_relative(name)
        if not name.startswith('pearl_metal_miner/') or name in changed:
            raise RuntimeError('patch changes a native or duplicate source: ' + name)
        changed.add(name)
        if name not in result:
            raise RuntimeError('patch source is missing: ' + name)
        original = result[name].decode('utf-8').splitlines(keepends=True)
        output, cursor = [], 0
        index += 1
        if index < len(lines) and lines[index].startswith('index '):
            index += 1
        if lines[index:index + 2] != ['--- a/' + name + '\n', '+++ b/' + name + '\n']:
            raise RuntimeError('invalid patch file headers: ' + name)
        index += 2
        hunks = 0
        while index < len(lines) and not lines[index].startswith('diff --git '):
            header = HUNK.match(lines[index])
            if not header:
                raise RuntimeError('invalid compatibility patch hunk: ' + name)
            old_start, old_count = int(header[1]), int(header[2] or '1')
            new_start, new_count = int(header[3]), int(header[4] or '1')
            start = old_start - 1
            if start < cursor or start > len(original):
                raise RuntimeError('out-of-order compatibility patch: ' + name)
            output.extend(original[cursor:start])
            if len(output) != new_start - 1:
                raise RuntimeError('patch output position mismatch: ' + name)
            cursor, old_seen, new_seen = start, 0, 0
            index += 1
            while (index < len(lines) and not lines[index].startswith('diff --git ')
                   and not lines[index].startswith('@@ ')):
                line = lines[index]
                if not line or line[0] not in ' +-':
                    raise RuntimeError('unsupported patch line: ' + name)
                if line[0] in ' -':
                    if cursor >= len(original) or original[cursor] != line[1:]:
                        raise RuntimeError('patch context differs from pinned source: ' + name)
                    cursor += 1
                    old_seen += 1
                if line[0] in ' +':
                    output.append(line[1:])
                    new_seen += 1
                index += 1
            if (old_seen, new_seen) != (old_count, new_count):
                raise RuntimeError('patch line counts differ: ' + name)
            hunks += 1
        if not hunks:
            raise RuntimeError('empty compatibility patch: ' + name)
        output.extend(original[cursor:])
        result[name] = ''.join(output).encode('utf-8')
    return result


def effective_sources(root: Path = ROOT) -> tuple[dict, dict[str, bytes]]:
    identity = verify_sources(root)
    vendor = Path(root) / VENDOR_RELATIVE
    files = {name: _read_file(vendor / 'upstream', name)
             for name in identity['upstream_files_sha256']}
    manifest = load_manifest(Path(root))
    patched = apply_patch_exact(files, _read_file(vendor, manifest['patch']['path']))
    changed = {name for name in files if files[name] != patched[name]}
    if changed != set(identity['patched_files_sha256']):
        raise RuntimeError('compatibility patch changed an unexpected source set')
    for name, wanted in identity['patched_files_sha256'].items():
        if digest(patched[name]) != wanted:
            raise RuntimeError('patched source differs from the published M2 control: ' + name)
    for name in files:
        if name.startswith('csrc/') and patched[name] != files[name]:
            raise RuntimeError('upstream native source must remain unchanged')
    return identity, patched


def prepare_runtime(root: Path = ROOT) -> dict:
    root = Path(root)
    identity, files = effective_sources(root)
    runtime = root / VENDOR_RELATIVE / 'build/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    if not runtime.resolve().is_relative_to((root / VENDOR_RELATIVE).resolve()):
        raise RuntimeError('comparison runtime escapes the vendor directory')
    # Never silently clean a cache or foreign module from a prior/manual run.
    # Source-only worker imports generate no bytecode, so none is needed here.
    allowed = set(files) | RUNTIME_BUILD_FILES
    validate_runtime_inventory(runtime, allowed, require_complete=False)
    for name, data in files.items():
        destination = runtime / _safe_relative(name)
        if destination.is_symlink() or not destination.resolve().is_relative_to(runtime.resolve()):
            raise RuntimeError('comparison runtime source escaped its directory')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    identity['runtime_files_sha256'] = {name: digest(data) for name, data in files.items()}
    for name, expected in identity['runtime_files_sha256'].items():
        if digest(_read_file(runtime, name)) != expected:
            raise RuntimeError('runtime source reread failed: ' + name)
    validate_runtime_inventory(runtime, allowed, require_complete=False)
    return identity


def verify_build(root: Path = ROOT) -> dict:
    root = Path(root)
    vendor = root / VENDOR_RELATIVE
    expected, files = effective_sources(root)
    receipt = json.loads((vendor / 'build/build-manifest.json').read_text(encoding='utf-8'))
    if receipt.get('schema') != 'pearl-m-compare-build-v1':
        raise RuntimeError('unknown comparison build receipt')
    for name, value in expected.items():
        if receipt.get(name) != value:
            raise RuntimeError('comparison build no longer matches source identity: ' + name)
    runtime_expected = {name: digest(data) for name, data in files.items()}
    if receipt.get('runtime_files_sha256') != runtime_expected:
        raise RuntimeError('comparison runtime source manifest changed')
    runtime = vendor / 'build/runtime'
    expected_build_files = {
        'build/runtime/' + name for name in RUNTIME_BUILD_FILES
    }
    if set(receipt.get('build_files_sha256', {})) != expected_build_files:
        raise RuntimeError('comparison build manifest contains an unexpected artifact set')
    validate_runtime_inventory(runtime, set(runtime_expected) | RUNTIME_BUILD_FILES)
    for name, expected_hash in runtime_expected.items():
        if digest(_read_file(runtime, name)) != expected_hash:
            raise RuntimeError('comparison runtime changed: ' + name)
    for name, expected_hash in receipt['build_files_sha256'].items():
        if digest(_read_file(vendor, name)) != expected_hash:
            raise RuntimeError('comparison native build changed: ' + name)
    if LIBRARY_RELATIVE.as_posix() not in receipt['build_files_sha256']:
        raise RuntimeError('comparison build receipt omits its native library')
    return receipt


def build(root: Path = ROOT) -> dict:
    root = Path(root)
    verify_sources(root)
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('the comparison control must be built on native arm64 macOS')
    vendor = root / VENDOR_RELATIVE
    folder = vendor / 'build'
    folder.mkdir(exist_ok=True)
    lock = folder / '.build.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    temporary_library = None
    try:
        identity = prepare_runtime(root)
        runtime = folder / 'runtime'
        source = runtime / 'csrc/metal'
        kernel = (source / 'kernels/pearl_kernels.metal').read_bytes()
        embedded = (
            '/* Generated by packaging/build_macos.sh — do not edit. */\n'
            'static const unsigned char PEARL_KERNELS_MSL[] = {'
            + ','.join(str(value) for value in kernel) + '};\n'
            + f'static const unsigned long PEARL_KERNELS_MSL_LEN = {len(kernel)};\n'
        ).encode('utf-8')
        (source / 'kernels_embedded.h').write_bytes(embedded)
        library = vendor / LIBRARY_RELATIVE
        library.parent.mkdir(exist_ok=True)
        temporary_library = library.with_name('libpearlmetal-' + uuid.uuid4().hex + '.dylib')
        command = ['xcrun', 'clang++', '-std=c++17', '-O2', '-fobjc-arc', '-dynamiclib',
                   '-framework', 'Metal', '-framework', 'Foundation', '-o',
                   str(temporary_library), str(source / 'pearl_metal.mm')]
        subprocess.run(command, check=True, cwd=root, timeout=300)
        temporary_library.replace(library)
        sdk = subprocess.check_output(['xcrun', '--show-sdk-version'], text=True, timeout=20).strip()
        compiler = subprocess.check_output(['xcrun', 'clang++', '--version'], text=True, timeout=20).splitlines()[0]
        after = verify_sources(root)
        if after != {key: identity[key] for key in after}:
            raise RuntimeError('source identity changed while building the comparison control')
        receipt = {
            'schema': 'pearl-m-compare-build-v1', **identity,
            'built_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'python': platform.python_version(), 'macos': platform.mac_ver()[0],
            'machine': platform.machine(), 'sdk': sdk, 'compiler': compiler,
            'build_files_sha256': {
                LIBRARY_RELATIVE.as_posix(): digest(library.read_bytes()),
                'build/runtime/csrc/metal/kernels_embedded.h': digest(embedded),
            },
            'scope': 'Pinned upstream native GPU and host; disclosed cert3 Python patch only. No network or package installation.',
        }
        path = folder / 'build-manifest.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)
        return verify_build(root)
    finally:
        if temporary_library is not None and temporary_library.exists():
            temporary_library.unlink()
        lock.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify-only', action='store_true')
    mode.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = (verify_sources() if args.verify_only else
                  prepare_runtime() if args.prepare_only else build())
        print('COMPARE_CONTROL_BUILD ' + json.dumps(result, sort_keys=True), flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('comparison control: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
