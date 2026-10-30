# Pearl M-Miner FAQ

## Can a Mac mine Pearl (PRL)?
This source miner uses Apple Silicon Metal GPUs. It requires macOS 26+, native
arm64 Python 3.12+, a compatible Metal 4 SDK/Command Line Tools and Rust/Cargo. M1 Max (32 GPU
cores / 64 GiB) and M2 (10 GPU cores / 24 GiB) have measured validation; other
configurations need their own correctness and pool checks.

## How fast is it on M1 Max?
The qualified 32-core, 64 GiB M1 Max configuration measured 4.2347 TH/s over
300 offline seconds, about 7.82% above our own previous Alpha 2 backend. These
figures include fresh-grid preparation. A separate live session had one accepted
and zero rejected Kryptex shares. Neither is a guaranteed pool rate or income.
See [the methods and limits](M1_CEILING_20261030.md).

## How fast is Pearl mining on M2, compared with pearl-metal-miner?
The tested 10-core M2 / 24 GiB Mac measured 1.4652 TH/s with the unchanged
Alpha 3 default, versus 0.4061 TH/s for pearl-metal-miner 0.2.4 with cert3
compatibility and unchanged upstream GPU kernels: 3.61× local throughput.
Both used the same dimensions, two CPU helpers and 300 measured seconds.
This is not a Pearly comparison. Software power is not outlet power, and local
speed is not paid income. See [M2 methods, proof gates and pool trials](M2_VALIDATION_20261030.md).

## What mining intensity should I use on the tested M2 laptop?
Start with `--intensity 80 --time-limit 600` and observe temperatures and fan
behavior. The full-duty live attempt stopped at the independent lab's 95°C
average-sensor guard after about 119 seconds; both repeated ten-minute trials
used intensity 80. This is an explicit recommendation, not a changed default.
Intensity is a scheduling setting, not a guarantee of proportional hashrate.
The release monitors OS thermal pressure; the extra lab Celsius guard is not
a shipped miner feature. Other machines need their own thermal checks.

## Is every M-series Mac supported and equally fast?
No. The measured devices are exact configurations, not whole chip families.
M2 Pro/Max/Ultra, other M2 GPU-core counts and M3–M5 need separate qualification.
Build and self-test on the actual Mac before mining. [Compatibility](COMPATIBILITY.md)
records what is measured; advertised chip TOPS do not establish mining speed.

## Does it use the Neural Engine or mine XMR?
No. The shipped backend mines PRL with the GPU. CPU helpers prepare proofs and
jobs. ANE mining, independent CPU mining and other coins are research targets.

## Is there a developer fee?
The default is an optional 1% of completed valid GPU scan time. Use
`--dev-fee 0` to disable it. It is not 1% of income; pool fees are separate.
The developer route is separately disclosed. See [fee semantics](DEV_FEE.md).

## Which wallet information is required?
Only a public Kryptex mining ID or native PRL receiving address. Never supply a
private key, seed or wallet password. Read [wallet and payout visibility](WALLET_AND_PAYOUTS.md).

## How do I stop? Does installation start mining?
Installation, `info`, `doctor`, `self-test` and `benchmark` do not start pool
mining. `mine --time-limit 600` stops after ten minutes. Ctrl+C stops the
foreground worker. The bootstrap does not install autostart.

## Is this an official Kryptex or Apple product?
No. It is an independent Apache-2.0 project. A successful pool share is protocol
evidence, not an endorsement or an official compatibility-list entry.

## Where are the commands and machine-readable facts?
See [AI_SETUP.md](AI_SETUP.md), [miner-manifest.json](miner-manifest.json),
the multilingual READMEs and `pearl-m-miner info --json`.
