// Anti-hoisting control: every iteration reads a distinct runtime matrix pair.
#include <metal_stdlib>
#include <metal_simdgroup_matrix>
#include <metal_tensor>
#include <MetalPerformancePrimitives/MetalPerformancePrimitives.h>
using namespace metal;
using namespace mpp::tensor_ops;
#ifndef BENCH_CHAINS
#define BENCH_CHAINS 4
#endif

template<typename Scalar>
inline void run_sg(device const Scalar *ap,device const Scalar *bp,
    device float *out,constant uint4 &params,uint group,uint sg) {
  const uint index=group*params.y+sg;
  simdgroup_float8x8 c[BENCH_CHAINS];
  #pragma unroll
  for(uint q=0u;q<BENCH_CHAINS;++q)c[q]=simdgroup_float8x8(0.0f);
  for(uint iteration=0u;iteration<params.x;++iteration) {
    const ulong sequence=ulong(index)*params.z+iteration;
    simdgroup_matrix<Scalar,8,8> a;
    simdgroup_load(a,ap+sequence*64ul,8u);
    #pragma unroll
    for(uint q=0u;q<BENCH_CHAINS;++q) {
      simdgroup_matrix<Scalar,8,8> b;
      simdgroup_load(b,bp+(sequence*BENCH_CHAINS+q)*64ul,8u,ulong2(0),true);
      simdgroup_multiply_accumulate(c[q],a,b,c[q]);
    }
  }
  #pragma unroll
  for(uint q=0u;q<BENCH_CHAINS;++q)
    simdgroup_store(c[q],out+(ulong(index)*BENCH_CHAINS+q)*64ul,8u);
}
kernel void peak_half(device const half *ap [[buffer(0)]],device const half *bp [[buffer(1)]],
    device float *out [[buffer(2)]],constant uint4 &params [[buffer(3)]],
    uint group [[threadgroup_position_in_grid]],uint sg [[simdgroup_index_in_threadgroup]]) {
  run_sg(ap,bp,out,params,group,sg);
}
kernel void peak_float(device const float *ap [[buffer(0)]],device const float *bp [[buffer(1)]],
    device float *out [[buffer(2)]],constant uint4 &params [[buffer(3)]],
    uint group [[threadgroup_position_in_grid]],uint sg [[simdgroup_index_in_threadgroup]]) {
  run_sg(ap,bp,out,params,group,sg);
}
kernel void peak_mpp(device half *ap [[buffer(0)]],device half *bp [[buffer(1)]],
    device float *out [[buffer(2)]],constant uint4 &params [[buffer(3)]],
    uint group [[threadgroup_position_in_grid]],uint tid [[thread_index_in_threadgroup]]) {
  constexpr auto descriptor=matmul2d_descriptor(64,64,128,false,true,false,
      matmul2d_descriptor::mode::multiply_accumulate);
  using Operand=tensor<device half,extents<int,128,64>,tensor_inline>;
  matmul2d<descriptor,execution_simdgroups<4>> operation;
  auto accumulator=operation.get_destination_cooperative_tensor<Operand,Operand,float>();
  for(uint i=0u;i<accumulator.get_capacity();++i)
    if(accumulator.is_valid_element(i))accumulator[i]=0.0f;
  for(uint iteration=0u;iteration<params.x;++iteration) {
    const ulong sequence=ulong(group)*params.z+iteration;
    Operand a(ap+sequence*8192ul,extents<int,128,64>{},array<int,2>{1,128});
    Operand b(bp+sequence*8192ul,extents<int,128,64>{},array<int,2>{1,128});
    operation.run(a,b,accumulator);
  }
  threadgroup float matrix[4096];
  tensor<threadgroup float,extents<int,64,64>,tensor_inline>
      destination(matrix,extents<int,64,64>{},array<int,2>{1,64});
  accumulator.store(destination);
  threadgroup_barrier(mem_flags::mem_threadgroup);
  for(uint i=tid;i<4096u;i+=128u)out[ulong(group)*4096ul+i]=matrix[i];
}
