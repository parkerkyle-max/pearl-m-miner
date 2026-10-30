#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#define API extern "C" __attribute__((visibility("default")))
struct PfxPrepareDetail {
  uint64_t version,csr_cache_hit,host_copied_bytes,gpu_source_buffer_bytes;
  double argument_seconds,ownership_seconds,host_alloc_seconds,host_copy_seconds;
  double u_validation_seconds,leaf_validation_seconds,pa_validation_seconds;
  double csr_total_seconds,csr_lock_wait_seconds,csr_key_seconds,csr_build_seconds,csr_buffer_seconds;
  double source_buffer_seconds,private_buffer_seconds,misc_buffer_seconds;
  double encode_seconds,commit_seconds,wait_seconds,gpu_seconds,publish_seconds,total_wall_seconds;
  double completion_gap_seconds,unattributed_seconds;
};
static_assert(sizeof(PfxPrepareDetail)==216,"profile ABI size");
struct PfxSDetail {
  uint64_t version,method,scratch_reused,s_bytes,correction_bytes;
  double build_seconds,qb_validation_seconds,scratch_wait_seconds;
};
static_assert(sizeof(PfxSDetail)==64,"S detail ABI size");
namespace {
using Clock=std::chrono::steady_clock;
double elapsed(Clock::time_point t){return std::chrono::duration<double>(Clock::now()-t).count();}
void need(bool ok,const char *text){if(!ok)throw std::runtime_error(text);}
void metal_need(bool ok,const char *where,NSError *err=nil){
  if(!ok)throw std::runtime_error(std::string(where)+(err?std::string(": ")+err.localizedDescription.UTF8String:""));
}
template<class F> int checked(char *err,size_t size,F fn){
  @autoreleasepool {try{fn();if(err&&size)err[0]=0;return 0;}
    catch(const std::exception &e){if(err&&size)snprintf(err,size,"%s",e.what());return 1;}
    catch(...){if(err&&size)snprintf(err,size,"native unexpected exception");return 1;}}
}
struct CsrSnapshot {
  std::vector<uint32_t> qb;
  id<MTLBuffer> entries,offsets;
};
struct Context {
  id<MTLDevice> device;id<MTLCommandQueue> queue;
  id<MTLComputePipelineState> px,pv,pair,hash,scatter;
  id<MTLComputePipelineState> s_guard,s_uniform,s_form,s_finish;
  std::mutex csr_mutex;std::shared_ptr<const CsrSnapshot> csr;
  std::mutex prepare_mutex;id<MTLBuffer> s_float_scratch;
};
struct Prepared {
  std::shared_ptr<Context> c;std::mutex mutex;bool closed=false,bound_set=false;
  uint64_t generation=0,epoch=0;uint32_t m=0,n=0,next_band=0,prepare_kind=0;
  std::array<uint8_t,32> seed{},bound{};
  id<MTLBuffer> x,v,key,trans,digests,hits,dummy,debug_raw_x;
  PfxPrepareDetail detail{};
  PfxSDetail s_detail{};
};
std::mutex registry_mutex;
uint64_t next_id=1;
std::unordered_map<uint64_t,std::shared_ptr<Context>> contexts;
std::unordered_map<uint64_t,std::shared_ptr<Prepared>> prepared;
uint64_t identity(){need(next_id<std::numeric_limits<uint64_t>::max(),"identity exhausted");return next_id++;}
std::shared_ptr<Context> context(uint64_t h){std::lock_guard<std::mutex>l(registry_mutex);auto i=contexts.find(h);need(i!=contexts.end(),"unknown context");return i->second;}
std::shared_ptr<Prepared> snapshot(uint64_t h,uint64_t g){std::lock_guard<std::mutex>l(registry_mutex);auto i=prepared.find(h);need(i!=prepared.end()&&i->second->generation==g,"unknown handle/generation");return i->second;}
bool overlaps(const void*a,size_t as,const void*b,size_t bs){
  if(!as||!bs)return false;need(a&&b,"null nonempty span");
  const uintptr_t aa=reinterpret_cast<uintptr_t>(a),bb=reinterpret_cast<uintptr_t>(b);
  need(aa<=UINTPTR_MAX-as&&bb<=UINTPTR_MAX-bs,"pointer span overflow");return aa<bb+bs&&bb<aa+as;
}
void complete(id<MTLCommandBuffer>cb){metal_need(cb,"command buffer");[cb commit];[cb waitUntilCompleted];metal_need(cb.status==MTLCommandBufferStatusCompleted,"GPU command",cb.error);}
void reserve(id<MTLDevice>d,id<MTLBuffer> __strong &buffer,size_t bytes){
  if(!buffer||buffer.length<bytes)buffer=[d newBufferWithLength:bytes options:MTLResourceStorageModeShared];
  metal_need(buffer,"result allocation");
}
std::shared_ptr<const CsrSnapshot> csr_snapshot(std::shared_ptr<Context> c,const std::vector<uint32_t>&qb,PfxPrepareDetail&detail){
  auto stage=Clock::now();std::lock_guard<std::mutex>lock(c->csr_mutex);
  detail.csr_lock_wait_seconds=elapsed(stage);stage=Clock::now();
  const bool hit=c->csr&&c->csr->qb==qb;
  detail.csr_key_seconds=elapsed(stage);detail.csr_cache_hit=hit?1:0;
  if(hit)return c->csr;
  stage=Clock::now();
  need(qb.size()==8192,"QB length");
  std::array<std::vector<uint32_t>,128>buckets;
  for(uint32_t k=0;k<4096;++k){
    const uint32_t a=qb[2*k],b=qb[2*k+1];need(a<128&&b<128&&a!=b,"QB indices");
    buckets[a].push_back(k<<1);buckets[b].push_back((k<<1)|1u);
  }
  std::array<uint32_t,129>offsets{};std::vector<uint32_t>entries;entries.reserve(8192);
  for(uint32_t q=0;q<128;++q){offsets[q]=uint32_t(entries.size());entries.insert(entries.end(),buckets[q].begin(),buckets[q].end());}
  offsets[128]=uint32_t(entries.size());need(entries.size()==8192,"CSR length");
  auto s=std::make_shared<CsrSnapshot>();s->qb=qb;
  detail.csr_build_seconds=elapsed(stage);stage=Clock::now();
  s->entries=[c->device newBufferWithBytes:entries.data() length:entries.size()*4 options:MTLResourceStorageModeShared];
  s->offsets=[c->device newBufferWithBytes:offsets.data() length:offsets.size()*4 options:MTLResourceStorageModeShared];
  metal_need(s->entries&&s->offsets,"CSR owned buffers");
  detail.csr_buffer_seconds=elapsed(stage);
  c->csr=s;return s;
}
}

struct PfxPrep {double wall_seconds,upload_seconds,guard_gpu_seconds;uint32_t guard_flags,reserved;};
struct PfxResult {uint64_t epoch,tiles;uint32_t band_lo,n_bands,stored_hits,total_hits;double wall_seconds,gpu_seconds;};
static_assert(sizeof(PfxPrep)==32&&sizeof(PfxResult)==48,"ABI size");
API int pfx_thermal_state(){@autoreleasepool{return int(NSProcessInfo.processInfo.thermalState);}}
API uint32_t pfx_abi_version(){return 1;}
API uint32_t pfx_sparse_abi_version(){return 1;}
API uint32_t pfx_s_abi_version(){return 1;}
API uint32_t pfx_s_detail_size(){return uint32_t(sizeof(PfxSDetail));}
API uint32_t pfx_prepare_detail_abi_version(){return 1;}
API uint32_t pfx_prepare_detail_size(){return uint32_t(sizeof(PfxPrepareDetail));}

API int pfx_context_create(const char *source,size_t bytes,uint64_t *handle,char *err,size_t size){
  return checked(err,size,[&]{
    need(source&&bytes&&bytes<(4u<<20)&&handle,"invalid shader/context output");*handle=0;
    if(@available(macOS 26.0,*)) {
      auto c=std::make_shared<Context>();c->device=MTLCreateSystemDefaultDevice();
      if(!c->device)c->device=MTLCopyAllDevices().firstObject;metal_need(c->device,"Metal device");
      need(c->device.hasUnifiedMemory,"Apple Silicon unified-memory GPU required");
      c->queue=[c->device newCommandQueue];metal_need(c->queue,"queue");
      NSString *text=[[NSString alloc]initWithBytes:source length:bytes encoding:NSUTF8StringEncoding];need(text,"UTF8 shader");
      MTLCompileOptions *opt=[MTLCompileOptions new];opt.languageVersion=MTLLanguageVersion4_0;opt.mathMode=MTLMathModeSafe;
      NSError *e=nil;id<MTLLibrary>lib=[c->device newLibraryWithSource:text options:opt error:&e];metal_need(lib,"compile",e);
      auto pipeline=[&](NSString *name){id<MTLFunction>f=[lib newFunctionWithName:name];metal_need(f,"kernel name");
        id<MTLComputePipelineState>p=[c->device newComputePipelineStateWithFunction:f error:&e];metal_need(p,"pipeline",e);
        need(p.threadExecutionWidth==32&&p.maxTotalThreadsPerThreadgroup>=128,"unsupported SIMD/threads");return p;};
      c->px=pipeline(@"prepare_x");c->pv=pipeline(@"prepare_v");c->pair=pipeline(@"prefix_pair");c->hash=pipeline(@"prefix_hash");
      c->scatter=pipeline(@"scatter_prefix_csr");
      c->s_guard=pipeline(@"guard_s");c->s_uniform=pipeline(@"guard_uniform");
      c->s_form=pipeline(@"form_x");c->s_finish=pipeline(@"finish_x");
      std::lock_guard<std::mutex>l(registry_mutex);const uint64_t id=identity();contexts.emplace(id,c);*handle=id;
    } else throw std::runtime_error("requires macOS 26");
  });
}
API int pfx_context_close(uint64_t h,char *err,size_t size){return checked(err,size,[&]{
  std::lock_guard<std::mutex>l(registry_mutex);need(contexts.erase(h)==1,"unknown context");
});}
API int pfx_device_name(uint64_t h,char *name,size_t length,char *err,size_t size){return checked(err,size,[&]{
  need(name&&length,"device name output");auto c=context(h);snprintf(name,length,"%s",c->device.name.UTF8String);
});}

// Input sources must remain stable during this synchronous call. Once it
// returns, callers may mutate/free them: GPU half snapshots are private.
API int pfx_prepare(uint64_t ctx,const int32_t*x,size_t xb,const int8_t*v,size_t vb,
  uint32_t m,uint32_t n,const uint8_t*seed,uint64_t epoch,uint64_t *handle,uint64_t *generation,
  PfxPrep *stats,char *err,size_t size){return checked(err,size,[&]{
  const auto begin=Clock::now();need(handle&&generation&&stats,"prepare outputs");
  need(m>=64&&n>=64&&m<=16384&&n<=65536&&m%64==0&&n%64==0&&epoch&&seed,"shape/epoch/seed");
  need(x&&v&&xb==uint64_t(32)*m*128*4&&vb==uint64_t(n)*128,"input lengths");need(!overlaps(x,xb,v,vb),"aliased X/V");
  const void *inputs[3]={x,v,seed};const size_t input_sizes[3]={xb,vb,32};
  const void *outputs[3]={handle,generation,stats};const size_t output_sizes[3]={8,8,sizeof(*stats)};
  for(unsigned i=0;i<3;++i){for(unsigned j=0;j<3;++j)
    need(!overlaps(inputs[i],input_sizes[i],outputs[j],output_sizes[j]),"aliased prepare input/output");
    for(unsigned j=i+1;j<3;++j)need(!overlaps(outputs[i],output_sizes[i],outputs[j],output_sizes[j]),"aliased prepare outputs");}
  *handle=*generation=0;*stats={};
  auto p=std::make_shared<Prepared>();p->c=context(ctx);p->m=m;p->n=n;p->epoch=epoch;memcpy(p->seed.data(),seed,32);
  auto c=p->c;const auto upload=Clock::now();
  id<MTLBuffer>sx=[c->device newBufferWithBytes:x length:xb options:MTLResourceStorageModeShared];
  id<MTLBuffer>sv=[c->device newBufferWithBytes:v length:vb options:MTLResourceStorageModeShared];
  p->x=[c->device newBufferWithLength:xb/2 options:MTLResourceStorageModePrivate];
  p->v=[c->device newBufferWithLength:vb*2 options:MTLResourceStorageModePrivate];
  p->key=[c->device newBufferWithBytes:p->seed.data() length:32 options:MTLResourceStorageModeShared];
  p->dummy=[c->device newBufferWithLength:16 options:MTLResourceStorageModeShared];
  id<MTLBuffer>bad=[c->device newBufferWithLength:4 options:MTLResourceStorageModeShared];
  metal_need(sx&&sv&&p->x&&p->v&&p->key&&p->dummy&&bad,"prepare buffers");memset(bad.contents,0,4);
  stats->upload_seconds=elapsed(upload);
  id<MTLCommandBuffer>cb=[c->queue commandBuffer];metal_need(cb,"prepare command");
  id<MTLComputeCommandEncoder>e=[cb computeCommandEncoder];metal_need(e,"prepare encoder");
  uint32_t rows=32*m,elements=n*128;
  [e setComputePipelineState:c->px];[e setBuffer:sx offset:0 atIndex:0];[e setBuffer:p->x offset:0 atIndex:1];
  [e setBuffer:bad offset:0 atIndex:2];[e setBytes:&rows length:4 atIndex:3];
  [e dispatchThreads:MTLSizeMake(uint64_t(rows)*32,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];
  [e setComputePipelineState:c->pv];[e setBuffer:sv offset:0 atIndex:0];[e setBuffer:p->v offset:0 atIndex:1];
  [e setBuffer:bad offset:0 atIndex:2];[e setBytes:&elements length:4 atIndex:3];
  [e dispatchThreads:MTLSizeMake((elements+3)/4,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];
  [e endEncoding];complete(cb);stats->guard_gpu_seconds=cb.GPUEndTime-cb.GPUStartTime;
  stats->guard_flags=*static_cast<const uint32_t*>(bad.contents);stats->wall_seconds=elapsed(begin);
  need(stats->guard_flags==0,"GPU input guard rejected (1=half,2=abs bound,4=V range)");
  std::lock_guard<std::mutex>l(registry_mutex);const uint64_t h=identity();p->generation=identity();
  prepared.emplace(h,p);*handle=h;*generation=p->generation;
});}

// Additional ABI v1 path. Sources are stable only for this synchronous call;
// all published half snapshots are per-Prepared, private and never reused.
// flags bit0 keeps the private int32 transform for explicit debug readback.
API int pfx_prepare_sparse(uint64_t ctx,const int8_t*u,size_t ub,const uint32_t*pa,size_t pab,
  const uint32_t*qb,size_t qbb,const int8_t*leaf,size_t lb,uint32_t leaf_index,
  const int8_t*v,size_t vb,uint32_t m,uint32_t n,const uint8_t*seed,uint64_t epoch,uint32_t flags,
  uint64_t*handle,uint64_t*generation,PfxPrep*stats,char*err,size_t size){return checked(err,size,[&]{
  const auto began=Clock::now();PfxPrepareDetail detail{};detail.version=1;
  need(handle&&generation&&stats,"sparse prepare outputs");
  need(m>=64&&m<=16384&&n>=64&&n<=65536&&m%64==0&&n%64==0&&epoch&&seed&&flags<=1,"sparse shape/epoch/seed/flags");
  need(u&&pa&&qb&&leaf&&v&&ub==uint64_t(m)*128&&vb==uint64_t(n)*128&&pab==32768&&qbb==32768&&lb==1024&&leaf_index<uint64_t(m)*4,"sparse input sizes/index");
  const void*inputs[6]={u,pa,qb,leaf,v,seed};const size_t isizes[6]={ub,pab,qbb,lb,vb,32};
  const void*outputs[3]={handle,generation,stats};const size_t osizes[3]={8,8,sizeof(*stats)};
  for(unsigned i=0;i<3;++i){
    for(unsigned j=0;j<6;++j)need(!overlaps(outputs[i],osizes[i],inputs[j],isizes[j]),"aliased sparse input/output");
    for(unsigned j=i+1;j<3;++j)need(!overlaps(outputs[i],osizes[i],outputs[j],osizes[j]),"aliased sparse outputs");
  }
  *handle=*generation=0;*stats={};
  detail.argument_seconds=elapsed(began);auto stage=Clock::now();
  auto p=std::make_shared<Prepared>();p->c=context(ctx);p->m=m;p->n=n;p->epoch=epoch;p->prepare_kind=1;
  memcpy(p->seed.data(),seed,32);auto c=p->c;
  detail.ownership_seconds=elapsed(stage);stage=Clock::now();
  std::vector<int8_t>own_u(ub),own_v(vb),own_leaf(1024);
  std::vector<uint32_t>own_pa(8192),own_qb(8192);
  detail.host_alloc_seconds=elapsed(stage);stage=Clock::now();
  memcpy(own_u.data(),u,ub);memcpy(own_v.data(),v,vb);memcpy(own_leaf.data(),leaf,1024);
  memcpy(own_pa.data(),pa,pab);memcpy(own_qb.data(),qb,qbb);
  detail.host_copy_seconds=elapsed(stage);detail.host_copied_bytes=ub+vb+pab+qbb+1024+32;
  stage=Clock::now();
  for(int value:own_u)need(value>=-32&&value<=31,"U range");
  detail.u_validation_seconds=elapsed(stage);stage=Clock::now();
  for(int value:own_leaf)need(value>=-1&&value<=1,"nonce signal range");
  detail.leaf_validation_seconds=elapsed(stage);stage=Clock::now();
  for(uint32_t k=0;k<4096;++k)need(own_pa[2*k]<128&&own_pa[2*k+1]<128&&own_pa[2*k]!=own_pa[2*k+1],"PA indices");
  detail.pa_validation_seconds=elapsed(stage);stage=Clock::now();
  // Exact QB contents, rather than a caller generation/pointer, key the cache.
  const auto csr=csr_snapshot(c,own_qb,detail);
  detail.csr_total_seconds=elapsed(stage);
  const auto upload=Clock::now();
  stage=Clock::now();
  auto copy=[&](const void*data,size_t bytes){id<MTLBuffer>b=[c->device newBufferWithBytes:data length:bytes options:MTLResourceStorageModeShared];metal_need(b,"sparse source snapshot");return b;};
  id<MTLBuffer>us=copy(own_u.data(),ub),ps=copy(own_pa.data(),pab),ls=copy(own_leaf.data(),1024),vs=copy(own_v.data(),vb);
  detail.source_buffer_seconds=elapsed(stage);stage=Clock::now();
  detail.gpu_source_buffer_bytes=ub+vb+pab+1024+32+(detail.csr_cache_hit?0:32768+516);
  const uint64_t xe=uint64_t(32)*m*128;
  id<MTLBuffer>raw_x=[c->device newBufferWithLength:xe*4 options:MTLResourceStorageModePrivate];
  p->x=[c->device newBufferWithLength:xe*2 options:MTLResourceStorageModePrivate];
  p->v=[c->device newBufferWithLength:vb*2 options:MTLResourceStorageModePrivate];
  detail.private_buffer_seconds=elapsed(stage);stage=Clock::now();
  p->key=copy(p->seed.data(),32);p->dummy=[c->device newBufferWithLength:16 options:MTLResourceStorageModeShared];
  id<MTLBuffer>bad=[c->device newBufferWithLength:4 options:MTLResourceStorageModeShared];
  metal_need(raw_x&&p->x&&p->v&&p->dummy&&bad,"sparse private destinations");memset(bad.contents,0,4);
  detail.misc_buffer_seconds=elapsed(stage);
  stats->upload_seconds=elapsed(upload);
  stage=Clock::now();
  id<MTLCommandBuffer>cb=[c->queue commandBuffer];metal_need(cb,"sparse prepare command");
  id<MTLComputeCommandEncoder>e=[cb computeCommandEncoder];metal_need(e,"CSR encoder");
  const uint32_t dims[2]={m,leaf_index},rows=32*m,elements=n*128;
  [e setComputePipelineState:c->scatter];[e setBuffer:us offset:0 atIndex:0];[e setBuffer:ps offset:0 atIndex:1];
  [e setBuffer:csr->entries offset:0 atIndex:2];[e setBuffer:csr->offsets offset:0 atIndex:3];[e setBuffer:ls offset:0 atIndex:4];
  [e setBytes:dims length:8 atIndex:5];[e setBuffer:raw_x offset:0 atIndex:6];
  [e dispatchThreads:MTLSizeMake(uint64_t(m)*128,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];[e endEncoding];
  // Separate encoder: tracked raw_x write must complete before the guard read.
  e=[cb computeCommandEncoder];metal_need(e,"sparse guard encoder");
  [e setComputePipelineState:c->px];[e setBuffer:raw_x offset:0 atIndex:0];[e setBuffer:p->x offset:0 atIndex:1];
  [e setBuffer:bad offset:0 atIndex:2];[e setBytes:&rows length:4 atIndex:3];
  [e dispatchThreads:MTLSizeMake(uint64_t(rows)*32,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];
  [e setComputePipelineState:c->pv];[e setBuffer:vs offset:0 atIndex:0];[e setBuffer:p->v offset:0 atIndex:1];
  [e setBuffer:bad offset:0 atIndex:2];[e setBytes:&elements length:4 atIndex:3];
  [e dispatchThreads:MTLSizeMake((elements+3)/4,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];[e endEncoding];
  detail.encode_seconds=elapsed(stage);stage=Clock::now();
  [cb commit];detail.commit_seconds=elapsed(stage);stage=Clock::now();
  [cb waitUntilCompleted];detail.wait_seconds=elapsed(stage);
  metal_need(cb.status==MTLCommandBufferStatusCompleted,"GPU command",cb.error);
  stats->guard_gpu_seconds=cb.GPUEndTime-cb.GPUStartTime;stats->guard_flags=*static_cast<const uint32_t*>(bad.contents);
  detail.gpu_seconds=stats->guard_gpu_seconds;
  detail.completion_gap_seconds=detail.commit_seconds+detail.wait_seconds-detail.gpu_seconds;
  stats->wall_seconds=elapsed(began);need(stats->guard_flags==0,"actual sparse X/V GPU guard rejected");
  if(flags&1)p->debug_raw_x=raw_x;
  stage=Clock::now();
  std::lock_guard<std::mutex>lock(registry_mutex);const uint64_t h=identity();p->generation=identity();
  prepared.emplace(h,p);*handle=h;*generation=p->generation;
  detail.publish_seconds=elapsed(stage);detail.total_wall_seconds=elapsed(began);
  const double accounted=detail.argument_seconds+detail.ownership_seconds+detail.host_alloc_seconds+detail.host_copy_seconds+
    detail.u_validation_seconds+detail.leaf_validation_seconds+detail.pa_validation_seconds+detail.csr_total_seconds+
    detail.source_buffer_seconds+detail.private_buffer_seconds+detail.misc_buffer_seconds+detail.encode_seconds+
    detail.commit_seconds+detail.wait_seconds+detail.publish_seconds;
  detail.unattributed_seconds=detail.total_wall_seconds-accounted;
  p->detail=detail;
});}

// Additional S API; legacy and CSR entry points retain their exact signatures.
API int pfx_prepare_s(uint64_t ctx,const int8_t*u,size_t ub,const uint32_t*pa,size_t pab,
  const uint32_t*qb,size_t qbb,const int8_t*leaf,size_t lb,uint32_t leaf_index,
  const int8_t*v,size_t vb,uint32_t m,uint32_t n,const uint8_t*seed,uint64_t epoch,uint32_t flags,
  uint64_t*handle,uint64_t*generation,PfxPrep*stats,char*err,size_t size){return checked(err,size,[&]{
  const auto began=Clock::now();PfxPrepareDetail detail{};detail.version=1;
  PfxSDetail sd{};sd.version=1;sd.method=2;
  need(handle&&generation&&stats,"S prepare outputs");
  need(m>=64&&m<=16384&&n>=64&&n<=65536&&m%64==0&&n%64==0&&epoch&&seed&&flags<=1,"S shape/epoch/seed/flags");
  need(u&&pa&&qb&&leaf&&v&&ub==uint64_t(m)*128&&vb==uint64_t(n)*128&&pab==32768&&qbb==32768&&lb==1024&&leaf_index<uint64_t(m)*4,"S input sizes/index");
  const void*inputs[6]={u,pa,qb,leaf,v,seed};const size_t isizes[6]={ub,pab,qbb,lb,vb,32};
  const void*outputs[3]={handle,generation,stats};const size_t osizes[3]={8,8,sizeof(*stats)};
  for(unsigned i=0;i<3;++i){
    for(unsigned j=0;j<6;++j)need(!overlaps(outputs[i],osizes[i],inputs[j],isizes[j]),"aliased S input/output");
    for(unsigned j=i+1;j<3;++j)need(!overlaps(outputs[i],osizes[i],outputs[j],osizes[j]),"aliased S outputs");
  }
  *handle=*generation=0;*stats={};detail.argument_seconds=elapsed(began);auto stage=Clock::now();
  auto p=std::make_shared<Prepared>();p->c=context(ctx);p->m=m;p->n=n;p->epoch=epoch;p->prepare_kind=2;
  memcpy(p->seed.data(),seed,32);auto c=p->c;
  detail.ownership_seconds=elapsed(stage);stage=Clock::now();
  std::vector<int8_t>own_u(ub),own_v(vb),own_leaf(1024);
  std::vector<uint32_t>own_pa(8192),own_qb(8192);
  detail.host_alloc_seconds=elapsed(stage);stage=Clock::now();
  memcpy(own_u.data(),u,ub);memcpy(own_v.data(),v,vb);memcpy(own_leaf.data(),leaf,1024);
  memcpy(own_pa.data(),pa,pab);memcpy(own_qb.data(),qb,qbb);
  detail.host_copy_seconds=elapsed(stage);detail.host_copied_bytes=ub+vb+pab+qbb+1024+32;stage=Clock::now();
  for(int value:own_u)need(value>=-32&&value<=31,"U range");
  detail.u_validation_seconds=elapsed(stage);stage=Clock::now();
  for(int value:own_leaf)need(value>=-1&&value<=1,"nonce signal range");
  detail.leaf_validation_seconds=elapsed(stage);stage=Clock::now();
  for(uint32_t k=0;k<4096;++k)need(own_pa[2*k]<128&&own_pa[2*k+1]<128&&own_pa[2*k]!=own_pa[2*k+1],"PA indices");
  detail.pa_validation_seconds=elapsed(stage);stage=Clock::now();
  for(uint32_t k=0;k<4096;++k)need(own_qb[2*k]<128&&own_qb[2*k+1]<128&&own_qb[2*k]!=own_qb[2*k+1],"QB indices");
  sd.qb_validation_seconds=elapsed(stage);stage=Clock::now();
  std::vector<int32_t>st(32*128*128),current(128*128,0),correction(32*128);
  std::array<int32_t,128>nonce{};const uint32_t leaf_k=(leaf_index%4)*1024;
  for(uint32_t k=0;k<4096;++k){
    const uint32_t ap=own_pa[2*k],am=own_pa[2*k+1],bp=own_qb[2*k],bm=own_qb[2*k+1];
    ++current[bp*128+ap];--current[bm*128+ap];--current[bp*128+am];++current[bm*128+am];
    if(k>=leaf_k&&k<leaf_k+1024){const int32_t value=own_leaf[k-leaf_k];nonce[bp]+=value;nonce[bm]-=value;}
    if((k+1)%128==0){const uint32_t t=(k+1)/128-1;memcpy(st.data()+t*128*128,current.data(),128*128*4);memcpy(correction.data()+t*128,nonce.data(),128*4);}
  }
  sd.build_seconds=elapsed(stage);sd.s_bytes=st.size()*4;sd.correction_bytes=correction.size()*4;
  const auto upload=Clock::now();stage=Clock::now();
  auto copy=[&](const void*data,size_t bytes){id<MTLBuffer>b=[c->device newBufferWithBytes:data length:bytes options:MTLResourceStorageModeShared];metal_need(b,"S source snapshot");return b;};
  id<MTLBuffer>us=copy(own_u.data(),ub),ss=copy(st.data(),st.size()*4),ns=copy(correction.data(),correction.size()*4),vs=copy(own_v.data(),vb);
  detail.source_buffer_seconds=elapsed(stage);detail.gpu_source_buffer_bytes=ub+vb+sd.s_bytes+sd.correction_bytes+32;
  stage=Clock::now();
  // Only unpublished float scratch is reusable. The lock remains held through
  // GPU completion/guard read, including every exception path. Published half
  // snapshots and requested debug int32 outputs always belong to this p.
  std::unique_lock<std::mutex>scratch_lock(c->prepare_mutex,std::defer_lock);
  if(!(flags&1))scratch_lock.lock();
  sd.scratch_wait_seconds=elapsed(stage);stage=Clock::now();
  const uint64_t xe=uint64_t(32)*m*128;
  id<MTLBuffer>float_x;
  if(flags&1)float_x=[c->device newBufferWithLength:xe*4 options:MTLResourceStorageModePrivate];
  else{
    sd.scratch_reused=(c->s_float_scratch&&c->s_float_scratch.length>=xe*4)?1:0;
    if(!sd.scratch_reused){id<MTLBuffer>fresh=[c->device newBufferWithLength:xe*4 options:MTLResourceStorageModePrivate];metal_need(fresh,"S float scratch");c->s_float_scratch=fresh;}
    float_x=c->s_float_scratch;
  }
  id<MTLBuffer>half_u=[c->device newBufferWithLength:ub*2 options:MTLResourceStorageModePrivate];
  id<MTLBuffer>half_s=[c->device newBufferWithLength:st.size()*2 options:MTLResourceStorageModePrivate];
  p->x=[c->device newBufferWithLength:xe*2 options:MTLResourceStorageModePrivate];
  p->v=[c->device newBufferWithLength:vb*2 options:MTLResourceStorageModePrivate];
  if(flags&1)p->debug_raw_x=[c->device newBufferWithLength:xe*4 options:MTLResourceStorageModePrivate];
  detail.private_buffer_seconds=elapsed(stage);stage=Clock::now();
  p->key=copy(p->seed.data(),32);p->dummy=[c->device newBufferWithLength:16 options:MTLResourceStorageModeShared];
  id<MTLBuffer>bad=[c->device newBufferWithLength:4 options:MTLResourceStorageModeShared];
  metal_need(float_x&&half_u&&half_s&&p->x&&p->v&&p->dummy&&bad&&(!(flags&1)||p->debug_raw_x),"S private destinations");memset(bad.contents,0,4);
  detail.misc_buffer_seconds=elapsed(stage);stats->upload_seconds=elapsed(upload);stage=Clock::now();
  id<MTLCommandBuffer>cb=[c->queue commandBuffer];metal_need(cb,"S prepare command");
  id<MTLComputeCommandEncoder>e=[cb computeCommandEncoder];metal_need(e,"S input guard encoder");
  const uint32_t sr=32*128,ue=m*128,ve=n*128,params[4]={m,leaf_index/4,flags&1,0};
  [e setComputePipelineState:c->s_guard];[e setBuffer:ss offset:0 atIndex:0];[e setBuffer:half_s offset:0 atIndex:1];[e setBuffer:bad offset:0 atIndex:2];[e setBytes:&sr length:4 atIndex:3];
  [e dispatchThreads:MTLSizeMake(uint64_t(sr)*32,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];
  [e setComputePipelineState:c->s_uniform];[e setBuffer:us offset:0 atIndex:0];[e setBuffer:half_u offset:0 atIndex:1];[e setBuffer:bad offset:0 atIndex:2];[e setBytes:&ue length:4 atIndex:3];
  [e dispatchThreads:MTLSizeMake(ue,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];
  [e setBuffer:vs offset:0 atIndex:0];[e setBuffer:p->v offset:0 atIndex:1];[e setBytes:&ve length:4 atIndex:3];
  [e dispatchThreads:MTLSizeMake(ve,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];[e endEncoding];
  e=[cb computeCommandEncoder];metal_need(e,"S MPP encoder");
  [e setComputePipelineState:c->s_form];[e setBuffer:half_u offset:0 atIndex:0];[e setBuffer:half_s offset:0 atIndex:1];[e setBuffer:float_x offset:0 atIndex:2];[e setBytes:&m length:4 atIndex:3];
  [e dispatchThreadgroups:MTLSizeMake(2,m/64,32) threadsPerThreadgroup:MTLSizeMake(128,1,1)];[e endEncoding];
  e=[cb computeCommandEncoder];metal_need(e,"S correction/final guard encoder");
  [e setComputePipelineState:c->s_finish];[e setBuffer:float_x offset:0 atIndex:0];[e setBuffer:ns offset:0 atIndex:1];[e setBuffer:p->x offset:0 atIndex:2];[e setBuffer:((flags&1)?p->debug_raw_x:p->dummy) offset:0 atIndex:3];[e setBuffer:bad offset:0 atIndex:4];[e setBytes:params length:16 atIndex:5];
  [e dispatchThreads:MTLSizeMake(uint64_t(32)*m*32,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];[e endEncoding];
  detail.encode_seconds=elapsed(stage);stage=Clock::now();[cb commit];detail.commit_seconds=elapsed(stage);stage=Clock::now();
  [cb waitUntilCompleted];detail.wait_seconds=elapsed(stage);metal_need(cb.status==MTLCommandBufferStatusCompleted,"S GPU command",cb.error);
  stats->guard_gpu_seconds=cb.GPUEndTime-cb.GPUStartTime;stats->guard_flags=*static_cast<const uint32_t*>(bad.contents);
  if(scratch_lock.owns_lock())scratch_lock.unlock();
  detail.gpu_seconds=stats->guard_gpu_seconds;detail.completion_gap_seconds=detail.commit_seconds+detail.wait_seconds-detail.gpu_seconds;
  stats->wall_seconds=elapsed(began);need(stats->guard_flags==0,"actual S/X/V GPU guard rejected");
  stage=Clock::now();std::lock_guard<std::mutex>lock(registry_mutex);const uint64_t h=identity();p->generation=identity();
  prepared.emplace(h,p);*handle=h;*generation=p->generation;
  detail.publish_seconds=elapsed(stage);detail.total_wall_seconds=elapsed(began);
  const double accounted=detail.argument_seconds+detail.ownership_seconds+detail.host_alloc_seconds+detail.host_copy_seconds+
    detail.u_validation_seconds+detail.leaf_validation_seconds+detail.pa_validation_seconds+detail.csr_total_seconds+
    detail.source_buffer_seconds+detail.private_buffer_seconds+detail.misc_buffer_seconds+detail.encode_seconds+
    detail.commit_seconds+detail.wait_seconds+detail.publish_seconds;
  // Preserve legacy216-byte accounting. S-only sub-stages are explained by
  // the separate64-byte extension and remain inside its unattributed bucket.
  detail.unattributed_seconds=detail.total_wall_seconds-accounted;p->detail=detail;p->s_detail=sd;
});}

API int pfx_get_s_detail(uint64_t h,uint64_t g,uint64_t epoch,PfxSDetail*out,char*err,size_t size){return checked(err,size,[&]{
  need(out,"S profile output");auto p=snapshot(h,g);std::lock_guard<std::mutex>lock(p->mutex);
  need(!p->closed&&p->epoch==epoch&&p->prepare_kind==2&&p->s_detail.version==1,"S profile unavailable/epoch");*out=p->s_detail;
});}

API int pfx_get_prepare_detail(uint64_t h,uint64_t g,uint64_t epoch,PfxPrepareDetail*out,char*err,size_t size){return checked(err,size,[&]{
  need(out,"profile output");auto p=snapshot(h,g);std::lock_guard<std::mutex>lock(p->mutex);
  need(!p->closed&&p->epoch==epoch&&(p->prepare_kind==1||p->prepare_kind==2)&&p->detail.version==1,"profile unavailable/epoch");*out=p->detail;
});}

API int pfx_prepared_kind(uint64_t h,uint64_t g,uint64_t epoch,uint32_t*kind,char*err,size_t size){return checked(err,size,[&]{
  need(kind,"kind output");auto p=snapshot(h,g);std::lock_guard<std::mutex>lock(p->mutex);
  need(!p->closed&&p->epoch==epoch,"closed/epoch mismatch");*kind=p->prepare_kind;
});}

// Copies only, never exports Metal buffer pointers or writable contents.
API int pfx_export_sparse(uint64_t h,uint64_t g,uint64_t epoch,int32_t*out_x,size_t xb,
  uint16_t*out_half,size_t hb,char*err,size_t size){return checked(err,size,[&]{
  auto p=snapshot(h,g);std::lock_guard<std::mutex>lock(p->mutex);
  need(!p->closed&&p->epoch==epoch&&(p->prepare_kind==1||p->prepare_kind==2)&&p->debug_raw_x,"sparse debug snapshot unavailable/epoch");
  const uint64_t xe=uint64_t(32)*p->m*128;
  need((out_x&&xb==xe*4)||(!out_x&&!xb),"debug X output size");
  need((out_half&&hb==xe*2)||(!out_half&&!hb),"debug half output size");
  need(out_x||out_half,"empty debug export");need(!overlaps(out_x,xb,out_half,hb),"aliased debug outputs");
  auto c=p->c;
  id<MTLBuffer>x=out_x?[c->device newBufferWithLength:xb options:MTLResourceStorageModeShared]:nil;
  id<MTLBuffer>half=out_half?[c->device newBufferWithLength:hb options:MTLResourceStorageModeShared]:nil;
  metal_need((!out_x||x)&&(!out_half||half),"debug readback allocation");
  id<MTLCommandBuffer>cb=[c->queue commandBuffer];metal_need(cb,"debug command");
  id<MTLBlitCommandEncoder>blit=[cb blitCommandEncoder];metal_need(blit,"debug blit");
  if(out_x)[blit copyFromBuffer:p->debug_raw_x sourceOffset:0 toBuffer:x destinationOffset:0 size:xb];
  if(out_half)[blit copyFromBuffer:p->x sourceOffset:0 toBuffer:half destinationOffset:0 size:hb];
  [blit endEncoding];complete(cb);
  if(out_x)memcpy(out_x,x.contents,xb);if(out_half)memcpy(out_half,half.contents,hb);
});}

API int pfx_scan(uint64_t handle,uint64_t generation,uint64_t epoch,uint32_t band_lo,uint32_t n_bands,
  const uint8_t *seed,const uint8_t *bound,uint32_t *pairs,uint32_t hit_capacity,
  uint32_t *trans,size_t trans_bytes,uint8_t *digests,size_t digest_bytes,PfxResult *result,char *err,size_t size){
  return checked(err,size,[&]{
    const auto began=Clock::now();need(result&&seed&&bound&&pairs,"scan pointers");
    need(hit_capacity>=1&&hit_capacity<=4096,"hit capacity");
    auto p=snapshot(handle,generation);std::lock_guard<std::mutex>lock(p->mutex);
    need(!p->closed&&p->epoch==epoch&&!memcmp(seed,p->seed.data(),32),"closed/epoch/seed mismatch");
    need(n_bands>0&&band_lo==p->next_band&&band_lo<p->m/64&&n_bands<=p->m/64-band_lo,"region out of order/repeated/out of bounds");
    const uint32_t tiles=n_bands*32*(p->n/64);
    need((trans&&trans_bytes==uint64_t(tiles)*64)||(!trans&&!trans_bytes),"transcript output size");
    need((digests&&digest_bytes==uint64_t(tiles)*32)||(!digests&&!digest_bytes),"digest output size");
    const void *spans[4]={pairs,trans,digests,result};size_t lengths[4]={size_t(hit_capacity)*8,trans_bytes,digest_bytes,sizeof(*result)};
    for(unsigned i=0;i<4;++i)for(unsigned j=i+1;j<4;++j)need(!overlaps(spans[i],lengths[i],spans[j],lengths[j]),"aliased scan outputs");
    if(p->bound_set)need(!memcmp(bound,p->bound.data(),32),"target changed without new prepared epoch");
    else {memcpy(p->bound.data(),bound,32);p->bound_set=true;}
    auto c=p->c;reserve(c->device,p->trans,uint64_t(tiles)*64);reserve(c->device,p->hits,4+uint64_t(hit_capacity)*8);
    if(digests)reserve(c->device,p->digests,digest_bytes);
    memset(p->hits.contents,0,4);
    id<MTLCommandBuffer>cb=[c->queue commandBuffer];metal_need(cb,"scan command");
    id<MTLComputeCommandEncoder>e=[cb computeCommandEncoder];metal_need(e,"prefix encoder");
    const uint32_t dims[4]={p->m,p->n,band_lo,n_bands};
    [e setComputePipelineState:c->pair];[e setBuffer:p->x offset:0 atIndex:0];[e setBuffer:p->v offset:0 atIndex:1];
    [e setBuffer:p->trans offset:0 atIndex:2];[e setBytes:dims length:16 atIndex:3];
    [e dispatchThreadgroups:MTLSizeMake(p->n/64,n_bands,16) threadsPerThreadgroup:MTLSizeMake(128,1,1)];[e endEncoding];
    e=[cb computeCommandEncoder];metal_need(e,"hash encoder");
    const uint32_t params[4]={tiles,p->n/64,band_lo,hit_capacity},flags=digests?1u:0u;
    [e setComputePipelineState:c->hash];[e setBuffer:p->trans offset:0 atIndex:0];[e setBuffer:p->key offset:0 atIndex:1];
    [e setBuffer:(digests?p->digests:p->dummy) offset:0 atIndex:2];[e setBytes:params length:16 atIndex:3];
    [e setBytes:p->bound.data() length:32 atIndex:4];[e setBuffer:p->hits offset:0 atIndex:5];[e setBytes:&flags length:4 atIndex:6];
    [e dispatchThreads:MTLSizeMake(tiles,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];[e endEncoding];
    try{complete(cb);}catch(...){p->closed=true;throw;}
    const uint32_t total=*static_cast<const uint32_t*>(p->hits.contents),stored=std::min(total,hit_capacity);
    memcpy(pairs,static_cast<const uint8_t*>(p->hits.contents)+4,size_t(stored)*8);
    if(trans)memcpy(trans,p->trans.contents,trans_bytes);if(digests)memcpy(digests,p->digests.contents,digest_bytes);
    p->next_band=band_lo+n_bands;
    *result={epoch,tiles,band_lo,n_bands,stored,total,elapsed(began),cb.GPUEndTime-cb.GPUStartTime};
  });
}
API int pfx_close(uint64_t h,uint64_t g,char *err,size_t size){return checked(err,size,[&]{
  std::shared_ptr<Prepared>p;{std::lock_guard<std::mutex>l(registry_mutex);auto i=prepared.find(h);
    need(i!=prepared.end()&&i->second->generation==g,"unknown handle/generation");p=i->second;prepared.erase(i);}
  std::lock_guard<std::mutex>l(p->mutex);p->closed=true;
});}
