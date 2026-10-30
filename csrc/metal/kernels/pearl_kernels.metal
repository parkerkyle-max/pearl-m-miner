// Pearl PoW Metal kernels.
//
// Consensus reference: zk-pow/src in pearl-research-labs/pearl (ISC), pinned
// in PINNED_PEARL_COMMIT.txt; NumPy restatement in pearl_metal_miner/reference.py.
// Every stage here is differentially tested against that reference — exact
// integers, no tolerances.
//
// The job shape arrives as function constants (ADR-0004/0006): the compiler
// folds k, r, h, w and both PeriodicPattern shapes into the code as literals.

#include <metal_stdlib>
#include <metal_simdgroup_matrix>
#if FUSION_METAL4
#include <metal_tensor>
#include <MetalPerformancePrimitives/MetalPerformancePrimitives.h>
#if FUSION_SAFE_HALF_INPUT
using FusionSafeOperand = half;
#else
using FusionSafeOperand = signed char;
#endif
#ifndef FUSION_SAFE_SIMDGROUPS
#define FUSION_SAFE_SIMDGROUPS 4
#endif
#if FUSION_SAFE_SIMDGROUPS != 2 && FUSION_SAFE_SIMDGROUPS != 4 && FUSION_SAFE_SIMDGROUPS != 8
#error FUSION_SAFE_SIMDGROUPS_must_be_2_4_or_8
#endif
#endif
using namespace metal;

// Per-dispatch eligibility check for the bounded full-K accumulator below.
// ABI: buffer 0 = signed int8 A, 1 = signed int8 B-transpose, 2 = one uint32
// flag, 3 = uint2(a_elements, b_elements). One thread checks up to four
// elements in each buffer; dispatch ceil(max(a_elements,b_elements)/4).
// The host must clear flag before every check, wait for completion, require
// flag == 0 and K <= 4096, and bind the same immutable input buffers to the
// subsequent sweep. An invalid byte only sets flag to 1; it never clears it.
// Kept outside FUSION_METAL4: this check also compiles under MSL 2.3.
kernel void range_guard64(device const signed char *an [[buffer(0)]],
                          device const signed char *bnt [[buffer(1)]],
                          device atomic_uint *flag [[buffer(2)]],
                          constant uint2 &lengths [[buffer(3)]],
                          uint tid [[thread_position_in_grid]]) {
  // Use a wide offset so padded dispatches cannot wrap uint32 multiplication.
  const ulong first = ulong(tid) * 4ul;
  bool invalid = false;
  for (uint lane = 0; lane < 4u; ++lane) {
    const ulong idx = first + lane;
    if (idx < ulong(lengths.x)) {
      const int value = int(an[idx]);
      invalid = invalid || value < -64 || value > 64;
    }
    if (idx < ulong(lengths.y)) {
      const int value = int(bnt[idx]);
      invalid = invalid || value < -64 || value > 64;
    }
  }
  if (invalid) atomic_store_explicit(flag, 1u, memory_order_relaxed);
}

constant uint FC_K [[function_constant(0)]]; // common dimension
constant uint FC_R [[function_constant(1)]]; // noise rank
constant uint FC_H [[function_constant(2)]]; // |rows_pattern|
constant uint FC_W [[function_constant(3)]]; // |cols_pattern|
constant uint FC_ROW_S0 [[function_constant(4)]];
constant uint FC_ROW_L0 [[function_constant(5)]];
constant uint FC_ROW_S1 [[function_constant(6)]];
constant uint FC_ROW_L1 [[function_constant(7)]];
constant uint FC_ROW_S2 [[function_constant(8)]];
constant uint FC_ROW_L2 [[function_constant(9)]];
constant uint FC_COL_S0 [[function_constant(10)]];
constant uint FC_COL_L0 [[function_constant(11)]];
constant uint FC_COL_S1 [[function_constant(12)]];
constant uint FC_COL_L1 [[function_constant(13)]];
constant uint FC_COL_S2 [[function_constant(14)]];
constant uint FC_COL_L2 [[function_constant(15)]];

// PeriodicPattern element p, in to_list order:
//   off(p) = (p % l0)·s0 + ((p / l0) % l1)·s1 + (p / (l0·l1))·s2
inline uint row_pattern_offset(uint p) {
  return (p % FC_ROW_L0) * FC_ROW_S0 + ((p / FC_ROW_L0) % FC_ROW_L1) * FC_ROW_S1 +
         (p / (FC_ROW_L0 * FC_ROW_L1)) * FC_ROW_S2;
}
inline uint col_pattern_offset(uint p) {
  return (p % FC_COL_L0) * FC_COL_S0 + ((p / FC_COL_L0) % FC_COL_L1) * FC_COL_S1 +
         (p / (FC_COL_L0 * FC_COL_L1)) * FC_COL_S2;
}

// ── Keyed BLAKE3, single 64-byte block ──────────────────────────────────────
// The only BLAKE3 the GPU ever needs: every message is exactly one block, so
// flags = CHUNK_START|CHUNK_END|ROOT|KEYED_HASH, counter 0, len 64.

constant uint B3_IV0 = 0x6A09E667u;
constant uint B3_IV1 = 0xBB67AE85u;
constant uint B3_IV2 = 0x3C6EF372u;
constant uint B3_IV3 = 0xA54FF53Au;
constant uint B3_FLAGS = 1u | 2u | 8u | 16u; // CHUNK_START|CHUNK_END|ROOT|KEYED_HASH

inline uint rotr32(uint x, uint n) { return (x >> n) | (x << (32u - n)); }

inline void b3_g(thread uint *st, uint a, uint b, uint c, uint d, uint mx, uint my) {
  st[a] = st[a] + st[b] + mx;
  st[d] = rotr32(st[d] ^ st[a], 16u);
  st[c] = st[c] + st[d];
  st[b] = rotr32(st[b] ^ st[c], 12u);
  st[a] = st[a] + st[b] + my;
  st[d] = rotr32(st[d] ^ st[a], 8u);
  st[c] = st[c] + st[d];
  st[b] = rotr32(st[b] ^ st[c], 7u);
}

inline void b3_round(thread uint *st, thread const uint *m) {
  b3_g(st, 0, 4, 8, 12, m[0], m[1]);
  b3_g(st, 1, 5, 9, 13, m[2], m[3]);
  b3_g(st, 2, 6, 10, 14, m[4], m[5]);
  b3_g(st, 3, 7, 11, 15, m[6], m[7]);
  b3_g(st, 0, 5, 10, 15, m[8], m[9]);
  b3_g(st, 1, 6, 11, 12, m[10], m[11]);
  b3_g(st, 2, 7, 8, 13, m[12], m[13]);
  b3_g(st, 3, 4, 9, 14, m[14], m[15]);
}

constant uchar B3_PERM[16] = {2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8};

// msg: 16 words (the 64-byte block, little-endian words); key: 8 words; out: 8 words.
inline void blake3_64_keyed(thread const uint *msg, thread const uint *key, thread uint *out) {
  uint st[16];
  for (int i = 0; i < 8; i++) st[i] = key[i];
  st[8] = B3_IV0;
  st[9] = B3_IV1;
  st[10] = B3_IV2;
  st[11] = B3_IV3;
  st[12] = 0u; // counter lo
  st[13] = 0u; // counter hi
  st[14] = 64u; // block length
  st[15] = B3_FLAGS;
  uint m[16], t[16];
  for (int i = 0; i < 16; i++) m[i] = msg[i];
  for (int r = 0; r < 7; r++) {
    if (r != 0) {
      for (int i = 0; i < 16; i++) t[i] = m[B3_PERM[i]];
      for (int i = 0; i < 16; i++) m[i] = t[i];
    }
    b3_round(st, m);
  }
  for (int i = 0; i < 8; i++) out[i] = st[i] ^ st[i + 8];
}

// ── blake3_64: batch primitive (test surface for the function above) ────────

kernel void blake3_64(device const uint *msgs [[buffer(0)]],  // count × 16 words
                      device const uint *keys [[buffer(1)]],  // count × 8 words
                      device uint *out [[buffer(2)]],         // count × 8 words
                      constant uint &count [[buffer(3)]],
                      uint gid [[thread_position_in_grid]]) {
  if (gid >= count) return;
  uint m[16], k[8], d[8];
  for (int i = 0; i < 16; i++) m[i] = msgs[gid * 16 + i];
  for (int i = 0; i < 8; i++) k[i] = keys[gid * 8 + i];
  blake3_64_keyed(m, k, d);
  for (int i = 0; i < 8; i++) out[gid * 8 + i] = d[i];
}

// ── Noise generation (pearl_noise.rs) ───────────────────────────────────────
// Message: eight i32 slots with slot `prepend` ← 1+index, then the 32-byte
// seed label. One digest yields 32 uniform bytes or 8 permutation pairs.

inline void noise_digest(uint index, uint prepend_slot, device const uint *seed,
                         device const uint *key, thread uint *d) {
  uint m[16] = {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u};
  m[prepend_slot] = 1u + index;
  for (int i = 0; i < 8; i++) m[8 + i] = seed[i];
  uint k[8];
  for (int i = 0; i < 8; i++) k[i] = key[i];
  blake3_64_keyed(m, k, d);
}

// One thread per 32-byte block of the uniform table: value = (byte & 63) − 32.
kernel void noise_uniform(device const uint *seed [[buffer(0)]],
                          device const uint *key [[buffer(1)]],
                          device char *out [[buffer(2)]],
                          constant uint &nblocks [[buffer(3)]],
                          uint gid [[thread_position_in_grid]]) {
  if (gid >= nblocks) return;
  uint d[8];
  noise_digest(gid, 0u, seed, key, d);
  device char *o = out + gid * 32u;
  for (int i = 0; i < 8; i++) {
    uint w = d[i];
    for (int b = 0; b < 4; b++) {
      o[i * 4 + b] = (char)((int)((w >> (8u * b)) & 63u) - 32);
    }
  }
}

// One thread per digest = 8 permutation pairs:
//   first = u & (R−1);  second = first ^ (1 + mulhi(R−1, u))
kernel void noise_pairs(device const uint *seed [[buffer(0)]],
                        device const uint *key [[buffer(1)]],
                        device uint2 *out [[buffer(2)]],
                        constant uint &ndigests [[buffer(3)]],
                        uint gid [[thread_position_in_grid]]) {
  if (gid >= ndigests) return;
  uint d[8];
  noise_digest(gid, 1u, seed, key, d);
  for (uint j = 0; j < 8; j++) {
    uint kk = gid * 8u + j;
    if (kk >= FC_K) return;
    uint u = d[j];
    uint first = u & (FC_R - 1u);
    uint second = first ^ (1u + mulhi(FC_R - 1u, u));
    out[kk] = uint2(first, second);
  }
}

// Noised operand: out[row,l] = base[row,l] + table[row,first(l)] − table[row,second(l)].
// The sum provably fits int8 (committed [−64,64], noise [−63,63] → [−127,127]).
kernel void noise_apply(device const char *base [[buffer(0)]],
                        device const char *table [[buffer(1)]],
                        device const uint2 *pairs [[buffer(2)]],
                        device char *out [[buffer(3)]],
                        constant uint &rows [[buffer(4)]],
                        uint2 gid [[thread_position_in_grid]]) {
  if (gid.x >= FC_K || gid.y >= rows) return;
  uint2 p = pairs[gid.x];
  int noise = (int)table[gid.y * FC_R + p.x] - (int)table[gid.y * FC_R + p.y];
  out[gid.y * FC_K + gid.x] = (char)((int)base[gid.y * FC_K + gid.x] + noise);
}

// ── The PoW sweep (jackpot/helper.rs) ───────────────────────────────────────
// One threadgroup per hash tile; one thread per tile element (h·w ≤ 256).
// Per R-chunk: cooperative stage of the h and w operand slices, cumulative
// int32 accumulate, XOR-reduce the tile, rotate-left-13-and-XOR into the
// transcript slot (chunk mod 16). At the end, keyed BLAKE3 and an inclusive
// little-endian comparison against the bound.

struct PowParams {
  uint n_row_bases;
  uint n_col_bases;
  uint hits_cap;
  uint flags; // bit0: write digests_out; bit1: write debug captures
};

kernel void pow_sweep(device const char *an [[buffer(0)]],
                      device const char *bnt [[buffer(1)]],
                      device const uint *row_bases [[buffer(2)]],
                      device const uint *col_bases [[buffer(3)]],
                      device const uint *a_seed [[buffer(4)]],
                      device const uchar *bound [[buffer(5)]],
                      device atomic_uint *hits [[buffer(6)]],
                      constant PowParams &P [[buffer(7)]],
                      device uchar *digests_out [[buffer(8)]],
                      device int *csums_out [[buffer(9)]],
                      device uint *transcripts_out [[buffer(10)]],
                      threadgroup uchar *shmem [[threadgroup(0)]],
                      uint2 tgid [[threadgroup_position_in_grid]],
                      uint tid [[thread_index_in_threadgroup]],
                      uint lane [[thread_index_in_simdgroup]],
                      uint sgid [[simdgroup_index_in_threadgroup]],
                      uint nsg [[simdgroups_per_threadgroup]]) {
  const uint nthreads = FC_H * FC_W;
  const uint u = tid / FC_W;
  const uint v = tid % FC_W;
  const uint base_r = row_bases[tgid.y];
  const uint base_c = col_bases[tgid.x];
  const uint tile_idx = tgid.y * P.n_col_bases + tgid.x;
  const uint nchunks = FC_K / FC_R; // k mod R tail contributes nothing

  threadgroup uchar *As = shmem;                       // FC_H·FC_R bytes
  threadgroup uchar *Bs = shmem + FC_H * FC_R;         // FC_W·FC_R bytes
  threadgroup uint *scratch =                          // per-simdgroup XOR
      (threadgroup uint *)(shmem + FC_H * FC_R + FC_W * FC_R);
  threadgroup uint *tr = scratch + 8;                  // 16-word transcript

  if (tid < 16u) tr[tid] = 0u;

  int acc = 0; // this thread's CUMULATIVE int32 tile element

  for (uint t = 0; t < nchunks; t++) {
    const uint klo = t * FC_R;
    // Stage the h rows and w cols of this chunk.
    for (uint i = tid; i < FC_H * FC_R; i += nthreads) {
      uint rr = i / FC_R, ll = i % FC_R;
      As[i] = as_type<uchar>(an[(ulong)(base_r + row_pattern_offset(rr)) * FC_K + klo + ll]);
    }
    for (uint i = tid; i < FC_W * FC_R; i += nthreads) {
      uint cc = i / FC_R, ll = i % FC_R;
      Bs[i] = as_type<uchar>(bnt[(ulong)(base_c + col_pattern_offset(cc)) * FC_K + klo + ll]);
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

    threadgroup const char *arow = (threadgroup const char *)(As + u * FC_R);
    threadgroup const char *brow = (threadgroup const char *)(Bs + v * FC_R);
    int s = 0;
    for (uint l = 0; l < FC_R; l += 4) {
      char4 a4 = *((threadgroup const char4 *)(arow + l));
      char4 b4 = *((threadgroup const char4 *)(brow + l));
      s += (int)a4.x * (int)b4.x + (int)a4.y * (int)b4.y + (int)a4.z * (int)b4.z +
           (int)a4.w * (int)b4.w;
    }
    acc += s;

    // XOR-reduce the cumulative tile (order-free: XOR commutes).
    uint xr = simd_xor(as_type<uint>(acc));
    if (lane == 0) scratch[sgid] = xr;
    threadgroup_barrier(mem_flags::mem_threadgroup);
    if (tid == 0) {
      uint x = 0u;
      for (uint i = 0; i < nsg; i++) x ^= scratch[i];
      uint slot = t % 16u;
      uint prev = tr[slot];
      tr[slot] = ((prev << 13u) | (prev >> 19u)) ^ x;
    }
    if (P.flags & 2u) {
      csums_out[((ulong)tile_idx * nchunks + t) * nthreads + tid] = acc;
      threadgroup_barrier(mem_flags::mem_threadgroup);
      if (tid == 0)
        for (uint i = 0; i < 16u; i++)
          transcripts_out[((ulong)tile_idx * nchunks + t) * 16u + i] = tr[i];
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }

  if (tid != 0) return;

  uint msg[16], key[8], d[8];
  for (int i = 0; i < 16; i++) msg[i] = tr[i];
  for (int i = 0; i < 8; i++) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);

  if (P.flags & 1u) {
    device uchar *o = digests_out + (ulong)tile_idx * 32u;
    for (int i = 0; i < 8; i++) {
      uint w = d[i];
      o[i * 4 + 0] = w & 0xFFu;
      o[i * 4 + 1] = (w >> 8) & 0xFFu;
      o[i * 4 + 2] = (w >> 16) & 0xFFu;
      o[i * 4 + 3] = (w >> 24) & 0xFFu;
    }
  }

  // Inclusive little-endian comparison: digest ≤ bound.
  bool win = true;
  for (int i = 31; i >= 0; i--) {
    uchar hb = (d[i / 4] >> (8 * (i % 4))) & 0xFFu;
    uchar bb = bound[i];
    if (hb != bb) {
      win = hb < bb;
      break;
    }
  }
  if (win) {
    uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1 + 2 * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2 + 2 * idx], base_c, memory_order_relaxed);
    }
  }
}

// ── pow_sweep_v2: blocked fast path ─────────────────────────────────────────
// Requirements (host-enforced): rows_pattern == [0, S] (FC_ROW_S0 = S,
// FC_ROW_L0 = 2, upper levels trivial), cols_pattern == [0..63] (FC_COL_S0 = 1,
// FC_COL_L0 = 64). One threadgroup sweeps a 2S×64 output block = S hash tiles
// sharing one staged copy of the operands; each thread owns a 2×8 sub-tile of
// exactly one hash tile. Bit-exactness is unchanged — same cumulative int32,
// same fold, same digest; only the work decomposition differs.

kernel void pow_sweep_v2(device const char *an [[buffer(0)]],
                         device const char *bnt [[buffer(1)]],
                         device const uint *params2 [[buffer(2)]], // band_lo, n_col_bases
                         device const uint *a_seed [[buffer(4)]],
                         device const uchar *bound [[buffer(5)]],
                         device atomic_uint *hits [[buffer(6)]],
                         constant PowParams &P [[buffer(7)]],
                         device uchar *digests_out [[buffer(8)]],
                         uint2 tgid [[threadgroup_position_in_grid]],
                         uint tid [[thread_index_in_threadgroup]]) {
  const uint S = FC_ROW_S0;          // 32: bases per band; tile rows {o, o+S}
  const uint W = FC_COL_L0;          // 64: contiguous cols per tile
  const uint band = params2[0] + tgid.y;
  const uint base_c = tgid.x * W;
  const uint row0 = band * 2 * S;    // first row of this band
  const uint nchunks = FC_K / FC_R;

  // Only Bᵀ is staged: each Bs row is read by all S tiles' threads, while an
  // A row is shared by just 8 threads — the device cache covers that, and the
  // smaller footprint (10 KB vs 18 KB) lets 3 threadgroups reside per core.
  threadgroup uchar Bs[64 * 128];         // W × R
  threadgroup uint tr[32 * 16];           // S transcripts

  const uint o = tid / 8;            // this thread's tile (row base offset)
  const uint j0 = (tid % 8) * 8;     // first of its 8 columns

  for (uint i = tid; i < S * 16u; i += S * 8u) tr[i] = 0u;

  // This thread's cumulative int32 tile elements. These can exceed 2²⁴ and
  // must stay integer; only the bounded per-chunk partials use fp32 (below).
  int acc[2][8];
  for (int a = 0; a < 2; a++)
    for (int b = 0; b < 8; b++) acc[a][b] = 0;

  const uint nthreads = S * 8u;      // 256
  for (uint t = 0; t < nchunks; t++) {
    const uint klo = t * FC_R;
    // Cooperative stage of Bᵀ as u32 words (K and R are multiples of 4).
    device const uint *bnt32 = (device const uint *)bnt;
    threadgroup uint *Bs32 = (threadgroup uint *)Bs;
    const uint bwords = W * FC_R / 4;
    for (uint i = tid; i < bwords; i += nthreads) {
      uint cc = i / (FC_R / 4), lw = i % (FC_R / 4);
      Bs32[i] = bnt32[(ulong)(base_c + cc) * (FC_K / 4) + klo / 4 + lw];
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

    device const char4 *a0 =
        (device const char4 *)(an + (ulong)(row0 + o) * FC_K + klo);
    device const char4 *a1 =
        (device const char4 *)(an + (ulong)(row0 + o + S) * FC_K + klo);
    // Chunk partials in scalar fp32 FMA chains. Exact: every partial is an
    // integer ≤ R·127² = 2,064,512 < 2²⁴ and fast-math is off (IEEE). The
    // cumulative tile value (up to 66M > 2²⁴) lives only in int32 `acc`.
    float facc[2][8];
    for (int a = 0; a < 2; a++)
      for (int b = 0; b < 8; b++) facc[a][b] = 0.0f;
    for (uint l4 = 0; l4 < FC_R / 4; l4++) {
      float4 av0 = float4(a0[l4]);
      float4 av1 = float4(a1[l4]);
      for (uint b = 0; b < 8; b++) {
        float4 bv = float4(((threadgroup const char4 *)(Bs + (j0 + b) * FC_R))[l4]);
        facc[0][b] = fma(av0.x, bv.x, facc[0][b]);
        facc[0][b] = fma(av0.y, bv.y, facc[0][b]);
        facc[0][b] = fma(av0.z, bv.z, facc[0][b]);
        facc[0][b] = fma(av0.w, bv.w, facc[0][b]);
        facc[1][b] = fma(av1.x, bv.x, facc[1][b]);
        facc[1][b] = fma(av1.y, bv.y, facc[1][b]);
        facc[1][b] = fma(av1.z, bv.z, facc[1][b]);
        facc[1][b] = fma(av1.w, bv.w, facc[1][b]);
      }
    }
    for (int a = 0; a < 2; a++)
      for (int b = 0; b < 8; b++) acc[a][b] += (int)facc[a][b];

    uint my = 0u;
    for (int a = 0; a < 2; a++)
      for (int b = 0; b < 8; b++) my ^= as_type<uint>(acc[a][b]);
    // 8 threads per tile, consecutive lanes: butterfly XOR within the team.
    my ^= simd_shuffle_xor(my, 4u);
    my ^= simd_shuffle_xor(my, 2u);
    my ^= simd_shuffle_xor(my, 1u);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    if ((tid & 7u) == 0u) {
      uint slot = t % 16u;
      uint prev = tr[o * 16u + slot];
      tr[o * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ my;
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }

  if (tid >= S) return;
  uint msg[16], key[8], d[8];
  for (int i = 0; i < 16; i++) msg[i] = tr[tid * 16 + i];
  for (int i = 0; i < 8; i++) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);

  const uint base_r = row0 + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * S + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (int i = 0; i < 8; i++) {
      uint w = d[i];
      dst[i * 4 + 0] = w & 0xFFu;
      dst[i * 4 + 1] = (w >> 8) & 0xFFu;
      dst[i * 4 + 2] = (w >> 16) & 0xFFu;
      dst[i * 4 + 3] = (w >> 24) & 0xFFu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; i--) {
    uchar hb = (d[i / 4] >> (8 * (i % 4))) & 0xFFu;
    uchar bb = bound[i];
    if (hb != bb) {
      win = hb < bb;
      break;
    }
  }
  if (win) {
    uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1 + 2 * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2 + 2 * idx], base_c, memory_order_relaxed);
    }
  }
}

// Experimental v3: register transcripts remove one barrier per rank block.
// No consensus, tile layout, work counting, or difficulty changes.
kernel void pow_sweep_v3(device const char *an [[buffer(0)]],
                         device const char *bnt [[buffer(1)]],
                         device const uint *params2 [[buffer(2)]], // band_lo, n_col_bases
                         device const uint *a_seed [[buffer(4)]],
                         device const uchar *bound [[buffer(5)]],
                         device atomic_uint *hits [[buffer(6)]],
                         constant PowParams &P [[buffer(7)]],
                         device uchar *digests_out [[buffer(8)]],
                         uint2 tgid [[threadgroup_position_in_grid]],
                         uint tid [[thread_index_in_threadgroup]]) {
  const uint S = FC_ROW_S0;          // 32: bases per band; tile rows {o, o+S}
  const uint W = FC_COL_L0;          // 64: contiguous cols per tile
  const uint band = params2[0] + tgid.y;
  const uint base_c = tgid.x * W;
  const uint row0 = band * 2 * S;    // first row of this band
  const uint nchunks = FC_K / FC_R;

  // Only Bᵀ is staged: each Bs row is read by all S tiles' threads, while an
  // A row is shared by just 8 threads — the device cache covers that, and the
  // smaller footprint (10 KB vs 18 KB) lets 3 threadgroups reside per core.
  threadgroup uchar Bs[64 * 128];         // W × R
  threadgroup uint tr[32 * 16];           // S transcripts

  const uint o = tid / 8;            // this thread's tile (row base offset)
  const uint j0 = (tid % 8) * 8;     // first of its 8 columns

  uint local_tr[16];
  for (uint i = 0; i < 16; ++i) local_tr[i] = 0u;

  // This thread's cumulative int32 tile elements. These can exceed 2²⁴ and
  // must stay integer; only the bounded per-chunk partials use fp32 (below).
  int acc[2][8];
  for (int a = 0; a < 2; a++)
    for (int b = 0; b < 8; b++) acc[a][b] = 0;

  const uint nthreads = S * 8u;      // 256
  for (uint t = 0; t < nchunks; t++) {
    const uint klo = t * FC_R;
    // Cooperative stage of Bᵀ as u32 words (K and R are multiples of 4).
    device const uint *bnt32 = (device const uint *)bnt;
    threadgroup uint *Bs32 = (threadgroup uint *)Bs;
    const uint bwords = W * FC_R / 4;
    for (uint i = tid; i < bwords; i += nthreads) {
      uint cc = i / (FC_R / 4), lw = i % (FC_R / 4);
      Bs32[i] = bnt32[(ulong)(base_c + cc) * (FC_K / 4) + klo / 4 + lw];
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

    device const char4 *a0 =
        (device const char4 *)(an + (ulong)(row0 + o) * FC_K + klo);
    device const char4 *a1 =
        (device const char4 *)(an + (ulong)(row0 + o + S) * FC_K + klo);
    // Chunk partials in scalar fp32 FMA chains. Exact: every partial is an
    // integer ≤ R·127² = 2,064,512 < 2²⁴ and fast-math is off (IEEE). The
    // cumulative tile value (up to 66M > 2²⁴) lives only in int32 `acc`.
    float facc[2][8];
    for (int a = 0; a < 2; a++)
      for (int b = 0; b < 8; b++) facc[a][b] = 0.0f;
    for (uint l4 = 0; l4 < FC_R / 4; l4++) {
      float4 av0 = float4(a0[l4]);
      float4 av1 = float4(a1[l4]);
      for (uint b = 0; b < 8; b++) {
        float4 bv = float4(((threadgroup const char4 *)(Bs + (j0 + b) * FC_R))[l4]);
        facc[0][b] = fma(av0.x, bv.x, facc[0][b]);
        facc[0][b] = fma(av0.y, bv.y, facc[0][b]);
        facc[0][b] = fma(av0.z, bv.z, facc[0][b]);
        facc[0][b] = fma(av0.w, bv.w, facc[0][b]);
        facc[1][b] = fma(av1.x, bv.x, facc[1][b]);
        facc[1][b] = fma(av1.y, bv.y, facc[1][b]);
        facc[1][b] = fma(av1.z, bv.z, facc[1][b]);
        facc[1][b] = fma(av1.w, bv.w, facc[1][b]);
      }
    }
    for (int a = 0; a < 2; a++)
      for (int b = 0; b < 8; b++) acc[a][b] += (int)facc[a][b];

    uint my = 0u;
    for (int a = 0; a < 2; a++)
      for (int b = 0; b < 8; b++) my ^= as_type<uint>(acc[a][b]);
    // 8 threads per tile, consecutive lanes: butterfly XOR within the team.
    my ^= simd_shuffle_xor(my, 4u);
    my ^= simd_shuffle_xor(my, 2u);
    my ^= simd_shuffle_xor(my, 1u);
    // All readers finish this Bs chunk before the next cooperative overwrite.
    threadgroup_barrier(mem_flags::mem_threadgroup);
    if ((tid & 7u) == 0u) {
      uint slot = t % 16u;
      uint prev = local_tr[slot];
      local_tr[slot] = ((prev << 13u) | (prev >> 19u)) ^ my;
    }
  }
  // Preserve a full SIMD-group for final BLAKE3; transpose only once per sweep.
  if ((tid & 7u) == 0u)
    for (uint i = 0; i < 16; ++i) tr[o * 16u + i] = local_tr[i];
  threadgroup_barrier(mem_flags::mem_threadgroup);
  if (tid >= S) return;
  uint msg[16], key[8], d[8];
  for (int i = 0; i < 16; i++) msg[i] = tr[tid * 16 + i];
  for (int i = 0; i < 8; i++) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);

  const uint base_r = row0 + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * S + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (int i = 0; i < 8; i++) {
      uint w = d[i];
      dst[i * 4 + 0] = w & 0xFFu;
      dst[i * 4 + 1] = (w >> 8) & 0xFFu;
      dst[i * 4 + 2] = (w >> 16) & 0xFFu;
      dst[i * 4 + 3] = (w >> 24) & 0xFFu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; i--) {
    uchar hb = (d[i / 4] >> (8 * (i % 4))) & 0xFFu;
    uchar bb = bound[i];
    if (hb != bb) {
      win = hb < bb;
      break;
    }
  }
  if (win) {
    uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1 + 2 * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2 + 2 * idx], base_c, memory_order_relaxed);
    }
  }
}

// Experimental public SIMD-group matrix implementation.
// Each group computes four existing 2x64 hash tiles (8x64 output values),
// preserving exactly the same digest layout as v2. Matrix fragments are
// stored through the documented API: no assumed lane/register mapping.
// int8 operands are exactly representable in half; each rank-block sum is
// accumulated in float and is bounded by 128*127^2 < 2^24. The cumulative
// values are held in int32 between rank blocks, retaining bit exactness.
kernel void pow_sweep_simdgroup(device const char *an [[buffer(0)]],
                              device const char *bnt [[buffer(1)]],
                              device const uint *params2 [[buffer(2)]],
                              device const uint *a_seed [[buffer(4)]],
                              device const uchar *bound [[buffer(5)]],
                              device atomic_uint *hits [[buffer(6)]],
                              constant PowParams &P [[buffer(7)]],
                              device uchar *digests_out [[buffer(8)]],
                              uint2 tgid [[threadgroup_position_in_grid]],
                              uint tid [[thread_index_in_threadgroup]],
                              uint lane [[thread_index_in_simdgroup]],
                              uint sg [[simdgroup_index_in_threadgroup]]) {
  const uint band = params2[0] + tgid.y / 8u;
  const uint group_o = (tgid.y % 8u) * 4u;
  const uint row0 = band * 64u;
  const uint base_c = tgid.x * 64u;
  const uint nchunks = FC_K / FC_R;
  threadgroup half As[8 * 128];
  threadgroup half Bs[64 * 128];
  threadgroup float Cs[8 * 64];
  threadgroup uint tr[4 * 16];
  if (tid < 64u) tr[tid] = 0;
  int acc0 = 0, acc1 = 0, acc2 = 0, acc3 = 0;
  const uint col_pair = lane * 2u;
  for (uint t = 0; t < nchunks; ++t) {
    const uint klo = t * FC_R;
    for (uint i = tid; i < 8u * FC_R; i += 128u) {
      const uint r = i / FC_R, l = i % FC_R;
      const uint physical_r = row0 + group_o + (r < 4u ? r : r + 28u);
      As[i] = half(an[(ulong)physical_r * FC_K + klo + l]);
    }
    for (uint i = tid; i < 64u * FC_R; i += 128u) {
      const uint c = i / FC_R, l = i % FC_R;
      Bs[i] = half(bnt[(ulong)(base_c + c) * FC_K + klo + l]);
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    simdgroup_float8x8 c0 = simdgroup_float8x8(0.0f);
    simdgroup_float8x8 c1 = simdgroup_float8x8(0.0f);
    for (uint l = 0; l < FC_R; l += 8u) {
      simdgroup_half8x8 a, b0, b1;
      simdgroup_load(a, As + l, FC_R);
      simdgroup_load(b0, Bs + (sg * 16u) * FC_R + l, FC_R, ulong2(0), true);
      simdgroup_load(b1, Bs + (sg * 16u + 8u) * FC_R + l, FC_R, ulong2(0), true);
      simdgroup_multiply_accumulate(c0, a, b0, c0);
      simdgroup_multiply_accumulate(c1, a, b1, c1);
    }
    simdgroup_store(c0, Cs + sg * 16u, 64u);
    simdgroup_store(c1, Cs + sg * 16u + 8u, 64u);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    // Each SIMD group now owns one complete hash tile (two rows, 64 cols).
    acc0 += int(Cs[sg * 64u + col_pair]);
    acc1 += int(Cs[sg * 64u + col_pair + 1u]);
    acc2 += int(Cs[(sg + 4u) * 64u + col_pair]);
    acc3 += int(Cs[(sg + 4u) * 64u + col_pair + 1u]);
    uint folded = simd_xor(as_type<uint>(acc0) ^ as_type<uint>(acc1) ^
                           as_type<uint>(acc2) ^ as_type<uint>(acc3));
    if (lane == 0u) {
      const uint slot = t % 16u;
      const uint prev = tr[sg * 16u + slot];
      tr[sg * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ folded;
    }
    // The next staging barrier fences these Cs reads and transcript writes;
    // the next staging writes touch only As/Bs, no longer read after MMA.
  }
  threadgroup_barrier(mem_flags::mem_threadgroup);
  if (tid >= 4u) return;
  uint msg[16], key[8], d[8];
  for (uint i = 0; i < 16u; ++i) msg[i] = tr[tid * 16u + i];
  for (uint i = 0; i < 8u; ++i) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);
  const uint base_r = row0 + group_o + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * 32u + group_o + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (uint i = 0; i < 8u; ++i) {
      const uint word = d[i];
      dst[4u * i] = word & 0xffu;
      dst[4u * i + 1u] = (word >> 8u) & 0xffu;
      dst[4u * i + 2u] = (word >> 16u) & 0xffu;
      dst[4u * i + 3u] = (word >> 24u) & 0xffu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; --i) {
    const uchar h = (d[i / 4] >> (8u * (i % 4))) & 0xffu;
    if (h != bound[i]) { win = h < bound[i]; break; }
  }
  if (win) {
    const uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1u + 2u * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2u + 2u * idx], base_c, memory_order_relaxed);
    }
  }
}

kernel void convert_half4(device const char4 *input [[buffer(0)]],
                          device half4 *output [[buffer(1)]],
                          constant uint &count [[buffer(2)]],
                          uint tid [[thread_position_in_grid]]) {
  if (tid < count) output[tid] = half4(input[tid]);
}

// Fourth candidate: direct device half operands and a 32x64 output block.
// Sixteen existing 2x64 hash tiles share each group, four times the row reuse
// of pow_sweep_simdgroup. No per-rank input staging or int8 conversions;
// only the exact per-rank results cross threadgroup memory (9 KiB total).
// Inputs are refreshed by the host for every call, preserving shared-buffer
// mutation semantics. This conservative conversion cost is included in timing.
kernel void pow_sweep_simdgroup_device(device const half *an [[buffer(0)]],
                                     device const half *bnt [[buffer(1)]],
                                     device const uint *params2 [[buffer(2)]],
                                     device const uint *a_seed [[buffer(4)]],
                                     device const uchar *bound [[buffer(5)]],
                                     device atomic_uint *hits [[buffer(6)]],
                                     constant PowParams &P [[buffer(7)]],
                                     device uchar *digests_out [[buffer(8)]],
                                     uint2 tgid [[threadgroup_position_in_grid]],
                                     uint tid [[thread_index_in_threadgroup]],
                                     uint sg [[simdgroup_index_in_threadgroup]]) {
  const uint band = params2[0] + tgid.y / 2u;
  const uint group_o = (tgid.y % 2u) * 16u;
  const uint row0 = band * 64u;
  const uint base_c = tgid.x * 64u;
  const uint nchunks = FC_K / FC_R;
  const uint physical_r = row0 + group_o + sg * 8u + (sg >= 2u ? 16u : 0u);
  const uint o = tid / 8u;
  const uint j0 = (tid % 8u) * 8u;
  threadgroup float Cs[32 * 64];
  threadgroup uint tr[16 * 16];
  for (uint i = tid; i < 256u; i += 128u) tr[i] = 0;
  int acc[2][8];
  for (uint a = 0; a < 2u; ++a)
    for (uint b = 0; b < 8u; ++b) acc[a][b] = 0;
  for (uint t = 0; t < nchunks; ++t) {
    simdgroup_float8x8 c[8];
    for (uint q = 0; q < 8u; ++q) c[q] = simdgroup_float8x8(0.0f);
    const uint klo = t * FC_R;
    for (uint l = 0; l < FC_R; l += 8u) {
      simdgroup_half8x8 a;
      simdgroup_load(a, an + (ulong)physical_r * FC_K + klo + l, FC_K);
      for (uint q = 0; q < 8u; ++q) {
        simdgroup_half8x8 b;
        simdgroup_load(b, bnt + (ulong)(base_c + q * 8u) * FC_K + klo + l,
                      FC_K, ulong2(0), true);
        simdgroup_multiply_accumulate(c[q], a, b, c[q]);
      }
    }
    for (uint q = 0; q < 8u; ++q)
      simdgroup_store(c[q], Cs + (sg * 8u) * 64u + q * 8u, 64u);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    uint folded = 0;
    for (uint b = 0; b < 8u; ++b) {
      acc[0][b] += int(Cs[o * 64u + j0 + b]);
      acc[1][b] += int(Cs[(o + 16u) * 64u + j0 + b]);
      folded ^= as_type<uint>(acc[0][b]) ^ as_type<uint>(acc[1][b]);
    }
    folded ^= simd_shuffle_xor(folded, 4u);
    folded ^= simd_shuffle_xor(folded, 2u);
    folded ^= simd_shuffle_xor(folded, 1u);
    if ((tid & 7u) == 0u) {
      const uint slot = t % 16u;
      const uint prev = tr[o * 16u + slot];
      tr[o * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ folded;
    }
    // Cs cannot be overwritten until every output owner consumed this block.
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }
  if (tid >= 16u) return;
  uint msg[16], key[8], d[8];
  for (uint i = 0; i < 16u; ++i) msg[i] = tr[tid * 16u + i];
  for (uint i = 0; i < 8u; ++i) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);
  const uint base_r = row0 + group_o + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * 32u + group_o + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (uint i = 0; i < 8u; ++i) {
      const uint word = d[i];
      dst[4u * i] = word & 0xffu;
      dst[4u * i + 1u] = (word >> 8u) & 0xffu;
      dst[4u * i + 2u] = (word >> 16u) & 0xffu;
      dst[4u * i + 3u] = (word >> 24u) & 0xffu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; --i) {
    const uchar h = (d[i / 4] >> (8u * (i % 4))) & 0xffu;
    if (h != bound[i]) { win = h < bound[i]; break; }
  }
  if (win) {
    const uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1u + 2u * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2u + 2u * idx], base_c, memory_order_relaxed);
    }
  }
}

#if FUSION_METAL4
// Fifth candidate: public Metal 4 int8 matmul, with the cumulative int32
// matrix retained in a cooperative tensor across every rank boundary.
// Do NOT use matmul's multiply_accumulate mode for an unrestricted full-K
// sum: target testing found incorrect high-odd results beyond 2^24. Each rank
// product is exact; explicit int32 additions below preserve the full sum.
// A 64x64 output block is exactly 32 existing 2x64 PRL tiles, so the work
// count, row pairing, transcript, digest and target are unchanged.
// The cooperative layout is opaque: store to documented row-major shared
// tensor storage before folding. Never infer undocumented lane ownership.
kernel void pow_sweep_tensor(device signed char *an [[buffer(0)]],
                            device signed char *bnt [[buffer(1)]],
                            device const uint *params2 [[buffer(2)]],
                            device const uint *a_seed [[buffer(4)]],
                            device const uchar *bound [[buffer(5)]],
                            device atomic_uint *hits [[buffer(6)]],
                            constant PowParams &P [[buffer(7)]],
                            device uchar *digests_out [[buffer(8)]],
                            uint2 tgid [[threadgroup_position_in_grid]],
                            uint tid [[thread_index_in_threadgroup]]) {
  using namespace mpp::tensor_ops;
  constexpr int TM = 64, TN = 64, TK = FUSION_RANK;
  using Operand = tensor<device signed char, extents<int, TK, TM>, tensor_inline>;
  constexpr auto descriptor = matmul2d_descriptor(
      TM, TN, TK, false, true, false,
      matmul2d_descriptor::mode::multiply);
  matmul2d<descriptor, execution_simdgroups<4>> operation;
  auto partial = operation.get_destination_cooperative_tensor<
      Operand, Operand, int>();
  auto accumulator = operation.get_destination_cooperative_tensor<
      Operand, Operand, int>();
  for (uint i = 0; i < accumulator.get_capacity(); ++i)
    if (accumulator.is_valid_element(i)) accumulator[i] = 0;

  const uint band = params2[0] + tgid.y;
  const uint row0 = band * 64u;
  const uint base_c = tgid.x * 64u;
  const uint o = tid / 4u;
  const uint j0 = (tid % 4u) * 16u;
  const uint nchunks = FC_K / FC_R;
  threadgroup int Cs[64 * 64];
  threadgroup uint tr[32 * 16];
  tensor<threadgroup int, extents<int, TN, TM>, tensor_inline>
      destination(Cs, extents<int, TN, TM>{}, array<int, 2>{1, TN});
  for (uint i = tid; i < 512u; i += 128u) tr[i] = 0;

  for (uint t = 0; t < nchunks; ++t) {
    const uint klo = t * FC_R;
    Operand a(an + (ulong)row0 * FC_K + klo,
              extents<int, TK, TM>{}, array<int, 2>{1, int(FC_K)});
    Operand bt(bnt + (ulong)base_c * FC_K + klo,
               extents<int, TK, TN>{}, array<int, 2>{1, int(FC_K)});
    operation.run(a, bt, partial);
    for (uint i = 0; i < accumulator.get_capacity(); ++i)
      if (accumulator.is_valid_element(i)) accumulator[i] += partial[i];
    accumulator.store(destination);
    threadgroup_barrier(mem_flags::mem_threadgroup);

    uint folded = 0;
    for (uint b = 0; b < 16u; ++b)
      folded ^= as_type<uint>(Cs[o * 64u + j0 + b]) ^
                as_type<uint>(Cs[(o + 32u) * 64u + j0 + b]);
    folded ^= simd_shuffle_xor(folded, 2u);
    folded ^= simd_shuffle_xor(folded, 1u);
    if ((tid & 3u) == 0u) {
      const uint slot = t % 16u;
      const uint prev = tr[o * 16u + slot];
      tr[o * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ folded;
    }
    // Protect the shared output from the next rank's cooperative store.
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }
  if (tid >= 32u) return;
  uint msg[16], key[8], d[8];
  for (uint i = 0; i < 16u; ++i) msg[i] = tr[tid * 16u + i];
  for (uint i = 0; i < 8u; ++i) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);
  const uint base_r = row0 + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * 32u + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (uint i = 0; i < 8u; ++i) {
      const uint word = d[i];
      dst[4u * i] = word & 0xffu;
      dst[4u * i + 1u] = (word >> 8u) & 0xffu;
      dst[4u * i + 2u] = (word >> 16u) & 0xffu;
      dst[4u * i + 3u] = (word >> 24u) & 0xffu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; --i) {
    const uchar h = (d[i / 4] >> (8u * (i % 4))) & 0xffu;
    if (h != bound[i]) { win = h < bound[i]; break; }
  }
  if (win) {
    const uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1u + 2u * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2u + 2u * idx], base_c, memory_order_relaxed);
    }
  }
}

// Bounded fast candidate: identical layout, rank-boundary transcript and
// output ABI to pow_sweep_tensor, but uses full-K multiply_accumulate.
// Preconditions are enforced by the host before EACH dispatch: K <= 4096,
// range_guard64 passed on the exact immutable input buffers, all elements
// in [-64,64], and all the original tensor shape restrictions hold. Then
// any subset sum of integer products has magnitude <= 4096*64*64 == 2^24.
// Target precision probes cover this inclusive boundary. Do not use this
// entry point for unrestricted int8 inputs: use pow_sweep_tensor instead.
kernel void pow_sweep_tensor_safe_accum(device FusionSafeOperand *an [[buffer(0)]],
                            device FusionSafeOperand *bnt [[buffer(1)]],
                            device const uint *params2 [[buffer(2)]],
                            device const uint *a_seed [[buffer(4)]],
                            device const uchar *bound [[buffer(5)]],
                            device atomic_uint *hits [[buffer(6)]],
                            constant PowParams &P [[buffer(7)]],
                            device uchar *digests_out [[buffer(8)]],
                            uint2 tgid [[threadgroup_position_in_grid]],
                            uint tid [[thread_index_in_threadgroup]]) {
  using namespace mpp::tensor_ops;
#if FUSION_SAFE_FLOAT_ACCUM
  using AccumScalar = float;
#else
  using AccumScalar = int;
#endif
  constexpr uint SAFE_THREADS = 32u * FUSION_SAFE_SIMDGROUPS;
  constexpr int TM = 64, TN = 64, TK = FUSION_RANK;
  using Operand = tensor<device FusionSafeOperand, extents<int, TK, TM>, tensor_inline>;
  constexpr auto descriptor = matmul2d_descriptor(
      TM, TN, TK, false, true, false,
      matmul2d_descriptor::mode::multiply_accumulate);
  matmul2d<descriptor, execution_simdgroups<FUSION_SAFE_SIMDGROUPS>> operation;
  auto accumulator = operation.get_destination_cooperative_tensor<
      Operand, Operand, AccumScalar>();
  for (uint i = 0; i < accumulator.get_capacity(); ++i)
    if (accumulator.is_valid_element(i)) accumulator[i] = 0;

  const uint band = params2[0] + tgid.y;
  const uint row0 = band * 64u;
  const uint base_c = tgid.x * 64u;
  const uint nchunks = FC_K / FC_R;
  threadgroup AccumScalar Cs[64 * 64];
  threadgroup uint tr[32 * 16];
  tensor<threadgroup AccumScalar, extents<int, TN, TM>, tensor_inline>
      destination(Cs, extents<int, TN, TM>{}, array<int, 2>{1, TN});
  for (uint i = tid; i < 512u; i += SAFE_THREADS) tr[i] = 0;

  for (uint t = 0; t < nchunks; ++t) {
    const uint klo = t * FC_R;
    Operand a(an + (ulong)row0 * FC_K + klo,
              extents<int, TK, TM>{}, array<int, 2>{1, int(FC_K)});
    Operand bt(bnt + (ulong)base_c * FC_K + klo,
               extents<int, TK, TN>{}, array<int, 2>{1, int(FC_K)});
    operation.run(a, bt, accumulator);
    accumulator.store(destination);
    threadgroup_barrier(mem_flags::mem_threadgroup);

    // Logical lanes preserve the original four-lane row-pair reduction.
    // SG2 executes two full-simdgroup iterations; SG8 leaves four whole
    // simdgroups idle here. No shuffle crosses an inactive partial group.
    for (uint logical = tid; logical < 128u; logical += SAFE_THREADS) {
      const uint o = logical / 4u;
      const uint j0 = (logical % 4u) * 16u;
      uint folded = 0;
      for (uint b = 0; b < 16u; ++b)
        folded ^= as_type<uint>(int(Cs[o * 64u + j0 + b])) ^
                  as_type<uint>(int(Cs[(o + 32u) * 64u + j0 + b]));
      folded ^= simd_shuffle_xor(folded, 2u);
      folded ^= simd_shuffle_xor(folded, 1u);
      if ((logical & 3u) == 0u) {
        const uint slot = t % 16u;
        const uint prev = tr[o * 16u + slot];
        tr[o * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ folded;
      }
    }
    // Protect the shared output from the next rank's cooperative store.
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }
  if (tid >= 32u) return;
  uint msg[16], key[8], d[8];
  for (uint i = 0; i < 16u; ++i) msg[i] = tr[tid * 16u + i];
  for (uint i = 0; i < 8u; ++i) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);
  const uint base_r = row0 + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * 32u + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (uint i = 0; i < 8u; ++i) {
      const uint word = d[i];
      dst[4u * i] = word & 0xffu;
      dst[4u * i + 1u] = (word >> 8u) & 0xffu;
      dst[4u * i + 2u] = (word >> 16u) & 0xffu;
      dst[4u * i + 3u] = (word >> 24u) & 0xffu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; --i) {
    const uchar h = (d[i / 4] >> (8u * (i % 4))) & 0xffu;
    if (h != bound[i]) { win = h < bound[i]; break; }
  }
  if (win) {
    const uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1u + 2u * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2u + 2u * idx], base_c, memory_order_relaxed);
    }
  }
}

// Sixth candidate: coordinate-driven register aggregation of cumulative
// int32 values, then one shared atomic XOR per locally aggregated row pair.
// Uses only public cooperative-tensor coordinate accessors. The four-entry
// register table may flush multiple times and is correct for any layout.
// Shared storage drops from 18 KiB to 2176 bytes; real speed is measured,
// never inferred from the reduction in scratch storage.
kernel void pow_sweep_tensor_fold(device signed char *an [[buffer(0)]],
                            device signed char *bnt [[buffer(1)]],
                            device const uint *params2 [[buffer(2)]],
                            device const uint *a_seed [[buffer(4)]],
                            device const uchar *bound [[buffer(5)]],
                            device atomic_uint *hits [[buffer(6)]],
                            constant PowParams &P [[buffer(7)]],
                            device uchar *digests_out [[buffer(8)]],
                            uint2 tgid [[threadgroup_position_in_grid]],
                            uint tid [[thread_index_in_threadgroup]]) {
  using namespace mpp::tensor_ops;
  constexpr int TM = 64, TN = 64, TK = FUSION_RANK;
  using Operand = tensor<device signed char, extents<int, TK, TM>, tensor_inline>;
  constexpr auto descriptor = matmul2d_descriptor(
      TM, TN, TK, false, true, false,
      matmul2d_descriptor::mode::multiply);
  matmul2d<descriptor, execution_simdgroups<4>> operation;
  auto partial = operation.get_destination_cooperative_tensor<
      Operand, Operand, int>();
  auto accumulator = operation.get_destination_cooperative_tensor<
      Operand, Operand, int>();
  for (uint i = 0; i < accumulator.get_capacity(); ++i)
    if (accumulator.is_valid_element(i)) accumulator[i] = 0;

  const uint band = params2[0] + tgid.y;
  const uint row0 = band * 64u;
  const uint base_c = tgid.x * 64u;
  const uint nchunks = FC_K / FC_R;
  threadgroup atomic_uint folds[32];
  threadgroup uint tr[32 * 16];
  for (uint i = tid; i < 512u; i += 128u) tr[i] = 0;
  if (tid < 32u) atomic_store_explicit(&folds[tid], 0u, memory_order_relaxed);
  threadgroup_barrier(mem_flags::mem_threadgroup);

  for (uint t = 0; t < nchunks; ++t) {
    const uint klo = t * FC_R;
    Operand a(an + (ulong)row0 * FC_K + klo,
              extents<int, TK, TM>{}, array<int, 2>{1, int(FC_K)});
    Operand bt(bnt + (ulong)base_c * FC_K + klo,
               extents<int, TK, TN>{}, array<int, 2>{1, int(FC_K)});
    operation.run(a, bt, partial);
    // Four explicitly named slots stay scalar registers. A full table is
    // flushed before reuse, so arbitrary future cooperative layouts remain
    // correct; there is no assumed number/order of rows per lane.
    constexpr uint empty = 0xffffffffu;
    uint key0 = empty, key1 = empty, key2 = empty, key3 = empty;
    uint val0 = 0u, val1 = 0u, val2 = 0u, val3 = 0u;
    for (uint i = 0; i < accumulator.get_capacity(); ++i) {
      if (!accumulator.is_valid_element(i)) continue;
      accumulator[i] += partial[i];
      const auto xy = accumulator.get_multidimensional_index(i);
      const uint pair = uint(xy[1]) & 31u;
      const uint word = as_type<uint>(accumulator[i]);
      if (pair == key0) val0 ^= word;
      else if (pair == key1) val1 ^= word;
      else if (pair == key2) val2 ^= word;
      else if (pair == key3) val3 ^= word;
      else if (key0 == empty) { key0 = pair; val0 = word; }
      else if (key1 == empty) { key1 = pair; val1 = word; }
      else if (key2 == empty) { key2 = pair; val2 = word; }
      else if (key3 == empty) { key3 = pair; val3 = word; }
      else {
        atomic_fetch_xor_explicit(&folds[key0], val0, memory_order_relaxed);
        atomic_fetch_xor_explicit(&folds[key1], val1, memory_order_relaxed);
        atomic_fetch_xor_explicit(&folds[key2], val2, memory_order_relaxed);
        atomic_fetch_xor_explicit(&folds[key3], val3, memory_order_relaxed);
        key0 = pair; val0 = word;
        key1 = key2 = key3 = empty;
        val1 = val2 = val3 = 0u;
      }
    }
    if (key0 != empty) atomic_fetch_xor_explicit(&folds[key0], val0, memory_order_relaxed);
    if (key1 != empty) atomic_fetch_xor_explicit(&folds[key1], val1, memory_order_relaxed);
    if (key2 != empty) atomic_fetch_xor_explicit(&folds[key2], val2, memory_order_relaxed);
    if (key3 != empty) atomic_fetch_xor_explicit(&folds[key3], val3, memory_order_relaxed);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    if (tid < 32u) {
      const uint folded = atomic_load_explicit(&folds[tid], memory_order_relaxed);
      const uint slot = t % 16u;
      const uint prev = tr[tid * 16u + slot];
      tr[tid * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ folded;
      // The same owner consumes and clears this fold. The barrier below
      // prevents any next-rank atomics from racing with this reset.
      atomic_store_explicit(&folds[tid], 0u, memory_order_relaxed);
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }
  if (tid >= 32u) return;
  uint msg[16], key[8], d[8];
  for (uint i = 0; i < 16u; ++i) msg[i] = tr[tid * 16u + i];
  for (uint i = 0; i < 8u; ++i) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);
  const uint base_r = row0 + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * 32u + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (uint i = 0; i < 8u; ++i) {
      const uint word = d[i];
      dst[4u * i] = word & 0xffu;
      dst[4u * i + 1u] = (word >> 8u) & 0xffu;
      dst[4u * i + 2u] = (word >> 16u) & 0xffu;
      dst[4u * i + 3u] = (word >> 24u) & 0xffu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; --i) {
    const uchar h = (d[i / 4] >> (8u * (i % 4))) & 0xffu;
    if (h != bound[i]) { win = h < bound[i]; break; }
  }
  if (win) {
    const uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1u + 2u * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2u + 2u * idx], base_c, memory_order_relaxed);
    }
  }
}

// Guarded single-accumulator coordinate fold. Same eligibility as
// pow_sweep_tensor_safe_accum; the host always validates both real buffers.
// Coordinates come only from the public cooperative tensor accessor. The
// four-slot register table is layout independent, including SG2/4/8 layouts.
// Shared memory is 2176 bytes: 32 atomic row-pair folds + 32x16 transcript.
kernel void pow_sweep_tensor_safe_fold(device FusionSafeOperand *an [[buffer(0)]],
                            device FusionSafeOperand *bnt [[buffer(1)]],
                            device const uint *params2 [[buffer(2)]],
                            device const uint *a_seed [[buffer(4)]],
                            device const uchar *bound [[buffer(5)]],
                            device atomic_uint *hits [[buffer(6)]],
                            constant PowParams &P [[buffer(7)]],
                            device uchar *digests_out [[buffer(8)]],
                            uint2 tgid [[threadgroup_position_in_grid]],
                            uint tid [[thread_index_in_threadgroup]]) {
  using namespace mpp::tensor_ops;
#if FUSION_SAFE_FLOAT_ACCUM
  using AccumScalar = float;
#else
  using AccumScalar = int;
#endif
  constexpr uint SAFE_THREADS = 32u * FUSION_SAFE_SIMDGROUPS;
  constexpr int TM = 64, TN = 64, TK = FUSION_RANK;
  using Operand = tensor<device FusionSafeOperand, extents<int, TK, TM>, tensor_inline>;
  constexpr auto descriptor = matmul2d_descriptor(
      TM, TN, TK, false, true, false,
      matmul2d_descriptor::mode::multiply_accumulate);
  matmul2d<descriptor, execution_simdgroups<FUSION_SAFE_SIMDGROUPS>> operation;
  auto accumulator = operation.get_destination_cooperative_tensor<
      Operand, Operand, AccumScalar>();
  for (uint i = 0; i < accumulator.get_capacity(); ++i)
    if (accumulator.is_valid_element(i)) accumulator[i] = 0;

  const uint band = params2[0] + tgid.y;
  const uint row0 = band * 64u;
  const uint base_c = tgid.x * 64u;
  const uint nchunks = FC_K / FC_R;
  threadgroup atomic_uint folds[32];
  threadgroup uint tr[32 * 16];
  for (uint i = tid; i < 512u; i += SAFE_THREADS) tr[i] = 0;
  if (tid < 32u) atomic_store_explicit(&folds[tid], 0u, memory_order_relaxed);
  threadgroup_barrier(mem_flags::mem_threadgroup);

  for (uint t = 0; t < nchunks; ++t) {
    const uint klo = t * FC_R;
    Operand a(an + (ulong)row0 * FC_K + klo,
              extents<int, TK, TM>{}, array<int, 2>{1, int(FC_K)});
    Operand bt(bnt + (ulong)base_c * FC_K + klo,
               extents<int, TK, TN>{}, array<int, 2>{1, int(FC_K)});
    operation.run(a, bt, accumulator);
    // Four explicitly named slots stay scalar registers. A full table is
    // flushed before reuse, so arbitrary future cooperative layouts remain
    // correct; there is no assumed number/order of rows per lane.
    constexpr uint empty = 0xffffffffu;
    uint key0 = empty, key1 = empty, key2 = empty, key3 = empty;
    uint val0 = 0u, val1 = 0u, val2 = 0u, val3 = 0u;
    for (uint i = 0; i < accumulator.get_capacity(); ++i) {
      if (!accumulator.is_valid_element(i)) continue;
      const auto xy = accumulator.get_multidimensional_index(i);
      const uint pair = uint(xy[1]) & 31u;
      const uint word = as_type<uint>(int(accumulator[i]));
      if (pair == key0) val0 ^= word;
      else if (pair == key1) val1 ^= word;
      else if (pair == key2) val2 ^= word;
      else if (pair == key3) val3 ^= word;
      else if (key0 == empty) { key0 = pair; val0 = word; }
      else if (key1 == empty) { key1 = pair; val1 = word; }
      else if (key2 == empty) { key2 = pair; val2 = word; }
      else if (key3 == empty) { key3 = pair; val3 = word; }
      else {
        atomic_fetch_xor_explicit(&folds[key0], val0, memory_order_relaxed);
        atomic_fetch_xor_explicit(&folds[key1], val1, memory_order_relaxed);
        atomic_fetch_xor_explicit(&folds[key2], val2, memory_order_relaxed);
        atomic_fetch_xor_explicit(&folds[key3], val3, memory_order_relaxed);
        key0 = pair; val0 = word;
        key1 = key2 = key3 = empty;
        val1 = val2 = val3 = 0u;
      }
    }
    if (key0 != empty) atomic_fetch_xor_explicit(&folds[key0], val0, memory_order_relaxed);
    if (key1 != empty) atomic_fetch_xor_explicit(&folds[key1], val1, memory_order_relaxed);
    if (key2 != empty) atomic_fetch_xor_explicit(&folds[key2], val2, memory_order_relaxed);
    if (key3 != empty) atomic_fetch_xor_explicit(&folds[key3], val3, memory_order_relaxed);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    if (tid < 32u) {
      const uint folded = atomic_load_explicit(&folds[tid], memory_order_relaxed);
      const uint slot = t % 16u;
      const uint prev = tr[tid * 16u + slot];
      tr[tid * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ folded;
      // The same owner consumes and clears this fold. The barrier below
      // prevents any next-rank atomics from racing with this reset.
      atomic_store_explicit(&folds[tid], 0u, memory_order_relaxed);
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }
  if (tid >= 32u) return;
  uint msg[16], key[8], d[8];
  for (uint i = 0; i < 16u; ++i) msg[i] = tr[tid * 16u + i];
  for (uint i = 0; i < 8u; ++i) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);
  const uint base_r = row0 + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * 32u + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (uint i = 0; i < 8u; ++i) {
      const uint word = d[i];
      dst[4u * i] = word & 0xffu;
      dst[4u * i + 1u] = (word >> 8u) & 0xffu;
      dst[4u * i + 2u] = (word >> 16u) & 0xffu;
      dst[4u * i + 3u] = (word >> 24u) & 0xffu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; --i) {
    const uchar h = (d[i / 4] >> (8u * (i % 4))) & 0xffu;
    if (h != bound[i]) { win = h < bound[i]; break; }
  }
  if (win) {
    const uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1u + 2u * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2u + 2u * idx], base_c, memory_order_relaxed);
    }
  }
}
#endif

// Experimental SG4 specialization, with same-pipeline public-coordinate validation.
// Input magnitude/K precision guard remains mandatory in the native dispatcher.
// Any layout mismatch uses the original direct-store transcript in this kernel.
// P.flags bit2 enables per-threadgroup branch counters at buffer9; bit3 forces fallback.
// Both paths retain full exact int transcript semantics for char-int and half-float.
#if FUSION_METAL4 && FUSION_SAFE_SIMDGROUPS == 4
kernel void pow_sweep_tensor_safe_specialized(device FusionSafeOperand *an [[buffer(0)]],
                            device FusionSafeOperand *bnt [[buffer(1)]],
                            device const uint *params2 [[buffer(2)]],
                            device const uint *a_seed [[buffer(4)]],
                            device const uchar *bound [[buffer(5)]],
                            device atomic_uint *hits [[buffer(6)]],
                            constant PowParams &P [[buffer(7)]],
                            device uchar *digests_out [[buffer(8)]],
                            device atomic_uint *layout_counts [[buffer(9)]],
                            uint2 tgid [[threadgroup_position_in_grid]],
                            uint tid [[thread_index_in_threadgroup]],
                            uint lane [[thread_index_in_simdgroup]],
                            uint sg [[simdgroup_index_in_threadgroup]]) {
  using namespace mpp::tensor_ops;
#if FUSION_SAFE_FLOAT_ACCUM
  using AccumScalar = float;
#else
  using AccumScalar = int;
#endif
  constexpr uint SAFE_THREADS = 32u * FUSION_SAFE_SIMDGROUPS;
  constexpr int TM = 64, TN = 64, TK = FUSION_RANK;
  using Operand = tensor<device FusionSafeOperand, extents<int, TK, TM>, tensor_inline>;
  constexpr auto descriptor = matmul2d_descriptor(
      TM, TN, TK, false, true, false,
      matmul2d_descriptor::mode::multiply_accumulate);
  matmul2d<descriptor, execution_simdgroups<FUSION_SAFE_SIMDGROUPS>> operation;
  auto accumulator = operation.get_destination_cooperative_tensor<
      Operand, Operand, AccumScalar>();
  for (uint i = 0; i < accumulator.get_capacity(); ++i)
    if (accumulator.is_valid_element(i)) accumulator[i] = 0;

  const uint band = params2[0] + tgid.y;
  const uint row0 = band * 64u;
  const uint base_c = tgid.x * 64u;
  const uint nchunks = FC_K / FC_R;
  threadgroup AccumScalar Cs[64 * 64];
  threadgroup uint tr[32 * 16];
  tensor<threadgroup AccumScalar, extents<int, TN, TM>, tensor_inline>
      destination(Cs, extents<int, TN, TM>{}, array<int, 2>{1, TN});
  for (uint i = tid; i < 512u; i += SAFE_THREADS) tr[i] = 0;

  // This is the actual production accumulator, not a diagnostic proxy.
  // Check every public coordinate before selecting the specialization.
  threadgroup atomic_uint layout_bad;
  // One writer per (column side, row pair), proven by the public-coordinate guard.
  threadgroup uint partials[64];
  if (tid == 0u) atomic_store_explicit(&layout_bad, 0u, memory_order_relaxed);
  threadgroup_barrier(mem_flags::mem_threadgroup);
  bool local_ok = accumulator.get_capacity() == 32u && lane < 32u && sg < 4u;
  for (uint slot = 0; slot < accumulator.get_capacity(); ++slot) {
    if (!accumulator.is_valid_element(slot)) { local_ok = false; continue; }
    const auto xy = accumulator.get_multidimensional_index(slot);
    const uint expected_col = (sg & 1u) * 8u + (lane & 1u) * 2u +
        ((lane >> 3u) & 1u) * 4u + (slot & 1u) + ((slot >> 1u) & 3u) * 16u;
    const uint expected_row = (sg >> 1u) * 8u + ((lane >> 1u) & 3u) +
        ((lane >> 4u) & 1u) * 4u + (slot >> 3u) * 16u;
    if (uint(xy[0]) != expected_col || uint(xy[1]) != expected_row)
      local_ok = false;
  }
  if (!local_ok) atomic_store_explicit(&layout_bad, 1u, memory_order_relaxed);
  threadgroup_barrier(mem_flags::mem_threadgroup);
  // P.flags bit3 forces the fallback without recompiling this same pipeline.
  const bool specialized = atomic_load_explicit(&layout_bad, memory_order_relaxed) == 0u &&
      (P.flags & 8u) == 0u;
  if (tid == 0u && (P.flags & 4u))
    atomic_fetch_add_explicit(&layout_counts[specialized ? 0u : 1u], 1u, memory_order_relaxed);
  uint pair0 = 0u, pair1 = 0u;
  if (specialized) {
    uint first_slot = 0u;
    const auto xy0 = accumulator.get_multidimensional_index(first_slot);
    const auto xy1 = accumulator.get_multidimensional_index(8u);
    pair0 = uint(xy0[1]) & 31u;
    pair1 = uint(xy1[1]) & 31u;
  }

  for (uint t = 0; t < nchunks; ++t) {
    const uint klo = t * FC_R;
    Operand a(an + (ulong)row0 * FC_K + klo,
              extents<int, TK, TM>{}, array<int, 2>{1, int(FC_K)});
    Operand bt(bnt + (ulong)base_c * FC_K + klo,
               extents<int, TK, TN>{}, array<int, 2>{1, int(FC_K)});
    operation.run(a, bt, accumulator);
    if (specialized) {
      uint f0 = 0u, f1 = 0u;
      #pragma unroll
      for (uint slot = 0u; slot < 8u; ++slot) {
        f0 ^= as_type<uint>(int(accumulator[slot])) ^
              as_type<uint>(int(accumulator[slot + 16u]));
        f1 ^= as_type<uint>(int(accumulator[slot + 8u])) ^
              as_type<uint>(int(accumulator[slot + 24u]));
      }
      f0 ^= simd_shuffle_xor(f0, 8u);
      f0 ^= simd_shuffle_xor(f0, 1u);
      f1 ^= simd_shuffle_xor(f1, 8u);
      f1 ^= simd_shuffle_xor(f1, 1u);
      // Guarded public coordinates prove these four lanes share a row pair.
      // Exactly 64 distinct destinations are fully written every rank.
      // sg&1 identifies the two column sides; no atomics or clearing needed.
      if ((lane & 9u) == 0u) {
        const uint side = (sg & 1u) * 32u;
        partials[side + pair0] = f0;
        partials[side + pair1] = f1;
      }
      threadgroup_barrier(mem_flags::mem_threadgroup);
      if (tid < 32u) {
        const uint folded = partials[tid] ^ partials[32u + tid];
        const uint slot = t % 16u;
        const uint prev = tr[tid * 16u + slot];
        tr[tid * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ folded;
      }
    } else {
      accumulator.store(destination);
      threadgroup_barrier(mem_flags::mem_threadgroup);
  
      // Logical lanes preserve the original four-lane row-pair reduction.
      // SG2 executes two full-simdgroup iterations; SG8 leaves four whole
      // simdgroups idle here. No shuffle crosses an inactive partial group.
      for (uint logical = tid; logical < 128u; logical += SAFE_THREADS) {
        const uint o = logical / 4u;
        const uint j0 = (logical % 4u) * 16u;
        uint folded = 0;
        for (uint b = 0; b < 16u; ++b)
          folded ^= as_type<uint>(int(Cs[o * 64u + j0 + b])) ^
                    as_type<uint>(int(Cs[(o + 32u) * 64u + j0 + b]));
        folded ^= simd_shuffle_xor(folded, 2u);
        folded ^= simd_shuffle_xor(folded, 1u);
        if ((logical & 3u) == 0u) {
          const uint slot = t % 16u;
          const uint prev = tr[o * 16u + slot];
          tr[o * 16u + slot] = ((prev << 13u) | (prev >> 19u)) ^ folded;
        }
      }
    }
    // Protect the shared output from the next rank's cooperative store.
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }
  if (tid >= 32u) return;
  uint msg[16], key[8], d[8];
  for (uint i = 0; i < 16u; ++i) msg[i] = tr[tid * 16u + i];
  for (uint i = 0; i < 8u; ++i) key[i] = a_seed[i];
  blake3_64_keyed(msg, key, d);
  const uint base_r = row0 + tid;
  if (P.flags & 1u) {
    const uint tile_idx = (band * 32u + tid) * P.n_col_bases + tgid.x;
    device uchar *dst = digests_out + (ulong)tile_idx * 32u;
    for (uint i = 0; i < 8u; ++i) {
      const uint word = d[i];
      dst[4u * i] = word & 0xffu;
      dst[4u * i + 1u] = (word >> 8u) & 0xffu;
      dst[4u * i + 2u] = (word >> 16u) & 0xffu;
      dst[4u * i + 3u] = (word >> 24u) & 0xffu;
    }
  }
  bool win = true;
  for (int i = 31; i >= 0; --i) {
    const uchar h = (d[i / 4] >> (8u * (i % 4))) & 0xffu;
    if (h != bound[i]) { win = h < bound[i]; break; }
  }
  if (win) {
    const uint idx = atomic_fetch_add_explicit(&hits[0], 1u, memory_order_relaxed);
    if (idx < P.hits_cap) {
      atomic_store_explicit(&hits[1u + 2u * idx], base_r, memory_order_relaxed);
      atomic_store_explicit(&hits[2u + 2u * idx], base_c, memory_order_relaxed);
    }
  }
}
#endif
