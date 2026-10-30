// Research-only include after pearl_metal.mm's existing extern-C block.
// Every prepared grid owns immutable PRIVATE snapshots and strong Metal
// resources. No asynchronous object/callback retains a raw pm_ctx pointer.
// Creation requires a live, exclusively used ctx/source buffers, just as the
// synchronous API does. After creation ctx/source lifetime is independent.
#include <atomic>
#include <map>
#include <memory>
#include <limits>
#include <stdexcept>

struct PMAsyncResult {
  uint64_t ticket, generation, tiles;
  uint32_t band_lo, n_bands, stored_hits, total_hits, pipeline_index, threads;
  double wall_seconds, gpu_seconds;
};
struct PMAsyncStats {
  uint64_t scheduled, completed, returned, discarded, failed;
  uint64_t tiles_scheduled, tiles_returned, tiles_discarded;
  uint64_t guard_fast, guard_fallback, missing_gpu_timestamps;
  double preparation_wall_seconds, preparation_gpu_seconds;
  double gpu_seconds, wait_wall_seconds;
};

namespace fusion_async_research {
using Clock = std::chrono::steady_clock;
constexpr uint32_t kHitsCapacity = 4096;
constexpr uint64_t kHitsBytes = 4 + uint64_t(kHitsCapacity) * 8;
struct Work {
  uint64_t ticket = 0, tiles = 0;
  uint32_t band_lo = 0, n_bands = 0;
  uint64_t digest_offset = 0, digest_bytes = 0;
  id<MTLBuffer> hits, digests;
  id<MTLCommandBuffer> command;
  Clock::time_point submitted;
};
struct Prepared {
  std::mutex mutex;
  uint64_t handle = 0, generation = 0;
  uint32_t depth = 0, m_rows = 0, n_rows = 0;
  uint32_t pipeline_index = 0, threads = 0, next_band = 0;
  bool started = false, bound_set = false, want_digests = false;
  bool force_layout_fallback = false;
  bool closing = false, closed = false;
  pm_shape shape{};
  std::array<uint8_t, 32> seed{}, bound{};
  id<MTLDevice> device;
  id<MTLCommandQueue> queue;
  id<MTLComputePipelineState> pipeline;
  id<MTLBuffer> a, bt, dummy;
  id<NSObject> activity;
  std::map<uint64_t, std::shared_ptr<Work>> pending;
  PMAsyncStats stats{};
  ~Prepared() {
    // Designed close drains first; this also protects exceptional create paths.
    for (auto &item : pending) [item.second->command waitUntilCompleted];
    if (activity) [[NSProcessInfo processInfo] endActivity:activity];
  }
};
std::mutex registry_mutex;
std::map<uint64_t, std::shared_ptr<Prepared>> registry;
std::atomic<uint64_t> next_id{1};

uint64_t unique_id() {
  uint64_t value = next_id.load(std::memory_order_relaxed);
  while (value != std::numeric_limits<uint64_t>::max()) {
    if (next_id.compare_exchange_weak(value, value + 1, std::memory_order_relaxed)) return value;
  }
  throw std::runtime_error("async monotonic identity space exhausted");
}
std::shared_ptr<Prepared> lookup(uint64_t handle, uint64_t generation) {
  std::lock_guard<std::mutex> lock(registry_mutex);
  auto found = registry.find(handle);
  if (!handle || !generation || found == registry.end() || found->second->generation != generation)
    throw std::runtime_error("invalid or closed async handle/generation");
  return found->second;
}
void require(bool condition, const char *message) {
  if (!condition) throw std::runtime_error(message);
}
bool output_overlap(const void *a, uint64_t a_bytes, const void *b, uint64_t b_bytes) {
  if (!a_bytes || !b_bytes) return false;
  const uintptr_t first = reinterpret_cast<uintptr_t>(a), second = reinterpret_cast<uintptr_t>(b);
  require(a && b && a_bytes <= UINTPTR_MAX - first && b_bytes <= UINTPTR_MAX - second,
          "async output pointer extent is invalid");
  return first < second + b_bytes && second < first + a_bytes;
}
double gpu_seconds(id<MTLCommandBuffer> command, bool *valid = nullptr) {
  double start = command.GPUStartTime, end = command.GPUEndTime;
  bool okay = command && command.status == MTLCommandBufferStatusCompleted &&
      std::isfinite(start) && std::isfinite(end) && start > 0 && end >= start;
  if (valid) *valid = okay;
  return okay ? end - start : 0.0;
}
void require_completed(id<MTLCommandBuffer> command) {
  require(command != nil, "async command allocation failed");
  [command waitUntilCompleted];
  if (command.status != MTLCommandBufferStatusCompleted) {
    NSString *message = command.error.localizedDescription;
    throw std::runtime_error(message ? message.UTF8String : "async command did not complete successfully");
  }
}
void account(Prepared &p, Work &w, bool returned) {
  bool valid = false;
  p.stats.gpu_seconds += gpu_seconds(w.command, &valid);
  if (!valid) ++p.stats.missing_gpu_timestamps;
  if (w.command.status == MTLCommandBufferStatusCompleted) ++p.stats.completed;
  else ++p.stats.failed;
  if (returned) { ++p.stats.returned; p.stats.tiles_returned += w.tiles; }
  else { ++p.stats.discarded; p.stats.tiles_discarded += w.tiles; }
}
int error(char *err, size_t errlen, const std::exception &exception) {
  set_err(err, errlen, [NSString stringWithUTF8String:exception.what()]);
  return 1;
}
} // namespace fusion_async_research

extern "C" {

// flags bit0 enables complete digests for bounded correctness tests only.
// The target is bound by the first submit; later target/seed changes reject.
int pm_async_prepare(pm_ctx *ctx, void *an, void *bnt,
                     uint32_t m_rows, uint32_t n_rows, const uint8_t *seed,
                     uint32_t depth, uint32_t flags,
                     uint64_t *handle, uint64_t *generation, char *err, size_t errlen) {
  using namespace fusion_async_research;
  @autoreleasepool { try {
    require(handle && generation && handle != generation,
            "async prepare requires distinct output identity storage");
    *handle = *generation = 0;
    require(ctx && ctx->compiled && ctx->sweep_pipeline == 12,
            "async prepare requires a compiled tensor-safe-accum context");
    require(seed && an && bnt && depth >= 1 && depth <= 3 && !(flags & ~1u),
            "invalid async prepare pointers, depth or flags");
    auto p = std::make_shared<Prepared>();
    p->shape = ctx->shape;
    p->device = ctx->device;
    // A dedicated FIFO keeps this prepared grid independent from recompile,
    // later synchronous work, and ctx destruction. No callbacks touch ctx.
    p->queue = [p->device newCommandQueue];
    id<MTLComputePipelineState> candidate = ctx->pipelines[ctx->safe_pipeline];
    id<MTLComputePipelineState> fallback = ctx->pipelines[10];
    id<MTLComputePipelineState> guard = ctx->pipelines[13];
    id<MTLComputePipelineState> convert = ctx->pipelines[9];
    const bool candidate_half_input = ctx->safe_half_input;
    const uint32_t candidate_index = ctx->safe_pipeline;
    const uint32_t candidate_threads = 32u * ctx->safe_simdgroups;
    const pm_shape &s = p->shape;
    require(p->device && p->queue && candidate && fallback && guard,
            "async prepare requires candidate, fallback and range-guard resources");
    require(s.k >= 1024 && s.k <= 65536 && s.k % 64 == 0 &&
            (s.r == 32 || s.r == 64 || s.r == 128) && s.k >= s.r &&
            s.rows[0] == 32 && s.rows[1] == 2 && s.rows[3] == 1 && s.rows[5] == 1 &&
            s.cols[0] == 1 && s.cols[1] == 64 && s.cols[3] == 1 && s.cols[5] == 1 &&
            s.h == 2 && s.w == 64,
            "async prepare shape is not eligible for the blocked tensor kernel");
    require(m_rows && n_rows && m_rows <= (1u << 24) && n_rows <= (1u << 24) &&
            m_rows % 64 == 0 && n_rows % 64 == 0,
            "async prepare dimensions must be bounded whole 64-row bands");
    const uint64_t a_bytes = uint64_t(m_rows) * s.k, b_bytes = uint64_t(n_rows) * s.k;
    id<MTLBuffer> source_a = mb(an), source_b = mb(bnt);
    require(source_a && source_b && source_a.device == p->device && source_b.device == p->device &&
            a_bytes <= source_a.length && b_bytes <= source_b.length &&
            a_bytes <= p->device.maxBufferLength && b_bytes <= p->device.maxBufferLength,
            "async source dimensions/device exceed buffer bounds");
    p->depth = depth; p->m_rows = m_rows; p->n_rows = n_rows;
    p->want_digests = (flags & 1u) != 0;
    memcpy(p->seed.data(), seed, 32);
    p->a = [p->device newBufferWithLength:a_bytes options:MTLResourceStorageModePrivate];
    p->bt = [p->device newBufferWithLength:b_bytes options:MTLResourceStorageModePrivate];
    p->dummy = [p->device newBufferWithLength:16 options:MTLResourceStorageModeShared];
    require(p->a && p->bt && p->dummy, "async immutable snapshot allocation failed");
    const auto began = Clock::now();
    id<MTLCommandBuffer> command = [p->queue commandBuffer];
    require(command != nil, "async prepare command allocation failed");
    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    require(blit != nil, "async snapshot blit encoder allocation failed");
    [blit copyFromBuffer:source_a sourceOffset:0 toBuffer:p->a destinationOffset:0 size:a_bytes];
    [blit copyFromBuffer:source_b sourceOffset:0 toBuffer:p->bt destinationOffset:0 size:b_bytes];
    [blit endEncoding];
    const bool eligible_k = s.k <= 4096 && a_bytes <= UINT32_MAX && b_bytes <= UINT32_MAX;
    id<MTLBuffer> flag = nil;
    if (eligible_k) {
      flag = [p->device newBufferWithLength:4 options:MTLResourceStorageModeShared];
      require(flag != nil, "async range-guard flag allocation failed");
      *static_cast<uint32_t *>(flag.contents) = 0;
      id<MTLComputeCommandEncoder> check = [command computeCommandEncoder];
      require(check != nil, "async range-guard encoder allocation failed");
      const uint32_t lengths[2] = {uint32_t(a_bytes), uint32_t(b_bytes)};
      const NSUInteger lanes = (MAX(a_bytes, b_bytes) + 3) / 4;
      const NSUInteger width = MIN(NSUInteger(256), guard.maxTotalThreadsPerThreadgroup);
      require(width > 0, "async range-guard pipeline has no legal threadgroup size");
      [check setComputePipelineState:guard];
      [check setBuffer:p->a offset:0 atIndex:0];
      [check setBuffer:p->bt offset:0 atIndex:1];
      [check setBuffer:flag offset:0 atIndex:2];
      [check setBytes:lengths length:8 atIndex:3];
      [check dispatchThreads:MTLSizeMake(lanes, 1, 1) threadsPerThreadgroup:MTLSizeMake(width, 1, 1)];
      [check endEncoding];
    }
    [command commit];
    require_completed(command);
    const bool safe = eligible_k && *static_cast<uint32_t *>(flag.contents) == 0;
    double preparation_gpu = gpu_seconds(command);
    if (safe && candidate_half_input) {
      require(convert && a_bytes % 4 == 0 && b_bytes % 4 == 0 &&
              a_bytes * 2 <= p->device.maxBufferLength && b_bytes * 2 <= p->device.maxBufferLength,
              "async half-input candidate cannot convert these snapshot buffers");
      id<MTLBuffer> half_a = [p->device newBufferWithLength:a_bytes * 2 options:MTLResourceStorageModePrivate];
      id<MTLBuffer> half_b = [p->device newBufferWithLength:b_bytes * 2 options:MTLResourceStorageModePrivate];
      require(half_a && half_b, "async private half snapshot allocation failed");
      id<MTLCommandBuffer> conversion = [p->queue commandBuffer];
      require(conversion != nil, "async half conversion command allocation failed");
      for (uint32_t side = 0; side < 2; ++side) {
        id<MTLBuffer> source = side ? p->bt : p->a;
        id<MTLBuffer> destination = side ? half_b : half_a;
        const uint32_t count = uint32_t(source.length / 4);
        id<MTLComputeCommandEncoder> enc = [conversion computeCommandEncoder];
        require(enc != nil, "async half conversion encoder allocation failed");
        [enc setComputePipelineState:convert];
        [enc setBuffer:source offset:0 atIndex:0];
        [enc setBuffer:destination offset:0 atIndex:1];
        [enc setBytes:&count length:4 atIndex:2];
        const NSUInteger width = MIN(NSUInteger(256), convert.maxTotalThreadsPerThreadgroup);
        require(width > 0, "async conversion pipeline has no legal threadgroup size");
        [enc dispatchThreads:MTLSizeMake(count, 1, 1) threadsPerThreadgroup:MTLSizeMake(width, 1, 1)];
        [enc endEncoding];
      }
      [conversion commit];
      require_completed(conversion);
      preparation_gpu += gpu_seconds(conversion);
      p->a = half_a; p->bt = half_b;
    }
    p->pipeline = safe ? candidate : fallback;
    p->pipeline_index = safe ? candidate_index : 10;
    p->threads = safe ? candidate_threads : 128;
    const char *layout_force = std::getenv("FUSION_METAL_LAYOUT_FALLBACK");
    if (p->pipeline_index == 15 && layout_force && *layout_force) {
      require(!std::strcmp(layout_force, "0") || !std::strcmp(layout_force, "1"),
              "FUSION_METAL_LAYOUT_FALLBACK must be 0 or 1");
      p->force_layout_fallback = !std::strcmp(layout_force, "1");
    }
    require(p->pipeline.staticThreadgroupMemoryLength <= p->device.maxThreadgroupMemoryLength &&
            p->threads <= p->pipeline.maxTotalThreadsPerThreadgroup,
            "async selected pipeline exceeds resource limits");
    p->stats.guard_fast = safe ? 1 : 0;
    p->stats.guard_fallback = safe ? 0 : 1;
    p->stats.preparation_wall_seconds = std::chrono::duration<double>(Clock::now() - began).count();
    p->stats.preparation_gpu_seconds = preparation_gpu;
    p->activity = [[NSProcessInfo processInfo]
        beginActivityWithOptions:(NSActivityUserInitiated | NSActivityLatencyCritical)
        reason:@"bounded asynchronous Pearl research grid"];
    p->handle = unique_id(); p->generation = unique_id();
    { std::lock_guard<std::mutex> lock(registry_mutex); registry.emplace(p->handle, p); }
    *handle = p->handle; *generation = p->generation;
    return 0;
  } catch (const std::exception &exception) { return error(err, errlen, exception); } }
}

int pm_async_submit(uint64_t handle, uint64_t generation, uint32_t band_lo,
                    uint32_t n_bands, const uint8_t *seed, const uint8_t *bound,
                    uint64_t *ticket, char *err, size_t errlen) {
  using namespace fusion_async_research;
  @autoreleasepool { try {
    require(ticket && seed && bound, "async submit requires identity/seed/target outputs");
    *ticket = 0;
    auto p = lookup(handle, generation);
    std::lock_guard<std::mutex> lock(p->mutex);
    require(!p->closing && !p->closed, "async grid is closing");
    require(memcmp(p->seed.data(), seed, 32) == 0 &&
            (!p->bound_set || memcmp(p->bound.data(), bound, 32) == 0),
            "async seed/target epoch mismatch; close and prepare a new grid");
    require(p->pending.size() < p->depth, "async queue is full");
    require(n_bands && band_lo < p->m_rows / 64 &&
            uint64_t(band_lo) + n_bands <= p->m_rows / 64 &&
            (!p->started || band_lo == p->next_band),
            "async region is out of bounds, duplicated, overlapping or noncontiguous");
    auto w = std::make_shared<Work>();
    w->ticket = unique_id(); w->band_lo = band_lo; w->n_bands = n_bands;
    const uint32_t n_cols = p->n_rows / 64;
    w->tiles = uint64_t(n_bands) * 32 * n_cols;
    require(w->tiles <= UINT32_MAX, "async region would overflow the GPU hit counter");
    w->hits = [p->device newBufferWithLength:kHitsBytes options:MTLResourceStorageModeShared];
    require(w->hits != nil, "async hits allocation failed");
    memset(w->hits.contents, 0, kHitsBytes);
    if (p->want_digests) {
      const uint64_t end_tile = (uint64_t(band_lo) + n_bands) * 32 * n_cols;
      const uint64_t allocation = end_tile * 32;
      require(end_tile <= UINT32_MAX && allocation <= p->device.maxBufferLength,
              "async digest region exceeds kernel index/buffer bounds");
      w->digest_offset = uint64_t(band_lo) * 32 * n_cols * 32;
      w->digest_bytes = w->tiles * 32;
      w->digests = [p->device newBufferWithLength:allocation options:MTLResourceStorageModeShared];
      require(w->digests != nil, "async digest allocation failed");
      memset(w->digests.contents, 0xa5, allocation);
    }
    w->command = [p->queue commandBuffer];
    require(w->command != nil, "async region command allocation failed");
    id<MTLComputeCommandEncoder> enc = [w->command computeCommandEncoder];
    require(enc != nil, "async region encoder allocation failed");
    const uint32_t pp[2] = {band_lo, n_cols};
    const PowParams parameters = {n_bands, n_cols, kHitsCapacity,
        (p->want_digests ? 1u : 0u) | (p->force_layout_fallback ? 8u : 0u)};
    [enc setComputePipelineState:p->pipeline];
    [enc setBuffer:p->a offset:0 atIndex:0];
    [enc setBuffer:p->bt offset:0 atIndex:1];
    [enc setBytes:pp length:8 atIndex:2];
    [enc setBytes:p->seed.data() length:32 atIndex:4];
    [enc setBytes:bound length:32 atIndex:5];
    [enc setBuffer:w->hits offset:0 atIndex:6];
    [enc setBytes:&parameters length:sizeof(parameters) atIndex:7];
    [enc setBuffer:(w->digests ? w->digests : p->dummy) offset:0 atIndex:8];
    // The layout specialization only writes counters when P.flags bit2 is set.
    // Async never exposes/reuses a synchronous context diagnostic buffer.
    [enc setBuffer:p->dummy offset:0 atIndex:9];
    [enc dispatchThreadgroups:MTLSizeMake(n_cols, n_bands, 1)
         threadsPerThreadgroup:MTLSizeMake(p->threads, 1, 1)];
    [enc endEncoding];
    w->submitted = Clock::now();
    // Register before commit so every committed command is owned by close.
    p->pending.emplace(w->ticket, w);
    memcpy(p->bound.data(), bound, 32); p->bound_set = true;
    p->started = true; p->next_band = band_lo + n_bands;
    ++p->stats.scheduled; p->stats.tiles_scheduled += w->tiles;
    [w->command commit];
    *ticket = w->ticket;
    return 0;
  } catch (const std::exception &exception) { return error(err, errlen, exception); } }
}

// Output digests are compact for this region, despite the kernel's global
// digest indexing. Capacity is bytes; pairs_capacity counts (row,col) pairs.
int pm_async_wait(uint64_t handle, uint64_t generation, uint64_t ticket,
                  uint32_t *pairs, uint32_t pairs_capacity,
                  uint8_t *digests, size_t digests_capacity, PMAsyncResult *result,
                  char *err, size_t errlen) {
  using namespace fusion_async_research;
  @autoreleasepool { try {
    require(result != nullptr, "async wait requires result storage");
    auto p = lookup(handle, generation);
    std::lock_guard<std::mutex> lock(p->mutex);
    require(!p->closing && !p->closed && !p->pending.empty(), "async grid has no available ticket");
    auto found = p->pending.find(ticket);
    require(found != p->pending.end() && found == p->pending.begin(),
            "invalid, consumed or out-of-order async ticket");
    auto w = found->second;
    const auto began = Clock::now();
    [w->command waitUntilCompleted];
    p->stats.wait_wall_seconds += std::chrono::duration<double>(Clock::now() - began).count();
    require_completed(w->command);
    const uint32_t total = *static_cast<const uint32_t *>(w->hits.contents);
    const uint32_t count = MIN(total, kHitsCapacity);
    require((count == 0 || pairs) && pairs_capacity >= count,
            "async wait hit output capacity too small (ticket remains valid)");
    require(!p->want_digests || (digests && digests_capacity >= w->digest_bytes),
            "async wait digest output capacity too small (ticket remains valid)");
    const uint64_t pair_bytes = uint64_t(count) * 8;
    const uint64_t digest_bytes = p->want_digests ? w->digest_bytes : 0;
    require(!output_overlap(pairs, pair_bytes, digests, digest_bytes) &&
            !output_overlap(pairs, pair_bytes, result, sizeof(*result)) &&
            !output_overlap(digests, digest_bytes, result, sizeof(*result)),
            "async wait output buffers must not alias (ticket remains valid)");
    if (count) memcpy(pairs, static_cast<const uint8_t *>(w->hits.contents) + 4, size_t(count) * 8);
    if (p->want_digests)
      memcpy(digests, static_cast<const uint8_t *>(w->digests.contents) + w->digest_offset, w->digest_bytes);
    *result = {ticket, generation, w->tiles, w->band_lo, w->n_bands, count, total,
               p->pipeline_index, p->threads,
               std::chrono::duration<double>(Clock::now() - w->submitted).count(), gpu_seconds(w->command)};
    account(*p, *w, true);
    p->pending.erase(found);
    return 0;
  } catch (const std::exception &exception) { return error(err, errlen, exception); } }
}

int pm_async_stats(uint64_t handle, uint64_t generation, PMAsyncStats *stats,
                   char *err, size_t errlen) {
  using namespace fusion_async_research;
  @autoreleasepool { try {
    require(stats != nullptr, "async stats requires output storage");
    auto p = lookup(handle, generation);
    std::lock_guard<std::mutex> lock(p->mutex);
    require(!p->closed, "async grid is closed");
    *stats = p->stats; return 0;
  } catch (const std::exception &exception) { return error(err, errlen, exception); } }
}

int pm_async_close(uint64_t handle, uint64_t generation, PMAsyncStats *stats,
                   char *err, size_t errlen) {
  using namespace fusion_async_research;
  @autoreleasepool { try {
    require(stats != nullptr, "async close requires final stats storage");
    auto p = lookup(handle, generation);
    bool failed = false;
    {
      std::lock_guard<std::mutex> lock(p->mutex);
      require(!p->closing && !p->closed, "async grid already closing or closed");
      p->closing = true;
      for (auto &item : p->pending) {
        const auto began = Clock::now();
        [item.second->command waitUntilCompleted];
        p->stats.wait_wall_seconds += std::chrono::duration<double>(Clock::now() - began).count();
        if (item.second->command.status != MTLCommandBufferStatusCompleted) failed = true;
        account(*p, *item.second, false);
      }
      p->pending.clear(); p->closed = true;
      *stats = p->stats;
    }
    { std::lock_guard<std::mutex> lock(registry_mutex); registry.erase(handle); }
    require(!failed, "async close drained and invalidated grid after a GPU command failure");
    return 0;
  } catch (const std::exception &exception) { return error(err, errlen, exception); } }
}
} // extern C
