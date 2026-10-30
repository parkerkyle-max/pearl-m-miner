// Objective-C++ host for the Pearl Metal backend.
//
// Device selection: MTLCopyAllDevices()[0] — MTLCreateSystemDefaultDevice()
// returns nil for plain command-line binaries on this platform (ADR-0004,
// measured). Shaders compile from embedded source at pm_compile time with the
// job shape as function constants; there is no .metallib step.

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

#include <cstring>
#include <cstdlib>
#include <array>
#include <chrono>
#include <cmath>
#include <mutex>
#include <string>

#include "pearl_metal.h"
#include "kernels_embedded.h"

namespace {

void set_err(char *err, size_t errlen, NSString *msg) {
  if (err && errlen > 0) {
    snprintf(err, errlen, "%s", msg ? msg.UTF8String : "unknown error");
  }
}

constexpr uint32_t kNumKernels = 16;
const char *const kKernelNames[kNumKernels] = {
    "blake3_64", "noise_uniform", "noise_pairs", "noise_apply", "pow_sweep",
    "pow_sweep_v2", "pow_sweep_v3", "pow_sweep_simdgroup",
    "pow_sweep_simdgroup_device", "convert_half4", "pow_sweep_tensor",
    "pow_sweep_tensor_fold", "pow_sweep_tensor_safe_accum", "range_guard64",
    "pow_sweep_tensor_safe_fold", "pow_sweep_tensor_safe_specialized",
};

struct PowParams {
  uint32_t n_row_bases;
  uint32_t n_col_bases;
  uint32_t hits_cap;
  uint32_t flags;
};

struct Bytes32 {
  uint8_t b[32];
};

// Diagnostic totals only. Dispatch ordering, waits and error propagation are
// unchanged. GPU durations are distinct from host encode/commit/wait durations.
struct KernelTiming {
  uint64_t count = 0;
  uint64_t gpu_timestamp_count = 0;
  uint64_t failed_count = 0;
  double wall_seconds = 0.0;
  double gpu_seconds = 0.0;
  double first_gpu_start = 0.0;
  double last_gpu_end = 0.0;
};

} // namespace

struct pm_ctx {
  id<MTLDevice> device;
  id<MTLCommandQueue> queue;
  id<MTLComputePipelineState> pipelines[kNumKernels];
  id<MTLBuffer> dummy; // bound to unused optional buffer slots
  id<NSObject> activity; // App Nap / timer-throttle suppression token
  pm_shape shape;
  bool compiled = false;
  uint32_t sweep_pipeline = 5;
  // The guarded API remains variant 12. Only the successful guard branch
  // chooses this experimental pipeline/geometry; fallback 10 stays SG4.
  uint32_t safe_pipeline = 12;
  bool safe_float_accum = false;
  bool safe_half_input = false;
  uint32_t safe_simdgroups = 4;
  std::string tune_name = "sg4";
  id<MTLBuffer> half_a;
  id<MTLBuffer> half_b;
  id<MTLBuffer> range_flag;
  id<MTLBuffer> layout_counts;
  uint64_t layout_fast_groups = 0, layout_fallback_groups = 0;
  uint64_t guarded_fast_count = 0;
  uint64_t guarded_fallback_count = 0;
  std::mutex timing_mutex;
  std::array<KernelTiming, kNumKernels> timings{};
};

extern "C" {

// Diagnostic branch counts; synchronous context, same ownership as dispatch.
int pm_get_guard_counts(pm_ctx *ctx, uint64_t *fast, uint64_t *fallback) {
  if (!ctx || !fast || !fallback) return 1;
  *fast = ctx->guarded_fast_count;
  *fallback = ctx->guarded_fallback_count;
  return 0;
}

// Completed synchronous threadgroups only; asynchronous snapshots have their
// own lifetime and do not mutate this context's diagnostic counters.
int pm_get_layout_counts(pm_ctx *ctx, uint64_t *fast, uint64_t *fallback) {
  if (!ctx || !fast || !fallback) return 1;
  *fast = ctx->layout_fast_groups; *fallback = ctx->layout_fallback_groups;
  return 0;
}

pm_ctx *pm_create(char *err, size_t errlen) {
  @autoreleasepool {
    NSArray<id<MTLDevice>> *devices = MTLCopyAllDevices();
    if (devices.count == 0) {
      set_err(err, errlen, @"no Metal devices (MTLCopyAllDevices returned none)");
      return nullptr;
    }
    pm_ctx *ctx = new pm_ctx();
    ctx->device = devices[0];
    // Without this, macOS App Nap suspends an unattended background miner
    // after a minute — measured: full speed for ~30 s, then near-total stall.
    // UserInitiated disables App Nap and idle system sleep; LatencyCritical
    // also disables timer throttling. Held for the context's lifetime.
    ctx->activity = [[NSProcessInfo processInfo]
        beginActivityWithOptions:(NSActivityUserInitiated | NSActivityLatencyCritical)
                          reason:@"pearl-metal-miner mining"];
    ctx->queue = [ctx->device newCommandQueue];
    ctx->dummy = [ctx->device newBufferWithLength:16
                                          options:MTLResourceStorageModeShared];
    if (!ctx->queue || !ctx->dummy) {
      set_err(err, errlen, @"failed to create command queue");
      pm_destroy(ctx);
      return nullptr;
    }
    return ctx;
  }
}

void pm_destroy(pm_ctx *ctx) {
  if (!ctx) return;
  // Symmetry with beginActivity above: the token outlives the context
  // otherwise, and a caller that creates and destroys a context without
  // exiting would keep App Nap suppressed for the rest of the process.
  if (ctx->activity) {
    [[NSProcessInfo processInfo] endActivity:ctx->activity];
    ctx->activity = nil;
  }
  delete ctx;
}

int pm_device_info(pm_ctx *ctx, char *name, size_t namelen,
                   uint64_t *max_threadgroup_mem, uint64_t *max_threads_per_tg) {
  @autoreleasepool {
    if (name && namelen) snprintf(name, namelen, "%s", ctx->device.name.UTF8String);
    if (max_threadgroup_mem) *max_threadgroup_mem = ctx->device.maxThreadgroupMemoryLength;
    if (max_threads_per_tg)
      *max_threads_per_tg = ctx->device.maxThreadsPerThreadgroup.width;
    return 0;
  }
}

// Research-only read API, intentionally separate from the production header:
//   size_t pm_get_timing(pm_ctx *ctx, char *json, size_t capacity)
// Returns the required buffer length INCLUDING the terminating NUL, or 0 on
// error. A null/undersized buffer is not written. Callers may query size first
// and retry if another dispatch grew the JSON. Reading never resets totals.
// Context lifetime remains caller-owned, just as for the other native APIs.
size_t pm_get_timing(pm_ctx *ctx, char *json, size_t capacity) {
  if (!ctx) return 0;
  @autoreleasepool {
    std::array<KernelTiming, kNumKernels> snapshot;
    {
      std::lock_guard<std::mutex> guard(ctx->timing_mutex);
      snapshot = ctx->timings;
    }
    NSMutableArray *rows = [NSMutableArray arrayWithCapacity:kNumKernels];
    for (uint32_t i = 0; i < kNumKernels; ++i) {
      const KernelTiming &entry = snapshot[i];
      [rows addObject:@{
        @"kernel_index": @(i),
        @"kernel": [NSString stringWithUTF8String:kKernelNames[i]],
        @"compiled": @(ctx->pipelines[i] != nil),
        @"static_threadgroup_bytes": @(ctx->pipelines[i].staticThreadgroupMemoryLength),
        @"max_threads_per_threadgroup": @(ctx->pipelines[i].maxTotalThreadsPerThreadgroup),
        @"count": @(entry.count),
        @"gpu_timestamp_count": @(entry.gpu_timestamp_count),
        @"missing_gpu_timestamps": @(entry.count - entry.gpu_timestamp_count),
        @"failed_count": @(entry.failed_count),
        @"wall_seconds": @(entry.wall_seconds),
        @"gpu_seconds": @(entry.gpu_seconds),
        @"first_gpu_start": @(entry.first_gpu_start),
        @"last_gpu_end": @(entry.last_gpu_end),
      }];
    }
    NSDictionary *record = @{
      @"schema_version": @1,
      @"scope": @"completed synchronous run calls over context lifetime",
      @"wall_clock": @"std::chrono::steady_clock elapsed seconds",
      @"gpu_clock": @"MTLCommandBuffer GPUStartTime/GPUEndTime host seconds",
      @"guarded_fast_count": @(ctx->guarded_fast_count),
      @"guarded_fallback_count": @(ctx->guarded_fallback_count),
      @"layout_fast_groups": @(ctx->layout_fast_groups),
      @"layout_fallback_groups": @(ctx->layout_fallback_groups),
      @"tune": [NSString stringWithUTF8String:ctx->tune_name.c_str()],
      @"safe_accumulator": ctx->safe_float_accum ? @"float" : @"int",
      @"safe_input": ctx->safe_half_input ? @"half" : @"signed-char",
      @"safe_pipeline_index": @(ctx->safe_pipeline),
      @"safe_pipeline": [NSString stringWithUTF8String:kKernelNames[ctx->safe_pipeline]],
      @"safe_threads_per_threadgroup": @(32u * ctx->safe_simdgroups),
      @"fallback_pipeline": @"pow_sweep_tensor",
      @"fallback_threads_per_threadgroup": @128,
      @"kernels": rows,
    };
    NSError *error = nil;
    NSData *encoded = [NSJSONSerialization dataWithJSONObject:record options:0 error:&error];
    if (!encoded || error) return 0;
    const size_t required = encoded.length + 1;
    if (json && capacity >= required) {
      memcpy(json, encoded.bytes, encoded.length);
      json[encoded.length] = '\0';
    }
    return required;
  }
}

int pm_compile(pm_ctx *ctx, const pm_shape *shape, char *err, size_t errlen) {
  @autoreleasepool {
    if (ctx->compiled && memcmp(&ctx->shape, shape, sizeof(pm_shape)) == 0) return 0;

    NSString *src = [[NSString alloc] initWithBytes:PEARL_KERNELS_MSL
                                             length:PEARL_KERNELS_MSL_LEN
                                           encoding:NSUTF8StringEncoding];
    MTLCompileOptions *opts = [MTLCompileOptions new];
    // The experimental SIMD-group matrix path uses the public MSL 2.3 API.
    // Its selection is explicit and never changes proof difficulty/counting.
    opts.languageVersion = MTLLanguageVersion2_3;
    const char *variant = std::getenv("FUSION_METAL_KERNEL");
    if (!variant || !*variant || !std::strcmp(variant, "v2")) ctx->sweep_pipeline = 5;
    else if (!std::strcmp(variant, "v3")) ctx->sweep_pipeline = 6;
    else if (!std::strcmp(variant, "simdgroup")) ctx->sweep_pipeline = 7;
    else if (!std::strcmp(variant, "simdgroup-device")) ctx->sweep_pipeline = 8;
    else if (!std::strcmp(variant, "tensor")) ctx->sweep_pipeline = 10;
    else if (!std::strcmp(variant, "tensor-fold")) ctx->sweep_pipeline = 11;
    else if (!std::strcmp(variant, "tensor-safe-accum")) ctx->sweep_pipeline = 12;
    else {
      set_err(err, errlen, @"FUSION_METAL_KERNEL must be v2, v3, simdgroup, simdgroup-device, tensor, tensor-fold, or tensor-safe-accum");
      return 1;
    }
    ctx->safe_pipeline = 12;
    ctx->safe_simdgroups = 4;
    ctx->tune_name = "sg4";
    const char *tune = std::getenv("FUSION_METAL_TUNE");
    if (tune && *tune && std::strcmp(tune, "default")) {
      if (ctx->sweep_pipeline != 12) {
        set_err(err, errlen, @"FUSION_METAL_TUNE requires FUSION_METAL_KERNEL=tensor-safe-accum");
        return 1;
      }
      if (!std::strcmp(tune, "sg2")) ctx->safe_simdgroups = 2;
      else if (!std::strcmp(tune, "sg4")) ctx->safe_simdgroups = 4;
      else if (!std::strcmp(tune, "sg8")) ctx->safe_simdgroups = 8;
      else if (!std::strcmp(tune, "fold-sg2")) { ctx->safe_pipeline = 14; ctx->safe_simdgroups = 2; }
      else if (!std::strcmp(tune, "fold-sg4")) { ctx->safe_pipeline = 14; ctx->safe_simdgroups = 4; }
      else if (!std::strcmp(tune, "fold-sg8")) { ctx->safe_pipeline = 14; ctx->safe_simdgroups = 8; }
      else if (!std::strcmp(tune, "specialized-sg4")) { ctx->safe_pipeline = 15; ctx->safe_simdgroups = 4; }
      else {
        set_err(err, errlen, @"FUSION_METAL_TUNE must be default, sg2, sg4, sg8, fold-sg2, fold-sg4, fold-sg8, or specialized-sg4");
        return 1;
      }
      ctx->tune_name = tune;
    }
    ctx->safe_float_accum = false;
    ctx->safe_half_input = false;
    const char *acc_type = std::getenv("FUSION_METAL_ACCUMULATOR");
    if (acc_type && *acc_type && std::strcmp(acc_type, "int")) {
      if (ctx->sweep_pipeline != 12 || (std::strcmp(acc_type, "float") && std::strcmp(acc_type, "half"))) {
        set_err(err, errlen, @"FUSION_METAL_ACCUMULATOR=float|half requires tensor-safe-accum");
        return 1;
      }
      ctx->safe_float_accum = true;
      ctx->safe_half_input = !std::strcmp(acc_type, "half");
    }
    // Metal 4 is an explicit opt-in. The baseline and older experiments still
    // compile as MSL 2.3 on older SDKs/macOS; they never parse the tensor code.
    if (ctx->sweep_pipeline >= 10 && ctx->sweep_pipeline <= 12) {
#if defined(__MAC_OS_X_VERSION_MAX_ALLOWED) && __MAC_OS_X_VERSION_MAX_ALLOWED >= 260000
      if (@available(macOS 26.0, *)) {
        opts.languageVersion = MTLLanguageVersion4_0;
        opts.preprocessorMacros = @{@"FUSION_METAL4": @1, @"FUSION_RANK": @(shape->r),
                                    @"FUSION_SAFE_SIMDGROUPS": @(ctx->safe_simdgroups),
                                    @"FUSION_SAFE_FLOAT_ACCUM": @(ctx->safe_float_accum),
                                    @"FUSION_SAFE_HALF_INPUT": @(ctx->safe_half_input)};
      } else {
        set_err(err, errlen, @"tensor path requires macOS 26 or later");
        return 1;
      }
#else
      set_err(err, errlen, @"tensor path requires a build with the macOS 26 SDK or later");
      return 1;
#endif
    }
    // IEEE fp32 semantics are load-bearing: the fast-path GEMM accumulates
    // chunk partials (integers < 2^24) in fp32 FMA, exactly, only because
    // fast-math is off. The self-test enforces the resulting bit-exactness.
    // macOS 15 renamed this knob; MTLMathModeSafe IS `fastMathEnabled = NO`,
    // so both spellings ask for exactly the same semantics — the split is
    // only to keep the build warning-free on both SDKs.
#if defined(__MAC_OS_X_VERSION_MAX_ALLOWED) && __MAC_OS_X_VERSION_MAX_ALLOWED >= 150000
    if (@available(macOS 15.0, *)) {
      opts.mathMode = MTLMathModeSafe;
    } else {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
      opts.fastMathEnabled = NO;
#pragma clang diagnostic pop
    }
#else
    opts.fastMathEnabled = NO;
#endif
    NSError *nserr = nil;
    id<MTLLibrary> lib = [ctx->device newLibraryWithSource:src options:opts error:&nserr];
    if (!lib) {
      set_err(err, errlen, [NSString stringWithFormat:@"MSL compile failed: %@",
                                                      nserr.localizedDescription]);
      return 1;
    }

    MTLFunctionConstantValues *cv = [MTLFunctionConstantValues new];
    uint32_t vals[16] = {shape->k,       shape->r,       shape->h,       shape->w,
                         shape->rows[0], shape->rows[1], shape->rows[2], shape->rows[3],
                         shape->rows[4], shape->rows[5], shape->cols[0], shape->cols[1],
                         shape->cols[2], shape->cols[3], shape->cols[4], shape->cols[5]};
    for (uint32_t i = 0; i < 16; i++) {
      [cv setConstantValue:&vals[i] type:MTLDataTypeUInt atIndex:i];
    }

    // Compile every kernel up front so shader errors surface here, once,
    // rather than at first dispatch (ADR-0004).
    for (uint32_t i = 0; i < kNumKernels; i++) {
      // The guarded experiment always compiles its exact-int32 fallback.
      const bool tensor_candidate = (i >= 10 && i <= 12) || i == 14 || i == 15;
      const bool needed_tensor = ctx->sweep_pipeline == 12
          ? (i == 10 || i == ctx->safe_pipeline)
          : i == ctx->sweep_pipeline;
      if (tensor_candidate && !needed_tensor) {
        ctx->pipelines[i] = nil;
        continue;
      }
      id<MTLFunction> fn =
          [lib newFunctionWithName:[NSString stringWithUTF8String:kKernelNames[i]]
                    constantValues:cv
                             error:&nserr];
      if (!fn) {
        set_err(err, errlen,
                [NSString stringWithFormat:@"function %s: %@", kKernelNames[i],
                                           nserr.localizedDescription]);
        return 1;
      }
      ctx->pipelines[i] = [ctx->device newComputePipelineStateWithFunction:fn error:&nserr];
      if (!ctx->pipelines[i]) {
        set_err(err, errlen,
                [NSString stringWithFormat:@"pipeline %s: %@", kKernelNames[i],
                                           nserr.localizedDescription]);
        return 1;
      }
      // The kernels' simd_xor/simd_shuffle_xor folds and per-simdgroup
      // scratch sizing assume 32-lane simdgroups — true of every Apple GPU
      // shipped to date (M1…M5). If a future GPU differs, refuse loudly here
      // rather than fail the self-test mysteriously.
      NSUInteger width = ctx->pipelines[i].threadExecutionWidth;
      if (width != 32) {
        set_err(err, errlen,
                [NSString stringWithFormat:
                              @"kernel %s: simdgroup width %lu (expected 32) — "
                              @"untested GPU generation; refusing to mine. "
                              @"Please open an issue with your chip and macOS "
                              @"version.",
                              kKernelNames[i], (unsigned long)width]);
        return 1;
      }
    }
    ctx->shape = *shape;
    ctx->compiled = true;
    return 0;
  }
}

void *pm_alloc(pm_ctx *ctx, size_t bytes) {
  @autoreleasepool {
    id<MTLBuffer> buf = [ctx->device newBufferWithLength:bytes
                                                 options:MTLResourceStorageModeShared];
    return (__bridge_retained void *)buf;
  }
}

void *pm_contents(void *buf) { return [(__bridge id<MTLBuffer>)buf contents]; }

void pm_release(void *buf) {
  id<MTLBuffer> b = (__bridge_transfer id<MTLBuffer>)buf;
  (void)b;
}

namespace {

// Synchronously run one compute pass. `configure` sets buffers/bytes.
int run(pm_ctx *ctx, uint32_t kernel_idx, MTLSize grid, MTLSize tg,
        NSUInteger tgmem, bool uniform_grid,
        void (^configure)(id<MTLComputeCommandEncoder>), char *err, size_t errlen) {
  @autoreleasepool {
    if (!ctx->compiled) {
      set_err(err, errlen, @"pm_compile has not run");
      return 1;
    }
    const auto wall_start = std::chrono::steady_clock::now();
    id<MTLCommandBuffer> cb = [ctx->queue commandBuffer];
    if (!cb) {
      set_err(err, errlen, @"could not allocate Metal command buffer");
      return 1;
    }
    id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
    if (!enc) {
      set_err(err, errlen, @"could not allocate Metal compute encoder");
      return 1;
    }
    [enc setComputePipelineState:ctx->pipelines[kernel_idx]];
    if (tgmem) [enc setThreadgroupMemoryLength:tgmem atIndex:0];
    configure(enc);
    if (uniform_grid) {
      [enc dispatchThreadgroups:grid threadsPerThreadgroup:tg];
    } else {
      [enc dispatchThreads:grid threadsPerThreadgroup:tg];
    }
    [enc endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    const double wall_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - wall_start).count();
    // Metal timestamps are valid only after completion. Unavailable/failed
    // samples are counted separately instead of pretending their GPU cost is 0.
    const double gpu_start = cb.GPUStartTime;
    const double gpu_end = cb.GPUEndTime;
    const bool valid_gpu_timestamps = cb.status == MTLCommandBufferStatusCompleted &&
        std::isfinite(gpu_start) && std::isfinite(gpu_end) &&
        gpu_start > 0.0 && gpu_end >= gpu_start;
    {
      std::lock_guard<std::mutex> guard(ctx->timing_mutex);
      KernelTiming &entry = ctx->timings[kernel_idx];
      ++entry.count;
      entry.wall_seconds += wall_seconds;
      if (cb.status != MTLCommandBufferStatusCompleted) ++entry.failed_count;
      if (valid_gpu_timestamps) {
        ++entry.gpu_timestamp_count;
        entry.gpu_seconds += gpu_end - gpu_start;
        if (entry.first_gpu_start == 0.0 || gpu_start < entry.first_gpu_start)
          entry.first_gpu_start = gpu_start;
        if (gpu_end > entry.last_gpu_end) entry.last_gpu_end = gpu_end;
      }
    }
    if (cb.status != MTLCommandBufferStatusCompleted) {
      set_err(err, errlen,
              [NSString stringWithFormat:@"GPU error: %@", cb.error.localizedDescription]);
      return 1;
    }
    return 0;
  }
}

inline id<MTLBuffer> mb(void *p) { return (__bridge id<MTLBuffer>)p; }

} // namespace

int pm_blake3_64(pm_ctx *ctx, void *msgs, void *keys, void *out, uint32_t count,
                 char *err, size_t errlen) {
  return run(
      ctx, 0, MTLSizeMake(count, 1, 1), MTLSizeMake(MIN(count, 256u), 1, 1), 0, false,
      ^(id<MTLComputeCommandEncoder> enc) {
        [enc setBuffer:mb(msgs) offset:0 atIndex:0];
        [enc setBuffer:mb(keys) offset:0 atIndex:1];
        [enc setBuffer:mb(out) offset:0 atIndex:2];
        [enc setBytes:&count length:4 atIndex:3];
      },
      err, errlen);
}

int pm_noise_uniform(pm_ctx *ctx, const uint8_t *seed, const uint8_t *key, void *out,
                     uint32_t rows, char *err, size_t errlen) {
  uint32_t nblocks = rows * ctx->shape.r / 32;
  Bytes32 seed32, key32;
  memcpy(seed32.b, seed, 32);
  memcpy(key32.b, key, 32);
  return run(
      ctx, 1, MTLSizeMake(nblocks, 1, 1), MTLSizeMake(MIN(nblocks, 256u), 1, 1), 0, false,
      ^(id<MTLComputeCommandEncoder> enc) {
        [enc setBytes:seed32.b length:32 atIndex:0];
        [enc setBytes:key32.b length:32 atIndex:1];
        [enc setBuffer:mb(out) offset:0 atIndex:2];
        [enc setBytes:&nblocks length:4 atIndex:3];
      },
      err, errlen);
}

int pm_noise_pairs(pm_ctx *ctx, const uint8_t *seed, const uint8_t *key, void *out,
                   char *err, size_t errlen) {
  uint32_t ndigests = (ctx->shape.k + 7) / 8;
  Bytes32 seed32, key32;
  memcpy(seed32.b, seed, 32);
  memcpy(key32.b, key, 32);
  return run(
      ctx, 2, MTLSizeMake(ndigests, 1, 1), MTLSizeMake(MIN(ndigests, 256u), 1, 1), 0,
      false,
      ^(id<MTLComputeCommandEncoder> enc) {
        [enc setBytes:seed32.b length:32 atIndex:0];
        [enc setBytes:key32.b length:32 atIndex:1];
        [enc setBuffer:mb(out) offset:0 atIndex:2];
        [enc setBytes:&ndigests length:4 atIndex:3];
      },
      err, errlen);
}

int pm_noise_apply(pm_ctx *ctx, void *base, void *table, void *pairs, void *out,
                   uint32_t rows, char *err, size_t errlen) {
  return run(
      ctx, 3, MTLSizeMake(ctx->shape.k, rows, 1), MTLSizeMake(64, 4, 1), 0, false,
      ^(id<MTLComputeCommandEncoder> enc) {
        [enc setBuffer:mb(base) offset:0 atIndex:0];
        [enc setBuffer:mb(table) offset:0 atIndex:1];
        [enc setBuffer:mb(pairs) offset:0 atIndex:2];
        [enc setBuffer:mb(out) offset:0 atIndex:3];
        [enc setBytes:&rows length:4 atIndex:4];
      },
      err, errlen);
}

static int pow_sweep_impl(pm_ctx *ctx, void *an, void *bnt, void *row_bases,
                          uint32_t n_row_bases, void *col_bases, uint32_t n_col_bases,
                          const uint8_t *a_seed, const uint8_t *bound, void *hits,
                          uint32_t hits_capacity, void *digests_out, void *csums_out,
                          void *transcripts_out, char *err, size_t errlen) {
  const pm_shape &s = ctx->shape;
  uint32_t nthreads = s.h * s.w;
  NSUInteger tgmem = (NSUInteger)(s.h + s.w) * s.r + (8 + 16) * 4;
  uint64_t dev_max = ctx->device.maxThreadgroupMemoryLength;
  if (tgmem > dev_max) {
    set_err(err, errlen,
            [NSString stringWithFormat:@"tiling needs %lu B threadgroup memory, device has %llu"
                                       @" — refusing (query-don't-assume)",
                                       (unsigned long)tgmem, dev_max]);
    return 1;
  }
  if (nthreads > ctx->device.maxThreadsPerThreadgroup.width) {
    set_err(err, errlen, @"h*w exceeds device max threads per threadgroup");
    return 1;
  }
  PowParams P = {n_row_bases, n_col_bases, hits_capacity,
                 (digests_out ? 1u : 0u) | (csums_out ? 2u : 0u)};
  Bytes32 seed32, bound32;
  memcpy(seed32.b, a_seed, 32);
  memcpy(bound32.b, bound, 32);
  return run(
      ctx, 4, MTLSizeMake(n_col_bases, n_row_bases, 1), MTLSizeMake(nthreads, 1, 1),
      tgmem, true,
      ^(id<MTLComputeCommandEncoder> enc) {
        [enc setBuffer:mb(an) offset:0 atIndex:0];
        [enc setBuffer:mb(bnt) offset:0 atIndex:1];
        [enc setBuffer:mb(row_bases) offset:0 atIndex:2];
        [enc setBuffer:mb(col_bases) offset:0 atIndex:3];
        [enc setBytes:seed32.b length:32 atIndex:4];
        [enc setBytes:bound32.b length:32 atIndex:5];
        [enc setBuffer:mb(hits) offset:0 atIndex:6];
        [enc setBytes:&P length:sizeof(P) atIndex:7];
        [enc setBuffer:(digests_out ? mb(digests_out) : ctx->dummy) offset:0 atIndex:8];
        [enc setBuffer:(csums_out ? mb(csums_out) : ctx->dummy) offset:0 atIndex:9];
        [enc setBuffer:(transcripts_out ? mb(transcripts_out) : ctx->dummy)
                offset:0
               atIndex:10];
      },
      err, errlen);
}

int pm_pow_sweep(pm_ctx *ctx, void *an, void *bnt, void *row_bases, uint32_t n_row_bases,
                 void *col_bases, uint32_t n_col_bases, const uint8_t *a_seed,
                 const uint8_t *bound, void *hits, uint32_t hits_capacity,
                 void *digests_out, char *err, size_t errlen) {
  return pow_sweep_impl(ctx, an, bnt, row_bases, n_row_bases, col_bases, n_col_bases,
                        a_seed, bound, hits, hits_capacity, digests_out, nullptr, nullptr,
                        err, errlen);
}

/* Fast-path blocked sweep. Host must ensure rows_pattern == [0,32] (two-level),
 * cols_pattern == [0..63], r <= 128, m % 64 == 0, n % 64 == 0. */
int pm_pow_sweep2(pm_ctx *ctx, void *an, void *bnt, uint32_t band_lo,
                  uint32_t n_bands, uint32_t n_col_bases, const uint8_t *a_seed,
                  const uint8_t *bound, void *hits, uint32_t hits_capacity,
                  void *digests_out, char *err, size_t errlen) {
  const pm_shape &s = ctx->shape;
  if (!(s.rows[0] == 32 && s.rows[1] == 2 && s.rows[3] == 1 && s.rows[5] == 1 &&
        s.cols[0] == 1 && s.cols[1] == 64 && s.cols[3] == 1 && s.cols[5] == 1 &&
        s.r <= 128)) {
    set_err(err, errlen, @"shape not eligible for pow_sweep_v2 fast path");
    return 1;
  }
  PowParams P = {n_bands, n_col_bases, hits_capacity, digests_out ? 1u : 0u};
  Bytes32 seed32, bound32;
  memcpy(seed32.b, a_seed, 32);
  memcpy(bound32.b, bound, 32);
  // Blocks cannot capture C arrays; capture scalars and rebuild inside.
  const uint32_t p2a = band_lo, p2b = n_col_bases;
  const bool device_matrix = ctx->sweep_pipeline == 8;
  const bool tensor_matrix = ctx->sweep_pipeline >= 10 && ctx->sweep_pipeline <= 12;
  const bool matrix = ctx->sweep_pipeline == 7 || device_matrix;
  if (matrix && (s.r % 8 != 0)) {
    set_err(err, errlen, @"SIMD-group matrix path requires rank divisible by 8");
    return 1;
  }
  uint32_t threads = (matrix || tensor_matrix) ? 128u : 256u;
  const uint32_t groups_y = n_bands * (device_matrix ? 2u : matrix ? 8u : 1u);
  const uint32_t requested_pipeline = ctx->sweep_pipeline == 12
      ? ctx->safe_pipeline : ctx->sweep_pipeline;
  if (ctx->sweep_pipeline == 12) threads = 32u * ctx->safe_simdgroups;
  id<MTLComputePipelineState> pipeline = ctx->pipelines[requested_pipeline];
  if (!pipeline || pipeline.staticThreadgroupMemoryLength > ctx->device.maxThreadgroupMemoryLength ||
      threads > pipeline.maxTotalThreadsPerThreadgroup) {
    set_err(err, errlen, @"experimental sweep exceeds device/pipeline resource limits");
    return 1;
  }
  // Refresh every sweep: this preserves the existing public API's semantics
  // even when a caller edits an input through its shared CPU view. Allocation
  // is reused, but values are never cached by pointer identity. Conversion is
  // amortized over a region and eliminated from every threadgroup/rank block.
  id<MTLBuffer> input_a = mb(an), input_b = mb(bnt);
  uint32_t selected_pipeline = ctx->sweep_pipeline;
  if (selected_pipeline == 12) {
    // Each call checks the actual shared input contents. Never trust the
    // signal generator, caller metadata, pointer identity or a prior call.
    // Callers, as for every existing synchronous API, must not mutate an
    // input concurrently with dispatch. Between-call mutations are allowed.
    const uint64_t required_a = (uint64_t(band_lo) + n_bands) * 64 * s.k;
    const uint64_t required_b = uint64_t(n_col_bases) * 64 * s.k;
    if (input_a == mb(hits) || input_b == mb(hits) ||
        (digests_out && (input_a == mb(digests_out) || input_b == mb(digests_out)))) {
      set_err(err, errlen, @"guarded tensor input cannot alias writable output");
      return 1;
    }
    if (!n_bands || !n_col_bases || !s.k ||
        required_a > input_a.length || required_b > input_b.length) {
      set_err(err, errlen, @"guarded tensor input dimensions exceed buffer extent");
      return 1;
    }
    bool safe = false;
    if (s.k <= 4096 && input_a.length <= UINT32_MAX && input_b.length <= UINT32_MAX) {
      if (!ctx->range_flag)
        ctx->range_flag = [ctx->device newBufferWithLength:4 options:MTLResourceStorageModeShared];
      if (!ctx->range_flag) {
        set_err(err, errlen, @"could not allocate range guard flag");
        return 1;
      }
      *static_cast<uint32_t *>(ctx->range_flag.contents) = 0;
      const uint32_t count_a = (uint32_t)input_a.length;
      const uint32_t count_b = (uint32_t)input_b.length;
      const uint32_t lanes = (uint32_t)((uint64_t(MAX(count_a, count_b)) + 3) / 4);
      const int rc = run(ctx, 13, MTLSizeMake(lanes, 1, 1), MTLSizeMake(MIN(lanes, 256u), 1, 1), 0, false,
        ^(id<MTLComputeCommandEncoder> enc) {
          const uint32_t lengths[2] = {count_a, count_b};
          [enc setBuffer:input_a offset:0 atIndex:0];
          [enc setBuffer:input_b offset:0 atIndex:1];
          [enc setBuffer:ctx->range_flag offset:0 atIndex:2];
          [enc setBytes:lengths length:8 atIndex:3];
        }, err, errlen);
      if (rc) return rc;
      safe = *static_cast<uint32_t *>(ctx->range_flag.contents) == 0;
    }
    // K*64*64 <= 2^24 bounds every possible subset sum, regardless of
    // accumulation order. This route is validated with boundary transcripts.
    if (safe) {
      selected_pipeline = ctx->safe_pipeline;
      ++ctx->guarded_fast_count;
    } else {
      selected_pipeline = 10;
      threads = 128u;
      ++ctx->guarded_fallback_count;
    }
    id<MTLComputePipelineState> chosen = ctx->pipelines[selected_pipeline];
    if (!chosen || chosen.staticThreadgroupMemoryLength > ctx->device.maxThreadgroupMemoryLength ||
        threads > chosen.maxTotalThreadsPerThreadgroup) {
      set_err(err, errlen, @"guarded tensor branch exceeds pipeline resource limits");
      return 1;
    }
  }
  if (selected_pipeline == 15) {
    const char *force = std::getenv("FUSION_METAL_LAYOUT_FALLBACK");
    if (force && *force && std::strcmp(force, "0") && std::strcmp(force, "1")) {
      set_err(err, errlen, @"FUSION_METAL_LAYOUT_FALLBACK must be 0 or 1");
      return 1;
    }
    if (!ctx->layout_counts)
      ctx->layout_counts = [ctx->device newBufferWithLength:16 options:MTLResourceStorageModeShared];
    if (!ctx->layout_counts) { set_err(err, errlen, @"layout diagnostic allocation failed"); return 1; }
    memset(ctx->layout_counts.contents, 0, 16);
    P.flags |= 4u;
    if (force && !std::strcmp(force, "1")) P.flags |= 8u;
  }
  if (device_matrix || (ctx->sweep_pipeline == 12 && selected_pipeline == ctx->safe_pipeline && ctx->safe_half_input)) {
    if (input_a.length % 4 || input_b.length % 4) {
      set_err(err, errlen, @"device matrix path requires four-byte input alignment");
      return 1;
    }
    if (!ctx->half_a || ctx->half_a.length != input_a.length * 2)
      ctx->half_a = [ctx->device newBufferWithLength:input_a.length * 2 options:MTLResourceStorageModeShared];
    if (!ctx->half_b || ctx->half_b.length != input_b.length * 2)
      ctx->half_b = [ctx->device newBufferWithLength:input_b.length * 2 options:MTLResourceStorageModeShared];
    if (!ctx->half_a || !ctx->half_b) {
      set_err(err, errlen, @"could not allocate reusable half conversion buffers");
      return 1;
    }
    for (uint32_t which = 0; which < 2; ++which) {
      id<MTLBuffer> src = which ? input_b : input_a;
      id<MTLBuffer> dst = which ? ctx->half_b : ctx->half_a;
      const uint64_t count64 = src.length / 4;
      if (count64 > UINT32_MAX) {
        set_err(err, errlen, @"half conversion buffer exceeds supported element count");
        return 1;
      }
      const uint32_t count = (uint32_t)count64;
      int rc = run(ctx, 9, MTLSizeMake(count, 1, 1), MTLSizeMake(MIN(count, 256u), 1, 1), 0, false,
        ^(id<MTLComputeCommandEncoder> enc) {
          [enc setBuffer:src offset:0 atIndex:0];
          [enc setBuffer:dst offset:0 atIndex:1];
          [enc setBytes:&count length:4 atIndex:2];
        }, err, errlen);
      if (rc) return rc;
    }
    input_a = ctx->half_a;
    input_b = ctx->half_b;
  }
  const int sweep_result = run(
      ctx, selected_pipeline, MTLSizeMake(n_col_bases, groups_y, 1), MTLSizeMake(threads, 1, 1), 0, true,
      ^(id<MTLComputeCommandEncoder> enc) {
        uint32_t pp[2] = {p2a, p2b};
        [enc setBuffer:input_a offset:0 atIndex:0];
        [enc setBuffer:input_b offset:0 atIndex:1];
        [enc setBytes:pp length:8 atIndex:2];
        [enc setBytes:seed32.b length:32 atIndex:4];
        [enc setBytes:bound32.b length:32 atIndex:5];
        [enc setBuffer:mb(hits) offset:0 atIndex:6];
        [enc setBytes:&P length:sizeof(P) atIndex:7];
        [enc setBuffer:(digests_out ? mb(digests_out) : ctx->dummy) offset:0 atIndex:8];
        [enc setBuffer:(selected_pipeline == 15 ? ctx->layout_counts : ctx->dummy) offset:0 atIndex:9];
      },
      err, errlen);
  if (sweep_result == 0 && selected_pipeline == 15) {
    const uint32_t *counts = static_cast<const uint32_t *>(ctx->layout_counts.contents);
    ctx->layout_fast_groups += counts[0];
    ctx->layout_fallback_groups += counts[1];
  }
  return sweep_result;
}

int pm_pow_sweep_debug(pm_ctx *ctx, void *an, void *bnt, void *row_bases,
                       uint32_t n_row_bases, void *col_bases, uint32_t n_col_bases,
                       const uint8_t *a_seed, const uint8_t *bound, void *hits,
                       uint32_t hits_capacity, void *digests_out, void *csums_out,
                       void *transcripts_out, char *err, size_t errlen) {
  return pow_sweep_impl(ctx, an, bnt, row_bases, n_row_bases, col_bases, n_col_bases,
                        a_seed, bound, hits, hits_capacity, digests_out, csums_out,
                        transcripts_out, err, errlen);
}

} // extern "C"

#include "async_research.inc"
