// Independent exact-prefix research; not integrated into the miner.
#include <metal_stdlib>
#include <metal_tensor>
#include <MetalPerformancePrimitives/MetalPerformancePrimitives.h>
using namespace metal;
using namespace mpp::tensor_ops;

// Exact CSR transform from the independently validated GPU prepare probe.
// Each output q's CSR bucket is owned, validated and sorted by increasing k.
// The full 1024-byte leaf contributes, including any nonzero trailing bytes.
kernel void scatter_prefix_csr(device const signed char *u [[buffer(0)]],
    device const uint2 *pa [[buffer(1)]],device const uint *entries [[buffer(2)]],
    device const uint *offsets [[buffer(3)]],device const signed char *leaf [[buffer(4)]],
    constant uint2 &shape [[buffer(5)]],device int *x [[buffer(6)]],
    uint gid [[thread_position_in_grid]]) {
  const uint row=gid/128u,q=gid%128u;
  if(row>=shape.x)return;
  uint cursor=offsets[q],end=offsets[q+1u];
  const uint nonce_lo=shape.y*1024u,nonce_hi=nonce_lo+1024u;
  int acc=0;
  for(uint t=0u;t<32u;++t){
    const uint limit=(t+1u)*128u;
    while(cursor<end){
      const uint code=entries[cursor],k=code>>1u;
      if(k>=limit)break;
      const uint2 pair=pa[k];
      int a=int(u[row*128u+pair.x])-int(u[row*128u+pair.y]);
      const uint pos=row*4096u+k;
      if(pos>=nonce_lo&&pos<nonce_hi)a+=int(leaf[pos-nonce_lo]);
      acc+=(code&1u)?-a:a;++cursor;
    }
    x[(ulong(t)*shape.x+row)*128ul+q]=acc;
  }
}

// Actual copied source snapshots are checked while converted to private half.
// X: one SIMDgroup per row/prefix, four contiguous int32 entries per lane.
// Invalid values never wrap an unsigned sum; they independently set bit 0.
kernel void prepare_x(device const int *source [[buffer(0)]],
                      device half *dest [[buffer(1)]],
                      device atomic_uint *bad [[buffer(2)]],
                      constant uint &rows [[buffer(3)]],
                      uint gid [[thread_position_in_grid]],
                      uint lane [[thread_index_in_simdgroup]]) {
  const uint row=gid/32u;
  if(row>=rows) return;
  const ulong begin=ulong(row)*128ul+lane*4u;
  uint sum=0u;bool invalid=false;
  for(uint i=0u;i<4u;++i) {
    const int value=source[begin+i];
    const bool range=value>=-65504 && value<=65504;
    const half h=range?half(value):half(0);
    invalid=invalid || !range || float(h)!=float(value);
    dest[begin+i]=h;
    if(range)sum+=uint(abs(value));
  }
  const uint total=simd_sum(sum);
  if(invalid) atomic_fetch_or_explicit(bad,1u,memory_order_relaxed);
  if(lane==0u && total>524288u) atomic_fetch_or_explicit(bad,2u,memory_order_relaxed);
}
kernel void prepare_v(device const signed char *source [[buffer(0)]],
                      device half *dest [[buffer(1)]],
                      device atomic_uint *bad [[buffer(2)]],
                      constant uint &elements [[buffer(3)]],
                      uint gid [[thread_position_in_grid]]) {
  const ulong begin=ulong(gid)*4ul;
  bool invalid=false;
  for(uint i=0u;i<4u && begin+i<elements;++i) {
    const int value=int(source[begin+i]);
    invalid=invalid || value < -32 || value > 31;
    dest[begin+i]=half(value);
  }
  if(invalid) atomic_fetch_or_explicit(bad,4u,memory_order_relaxed);
}

// X is [32,M,128], V is [N,128]. X already includes nonce correction.
// This kernel is dispatched only after native validation of every actual
// integer half conversion and a conservative <=2^24 absolute dot-product sum.
// Each TG computes one final transcript slot and has no cross-rank dependency.
kernel void prefix_pair(device half *xp [[buffer(0)]],
                        device half *vp [[buffer(1)]],
                        device uint *transcripts [[buffer(2)]],
                        constant uint4 &dims [[buffer(3)]],
                        uint3 group [[threadgroup_position_in_grid]],
                        uint tid [[thread_index_in_threadgroup]]) {
  constexpr auto descriptor = matmul2d_descriptor(64, 64, 128, false, true, false,
      matmul2d_descriptor::mode::multiply_accumulate);
  using Operand = tensor<device half, extents<int,128,64>, tensor_inline>;
  matmul2d<descriptor, execution_simdgroups<4>> operation;
  auto accumulator = operation.get_destination_cooperative_tensor<Operand,Operand,float>();
  threadgroup float matrix[4096];
  tensor<threadgroup float, extents<int,64,64>, tensor_inline>
      destination(matrix, extents<int,64,64>{}, array<int,2>{1,64});
  const uint row0 = (dims.z + group.y) * 64u;
  const uint col0 = group.x * 64u;
  const uint slot = group.z;
  const uint pair = tid / 4u;
  const uint first_col = (tid & 3u) * 16u;
  uint result = 0u;
  for (uint phase = 0u; phase < 2u; ++phase) {
    for (uint i = 0u; i < accumulator.get_capacity(); ++i)
      if (accumulator.is_valid_element(i)) accumulator[i] = 0.0f;
    const uint prefix = slot + phase * 16u;
    Operand a(xp + (ulong(prefix) * dims.x + row0) * 128ul,
              extents<int,128,64>{}, array<int,2>{1,128});
    Operand b(vp + ulong(col0) * 128ul,
              extents<int,128,64>{}, array<int,2>{1,128});
    operation.run(a,b,accumulator);
    accumulator.store(destination);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    uint folded = 0u;
    for (uint j = 0u; j < 16u; ++j)
      folded ^= as_type<uint>(int(matrix[pair*64u + first_col+j])) ^
                as_type<uint>(int(matrix[(pair+32u)*64u + first_col+j]));
    folded ^= simd_shuffle_xor(folded,2u);
    folded ^= simd_shuffle_xor(folded,1u);
    if (phase == 0u) result = (folded << 13u) | (folded >> 19u);
    else result ^= folded;
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }
  if ((tid & 3u) == 0u) {
    const ulong row_pair = ulong(group.y)*32ul + pair;
    const ulong tile = row_pair * (dims.y/64u) + group.x;
    transcripts[tile*16ul + slot] = result;
  }
}

// Keyed BLAKE3, exactly one 64-byte block. Same public algorithm as the
// project's consensus-tested implementation; the Python oracle uses blake3.
constant uchar B3_PERM[16] = {2,6,3,10,7,0,4,13,1,11,12,5,9,14,15,8};
inline uint ror(uint x,uint n) { return (x>>n)|(x<<(32u-n)); }
inline void g(thread uint *v,uint a,uint b,uint c,uint d,uint x,uint y) {
  v[a]+=v[b]+x;v[d]=ror(v[d]^v[a],16u);v[c]+=v[d];v[b]=ror(v[b]^v[c],12u);
  v[a]+=v[b]+y;v[d]=ror(v[d]^v[a],8u);v[c]+=v[d];v[b]=ror(v[b]^v[c],7u);
}
inline void round_b3(thread uint *v,thread const uint *m) {
  g(v,0,4,8,12,m[0],m[1]);g(v,1,5,9,13,m[2],m[3]);
  g(v,2,6,10,14,m[4],m[5]);g(v,3,7,11,15,m[6],m[7]);
  g(v,0,5,10,15,m[8],m[9]);g(v,1,6,11,12,m[10],m[11]);
  g(v,2,7,8,13,m[12],m[13]);g(v,3,4,9,14,m[14],m[15]);
}
kernel void prefix_hash(device const uint *transcripts [[buffer(0)]],
                        device const uint *key [[buffer(1)]],
                        device uint *digests [[buffer(2)]],
                        constant uint4 &params [[buffer(3)]],
                        device const uchar *bound [[buffer(4)]],
                        device atomic_uint *hits [[buffer(5)]],
                        constant uint &flags [[buffer(6)]],
                        uint tid [[thread_position_in_grid]]) {
  if (tid >= params.x) return;
  uint v[16],m[16],tmp[16];
  for (uint i=0u;i<8u;++i) v[i]=key[i];
  v[8]=0x6A09E667u;v[9]=0xBB67AE85u;v[10]=0x3C6EF372u;v[11]=0xA54FF53Au;
  v[12]=0u;v[13]=0u;v[14]=64u;v[15]=27u;
  for (uint i=0u;i<16u;++i) m[i]=transcripts[ulong(tid)*16ul+i];
  for (uint r=0u;r<7u;++r) {
    if (r!=0u) { for(uint i=0u;i<16u;++i) tmp[i]=m[B3_PERM[i]];
                 for(uint i=0u;i<16u;++i) m[i]=tmp[i]; }
    round_b3(v,m);
  }
  uint d[8];
  for(uint i=0u;i<8u;++i) {d[i]=v[i]^v[i+8u];if(flags&1u)digests[ulong(tid)*8ul+i]=d[i];}
  bool win=true;
  for(int i=31;i>=0;--i) {
    const uchar h=uchar((d[i/4]>>(8u*(i%4)))&255u);
    if(h!=bound[i]) {win=h<bound[i];break;}
  }
  if(win) {
    const uint idx=atomic_fetch_add_explicit(hits,1u,memory_order_relaxed);
    if(idx<params.w) {
      const uint ri=tid/params.y;
      atomic_store_explicit(&hits[1u+2u*idx],(params.z+ri/32u)*64u+ri%32u,memory_order_relaxed);
      atomic_store_explicit(&hits[2u+2u*idx],(tid%params.y)*64u,memory_order_relaxed);
    }
  }
}


// S is stored transposed: [prefix,q,a]. Each guarded row is a column of S,
// so its absolute sum * max|U|=32 bounds every U*S dot in any FP32 order.
kernel void guard_s(device const int *source [[buffer(0)]],device half *dest [[buffer(1)]],
    device atomic_uint *bad [[buffer(2)]],constant uint &rows [[buffer(3)]],
    uint gid [[thread_position_in_grid]],uint lane [[thread_index_in_simdgroup]]) {
    const uint row=gid/32u;if(row>=rows)return;
    const ulong begin=ulong(row)*128ul+lane*4u;uint sum=0u;bool invalid=false;
    for(uint i=0u;i<4u;++i){
        const int value=source[begin+i];const bool range=value>=-65504&&value<=65504;
        const half h=range?half(value):half(0);invalid=invalid||!range||float(h)!=float(value);
        dest[begin+i]=h;if(range)sum+=uint(abs(value));
    }
    const uint total=simd_sum(sum);
    if(invalid)atomic_fetch_or_explicit(bad,16u,memory_order_relaxed);
    if(lane==0u&&total>524288u)atomic_fetch_or_explicit(bad,32u,memory_order_relaxed);
}
kernel void guard_uniform(device const signed char *source [[buffer(0)]],device half *dest [[buffer(1)]],
    device atomic_uint *bad [[buffer(2)]],constant uint &count [[buffer(3)]],uint gid [[thread_position_in_grid]]) {
    if(gid>=count)return;const int value=source[gid];dest[gid]=half(value);
    if(value < -32||value > 31)atomic_fetch_or_explicit(bad,4u,memory_order_relaxed);
}

// Known, explicit tensor store layout. No assumption about the internal
// cooperative accumulator's lane/element mapping is used.
kernel void form_x(device half *u [[buffer(0)]],device half *st [[buffer(1)]],
    device float *x [[buffer(2)]],constant uint &m [[buffer(3)]],
    uint3 group [[threadgroup_position_in_grid]],uint tid [[thread_index_in_threadgroup]]) {
    constexpr auto descriptor=matmul2d_descriptor(64,64,128,false,true,false,
        matmul2d_descriptor::mode::multiply_accumulate);
    using Operand=tensor<device half,extents<int,128,64>,tensor_inline>;
    matmul2d<descriptor,execution_simdgroups<4>> operation;
    auto acc=operation.get_destination_cooperative_tensor<Operand,Operand,float>();
    for(uint i=0u;i<acc.get_capacity();++i)if(acc.is_valid_element(i))acc[i]=0.0f;
    const uint row0=group.y*64u,q0=group.x*64u,t=group.z;
    Operand a(u+ulong(row0)*128ul,extents<int,128,64>{},array<int,2>{1,128});
    Operand b(st+(ulong(t)*128ul+q0)*128ul,extents<int,128,64>{},array<int,2>{1,128});
    operation.run(a,b,acc);
    threadgroup float matrix[4096];
    tensor<threadgroup float,extents<int,64,64>,tensor_inline>
        destination(matrix,extents<int,64,64>{},array<int,2>{1,64});
    acc.store(destination);threadgroup_barrier(mem_flags::mem_threadgroup);
    for(uint i=tid;i<4096u;i+=128u)
        x[(ulong(t)*m+row0+i/64u)*128ul+q0+i%64u]=matrix[i];
}

// Float U*S must be an exact integer. Add nonce correction in int32, then
// check actual resulting X half representation and complete128-term L1 bound.
kernel void finish_x(device const float *source [[buffer(0)]],device const int *correction [[buffer(1)]],
    device half *half_x [[buffer(2)]],device int *debug_x [[buffer(3)]],
    device atomic_uint *bad [[buffer(4)]],constant uint4 &params [[buffer(5)]],
    uint gid [[thread_position_in_grid]],uint lane [[thread_index_in_simdgroup]]) {
    const uint row=gid/32u;if(row>=params.x*32u)return;
    const ulong begin=ulong(row)*128ul+lane*4u;uint sum=0u;bool invalid=false,bad_float=false;
    for(uint i=0u;i<4u;++i){
        const float f=source[begin+i];
        const bool exact=isfinite(f)&&f>=-16777216.0f&&f<=16777216.0f&&trunc(f)==f;
        bad_float=bad_float||!exact;
        int value=exact?int(f):0;
        if(row%params.x==params.y)value+=correction[(row/params.x)*128u+lane*4u+i];
        const bool range=value>=-65504&&value<=65504;
        const half h=range?half(value):half(0);invalid=invalid||!range||float(h)!=float(value);
        half_x[begin+i]=h;if(params.z)debug_x[begin+i]=value;
        if(range)sum+=uint(abs(value));
    }
    const uint total=simd_sum(sum);
    if(invalid)atomic_fetch_or_explicit(bad,1u,memory_order_relaxed);
    if(lane==0u&&total>524288u)atomic_fetch_or_explicit(bad,2u,memory_order_relaxed);
    if(bad_float)atomic_fetch_or_explicit(bad,8u,memory_order_relaxed);
}
