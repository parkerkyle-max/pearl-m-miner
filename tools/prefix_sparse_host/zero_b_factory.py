"""Opt-in zero-B / sparse-A-nonce immutable grids for the prefix miner.

Import starts no threads, GPUs or mining. install_zero_b(miner) replaces only
that module's GridFactory; pair with install_prefix_engine from its native
adapter. The background factory owns an independent Metal noise context.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import uuid
import weakref

import numpy as np
import pearl_mining as pm
from pearl_metal_miner import host, reference as ref
from pearl_metal_miner.metal_capi import Metal

_HERE = Path(__file__).resolve().parent
_OVERLAY = os.environ.get('FUSION_OVERLAY_ROOT')
if _OVERLAY:
    sys.path.insert(0, str(Path(_OVERLAY).resolve()))
else:
    for _candidate in (_HERE.parent/'m1-merkle-incremental-research',
                       Path(host.__file__).resolve().parents[1]/'tools/merkle_overlay'):
        if (_candidate/'overlay_probe.py').exists():
            sys.path.insert(0, str(_candidate))
            break
from overlay_probe import LEAF, NativePath, NonceOverlayFactory, OverlayScope

_FACTORIES = weakref.WeakSet()


def _enabled():
    value = os.environ.get('FUSION_METAL_ZERO_B', '0')
    if value not in ('0', '1'):
        raise ValueError('FUSION_METAL_ZERO_B must be 0 or 1')
    return value == '1'


@dataclass(frozen=True)
class OverlayTree:
    overlay: object = field(repr=False, compare=False)

    @property
    def root(self):
        return self.overlay.root

    def get_multileaf_proof(self, indices):
        return self.overlay.proof(pm, indices, scope=self.overlay.scope)


@dataclass(frozen=True)
class PrefixGrid:
    shape: object
    m_dim: int
    n_dim: int
    cert_version: int
    job_key: bytes
    a_seed: bytes
    b_seed: bytes
    tree_a: object = field(repr=False, compare=False)
    tree_bt: object = field(repr=False, compare=False)
    b_generation: host.BGeneration
    _base_a: bytes = field(repr=False)
    _b_bytes: bytes = field(repr=False)
    _x_bytes: bytes = field(repr=False)
    _v_bytes: bytes = field(repr=False)
    profile_items: tuple = field(repr=False)
    _fusion_zero_b_prefix = True
    prefix_x_layout = 'prefix-major'

    @property
    def prefix_x(self):
        return np.frombuffer(self._x_bytes, np.int32).reshape(32, self.m_dim, 128)

    @property
    def prefix_v(self):
        return np.frombuffer(self._v_bytes, np.int8).reshape(self.n_dim, 128)

    @property
    def A(self):
        # Compatibility/oracle only. Normal prefix preparation/proof never
        # materializes a full A snapshot, avoiding two 64MiB copies per grid.
        overlay = self.tree_a.overlay
        lo = overlay.nonce_index * LEAF
        data = self._base_a[:lo] + overlay.leaf + self._base_a[lo+LEAF:]
        return np.frombuffer(data, np.int8).reshape(self.m_dim, self.shape.k)

    @property
    def Bt(self):
        return np.frombuffer(self._b_bytes, np.int8).reshape(self.n_dim, self.shape.k)

    def craft_proof(self, base_r, base_c):
        return host.Grid.craft_proof(self, base_r, base_c)


@dataclass(frozen=True)
class SparsePrefixGrid(PrefixGrid):
    """Committed sparse sources; normal mining never materializes host X."""
    _u_bytes: bytes = field(repr=False)
    _pa_bytes: bytes = field(repr=False)
    _qb_bytes: bytes = field(repr=False)
    _nonce_leaf: bytes = field(repr=False)
    nonce_leaf_index: int
    _fusion_zero_b_sparse = True

    @property
    def prefix_u(self):
        return np.frombuffer(self._u_bytes,np.int8).reshape(self.m_dim,128)

    @property
    def prefix_pa(self):
        return np.frombuffer(self._pa_bytes,np.uint32).reshape(4096,2)

    @property
    def prefix_qb(self):
        return np.frombuffer(self._qb_bytes,np.uint32).reshape(4096,2)

    @property
    def prefix_nonce_leaf(self):
        return self._nonce_leaf

    @property
    def prefix_x(self):
        raise RuntimeError('sparse grid has no host X; explicitly call materialize_prefix_x() only for an oracle')

    def materialize_prefix_x(self,workers=2):
        """Explicit expensive compatibility oracle; never called by mining."""
        transform=SparseTransform(workers,os.environ.get('FUSION_PREFIX_TRANSFORM_LIBRARY'))
        try:
            x=transform.build(self.prefix_u,self.prefix_pa,self.prefix_qb,self._nonce_leaf,self.nonce_leaf_index)
            return np.frombuffer(x.tobytes(),np.int32).reshape(32,self.m_dim,128)
        finally:
            transform.close()


class SparseTransform:
    def __init__(self, workers=2, library=None):
        if not 1 <= workers <= 64:
            raise ValueError('prefix workers must be 1..64')
        if library is None:
            library = next((p for p in (_HERE/'build/libprefixsparse.dylib',
                                       _HERE/'build/libprefixsparse.so') if p.exists()), None)
        if library is None:
            raise RuntimeError('run sh build_sparse.sh first')
        self.lib = C.CDLL(str(library))
        self.fn = self.lib.zf_build_zero_nonce_prefix
        self.fn.argtypes = [C.c_void_p]*3+[C.c_char_p,C.c_uint64]+[C.c_uint32]*5+[C.c_void_p]
        self.fn.restype = C.c_int
        self.workers = workers
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='prefix-scatter')

    def build(self, u, pa, qb, leaf, leaf_index):
        m = u.shape[0]
        if (u.dtype != np.int8 or u.shape != (m,128) or not u.flags.c_contiguous
            or pa.dtype != np.uint32 or pa.shape != (4096,2) or not pa.flags.c_contiguous
            or qb.dtype != np.uint32 or qb.shape != (4096,2) or not qb.flags.c_contiguous
            or type(leaf) is not bytes or len(leaf) != LEAF):
            raise ValueError('unexpected prefix transform input')
        if type(leaf_index) is not int or not 0 <= leaf_index < m*4:
            raise ValueError('nonce leaf outside A')
        out = np.empty((32,m,128), np.int32)
        def run(lo,hi):
            rc = self.fn(u.ctypes.data,pa.ctypes.data,qb.ctypes.data,leaf,leaf_index,
                         m,4096,128,lo,hi-lo,out.ctypes.data)
            if rc:
                raise RuntimeError(f'sparse prefix transform rejected inputs: {rc}')
        edges = np.linspace(0,m,min(self.workers,m)+1,dtype=int)
        futures = [self.executor.submit(run,int(lo),int(hi)) for lo,hi in zip(edges[:-1],edges[1:])]
        # Even on failure, wait for every disjoint writer before releasing out.
        error = None
        for future in futures:
            try:
                future.result()
            except Exception as caught:
                error = error or caught
        if error:
            raise error
        return out

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=False)


class NoiseSource:
    """Owned synchronous noise context; never shares mutable Engine buffers."""
    def __init__(self, shape, m, n, backend='metal'):
        self.shape,self.m,self.n,self.backend = shape,m,n,backend
        self.metal = None
        self.buffers = []
        self.b_seed = self.v_bytes = self.qb_bytes = None
        if backend == 'metal':
            try:
                self.metal = Metal(os.environ['FUSION_PREFIX_NOISE_LIBRARY']) if os.environ.get('FUSION_PREFIX_NOISE_LIBRARY') else Metal()
                self.metal.compile(shape)
                for size in (m*128,n*128,4096*8,4096*8):
                    self.buffers.append(self.metal.alloc(size))
                self.ua,self.ub,self.pa,self.qb = self.buffers
            except BaseException:
                self.close()
                raise
        elif backend != 'reference':
            raise ValueError('FUSION_PREFIX_NOISE must be metal or reference')

    def get(self,a_seed,b_seed):
        if self.backend == 'metal':
            self.metal.noise_uniform(ref.SEED_LABEL_A,a_seed,self.ua,self.m)
            self.metal.noise_pairs(ref.SEED_LABEL_A,a_seed,self.pa)
            u = self.ua.array(np.int8,(self.m,128))
            pa = self.pa.array(np.uint32,(4096,2))
        else:
            u = ref.uniform_noise_rows(ref.SEED_LABEL_A,a_seed,range(self.m),128)
            pa = ref.permutation_pairs(ref.SEED_LABEL_A,a_seed,4096,128)
        if self.b_seed != b_seed:
            if self.backend == 'metal':
                self.metal.noise_uniform(ref.SEED_LABEL_B,b_seed,self.ub,self.n)
                self.metal.noise_pairs(ref.SEED_LABEL_B,b_seed,self.qb)
                v = self.ub.array(np.int8,(self.n,128))
                qb = self.qb.array(np.uint32,(4096,2))
            else:
                v = ref.uniform_noise_rows(ref.SEED_LABEL_B,b_seed,range(self.n),128)
                qb = ref.permutation_pairs(ref.SEED_LABEL_B,b_seed,4096,128)
            # Commit cache only after both independent GPU calls succeeded.
            v_bytes,qb_bytes = v.tobytes(),qb.tobytes()
            self.b_seed,self.v_bytes,self.qb_bytes = b_seed,v_bytes,qb_bytes
        return u,pa,self.v_bytes,np.frombuffer(self.qb_bytes,np.uint32).reshape(4096,2)

    def invalidate_b(self):
        self.b_seed = self.v_bytes = self.qb_bytes = None

    def close(self):
        for buf in self.buffers:
            buf.release()
        self.buffers.clear()
        if self.metal is not None and self.metal._ctx:
            self.metal._lib.pm_destroy(self.metal._ctx)
            self.metal._ctx = None
        self.metal = None
        self.invalidate_b()


class ZeroBFactory:
    def __init__(self, rng=None, *, workers=None, noise_backend=None):
        self._lock = threading.RLock()
        self._owner = uuid.uuid4().hex
        self._generation = 0
        self._scope = None
        self._noise = None
        self._resource_shape = None
        self._closed = False
        configured = os.environ.get('FUSION_PREFIX_NONCE_START')
        self._next = int(configured,0) if configured is not None else secrets.randbits(128)
        if not 0 <= self._next < (1<<128):
            raise ValueError('nonce start exceeds 128 bits')
        self._backend = noise_backend or os.environ.get('FUSION_PREFIX_NOISE','metal')
        flag=os.environ.get('FUSION_PREFIX_GPU_PREPARE','0')
        if flag not in ('0','1'):
            raise ValueError('FUSION_PREFIX_GPU_PREPARE must be 0 or 1')
        self._gpu_prepare=flag=='1'
        self._transform = None if self._gpu_prepare else SparseTransform(
            workers or int(os.environ.get('FUSION_PREFIX_WORKERS','2')),
            os.environ.get('FUSION_PREFIX_TRANSFORM_LIBRARY'))
        self.last_profile = {}

    def prepare(self, shape, m_dim, n_dim, header_bytes, *, cert_version=2, job_identity=None):
        with self._lock:
            if self._closed:
                raise RuntimeError('zero-B factory is closed')
            began = time.perf_counter()
            ref.validate_shape(m_dim,n_dim,shape.k,shape.r,shape.rows_pattern,shape.cols_pattern)
            if (shape.k != 4096 or shape.r != 128 or not 64<=m_dim<=16384 or not 64<=n_dim<=65536 or m_dim%64 or n_dim%64
                or shape.rows_pattern.to_list() != [0,32]
                or shape.cols_pattern.to_list() != list(range(64))):
                raise ValueError('prefix experiment requires K4096 rank128 64-divisible default tile shape')
            cert_version = ref.validate_cert_version(cert_version)
            header_bytes = bytes(header_bytes)
            config = ref.config_to_bytes(shape.k,shape.r,shape.rows_pattern,shape.cols_pattern)
            identity = host._immutable_identity(job_identity)
            nonce_leaf = int(os.environ.get('FUSION_METAL_NONCE_LEAF','0'),0)
            if not 0 <= nonce_leaf < m_dim*4:
                raise ValueError('nonce leaf outside A')
            scope = (identity,header_bytes,config,cert_version,m_dim,n_dim,nonce_leaf)
            profile = {'noise_backend':self._backend,'b_reused':scope==self._scope,
                       'cold_commit_s':0.0,'noise_context_init_s':0.0,'a_snapshot_copied_bytes':0}
            resource_shape = (shape,m_dim,n_dim)
            if resource_shape != self._resource_shape:
                at = time.perf_counter()
                if self._noise is not None:
                    self._noise.close()
                    self._noise = None
                    self._resource_shape = None
                self._noise = NoiseSource(shape,m_dim,n_dim,self._backend)
                self._resource_shape = resource_shape
                profile['noise_context_init_s'] = time.perf_counter()-at
            if scope != self._scope:
                at = time.perf_counter()
                job_key = ref.compute_job_key(header_bytes,config)
                base_a,b_bytes = bytes(m_dim*4096),bytes(n_dim*4096)
                tree_a = pm.MerkleTree(data=base_a,key=job_key)
                tree_b = pm.MerkleTree(data=b_bytes,key=job_key)
                overlay_scope = OverlayScope(identity,header_bytes,config,cert_version,m_dim,n_dim,4096)
                nonce_factory = NonceOverlayFactory(pm,tree_a,job_key,nonce_leaf,m_dim*4,
                    overlay_scope,NativePath(os.environ.get('FUSION_MERKLE_LIBRARY') or None))
                b_seed,_ = ref.commitment_from_roots(job_key,bytes(tree_a.root),bytes(tree_b.root),
                    cert_version=cert_version,m=m_dim,n=n_dim)
                self._generation += 1
                generation = host.BGeneration(self._owner,self._generation,scope,bytes(tree_b.root),b_seed)
                self._base_a,self._b_bytes,self._tree_b = base_a,b_bytes,tree_b
                self._job_key,self._nonce_factory = job_key,nonce_factory
                self._b_generation,self._scope = generation,scope
                self._noise.invalidate_b()
                profile['cold_commit_s'] = time.perf_counter()-at
            if self._next >= (1<<128):
                raise RuntimeError('nonce range exhausted; create a new worker scope')
            at = time.perf_counter()
            overlay = self._nonce_factory.make(self._next,scope=self._nonce_factory.scope)
            self._next += 1
            b_seed,a_seed = ref.commitment_from_roots(self._job_key,overlay.root,bytes(self._tree_b.root),
                cert_version=cert_version,m=m_dim,n=n_dim)
            if b_seed != self._b_generation.seed:
                raise RuntimeError('nonce altered cached B commitment seed')
            profile['nonce_path_and_seed_s'] = time.perf_counter()-at
            at = time.perf_counter()
            u,pa,v_bytes,qb = self._noise.get(a_seed,b_seed)
            profile['noise_s'] = time.perf_counter()-at
            if self._gpu_prepare:
                at=time.perf_counter()
                # Detach all source snapshots from the factory's reusable Metal
                # buffers. No borrowed addresses or mutable NumPy ownership.
                u_bytes,pa_bytes,qb_bytes=u.tobytes(),pa.tobytes(),qb.tobytes()
                leaf=bytes(overlay.leaf)
                profile['sparse_freeze_s']=time.perf_counter()-at
                profile['gpu_prepare']=True
                profile['x_transform_s']=profile['x_freeze_s']=0.0
                profile['x_snapshot_copied_bytes']=0
                profile['sparse_snapshot_copied_bytes']=len(u_bytes)+len(pa_bytes)+len(qb_bytes)+len(leaf)
                profile['b_generation']=self._generation
                profile['nonce_leaf']=nonce_leaf
                profile['total_s']=time.perf_counter()-began
                self.last_profile=profile
                return SparsePrefixGrid(shape,m_dim,n_dim,cert_version,self._job_key,a_seed,b_seed,
                    OverlayTree(overlay),self._tree_b,self._b_generation,self._base_a,self._b_bytes,
                    b'',v_bytes,tuple(profile.items()),u_bytes,pa_bytes,qb_bytes,leaf,nonce_leaf)
            at = time.perf_counter()
            x = self._transform.build(u,pa,qb,overlay.leaf,nonce_leaf)
            profile['x_transform_s'] = time.perf_counter()-at
            at = time.perf_counter()
            x_bytes = x.tobytes()
            del x
            profile['x_freeze_s'] = time.perf_counter()-at
            profile['x_snapshot_copied_bytes'] = len(x_bytes)
            profile['b_generation'] = self._generation
            profile['nonce_leaf'] = nonce_leaf
            profile['total_s'] = time.perf_counter()-began
            self.last_profile = profile
            return PrefixGrid(shape,m_dim,n_dim,cert_version,self._job_key,a_seed,b_seed,
                OverlayTree(overlay),self._tree_b,self._b_generation,self._base_a,self._b_bytes,
                x_bytes,v_bytes,tuple(profile.items()))

    def clear(self):
        with self._lock:
            self._scope = None
            for name in ('_base_a','_b_bytes','_tree_b','_job_key','_nonce_factory','_b_generation'):
                self.__dict__.pop(name,None)
            if self._noise is not None:
                self._noise.invalidate_b()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.clear()
            if self._noise is not None:
                self._noise.close()
                self._noise = None
            if self._transform is not None:
                self._transform.close()


def install_zero_b(miner_module=None):
    """Install factory only. No live worker/Metal context starts until used."""
    if not _enabled():
        return False
    if miner_module is None:
        from pearl_metal_miner import miner as miner_module
    if getattr(miner_module,'_fusion_zero_b_installed',False):
        return True
    if getattr(miner_module,'_fusion_fixed_b_installed',False):
        raise RuntimeError('zero-B worker is independent; do not combine the old fixed-B factory patch')

    class PrefixGridFactory(threading.Thread):
        def __init__(self,shape,m_dim,n_dim):
            super().__init__(daemon=True,name='prefix-grid-prepare')
            self.shape,self.m_dim,self.n_dim = shape,m_dim,n_dim
            self._host_factory = ZeroBFactory()
            self._condition = threading.Condition()
            self._stop_requested = False
            self._queued = self._building = None
            self._ready = []
            self.profile_totals = {'grids':0,'prepare_seconds':0.0,'discarded_ready':0}
            _FACTORIES.add(self)
            self.start()

        def _snapshot(self,job):
            identity = miner_module.job_identity(job)
            if not isinstance(identity,tuple) or len(identity)!=4:
                raise ValueError('unexpected miner job identity')
            identity = host._immutable_identity((identity[0],identity[1],bytes(identity[2]),identity[3]))
            return identity,identity[2],identity[3]

        def _request_locked(self,snapshot):
            if self._stop_requested:
                raise RuntimeError('prefix factory is closed')
            if self._building != snapshot and self._queued != snapshot and not any(item[0]==snapshot for item in self._ready):
                self._queued = snapshot  # latest requested job replaces stale queued work
                self._condition.notify_all()

        def request(self,job):
            snapshot = self._snapshot(job)
            with self._condition:
                self._request_locked(snapshot)

        def take(self,job):
            snapshot = self._snapshot(job)
            with self._condition:
                while True:
                    if self._stop_requested:
                        raise RuntimeError('prefix factory closed while waiting')
                    while self._ready:
                        prepared,grid,error = self._ready.pop(0)
                        if prepared != snapshot:
                            self.profile_totals['discarded_ready'] += 1
                            continue
                        if error is not None:
                            raise RuntimeError('prefix background preparation failed') from error
                        return grid
                    self._request_locked(snapshot)
                    self._condition.wait()

        def run(self):
            try:
                while True:
                    with self._condition:
                        while self._queued is None and not self._stop_requested:
                            self._condition.wait()
                        if self._stop_requested:
                            return
                        snapshot,self._queued = self._queued,None
                        self._building = snapshot
                    identity,header,cert = snapshot
                    grid,error = None,None
                    try:
                        grid = self._host_factory.prepare(self.shape,self.m_dim,self.n_dim,header,
                            cert_version=cert,job_identity=identity)
                    except BaseException as caught:
                        error = caught
                    with self._condition:
                        self._building = None
                        if self._stop_requested:
                            return
                        # At most one ready generation; old snapshots already
                        # returned to callers remain immutable and owned there.
                        self.profile_totals['discarded_ready'] += len(self._ready)
                        self._ready[:] = [(snapshot,grid,error)]
                        if grid is not None:
                            self.profile_totals['grids'] += 1
                            self.profile_totals['prepare_seconds'] += self._host_factory.last_profile['total_s']
                        self._condition.notify_all()
            finally:
                self._host_factory.close()

        def close(self):
            with self._condition:
                self._stop_requested = True
                self._queued = None
                self._ready.clear()
                self._condition.notify_all()
            if threading.current_thread() is not self:
                self.join()  # native synchronous calls must finish before freeing buffers

    miner_module.GridFactory = PrefixGridFactory
    miner_module._fusion_zero_b_installed = True
    return True


def close_factories():
    records = []
    for factory in list(_FACTORIES):
        factory.close()
        records.append(dict(factory.profile_totals))
    return records
