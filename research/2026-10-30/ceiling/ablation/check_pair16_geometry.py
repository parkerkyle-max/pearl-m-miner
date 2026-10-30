"""CPU-only row/XOR oracle; does not certify MPP compilation or GPU proofs."""
from pathlib import Path
from random import Random
import hashlib
import json

HERE = Path(__file__).resolve().parent
MASK = (1 << 32) - 1


def check_case(matrices):
    results = []
    for slot in range(16):
        output = [0] * 128
        expected = [0] * 32
        for phase in range(2):
            matrix = matrices[slot + phase * 16]
            lanes = [0] * 128
            consumed = [[] for _ in range(128)]
            for row_block in range(4):
                local_store = matrix[row_block * 16:(row_block + 1) * 16]
                # All lanes participate in MPP/store/barriers. Only reads branch.
                for tid in range(128):
                    pair, lane = divmod(tid, 4)
                    if (pair >> 4) == (row_block & 1):
                        for j in range(16):
                            col = lane * 16 + j
                            lanes[tid] ^= local_store[pair & 15][col] & MASK
                            consumed[tid].append((row_block * 16 + (pair & 15), col))
            for tid in range(128):
                pair, lane = divmod(tid, 4)
                exact = [(r, c) for r in (pair, pair + 32)
                         for c in range(lane * 16, lane * 16 + 16)]
                assert consumed[tid] == exact
            for distance in (2, 1):
                lanes = [v ^ lanes[tid ^ distance] for tid, v in enumerate(lanes)]
            for tid, value in enumerate(lanes):
                if phase == 0:
                    output[tid] = ((value << 13) | (value >> 19)) & MASK
                else:
                    output[tid] ^= value
            for pair in range(32):
                value = 0
                for col in range(64):
                    value ^= matrix[pair][col] & MASK
                    value ^= matrix[pair + 32][col] & MASK
                if phase == 0:
                    expected[pair] = ((value << 13) | (value >> 19)) & MASK
                else:
                    expected[pair] ^= value
        assert output[::4] == expected
        assert all(v == expected[tid // 4] for tid, v in enumerate(output))
        results.extend(expected)
    return hashlib.sha256(b''.join(x.to_bytes(4, 'little') for x in results)).hexdigest()


def main():
    baseline = (HERE / 'prefix_baseline.metal').read_text()
    candidate = (HERE / 'prefix_pair16.metal').read_text()
    marker = '// Keyed BLAKE3'
    assert baseline[baseline.index(marker):] == candidate[candidate.index(marker):]
    for literal in ('matmul2d_descriptor(16, 64, 128, false, true, false',
                    'execution_simdgroups<4>', 'threadgroup float matrix[1024]',
                    '(pair >> 4u) == (row_block & 1u)',
                    'row0 + row_block * 16u', 'extents<int,64,16>'):
        assert literal in candidate, literal
    rng = Random(0x504149523332)
    fixtures = [
        lambda p, r, c: 0,
        lambda p, r, c: (1 << 24) if (p + r + c) % 2 else -(1 << 24),
        lambda p, r, c: (p * 4099 + r * 131 + c * 17) * (-1 if (r + c) % 3 else 1),
        lambda p, r, c: rng.randrange(-(1 << 24), (1 << 24) + 1),
    ]
    hashes = []
    for fixture in fixtures:
        matrices = [[[fixture(p, r, c) for c in range(64)] for r in range(64)]
                    for p in range(32)]
        hashes.append(check_case(matrices))
    # Match the independent 32-row oracle's deterministic expected transcripts.
    assert hashes == [
        'e5a00aa9991ac8a5ee3109844d84a55583bd20572ad3ffcd42792f3c36b183ad',
        'e5a00aa9991ac8a5ee3109844d84a55583bd20572ad3ffcd42792f3c36b183ad',
        '2aa05948e2fa7d910bf0257d62c82491856a89838bff25c7d7699412d9af07c9',
        '694cee2913a5c114a451f6d4eedc2e7f7f56ad66d8b85faff2627cf21610b151',
    ]
    for m in range(64, 16385, 64):
        for band in range(m // 64):
            for block in range(4):
                assert band * 64 + block * 16 + 15 < m
    print(json.dumps({
        'status': 'CPU_GEOMETRY_ONLY_PASS',
        'fixtures': len(fixtures), 'prefixes_per_fixture': 32,
        'fixture_transcript_sha256': hashes,
        'row_shapes_checked': 256,
        'macs_per_threadgroup': 8 * 16 * 64 * 128,
        'gpu_compilation_or_proof_verified': False, 'miner_hashrate': None,
    }, indent=2))


if __name__ == '__main__':
    main()
