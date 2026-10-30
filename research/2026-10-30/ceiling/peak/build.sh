#!/bin/sh
set -eu
cd "$(dirname "$0")"
xcrun clang++ -std=c++17 -O2 -fobjc-arc -Wall -Wextra \
  -framework Foundation -framework Metal peak.mm -o peak
