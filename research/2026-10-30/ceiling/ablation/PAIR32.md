# Offline 32-row subblock candidate

`prefix_pair32.metal` changes only `prefix_pair`. Production source, native
dispatch and preparation/hash/target code remain unchanged. This candidate
has not been approved for deployment. CPU geometry validation is not Metal
compilation, numerical validation, a valid share, or a performance result.

For each existing 64-row band and prefix, it computes rows 0..31 and 32..63
in two consecutive MPP operations. Both use the original K=128 reduction,
half operands, float accumulators and public `accumulator.store` API. The
four lanes assigned to one row-pair XOR their 16-column slices across both
stores, then perform the unchanged XOR-shuffle reduction and phase rotation.
Every threadgroup thread reaches both barriers on each subpass. The second
barrier prevents overwriting the shared matrix while another thread reads it.

Geometry and required GPU correctness gates:

- MPP descriptor ordering is M,N,K; descriptor(32,64,128) uses Left extents
  (128,32), Right (128,64) and destination (64,32), stride (1,64).
  Apple's [MPP Programming Guide](https://developer.apple.com/download/files/Metal-Performance-Primitives-Programming-Guide.pdf)
  page 6 confirms descriptor(SM,SN), A extents(K,SM), output extents(SN,SM).
  Right is transposed in our descriptor, so its storage is (K,N). The actual
  asymmetric shader must still pass compilation and complete output checks.
- Existing native dispatch remains 128 threads and 4 SIMDgroups. Apple SIMD
  width is 32, so each four-lane XOR group lies within a SIMDgroup.
- M,N and row-band dimensions meet the existing multiples-of-64 validation.
  `dims.z` remains a band offset. Transcript row ownership uses group.y,
  exactly as in baseline, and each group.z owns one of the 16 final slots.
- No assumption is made about the private cooperative-tensor element layout.

The logical accumulator and shared store shrink from 4096 to 2048 float
elements (16 KiB to 8 KiB). There are four MPP runs instead of two and twice
as many shared-store barrier pairs. Occupancy may improve, but extra dispatch
work inside the threadgroup or a less efficient MPP shape may make this slower.

Exact arithmetic count is unchanged:

`old: 2*64*64*128 = new: 4*32*64*128 = 1048576 MAC / threadgroup`.

Each threadgroup produces one transcript slot for 32 tiles; 16 slots make
the full 32-prefix transcript, hence 524288 MAC / credited tile and 1048576
FLOP / tile. No calculation is omitted or counted as a second mining result.

Run `check_pair32_geometry.py` locally for the limited CPU regrouping oracle.
Before timing on the Mac, run the release's `check_sparse_native.py` with
`--method s --shader /path/to/prefix_pair32.metal`, matching the existing
baseline library and source/factory roots. Run both the small all-transcript
gate and `--m 16384 --n 65536 --full-export-only`. Any failure stops testing.
Then compare fresh-grid full-work benchmarks with alternating baseline runs.
The component profiler is diagnostic and repeats immutable work; its speed
must not be reported as a fresh-work mining hashrate.
