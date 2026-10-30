# Pearl M-Miner FAQ

## Can a Mac mine Pearl (PRL)?
This source miner uses Apple Silicon Metal GPUs. It requires macOS 26+, native
arm64 Python 3.12+, Metal 4 tools and Rust/Cargo. M1 Max has measured validation;
other M-series devices need local correctness and pool checks.

## How fast is it on M1 Max?
The qualified 32-core, 64 GiB M1 Max configuration measured 4.2347 TH/s over
300 offline seconds, about 7.82% above our own previous Alpha 2 backend. These
figures include fresh-grid preparation. A separate live session had one accepted
and zero rejected Kryptex shares. Neither is a guaranteed pool rate or income.
See [the methods and limits](M1_CEILING_20261030.md).

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
