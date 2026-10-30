# Offline 16-row shape candidate

`prefix_pair16.metal` changes only `prefix_pair` from the original baseline.
The 32-row candidate and production source are untouched. This experiment
preserves full K=128 arithmetic, all 32 prefixes, transcript hashes and targets.
It has no new ABI or dispatch geometry. No deployment is authorized by this file.

Each original 64-row band is four sequential public MPP stores of 16x64
float outputs. The descriptor is (M,N,K)=(16,64,128), left extents (128,16),
transposed right extents (128,64), and output extents (64,16), stride (1,64).
The shared array is 1024 floats, or 4 KiB. All 128 threads in four SIMDgroups
execute every MPP call and both barriers per subpass. Only reading the output
is conditional: row-pairs 0..15 consume row blocks 0 and 2, while pairs 16..31
consume blocks 1 and 3, always local row `pair & 15`. Each lane consumes its
original 16 columns. The final XOR reductions and phase rotation are unchanged.

The native width-32 check keeps each four-lane shuffle within a SIMDgroup.
Existing multiples-of-64 M/N guards cover every subblock completely. No private
cooperative-tensor layout is used. Integer conversion and exactness guards remain
unchanged. The public API describes this shape; target compilation and complete
GPU correctness gates are still required before any timing comparison.

Per threadgroup, MPP calls grow from 2 (baseline) to 4 (pair32) to 8 (pair16),
with one complete K=128 reduction each. Barrier pairs increase accordingly.
Total arithmetic stays `8*16*64*128 = 1048576 MAC/threadgroup`, or 524288 MAC
per credited tile after all 16 transcript slots. This is a shape/occupancy
experiment, not omitted work or a new hashrate counting convention.

`check_pair16_geometry.py` verifies read ownership, all 32 prefixes, row bounds
for all 256 admitted M sizes, and exact agreement with direct baseline XOR
on four deterministic fixtures. This CPU check does not validate MPP compilation,
floating-point implementation, pool shares or speed. Run the existing small,
large and no-export GPU/proof gates, then a bounded full-work A/B. The smaller
store does not establish actual register usage or occupancy, and extra calls,
barriers and idle readers may outweigh the memory savings.
