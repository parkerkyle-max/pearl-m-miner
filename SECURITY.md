# Security

This is experimental mining software. Correct arithmetic, job identity and proof binding are part of its security boundary: invalid or replayed work must not be reported as valid hashrate.

Do not place private keys, wallet recovery phrases or exchange credentials in the miner's configuration or an issue. Mining needs a public receiving identity; it does not need custody of the wallet. Review scripts and dependencies before running them. Build and mine as a normal user; installation should not require a privileged persistent service.

The public release does not install an autostart service. Stop the foreground process to stop its owned worker. Report unexpected surviving processes, identity crossover, fee-routing failures, stale-result crediting, unsafe buffer lifetime, failed precision guards or temperature protection defects.

For a sensitive report, use the repository's **Security → Report a vulnerability** option if available. If that option is unavailable, open an issue asking for a private contact without including exploit details or secrets. Do not assume a private-reporting feature has been enabled merely because this document mentions it.

Only the current experimental version is a maintenance target; there is no long-term support promise. The maintainer has not claimed an independent security audit or cross-generation hardware certification.
