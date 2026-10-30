# Help test your Mac with an offline comparison

Owners of other Apple Silicon configurations can help by contributing successful,
slower and failed tests. The experimental `compare` and `share-report` commands
are in the **`main` development preview, version `0.1.0a4.dev1`**. They are not in
the `v0.1.0-alpha.3` release tag. This preview is not a new release, and the
historical Alpha 3 M1 Max and M2 measurements do not validate this new comparison
runner on those or other Macs. Native Mac acceptance of the integrated runner
remains pending; its runtime correctness checks are required on every device.

The first comparator is **pearl-metal-miner 0.2.4 + disclosed cert3 compatibility**.
It is pinned to upstream commit
`3d4cc7dadbd1de98ba20e9beb162806a0e70266b`; this is not a test against a moving
upstream branch. See [comparator selection and limitations](COMPARATORS.md).

## Install the preview in a new directory

On an Apple Silicon Mac with the project's [build requirements](../README.md#part-2),
open Terminal and use a new directory so an existing miner installation stays
separate:

```sh
git clone --branch main https://github.com/parkerkyle-max/pearl-m-miner.git pearl-m-miner-test
cd pearl-m-miner-test
sh bootstrap.sh
```

Cloning and initial dependency installation need network access. After setup,
the comparison itself is offline. Its reference source, Apache-2.0 license,
notice and compatibility patch are included in this checkout. The command builds
an isolated reference library locally; it does not download or separately install
another miner. [The retained source and patch](../comparators/pearl-metal-miner/README.md)
document the control's provenance and exact build checks.

## Inspect the plan, then start the test

```sh
.venv/bin/pearl-m-miner compare --plan
```

The plan prints the parameters without starting native work, writing a report,
opening a wallet or using the network. To run it:

```sh
.venv/bin/pearl-m-miner compare --against pearl-metal-miner --output ./my-comparison
```

Read the prompt and confirm to start. Keep the Mac on AC power and stop other
mining, games and GPU workloads so both backends get comparable conditions.
The output directory must not already exist; use a new name for each attempt.
For an unattended run that you have already agreed to, append `--yes`. That
option accepts the GPU workload without a prompt; it does not authorize sharing.

Default measurement conditions are:

| Setting | Default |
| --- | --- |
| Backends | A: pinned upstream control; B: current Pearl M-Miner checkout |
| Order | A, B, B, A; two timed runs per backend |
| Measured window | 60 seconds per run, 240 seconds in total |
| Cooldown | 30 seconds before every timed run, 120 seconds in total |
| Work | Certificate 3, M=8192, N=16384, K=4096, rank=128 |
| Host / dispatch | 2 CPU threads, 512 region rows, 100% comparison intensity |
| Additional work | Reference build, warmup and correctness/proof gates before and after timing |

The default timed windows and cooldowns total six minutes, with additional time
for the build, warmup and gates. This is not a six-minute completion promise.
`compare --help` lists the bounded duration, repetition, cooldown and shape
options; record any changes and compare only matching settings.

This is a full-duty offline GPU test. The controller checks AC power and macOS
thermal pressure for both backends. Unknown conditions, a switch to battery,
disallowed thermal pressure, a timeout or a failed correctness check invalidate
the comparison. The thermal-pressure signal is not a Celsius sensor or the
external 95°C guard used in the historical M2 laboratory trial. Stop with Ctrl-C
if needed; an interrupted attempt is kept as an incomplete result.

## Understand the measurement

Both backends use the same requested protocol, shape, duration and CPU thread
cap. Each retains its own production preparation strategy and chosen matrices;
the test does not claim byte-identical matrices between backends. The control's
cert3 seed/proof/session compatibility patch leaves its original native host and
GPU kernels unchanged.

The reported rate covers **fresh preparation plus completed scans**. Warmup,
compilation, correctness gates, pool/network activity and hit-triggered proof
construction are outside the timed rate. Proof correctness is checked separately
before and after the timed runs. The offline command uses no wallet, pool
connection, developer-fee session or upload. A local PRL TH/s result does not
establish pool acceptance, sustained credited hashrate, power efficiency or income.

For a complete test, the summary compares the median of **all** completed runs
for each backend and retains the individual runs and their spread. A slower
candidate is a useful result and is not discarded. Failed, interrupted, battery,
thermal and timeout outcomes have no speed ratio or improvement claim; the
reason and any completed evidence remain in the report. A successful run is
still self-reported community evidence, pending independent review.

## Review and optionally share

The new output directory contains:

- `report.json`: machine-readable hardware, OS, version, source/build hashes,
  parameters, correctness outcomes and per-run throughput.
- `summary.md`: a readable account of the outcome and its measurement scope.

The report uses a bounded set of fields. It does not include raw stderr, account
usernames, absolute home paths, wallet addresses or wallet secrets. Relative
source paths and source/build hashes are retained for reproducibility. Read both
files before sharing; any files or notes you attach manually also need review.

Preview the public summary locally:

```sh
.venv/bin/pearl-m-miner share-report ./my-comparison/report.json
```

This default does not upload anything. To open a draft in your own browser:

```sh
.venv/bin/pearl-m-miner share-report ./my-comparison/report.json --open
```

`--open` opens a GitHub issue draft with a summary. **Attach the reviewed
`report.json`, review the draft and press Submit yourself.** Opening the draft
does not publish it. You can also use the [device-result form](https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=device-result.yml)
manually, including for installation or build failures that occurred before a
comparison report could be created.

For explicit direct publication, the optional GitHub CLI must already be installed
and signed in to your own account:

```sh
.venv/bin/pearl-m-miner share-report ./my-comparison/report.json --submit
```

`--submit` **creates a public GitHub issue** containing the reviewed, allowlisted
report. It does not install `gh` or sign you in automatically. Without that setup,
use `--open` or the manual form. A local submission receipt records the outcome;
if the network result is uncertain, check your GitHub issues before retrying.
The command does not silently submit the same report again.

Please include the exact chip, GPU-core count, memory, macOS, miner version,
command, settings and any relevant surrounding workload. Missing hardware fields,
unexpected behavior, slower runs and failed checks are worth reporting. Never
present a failed correctness check as a valid speed result.

Reports are not automatically added to the [public device matrix](../README.md#device-results).
Maintainers first review the evidence, source identity, scope and conflicting
observations. Published results stay specific to the measured configuration.
For a concern about an existing claim, use the [benchmark discrepancy form](https://github.com/parkerkyle-max/pearl-m-miner/issues/new?template=benchmark-discrepancy.yml);
you do not need a successful replacement benchmark to raise a concern.
