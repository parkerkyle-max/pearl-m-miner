#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p build
case "$(uname -s)" in
 Darwin) output=build/libprefixsparse.dylib; mode=-dynamiclib ;;
 Linux) output=build/libprefixsparse.so; mode=-shared ;;
 *) exit 1 ;;
esac
"${CC:-cc}" -O3 -std=c11 -fPIC "$mode" prefix_sparse.c -o "$output"
printf '%s\n' "$output"
