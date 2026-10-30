#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p build
case "$(uname -s)" in
  Darwin) output=build/libm1merkleprobe_c.dylib; mode=-dynamiclib ;;
  Linux) output=build/libm1merkleprobe_c.so; mode=-shared ;;
  *) echo 'Only macOS/Linux supported by this isolated probe.' >&2; exit 1 ;;
esac
"${CC:-cc}" -O3 -std=c11 -fPIC "$mode" -I c_vendor nonce_path.c c_vendor/blake3_portable.c -o "$output"
printf '%s\n' "$output"
