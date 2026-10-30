// Standalone arithmetic measurement. No Pearl jobs, proofs, targets or fees.
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
inline void run_sg(device const Scalar *ap, device const Scalar *bp,
    device float *out, constant uint2 &params, uint group, uint sg) {
  const uint index=group*params.y+sg;
  simdgroup_matrix<Scalar,8,8> a;
  simdgroup_matrix<Scalar,8,8> b[BENCH_CHAINS];
  simdgroup_float8x8 c[BENCH_CHAINS];
  // Runtime inputs are loaded once per dispatch. B differs between chains.
  simdgroup_load(a,ap+ulong(index)*64ul,8u);
  #pragma unroll
  for(uint q=0u;q<BENCH_CHAINS;++q) {
    simdgroup_load(b[q],bp+(ulong(index)*BENCH_CHAINS+q)*64ul,
                   8u,ulong2(0),true);
    c[q]=simdgroup_float8x8(0.0f);
  }
  // Iterations arrive in a runtime constant buffer. The output of every
  // accumulator is observed; no unused arithmetic is counted.
  for(uint iteration=0u;iteration<params.x;++iteration) {
    #pragma unroll
    for(uint q=0u;q<BENCH_CHAINS;++q)
      simdgroup_multiply_accumulate(c[q],a,b[q],c[q]);
  }
  #pragma unroll
  for(uint q=0u;q<BENCH_CHAINS;++q)
    simdgroup_store(c[q],out+(ulong(index)*BENCH_CHAINS+q)*64ul,8u);
}

kernel void peak_half(device const half *ap [[buffer(0)]],
    device const half *bp [[buffer(1)]],device float *out [[buffer(2)]],
    constant uint2 &params [[buffer(3)]],uint group [[threadgroup_position_in_grid]],
    uint sg [[simdgroup_index_in_threadgroup]]) {
  run_sg(ap,bp,out,params,group,sg);
}
kernel void peak_float(device const float *ap [[buffer(0)]],
    device const float *bp [[buffer(1)]],device float *out [[buffer(2)]],
    constant uint2 &params [[buffer(3)]],uint group [[threadgroup_position_in_grid]],
    uint sg [[simdgroup_index_in_threadgroup]]) {
  run_sg(ap,bp,out,params,group,sg);
}

// Production-shape comparison: one64x64x128 matmul per iteration, four
// SIMDgroups. Unlike the8x8 test, operation.run reads device-backed operands
// each iteration (usually hot in cache); this is NOT a register-only test.
kernel void peak_mpp(device half *ap [[buffer(0)]],
    device half *bp [[buffer(1)]],device float *out [[buffer(2)]],
    constant uint2 &params [[buffer(3)]],uint group [[threadgroup_position_in_grid]],
    uint tid [[thread_index_in_threadgroup]]) {
  constexpr auto descriptor=matmul2d_descriptor(64,64,128,false,true,false,
      matmul2d_descriptor::mode::multiply_accumulate);
  using Operand=tensor<device half,extents<int,128,64>,tensor_inline>;
  matmul2d<descriptor,execution_simdgroups<4>> operation;
  auto accumulator=operation.get_destination_cooperative_tensor<Operand,Operand,float>();
  for(uint i=0u;i<accumulator.get_capacity();++i)
    if(accumulator.is_valid_element(i))accumulator[i]=0.0f;
  Operand a(ap+ulong(group)*8192ul,extents<int,128,64>{},array<int,2>{1,128});
  Operand b(bp+ulong(group)*8192ul,extents<int,128,64>{},array<int,2>{1,128});
  for(uint iteration=0u;iteration<params.x;++iteration)
    operation.run(a,b,accumulator);
  threadgroup float matrix[4096];
  tensor<threadgroup float,extents<int,64,64>,tensor_inline>
      destination(matrix,extents<int,64,64>{},array<int,2>{1,64});
  accumulator.store(destination);
  threadgroup_barrier(mem_flags::mem_threadgroup);
  for(uint i=tid;i<4096u;i+=128u)out[ulong(group)*4096ul+i]=matrix[i];
}
