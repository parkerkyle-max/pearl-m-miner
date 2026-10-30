"""Host-side grid lifecycle: generate → commit → (on a hit) prove → verify.

Committed matrices are miner-chosen: any int8 values in [−64, +64] pass
the verifier's range check. The commitment and PlainProof come
from `py-pearl-mining` (ISC), per ADR-0001 — the host path is upstream's own
bit-exact machinery, not a reimplementation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
import threading
import time
import uuid
import numpy as np
import pearl_mining as pm

from . import reference as ref
from .metal_capi import JobShape


def _random_signal(rng: np.random.Generator, rows: int, cols: int) -> np.ndarray:
    """Uniform miner-chosen signals in [-64, 63], inside the allowed range.

    Reusing PCG raw bytes avoids NumPy's slow 129-value int8 rejection path.
    Signed right-shift maps each pair of byte values to one of 128
    equiprobable valid signals; consensus does not require using +64.
    Other generators use the public sampling API: random_raw's uint64
    container does not imply 64 random bits (MT19937 provides only 32).
    """
    signal_mode = os.environ.get('FUSION_METAL_SIGNAL', 'full')
    if signal_mode not in ('full', 'binary'):
        raise ValueError('FUSION_METAL_SIGNAL must be full or binary')
    # Experimental, explicit opt-in. The verifier permits any signal in
    # [-64,64]. Fresh random +/-1 signals bound noised values to [-64,64].
    # The native fast path independently checks actual input buffers; this
    # setting is never itself trusted as a precision/correctness guarantee.
    if not isinstance(rng.bit_generator, (np.random.PCG64, np.random.PCG64DXSM)):
        if signal_mode == 'binary':
            return rng.integers(0, 2, size=(rows, cols), dtype=np.int8) * 2 - 1
        return rng.integers(-64, 64, size=(rows, cols), dtype=np.int8)
    count = rows * cols
    values = rng.bit_generator.random_raw((count + 7) // 8).view(np.int8)[:count].reshape(rows, cols)
    if signal_mode == 'binary':
        np.right_shift(values, 7, out=values)
        np.bitwise_or(values, 1, out=values)
    else:
        np.right_shift(values, 1, out=values)
    return values


class Grid:
    """One committed pair (A, Bᵀ) bound to a job's header + config."""

    def __init__(self, shape: JobShape, m_dim: int, n_dim: int,
                 header_bytes: bytes, rng: np.random.Generator,
                 cert_version: int = 2):
        self.shape = shape
        self.cert_version = ref.validate_cert_version(cert_version)
        self.m_dim, self.n_dim = m_dim, n_dim
        self.A = _random_signal(rng, m_dim, shape.k)
        self.Bt = _random_signal(rng, n_dim, shape.k)
        config_bytes = ref.config_to_bytes(shape.k, shape.r,
                                           shape.rows_pattern, shape.cols_pattern)
        self.job_key = ref.compute_job_key(header_bytes, config_bytes)
        a_pad = ref.pad_to_chunk_boundary(self.A.tobytes())
        bt_pad = ref.pad_to_chunk_boundary(self.Bt.tobytes())
        self.tree_a = pm.MerkleTree(data=a_pad, key=self.job_key)
        self.tree_bt = pm.MerkleTree(data=bt_pad, key=self.job_key)
        # The already-built immutable Merkle trees expose the same keyed
        # BLAKE3 roots. Avoid hashing both full matrices for a second time.
        self.b_seed, self.a_seed = ref.commitment_from_roots(
            self.job_key, bytes(self.tree_a.root), bytes(self.tree_bt.root), cert_version=self.cert_version,
            m=m_dim, n=n_dim)

    def craft_proof(self, base_r: int, base_c: int) -> pm.PlainProof:
        rows = [base_r + p for p in self.shape.rows_pattern.to_list()]
        cols = [base_c + q for q in self.shape.cols_pattern.to_list()]
        la = pm.MerkleTree.compute_leaf_indices_from_rows(rows, (self.m_dim, self.shape.k))
        lb = pm.MerkleTree.compute_leaf_indices_from_rows(cols, (self.n_dim, self.shape.k))
        return pm.PlainProof(
            self.m_dim, self.n_dim, self.shape.k, self.shape.r,
            pm.MatrixMerkleProof(self.tree_a.get_multileaf_proof(la), rows),
            pm.MatrixMerkleProof(self.tree_bt.get_multileaf_proof(lb), cols), None)


def reuse_b_enabled() -> bool:
    """Explicit experiment switch; ordinary Grid construction is unchanged."""
    value = os.environ.get('FUSION_METAL_REUSE_B', '0')
    if value not in ('0', '1'):
        raise ValueError('FUSION_METAL_REUSE_B must be 0 or 1')
    return value == '1'


def _immutable_identity(value):
    """Reject mutable/custom identity members rather than caching their address."""
    if value is None or type(value) in (bool, int, str, bytes):
        return value
    if type(value) is tuple:
        return tuple(_immutable_identity(item) for item in value)
    raise TypeError('job identity must contain only immutable primitive values/tuples')


@dataclass(frozen=True)
class BGeneration:
    """An owned, content-bound generation, never an ndarray/pointer cache key."""
    owner: str
    number: int
    scope: tuple
    root: bytes
    seed: bytes


@dataclass(frozen=True)
class _FixedBState:
    generation: BGeneration
    data: bytes = field(repr=False)
    tree: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class ReusableGrid:
    """Committed immutable snapshots, so proof and upload cannot diverge.

    A merely read-only owning ndarray can be made writable again. These views
    instead terminate in immutable bytes: setflags(write=True) is refused.
    The frozen object also refuses replacing an operand/seed/tree field.
    """
    shape: JobShape
    m_dim: int
    n_dim: int
    cert_version: int
    job_key: bytes
    a_seed: bytes
    b_seed: bytes
    tree_a: object = field(repr=False, compare=False)
    tree_bt: object = field(repr=False, compare=False)
    b_generation: BGeneration
    _a_bytes: bytes = field(repr=False)
    _b_bytes: bytes = field(repr=False)

    @property
    def A(self) -> np.ndarray:
        return np.frombuffer(self._a_bytes, dtype=np.int8).reshape(self.m_dim, self.shape.k)

    @property
    def Bt(self) -> np.ndarray:
        return np.frombuffer(self._b_bytes, dtype=np.int8).reshape(self.n_dim, self.shape.k)

    def craft_proof(self, base_r: int, base_c: int) -> pm.PlainProof:
        return Grid.craft_proof(self, base_r, base_c)


class FixedBFactory:
    """One factory's single-job B cache; opt-in and thread-serialized.

    Callers supply the session/job identity as well as the header. Configuration,
    certificate version, matrix dimensions and signal mode are also bound. A
    scope change evicts the old cache; returning to a previous scope rebuilds B.
    No global cache or input-address identity is used.
    """

    def __init__(self, rng: np.random.Generator | None = None):
        self.rng = rng if rng is not None else np.random.default_rng()
        self._owner = uuid.uuid4().hex
        self._generation = 0
        self._state: _FixedBState | None = None
        self._a_roots: set[bytes] = set()
        self._lock = threading.Lock()
        self.last_profile: dict = {}

    def clear(self):
        with self._lock:
            self._state = None
            self._a_roots.clear()

    def prepare(self, shape: JobShape, m_dim: int, n_dim: int,
                header_bytes: bytes, *, cert_version: int = 2,
                job_identity=None) -> Grid | ReusableGrid:
        with self._lock:
            started = time.perf_counter()
            if not reuse_b_enabled():
                self._state = None
                self._a_roots.clear()
                grid = Grid(shape, m_dim, n_dim, header_bytes, self.rng, cert_version)
                self.last_profile = {'total_s': time.perf_counter() - started,
                                     'reuse_enabled': False, 'b_reused': False}
                return grid

            cert_version = ref.validate_cert_version(cert_version)
            ref.validate_shape(m_dim, n_dim, shape.k, shape.r,
                               shape.rows_pattern, shape.cols_pattern)
            header_bytes = bytes(header_bytes)
            config = ref.config_to_bytes(shape.k, shape.r,
                                         shape.rows_pattern, shape.cols_pattern)
            job_key = ref.compute_job_key(header_bytes, config)
            signal_mode = os.environ.get('FUSION_METAL_SIGNAL', 'full')
            if signal_mode not in ('full', 'binary'):
                raise ValueError('FUSION_METAL_SIGNAL must be full or binary')
            scope = (_immutable_identity(job_identity), header_bytes, config,
                     cert_version, m_dim, n_dim, signal_mode)
            if self._state is not None and self._state.generation.scope != scope:
                self._state = None
                self._a_roots.clear()
            state = self._state
            profile = {'reuse_enabled': True, 'b_reused': state is not None,
                       'b_generate_s': 0.0, 'b_freeze_s': 0.0, 'b_tree_s': 0.0}
            if state is None:
                at = time.perf_counter()
                b = _random_signal(self.rng, n_dim, shape.k)
                profile['b_generate_s'] = time.perf_counter() - at
                at = time.perf_counter()
                b_bytes = b.tobytes()
                del b
                profile['b_freeze_s'] = time.perf_counter() - at
                at = time.perf_counter()
                tree_bt = pm.MerkleTree(data=ref.pad_to_chunk_boundary(b_bytes), key=job_key)
                profile['b_tree_s'] = time.perf_counter() - at
            else:
                b_bytes, tree_bt = state.data, state.tree

            # Distinct commitments ensure new work even if a caller resets RNG.
            # A broken/repeating RNG fails closed rather than silently rescans.
            profile.update(a_generate_s=0.0, a_freeze_s=0.0, a_tree_s=0.0)
            for _ in range(4):
                at = time.perf_counter()
                a = _random_signal(self.rng, m_dim, shape.k)
                profile['a_generate_s'] += time.perf_counter() - at
                at = time.perf_counter()
                a_bytes = a.tobytes()
                del a
                profile['a_freeze_s'] += time.perf_counter() - at
                at = time.perf_counter()
                tree_a = pm.MerkleTree(data=ref.pad_to_chunk_boundary(a_bytes), key=job_key)
                a_root = bytes(tree_a.root)
                profile['a_tree_s'] += time.perf_counter() - at
                if a_root not in self._a_roots:
                    break
            else:
                raise RuntimeError('repeated A commitment: refusing duplicate mining work')
            at = time.perf_counter()
            b_seed, a_seed = ref.commitment_from_roots(
                job_key, a_root, bytes(tree_bt.root), cert_version=cert_version,
                m=m_dim, n=n_dim)
            profile['derive_seeds_s'] = time.perf_counter() - at
            if state is None:
                self._generation += 1
                token = BGeneration(self._owner, self._generation, scope, bytes(tree_bt.root), b_seed)
                state = _FixedBState(token, b_bytes, tree_bt)
                self._state = state
            elif b_seed != state.generation.seed or bytes(tree_bt.root) != state.generation.root:
                raise RuntimeError('fixed B commitment or seed changed inside its cache scope')
            self._a_roots.add(a_root)
            grid = ReusableGrid(shape, m_dim, n_dim, cert_version, job_key,
                                a_seed, b_seed, tree_a, tree_bt, state.generation,
                                a_bytes, b_bytes)
            profile['total_s'] = time.perf_counter() - started
            profile['b_generation'] = state.generation.number
            self.last_profile = profile
            return grid


def share_nbits(pool_target: int) -> int:
    """Compact encoding of the pool's base target, floor-rounded, for
    verify_plain_proof's nbits_override. Floor makes the local check equal or
    STRICTER than the pool's — a share that passes locally passes remotely
    (up to the pool's own view of the job)."""
    return ref.target_to_nbits(pool_target)


def verify_share(header: pm.IncompleteBlockHeader, proof: pm.PlainProof,
                 pool_target: int, cert_version: int = 2) -> tuple[bool, str]:
    """Local verification AT SHARE DIFFICULTY — never without the override
    (without it the verifier checks BLOCK difficulty and rejects perfectly
    valid shares, making the check theatre)."""
    ref.validate_cert_version(cert_version)
    return pm.verify_plain_proof_for_cert_version(
        cert_version, header, proof, nbits_override=share_nbits(pool_target))
