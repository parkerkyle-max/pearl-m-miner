#!/bin/sh
set -eu
cd "$(dirname "$0")"
xcrun clang++ -std=c++17 -O2 -fobjc-arc -fvisibility=hidden -dynamiclib \
  -framework Foundation -framework Metal prefix_native.mm -o libprefix.dylib
