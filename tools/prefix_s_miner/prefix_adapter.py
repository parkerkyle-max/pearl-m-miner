"""Independent synchronous prefix engine. Importing this module changes nothing."""
from __future__ import annotations
import ctypes as C
import hashlib
import itertools
import json
import os
from pathlib import Path
import threading
import time
import weakref
import numpy as np

HERE=Path(__file__).resolve().parent
_ENGINES=[]
_CONNECTIONS=[]
_EPOCHS=itertools.count(1)

class PrepStats(C.Structure):
    _fields_=[('wall_seconds',C.c_double),('upload_seconds',C.c_double),('guard_gpu_seconds',C.c_double),
              ('guard_flags',C.c_uint32),('reserved',C.c_uint32)]
    def record(self):return {name:getattr(self,name) for name,_ in self._fields_}

class ScanResult(C.Structure):
    _fields_=[('epoch',C.c_uint64),('tiles',C.c_uint64)]+[(name,C.c_uint32) for name in
              ('band_lo','n_bands','stored_hits','total_hits')]+[('wall_seconds',C.c_double),('gpu_seconds',C.c_double)]
    def record(self):return {name:getattr(self,name) for name,_ in self._fields_}

class PrefixError(RuntimeError):pass

class SDetail(C.Structure):
    _fields_=[(name,C.c_uint64) for name in ('version','method','scratch_reused','s_bytes','correction_bytes')]+[
        (name,C.c_double) for name in ('build_seconds','qb_validation_seconds','scratch_wait_seconds')]
    def record(self):return {name:getattr(self,name) for name,_ in self._fields_}

def selected_prepare_method(value=None):
    method=os.environ.get('FUSION_PREFIX_PREPARE_METHOD','csr') if value is None else value
    if method not in ('csr','s'):raise PrefixError('FUSION_PREFIX_PREPARE_METHOD must be csr or s')
    return method

class Native:
    def __init__(self,library=None,shader=None):
        self.lib=C.CDLL(str(Path(library or os.environ.get('FUSION_PREFIX_LIBRARY',HERE/'libprefix.dylib')).resolve()))
        self.lib.pfx_abi_version.argtypes=[];self.lib.pfx_abi_version.restype=C.c_uint32
        if self.lib.pfx_abi_version()!=1:raise PrefixError('unsupported prefix native ABI')
        self.lib.pfx_thermal_state.argtypes=[];self.lib.pfx_thermal_state.restype=C.c_int
        self._local=threading.local();self.context=0
        error=[C.c_char_p,C.c_size_t]
        self.lib.pfx_context_create.argtypes=[C.c_char_p,C.c_size_t,C.POINTER(C.c_uint64)]+error
        self.lib.pfx_context_close.argtypes=[C.c_uint64]+error
        self.lib.pfx_device_name.argtypes=[C.c_uint64,C.c_char_p,C.c_size_t]+error
        self.lib.pfx_prepare.argtypes=[C.c_uint64,C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,
            C.c_uint32,C.c_uint32,C.c_char_p,C.c_uint64,C.POINTER(C.c_uint64),C.POINTER(C.c_uint64),C.POINTER(PrepStats)]+error
        self.lib.pfx_scan.argtypes=[C.c_uint64]*3+[C.c_uint32]*2+[C.c_char_p]*2+[C.c_void_p,C.c_uint32,
            C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(ScanResult)]+error
        self.lib.pfx_close.argtypes=[C.c_uint64]*2+error
        for name in ('context_create','context_close','device_name','prepare','scan','close'):
            getattr(self.lib,'pfx_'+name).restype=C.c_int
        self.sparse_supported=False
        if hasattr(self.lib,'pfx_sparse_abi_version'):
            self.lib.pfx_sparse_abi_version.argtypes=[];self.lib.pfx_sparse_abi_version.restype=C.c_uint32
            if self.lib.pfx_sparse_abi_version()!=1:raise PrefixError('unsupported sparse native ABI')
            self.lib.pfx_prepare_sparse.argtypes=[C.c_uint64]+[C.c_void_p,C.c_size_t]*4+[
                C.c_uint32,C.c_void_p,C.c_size_t,C.c_uint32,C.c_uint32,C.c_char_p,C.c_uint64,C.c_uint32,
                C.POINTER(C.c_uint64),C.POINTER(C.c_uint64),C.POINTER(PrepStats)]+error
            self.lib.pfx_export_sparse.argtypes=[C.c_uint64]*3+[C.c_void_p,C.c_size_t]*2+error
            self.lib.pfx_prepared_kind.argtypes=[C.c_uint64]*3+[C.POINTER(C.c_uint32)]+error
            for name in ('prepare_sparse','export_sparse','prepared_kind'):
                getattr(self.lib,'pfx_'+name).restype=C.c_int
            self.sparse_supported=True
        self.s_supported=False
        if hasattr(self.lib,'pfx_s_abi_version'):
            self.lib.pfx_s_abi_version.argtypes=[];self.lib.pfx_s_abi_version.restype=C.c_uint32
            if self.lib.pfx_s_abi_version()!=1 or not self.sparse_supported:raise PrefixError('unsupported S prepare native ABI')
            self.lib.pfx_prepare_s.argtypes=self.lib.pfx_prepare_sparse.argtypes
            self.lib.pfx_prepare_s.restype=C.c_int
            self.lib.pfx_s_detail_size.argtypes=[];self.lib.pfx_s_detail_size.restype=C.c_uint32
            if self.lib.pfx_s_detail_size()!=C.sizeof(SDetail):raise PrefixError('S detail size mismatch')
            self.lib.pfx_get_s_detail.argtypes=[C.c_uint64]*3+[C.POINTER(SDetail)]+error
            self.lib.pfx_get_s_detail.restype=C.c_int
            self.s_supported=True
        source=Path(shader or os.environ.get('FUSION_PREFIX_SHADER',HERE/'prefix.metal')).read_bytes()
        handle=C.c_uint64()
        self.check(self.lib.pfx_context_create(source,len(source),C.byref(handle),self.err,len(self.err)))
        self.context=handle.value
        name=C.create_string_buffer(256)
        self.check(self.lib.pfx_device_name(self.context,name,len(name),self.err,len(self.err)))
        self.device_name=name.value.decode('utf-8','replace')
    @property
    def err(self):
        if not hasattr(self._local,'err'):self._local.err=C.create_string_buffer(2048)
        return self._local.err
    def check(self,code):
        if code:raise PrefixError(self.err.value.decode('utf-8','replace'))
    def close(self):
        if self.context:
            old,self.context=self.context,0
            self.check(self.lib.pfx_context_close(old,self.err,len(self.err)))

class Prepared:
    def __init__(self,native,x,v,seed,epoch=None):
        if not isinstance(x,np.ndarray) or x.dtype!=np.int32 or x.ndim!=3 or x.shape[0]!=32 or x.shape[2]!=128 or not x.flags.c_contiguous:
            raise ValueError('prefix X must be contiguous int32 [32,m,128]')
        if not isinstance(v,np.ndarray) or v.dtype!=np.int8 or v.ndim!=2 or v.shape[1]!=128 or not v.flags.c_contiguous:
            raise ValueError('prefix V must be contiguous int8 [n,128]')
        if len(seed)!=32:raise ValueError('seed length')
        self.native=native;self.m=x.shape[1];self.n=len(v);self.seed=bytes(seed)
        self.epoch=next(_EPOCHS) if epoch is None else int(epoch)
        self.handle=self.generation=0;self.stats=PrepStats()
        handle,generation=C.c_uint64(),C.c_uint64()
        native.check(native.lib.pfx_prepare(native.context,x.ctypes.data,x.nbytes,v.ctypes.data,v.nbytes,
            self.m,self.n,self.seed,self.epoch,C.byref(handle),C.byref(generation),C.byref(self.stats),native.err,len(native.err)))
        self.handle,self.generation=handle.value,generation.value
    def scan(self,band_lo,n_bands,bound,*,seed=None,exports=False):
        if len(bound)!=32 or len(self.seed if seed is None else seed)!=32:raise ValueError('seed/target length')
        if not 0<=band_lo<=0xffffffff or not 1<=n_bands<=0xffffffff:raise ValueError('region range')
        pairs=np.empty((4096,2),np.uint32);result=ScanResult();tiles=n_bands*32*(self.n//64)
        trans=np.empty((n_bands*32,self.n//64,16),np.uint32) if exports else None
        digests=np.empty((n_bands*32,self.n//64,32),np.uint8) if exports else None
        lib=self.native
        lib.check(lib.lib.pfx_scan(self.handle,self.generation,self.epoch,band_lo,n_bands,
            self.seed if seed is None else bytes(seed),bytes(bound),pairs.ctypes.data,4096,
            trans.ctypes.data if exports else None,trans.nbytes if exports else 0,
            digests.ctypes.data if exports else None,digests.nbytes if exports else 0,C.byref(result),lib.err,len(lib.err)))
        if (result.epoch,result.tiles,result.band_lo,result.n_bands)!=(self.epoch,tiles,band_lo,n_bands):
            raise PrefixError('native scan identity/region mismatch')
        hits=[(int(a),int(b)) for a,b in pairs[:result.stored_hits]]
        return hits,trans,digests,result
    def close(self):
        if self.handle:
            handle,generation=self.handle,self.generation
            self.handle=self.generation=0
            self.native.check(self.native.lib.pfx_close(handle,generation,self.native.err,len(self.native.err)))


class PreparedSparse(Prepared):
    """New private Prepared generation, built without a host X allocation."""
    def __init__(self,native,u,pa,qb,leaf,leaf_index,v,seed,epoch=None,debug=False,method=None):
        self.method=selected_prepare_method(method)
        if not getattr(native,'sparse_supported',False):
            raise PrefixError('GPU prefix prepare requested but sparse native ABI1 is unavailable')
        if self.method=='s' and not getattr(native,'s_supported',False):
            raise PrefixError('S prefix prepare requested but S native ABI1 is unavailable')
        if (not isinstance(u,np.ndarray) or u.ndim!=2 or not isinstance(v,np.ndarray) or v.ndim!=2):
            raise ValueError('sparse U/V must be matrices')
        for name,value,dtype,shape in (('U',u,np.int8,(len(u),128)),('PA',pa,np.uint32,(4096,2)),
                                       ('QB',qb,np.uint32,(4096,2)),('V',v,np.int8,(len(v),128))):
            if not isinstance(value,np.ndarray) or value.dtype!=dtype or value.shape!=shape or not value.flags.c_contiguous:
                raise ValueError(name+' sparse input dtype/shape/contiguity')
        if type(leaf) is not bytes or len(leaf)!=1024:raise ValueError('nonce leaf must be immutable1024 bytes')
        if type(leaf_index) is not int or not 0<=leaf_index<len(u)*4:raise ValueError('nonce leaf index')
        if len(seed)!=32:raise ValueError('seed length')
        self.native=native;self.m=len(u);self.n=len(v);self.seed=bytes(seed)
        self.epoch=next(_EPOCHS) if epoch is None else int(epoch)
        self.handle=self.generation=0;self.stats=PrepStats();self.debug=bool(debug)
        handle,generation=C.c_uint64(),C.c_uint64()
        leaf_view=np.frombuffer(leaf,np.int8)
        function=native.lib.pfx_prepare_s if self.method=='s' else native.lib.pfx_prepare_sparse
        native.check(function(native.context,u.ctypes.data,u.nbytes,
            pa.ctypes.data,pa.nbytes,qb.ctypes.data,qb.nbytes,leaf_view.ctypes.data,leaf_view.nbytes,
            leaf_index,v.ctypes.data,v.nbytes,self.m,self.n,self.seed,self.epoch,int(self.debug),
            C.byref(handle),C.byref(generation),C.byref(self.stats),native.err,len(native.err)))
        self.handle,self.generation=handle.value,generation.value
        try:
            kind=C.c_uint32()
            native.check(native.lib.pfx_prepared_kind(self.handle,self.generation,self.epoch,C.byref(kind),native.err,len(native.err)))
            expected_kind=2 if self.method=='s' else 1
            if kind.value!=expected_kind:raise PrefixError('native sparse preparation returned the wrong algorithm kind')
            self.kind=kind.value
            self.s_detail=None
            if self.kind==2:
                detail=SDetail()
                native.check(native.lib.pfx_get_s_detail(self.handle,self.generation,self.epoch,C.byref(detail),native.err,len(native.err)))
                if detail.version!=1 or detail.method!=2:raise PrefixError('S profile identity mismatch')
                self.s_detail=detail.record()
        except BaseException:
            self.close()
            raise

    def export_x(self):
        if not self.debug:raise PrefixError('sparse debug export was not explicitly enabled')
        raw=np.empty((32,self.m,128),np.int32);half=np.empty((32,self.m,128),np.float16)
        n=self.native
        n.check(n.lib.pfx_export_sparse(self.handle,self.generation,self.epoch,raw.ctypes.data,raw.nbytes,
            half.ctypes.data,half.nbytes,n.err,len(n.err)))
        return raw,half

def _observe_jobs(miner):
    if getattr(miner.PoolConnection,'_prefix_observer',False):return
    old=miner.PoolConnection.__init__
    def init(connection,*args,**kwargs):
        old(connection,*args,**kwargs)
        connection._prefix_latest=None;connection._prefix_lock=threading.Lock()
        put=connection.events.put
        def observe(event,*a,**kw):
            if isinstance(event,miner.Job):
                identity=miner.job_identity(event)
                snapshot=(tuple(identity),bytes(event.header_bytes),int(event.cert_version),int(event.target))
                with connection._prefix_lock:connection._prefix_latest=snapshot
            return put(event,*a,**kw)
        connection.events.put=observe
        _CONNECTIONS.append(weakref.ref(connection))
    miner.PoolConnection.__init__=init;miner.PoolConnection._prefix_observer=True

def install_prefix_engine(miner):
    if getattr(miner,'_prefix_engine_installed',False):return False
    _observe_jobs(miner)
    class PrefixEngine:
        def __init__(self,shape,m_dim,n_dim):
            selected_prepare_method()
            if (shape.k,shape.r)!=(4096,128) or shape.rows_pattern.to_list()!=[0,32] or shape.cols_pattern.to_list()!=list(range(64)):
                raise PrefixError('prefix engine requires K4096/R128/rows[0,32]/cols[0..63]')
            if not 64<=m_dim<=16384 or not 64<=n_dim<=65536 or m_dim%64 or n_dim%64:raise PrefixError('unsupported dimensions')
            self.shape,self.m_dim,self.n_dim=shape,m_dim,n_dim
            self.native=Native();self.device_name=self.native.device_name;self.fast=True
            self.n_bands=m_dim//64;self.n_cb=n_dim//64;self.n_tiles_grid=(m_dim//2)*self.n_cb
            self.lock=threading.RLock();self.prepared=None;self.grid=None;self.connection=None;self.job_snapshot=None
            self.grid_origin=None;self._nonce_owner=None;self._nonce_highwater=-1
            self.stale=False;self.closed=False
            self.stats={'prepares':0,'prepare_wall_s':0.0,'upload_s':0.0,'guard_gpu_s':0.0,'scans':0,
                        'gpu_s':0.0,'scan_wall_s':0.0,'completed_tiles':0,'valid_returned_tiles':0,'stale_discarded_tiles':0,'overflow_hits':0,
                        'stale_grid_loads':0,'duplicate_commitment_loads':0,'sparse_prepares':0,'legacy_prepares':0,
                        'csr_prepares':0,'s_prepares':0}
            _ENGINES.append(self)
            miner.log(f'prefix GPU engine: {self.device_name}; M={m_dim} N={n_dim}; prepare_method={selected_prepare_method()}; actual-input GPU guard; immutable snapshots; synchronous regions')
        def load_grid(self,grid):
            with self.lock:
                if self.closed:raise PrefixError('engine closed')
                if not getattr(grid,'_fusion_zero_b_prefix',False):raise PrefixError('requires committed zero-B prefix GridFactory')
                if ((selected_prepare_method()=='s' or os.environ.get('FUSION_PREFIX_GPU_PREPARE')=='1')
                    and not getattr(grid,'_fusion_zero_b_sparse',False)):
                    raise PrefixError('explicit GPU prepare selection requires the sparse-source factory')
                if grid.shape!=self.shape or (grid.m_dim,grid.n_dim)!=(self.m_dim,self.n_dim):raise PrefixError('grid shape mismatch')
                if self.prepared:self.prepared.close();self.prepared=None
                self.grid=None;self.stale=False;self.grid_origin=None
                scope=getattr(getattr(grid,'b_generation',None),'scope',None)
                if not isinstance(scope,tuple) or len(scope)!=7 or not isinstance(scope[0],tuple) or len(scope[0])!=4:
                    raise PrefixError('grid lacks complete immutable factory job binding')
                origin=scope[0]
                config=miner.ref.config_to_bytes(self.shape.k,self.shape.r,self.shape.rows_pattern,self.shape.cols_pattern)
                if (origin[2]!=scope[1] or origin[3]!=grid.cert_version or scope[2]!=config
                    or scope[3]!=grid.cert_version or scope[4:6]!=(grid.m_dim,grid.n_dim)
                    or miner.ref.compute_job_key(bytes(origin[2]),config)!=grid.job_key):
                    raise PrefixError('inconsistent grid/header/config/certificate binding')
                self.grid=grid;self.grid_origin=origin
                self.connection=next((ref() for ref in reversed(_CONNECTIONS) if ref() is not None),None)
                if self.connection is not None:
                    with self.connection._prefix_lock:self.job_snapshot=self.connection._prefix_latest
                else:self.job_snapshot=None
                if not self._scope_current():
                    self.stale=True;self.stats['stale_grid_loads']+=1;return
                # A single factory owns this engine for its entire lifetime.
                # Its globally increasing nonce survives job/session switches;
                # a bounded high-water rejects every prior nonce without eviction.
                owner=getattr(grid.b_generation,'owner',None)
                overlay=getattr(grid.tree_a,'overlay',None)
                nonce=getattr(overlay,'nonce',None)
                if not isinstance(owner,str) or not owner or type(nonce) is not int or not 0<=nonce<(1<<128):
                    raise PrefixError('missing factory owner/128-bit nonce identity')
                leaf=getattr(overlay,'leaf',None)
                expected=bytes(1 if (nonce>>bit)&1 else 255 for bit in range(128))+bytes(896)
                if leaf!=expected:raise PrefixError('nonce identity does not match committed zero-base leaf')
                if self._nonce_owner is not None and owner!=self._nonce_owner:
                    raise PrefixError('factory ownership changed; create a new worker process')
                if nonce<=self._nonce_highwater:
                    self.stale=True;self.stats['duplicate_commitment_loads']+=1;return
                if getattr(grid,'_fusion_zero_b_sparse',False):
                    u,pa,qb,v=grid.prefix_u,grid.prefix_pa,grid.prefix_qb,grid.prefix_v
                    if any(a.flags.writeable for a in (u,pa,qb,v)):
                        raise PrefixError('factory sparse arrays must be immutable during preparation')
                    leaf,index=grid.prefix_nonce_leaf,grid.nonce_leaf_index
                    overlay=getattr(grid.tree_a,'overlay',None)
                    if (overlay is None or type(leaf) is not bytes or leaf!=overlay.leaf
                        or index!=overlay.nonce_index or index!=scope[6]):
                        raise PrefixError('sparse nonce leaf/proof/scope binding differs')
                    self.prepared=PreparedSparse(self.native,u,pa,qb,leaf,index,v,bytes(grid.a_seed))
                    self.stats['sparse_prepares']+=1
                    method=getattr(self.prepared,'method',selected_prepare_method())
                    self.stats[method+'_prepares']+=1
                else:
                    x,v=grid.prefix_x,grid.prefix_v
                    if x.flags.writeable or v.flags.writeable:raise PrefixError('factory prefix arrays must be immutable during preparation')
                    self.prepared=Prepared(self.native,x,v,bytes(grid.a_seed))
                    self.stats['legacy_prepares']+=1
                self._nonce_owner=owner;self._nonce_highwater=nonce
                s=self.prepared.stats;self.stats['prepares']+=1;self.stats['prepare_wall_s']+=s.wall_seconds
                self.stats['upload_s']+=s.upload_seconds;self.stats['guard_gpu_s']+=s.guard_gpu_seconds
                if not self._scope_current():
                    self.stale=True;self.stats['stale_grid_loads']+=1
                    self.prepared.close();self.prepared=None
        def n_regions(self,region_rows):
            if not isinstance(region_rows,int) or region_rows<1:raise ValueError('region_rows')
            per=max(1,region_rows//32);return (self.n_bands+per-1)//per
        def _scope_current(self):
            if self.connection is None:return True
            c=self.connection
            with c._prefix_lock:latest=c._prefix_latest
            if c.dead.is_set() or latest is None or latest!=self.job_snapshot:return False
            identity,header,cert,target=latest
            return (identity==self.grid_origin and identity[0]==c.generation
                    and header==self.grid_origin[2] and cert==self.grid.cert_version)
        def _valid(self,bound):
            if not self._scope_current():return False
            if self.connection is None:return True
            # job_snapshot is immutable and _scope_current checked full equality
            # against latest; a concurrent change is caught after GPU completion.
            target=self.job_snapshot[3]
            value=target*miner.ref.difficulty_factor(self.shape.h,self.shape.w,self.shape.k,self.shape.r)
            return 0<=value<(1<<256) and value.to_bytes(32,'little')==bound
        def sweep_region(self,idx,region_rows,a_seed,bound):
            with self.lock:
                if self.closed or self.grid is None:raise PrefixError('load_grid required')
                seed,bound=bytes(a_seed),bytes(bound)
                if seed!=bytes(self.grid.a_seed) or len(bound)!=32:raise PrefixError('seed/target identity')
                if self.stale or not self._valid(bound):self.stale=True;return [],0
                if self.prepared is None:raise PrefixError('prepared snapshot required')
                count=self.n_regions(region_rows)
                if not isinstance(idx,int) or not 0<=idx<count:raise ValueError('region index')
                per=max(1,region_rows//32);lo=idx*per;bands=min(per,self.n_bands-lo)
                from pearl_m_miner.safety import wait_until_safe
                wait_until_safe(self.native.lib.pfx_thermal_state)
                if not self._valid(bound):self.stale=True;return [],0
                hits,_,_,result=self.prepared.scan(lo,bands,bound,seed=seed)
                self.stats['scans']+=1;self.stats['gpu_s']+=result.gpu_seconds;self.stats['scan_wall_s']+=result.wall_seconds
                self.stats['completed_tiles']+=result.tiles
                self.stats['overflow_hits']+=result.total_hits-result.stored_hits
                if not self._valid(bound):
                    self.stale=True;self.stats['stale_discarded_tiles']+=result.tiles;return [],0
                self.stats['valid_returned_tiles']+=result.tiles
                from pearl_m_miner.safety import activity
                activity(result.wall_seconds,result.tiles)
                return hits,int(result.tiles)
        def close(self):
            with self.lock:
                if self.closed:return
                self.closed=True
                try:
                    if self.prepared:self.prepared.close();self.prepared=None
                finally:self.native.close()
    miner.Engine=PrefixEngine;miner._prefix_engine_installed=True
    return True

def close_prefix_engines():
    errors=[]
    for engine in _ENGINES:
        try:engine.close()
        except Exception as error:errors.append(str(error))
    reports=[dict(e.stats,device=e.device_name) for e in _ENGINES]
    print('PREFIX_ENGINE_STATS '+json.dumps({'engines':reports,'close_errors':errors}),flush=True)
    if errors:raise PrefixError('; '.join(errors))
    return reports
