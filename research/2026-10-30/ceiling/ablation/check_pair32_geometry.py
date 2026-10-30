"""CPU-only oracle for split-store row ownership and XOR regrouping.

Does not compile MPP, validate GPU numerical behavior, or count mining work.
The existing GPU full-transcript/digest and official-proof gates remain required.
"""
from pathlib import Path
from random import Random
import hashlib
import json

HERE = Path(__file__).resolve().parent
MASK = (1 << 32) - 1


def check_case(matrices):
    slots = []
    for slot in range(16):
        result = [0] * 128
        expected = [0] * 32
        for phase in range(2):
            matrix = matrices[slot + phase * 16]
            lanes = [0] * 128
            for half_rows in range(2):
                local_store = matrix[half_rows * 32:(half_rows + 1) * 32]
                for tid in range(128):
                    pair, lane = divmod(tid, 4)
                    for j in range(16):
                        lanes[tid] ^= local_store[pair][lane * 16 + j] & MASK
            for distance in (2, 1):
                lanes = [x ^ lanes[tid ^ distance] for tid, x in enumerate(lanes)]
            for tid, value in enumerate(lanes):
                if phase == 0:
                    result[tid] = ((value << 13) | (value >> 19)) & MASK
                else:
                    result[tid] ^= value
            for pair in range(32):
                value = 0
                for col in range(64):
                    value ^= matrix[pair][col] & MASK
                    value ^= matrix[pair + 32][col] & MASK
                if phase == 0:
                    expected[pair] = ((value << 13) | (value >> 19)) & MASK
                else:
                    expected[pair] ^= value
        assert result[::4] == expected
        for tid in range(128):
            assert result[tid] == expected[tid // 4]
            assert tid // 32 == (tid ^ 1) // 32 == (tid ^ 2) // 32
        slots.extend(expected)
    return hashlib.sha256(b''.join(x.to_bytes(4, 'little') for x in slots)).hexdigest()


def main():
    baseline = (HERE / 'prefix_baseline.metal').read_text()
    candidate = (HERE / 'prefix_pair32.metal').read_text()
    for marker in ('// Keyed BLAKE3',):
        assert baseline[baseline.index(marker):] == candidate[candidate.index(marker):]
    for literal in (
        'matmul2d_descriptor(32, 64, 128, false, true, false',
        'execution_simdgroups<4>', 'threadgroup float matrix[2048]',
        'row0 + half_rows * 32u', 'extents<int,64,32>',
    ):
        assert literal in candidate, literal
    rng = Random(0x504149523332)
    value_sets = [
        lambda p, r, c: 0,
        lambda p, r, c: (1 << 24) if (p + r + c) % 2 else -(1 << 24),
        lambda p, r, c: (p * 4099 + r * 131 + c * 17) * (-1 if (r + c) % 3 else 1),
        lambda p, r, c: rng.randrange(-(1 << 24), (1 << 24) + 1),
    ]
    hashes = []
    for fixture in value_sets:
        matrices = [[[fixture(p, r, c) for c in range(64)] for r in range(64)]
                    for p in range(32)]
        hashes.append(check_case(matrices))
    # Exact native output indexing is retained: every tile owns all 16 slots.
    columns = 65536 // 64
    ownership = set()
    for band in range(3):
        for column in (0, 17, columns - 1):
            for pair in range(32):
                tile = (band * 32 + pair) * columns + column
                for slot in range(16):
                    address = tile * 16 + slot
                    assert address not in ownership
                    ownership.add(address)
    print(json.dumps({
        'status': 'CPU_GEOMETRY_ONLY_PASS',
        'all_prefixes_per_fixture': 32, 'fixtures': len(hashes),
        'fixture_transcript_sha256': hashes,
        'unique_address_checks': len(ownership),
        'macs_per_threadgroup': 4 * 32 * 64 * 128,
        'gpu_compilation_or_proof_verified': False,
        'miner_hashrate': None,
    }, indent=2))


if __name__ == '__main__':
    main()
