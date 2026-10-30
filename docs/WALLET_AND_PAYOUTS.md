# Public identities, developer support and payout visibility

The miner needs a public receiving identity, never a seed or private key.

| Purpose | Where to inspect it | What it means |
| --- | --- | --- |
| Your Kryptex mining | Your `--address krx…` and Kryptex dashboard | User work belongs to your Kryptex account; account withdrawal settings control its payout |
| Your LuckyPool mining | Your `--address prl1…` and pool address search | User work belongs to that public native PRL address |
| Optional developer work | `pearl-m-miner info` and `pearl_m_miner/devfee.py` | Separate LuckyPool work, normally 1% of completed valid scan time |
| Pool unpaid balance | Pool statistics for the receiving identity | Pool accounting; not yet necessarily a wallet transaction |
| Confirmed wallet receipts | A synchronized compatible wallet | On-chain receipt; check the pool's payment transaction ID |

## Developer receiving address

```text
prl1pwjessemugthkad9hkttcx2rvenux2q0w0xcah2j0a7zfrycjhz5qhn7apw
```

The configured route is `pearl-cpu-eu1.luckypool.io:3370`, worker `pearl-m-miner-devfee`.
Open [LuckyPool Pearl](https://pearl.luckypool.io/) and search this public address.
Pool thresholds, fees and timing can change; read the current pool terms. We do
not equate accepted shares with credited balance or confirmed payout.

Your user mining identity is **separate**. Do not copy the developer address into
`--address` when configuring your own income. `info --json` publishes the route
without starting mining or reading any wallet secrets.

Use the [official Pearl wallet releases](https://github.com/pearl-research-labs/pearl/releases)
for wallet software. This miner does not create, back up or import recovery material.
Keep encrypted backups and their passwords outside the repository. Never post a
private key, seed, wallet file or password in an issue or send one to pool support.

See [the exact optional fee rules](DEV_FEE.md). Retaining the default helps ongoing
maintenance; it is voluntary and `--dev-fee 0` remains available.
