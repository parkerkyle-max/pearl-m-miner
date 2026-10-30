"""Isolated immutable single-nonce-leaf overlay using existing official proofs.

This never starts a miner. The only native helper computes a BLAKE3 leaf path;
all final proof objects are constructed with the installed pearl_mining API.
The strict bincode bridge is pinned to Pearl commit 3c84be9f... and fails on
layout changes. Do not integrate this research API into mining without gates.
"""
from __future__ import annotations

import base64
import ctypes as C
from dataclasses import dataclass, field
from pathlib import Path
import struct
import threading

LEAF = 1024
WRAPPER = (0x4D315052, 0x4F42454D, 0x45524B4C, 128)


def sibling_addresses(indices, total):
    current, size, level = set(indices), total, 0
    result = []
    while size > 1:
        for index in sorted(current):
            sibling = index ^ 1
            if sibling < size and sibling not in current:
                result.append((level, sibling))
        current = {index // 2 for index in current}
        size = (size + 1) // 2
        level += 1
    return tuple(result)


@dataclass(frozen=True)
class ProofParts:
    leaf_data: tuple[bytes, ...]
    leaf_indices: tuple[int, ...]
    total_leaves: int
    root: bytes
    siblings: tuple[bytes, ...]

    def validate(self):
        if self.total_leaves < 2 or not self.leaf_indices:
            raise ValueError('overlay requires a nonempty proof of a tree with >=2 leaves')
        if tuple(sorted(set(self.leaf_indices))) != self.leaf_indices:
            raise ValueError('leaf indices must be sorted and unique')
        if self.leaf_indices[0] < 0 or self.leaf_indices[-1] >= self.total_leaves:
            raise ValueError('leaf index out of bounds')
        if len(self.leaf_data) != len(self.leaf_indices) or any(len(x) != LEAF for x in self.leaf_data):
            raise ValueError('leaf bytes/count invalid')
        if len(self.root) != 32 or any(len(x) != 32 for x in self.siblings):
            raise ValueError('invalid root or sibling CV size')
        if len(self.siblings) != len(sibling_addresses(self.leaf_indices, self.total_leaves)):
            raise ValueError('wrong sibling count for selected leaves')
        return self

    def official(self, pm):
        self.validate()
        return pm.MerkleProof(list(self.leaf_data), list(self.leaf_indices), self.root,
                              list(self.siblings), self.total_leaves)


class _Reader:
    def __init__(self, data):
        if len(data) > 32 * 1024 * 1024:
            raise ValueError('proof wrapper exceeds isolated probe limit')
        self.data, self.pos = data, 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError('truncated proof wrapper')
        value = self.data[self.pos:self.pos + count]
        self.pos += count
        return value

    def usize(self):
        return struct.unpack('<Q', self.take(8))[0]

    def count(self, item_min=1):
        value = self.usize()
        if value > (len(self.data) - self.pos) // item_min:
            raise ValueError('proof vector length exceeds remaining bytes')
        return value

    def matrix(self):
        leaf_count = self.count(8 + LEAF)
        leaves = []
        for _ in range(leaf_count):
            if self.usize() != LEAF:
                raise ValueError('serialized leaf does not have 1024 bytes')
            leaves.append(self.take(LEAF))
        indices = tuple(self.usize() for _ in range(self.count(8)))
        total = self.usize()
        root = self.take(32)
        siblings = tuple(self.take(32) for _ in range(self.count(32)))
        rows = tuple(self.usize() for _ in range(self.count(8)))
        return ProofParts(tuple(leaves), indices, total, root, siblings).validate(), rows


def parts_from_wrapper_bytes(raw: bytes) -> ProofParts:
    reader = _Reader(raw)
    metadata = tuple(reader.usize() for _ in range(4))
    if metadata != WRAPPER:
        raise ValueError('unexpected pinned PlainProof metadata/layout')
    first, rows_a = reader.matrix()
    second, rows_b = reader.matrix()
    if first != second or rows_a != (0,) or rows_b != (0,):
        raise ValueError('official wrapper sides/row markers differ')
    if reader.take(1) != b'\0' or reader.pos != len(raw):
        raise ValueError('expected dense None trailer and no trailing data')
    return first


def official_parts(pm, proof) -> ProofParts:
    """Public APIs only; no access to a PyO3 object's layout or private pointers."""
    matrix = pm.MatrixMerkleProof(proof, [0])
    wrapper = pm.PlainProof(*WRAPPER, matrix, matrix, None)
    raw = base64.b64decode(wrapper.to_base64(), validate=True)
    return parts_from_wrapper_bytes(raw)


class NativePath:
    def __init__(self, library=None):
        root = Path(__file__).resolve().parent
        if library is None:
            choices = [root / 'build/libm1merkleprobe_c.dylib', root / 'build/libm1merkleprobe_c.so']
            library = next((path for path in choices if path.exists()), None)
        if library is None:
            raise RuntimeError('run sh build_c.sh first')
        self.library = str(library)
        self.lib = C.CDLL(self.library)
        self.function = self.lib.mi_nonce_path
        self.function.argtypes = [C.c_char_p, C.c_size_t, C.c_uint64, C.c_uint64,
                                  C.c_char_p, C.c_size_t, C.c_char_p, C.c_void_p,
                                  C.c_size_t, C.POINTER(C.c_size_t)]
        self.function.restype = C.c_int

    def path(self, leaf, index, total, siblings, key):
        if len(leaf) != LEAF or len(key) != 32 or any(len(value) != 32 for value in siblings):
            raise ValueError('invalid leaf/key/sibling length')
        if not 0 <= index < total <= (1 << 63) or len(siblings) > 64:
            raise ValueError('invalid index/total/sibling count')
        output, written = C.create_string_buffer(65 * 32), C.c_size_t()
        rc = self.function(leaf, len(leaf), index, total, b''.join(siblings), len(siblings),
                           key, output, 65, C.byref(written))
        if rc != 0:
            raise ValueError(f'native nonce path refused arguments: {rc}')
        if not 1 <= written.value <= 65:
            raise RuntimeError('native path returned invalid count')
        return tuple(output.raw[i * 32:(i + 1) * 32] for i in range(written.value))


def _frozen_identity(value):
    if value is None or type(value) in (bytes, str, int, bool):
        return value
    if type(value) is tuple:
        return tuple(_frozen_identity(item) for item in value)
    raise TypeError('scope must contain only immutable primitives/tuples')


@dataclass(frozen=True)
class OverlayScope:
    job_identity: tuple
    header: bytes
    config: bytes
    cert_version: int
    m: int
    n: int
    k: int

    def __post_init__(self):
        _frozen_identity(self.job_identity)
        if type(self.header) is not bytes or type(self.config) is not bytes:
            raise TypeError('scope header/config must be immutable bytes')
        if self.cert_version not in (1, 2, 3) or min(self.m, self.n, self.k) <= 0:
            raise ValueError('invalid certificate/dimensions')


@dataclass(frozen=True)
class NonceOverlay:
    base_root: bytes
    root: bytes
    nonce_index: int
    total_leaves: int
    leaf: bytes
    path: tuple[bytes, ...]
    scope: OverlayScope
    nonce: int
    _base_tree: object = field(repr=False, compare=False)

    def patch(self, original: ProofParts) -> ProofParts:
        original.validate()
        if original.root != self.base_root or original.total_leaves != self.total_leaves:
            raise ValueError('proof belongs to a different base commitment/tree size')
        overrides = {(level, self.nonce_index >> level): cv for level, cv in enumerate(self.path)}
        siblings = tuple(overrides.get(address, value) for address, value in zip(
            sibling_addresses(original.leaf_indices, original.total_leaves), original.siblings))
        leaves = tuple(self.leaf if index == self.nonce_index else data
                       for index, data in zip(original.leaf_indices, original.leaf_data))
        return ProofParts(leaves, original.leaf_indices, original.total_leaves, self.root, siblings).validate()

    def proof(self, pm, indices, *, scope: OverlayScope):
        if scope != self.scope:
            raise ValueError('job/header/certificate/config/dimensions changed')
        indices = tuple(indices)
        if not indices or any(type(i) is not int or not 0 <= i < self.total_leaves for i in indices):
            raise ValueError('invalid proof selection')
        original = official_parts(pm, self._base_tree.get_multileaf_proof(sorted(set(indices))))
        return self.patch(original).official(pm)


class NonceOverlayFactory:
    """An immutable base plus unique +/-1 nonce leaves; never mutates that base.

    Explicit nonces are for research reproducibility. An integration must use
    worker-unique base data/nonce ranges and retain old overlays until GPU and
    proof work for their generations are complete.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('base factory binding is immutable; construct a new job scope')
        object.__setattr__(self, name, value)

    def __init__(self, pm, tree, key, nonce_index, total_leaves, scope, native=None):
        if (type(nonce_index) is not int or type(total_leaves) is not int or
                total_leaves < 2 or not 0 <= nonce_index < total_leaves):
            raise ValueError('invalid nonce index/tree size')
        if (scope.m * scope.k + LEAF - 1) // LEAF != total_leaves:
            raise ValueError('A dimensions do not match the nonce base tree size')
        self.pm, self.tree, self.key = pm, tree, bytes(key)
        self.scope, self.native = scope, native if native is not None else NativePath()
        self.parts = official_parts(pm, tree.get_multileaf_proof([nonce_index]))
        if (self.parts.leaf_indices != (nonce_index,) or self.parts.total_leaves != total_leaves
                or self.parts.root != bytes(tree.root)):
            raise ValueError('base nonce proof identity/dimensions differ')
        old_path = self.native.path(self.parts.leaf_data[0], nonce_index, total_leaves,
                                    self.parts.siblings, self.key)
        if old_path[-1] != self.parts.root:
            raise ValueError('base nonce proof does not verify under this job key')
        # Preserve canonical zero padding if the final matrix leaf is partial.
        self.nonce_bits = min(128, scope.m * scope.k - nonce_index * LEAF)
        if self.nonce_bits <= 0:
            raise ValueError('nonce leaf contains no actual matrix values')
        self._last_nonce = [-1]  # monotonic high-water, fixed memory
        self._lock = threading.Lock()
        self._sealed = True

    def make(self, nonce: int, *, scope: OverlayScope):
        if scope != self.scope:
            raise ValueError('job/header/certificate/config/dimensions changed; rebuild base')
        if type(nonce) is not int or not 0 <= nonce < (1 << self.nonce_bits):
            raise ValueError(f'nonce must be an unsigned {self.nonce_bits}-bit integer')
        with self._lock:
            if nonce <= self._last_nonce[0]:
                raise ValueError('nonce must increase; replay and out-of-order work refused')
            original = self.parts.leaf_data[0]
            # Every changed signal remains +/-1. The other 896 bytes stay fixed.
            leaf = (bytes(1 if (nonce >> bit) & 1 else 255 for bit in range(self.nonce_bits))
                    + original[self.nonce_bits:])
            path = self.native.path(leaf, self.parts.leaf_indices[0], self.parts.total_leaves,
                                    self.parts.siblings, self.key)
            if path[-1] == self.parts.root:
                raise ValueError('nonce leaf equals the unchanged base; choose a different nonce')
            self._last_nonce[0] = nonce
            return NonceOverlay(self.parts.root, path[-1], self.parts.leaf_indices[0],
                                self.parts.total_leaves, leaf, path, self.scope, nonce, self.tree)
