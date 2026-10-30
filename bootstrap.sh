#!/bin/sh
# Reproducible source bootstrap. Nothing downloads or runs until invoked.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || {
  echo 'Apple Silicon macOS with native arm64 tools is required.' >&2; exit 1;
}
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 26 ] || { echo 'macOS 26+ required.' >&2; exit 1; }
xcrun --find clang++ >/dev/null
command -v cargo >/dev/null || { echo 'Install Rust/cargo first; no installer is run automatically.' >&2; exit 1; }
PY="${PYTHON:-python3}"
"$PY" -c 'import platform,sys; assert sys.version_info >= (3,12) and platform.machine()=="arm64", "native arm64 Python 3.12+ required"'
[ -d .venv ] || "$PY" -m venv .venv
PY="$ROOT/.venv/bin/python"
"$PY" -m pip install -r requirements-build.txt
WANT="$(tr -d '\r\n' < PINNED_PEARL_COMMIT.txt)"
case "$WANT" in *[!0-9a-f]*|'') echo 'Invalid pinned Pearl commit.' >&2; exit 1;; esac
[ "${#WANT}" = 40 ] || exit 1
mkdir -p .deps
if [ ! -d .deps/pearl/.git ]; then
  git clone --depth 1 https://github.com/pearl-research-labs/pearl.git .deps/pearl
fi
[ -z "$(git -C .deps/pearl status --porcelain)" ] || {
  echo '.deps/pearl has local changes; refusing to overwrite them.' >&2; exit 1;
}
git -C .deps/pearl fetch --depth 1 origin "$WANT"
git -C .deps/pearl checkout --detach "$WANT"
[ "$(git -C .deps/pearl rev-parse HEAD)" = "$WANT" ] || exit 1
(cd .deps/pearl/py-pearl-mining && "$ROOT/.venv/bin/maturin" build --release --locked --interpreter "$PY" --out "$ROOT/.deps/wheels")
"$PY" -m pip install --no-deps --force-reinstall .deps/wheels/py_pearl_mining-0.3.1-*.whl
sh packaging/build_macos.sh
sh tools/prefix_s_miner/build.sh
sh tools/prefix_sparse_host/build_sparse.sh
sh tools/merkle_overlay/build_c.sh
"$PY" -m pip install --no-deps --no-build-isolation -e .
"$PY" packaging/write_build_receipt.py
"$ROOT/.venv/bin/pearl-m-miner" doctor
echo 'Ready. Run .venv/bin/pearl-m-miner self-test before mining.'
