#!/bin/sh
set -eu
cd "$(dirname "$0")"
xcrun clang++ -std=c++17 -O2 -fobjc-arc \
  -framework Foundation -framework Metal \
  inspect_pipeline.mm -o inspect_pipeline
