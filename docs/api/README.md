# Core API reference

Reference for the core primitives. All of these are importable from the
top-level package: `from statelab import Lab, Time, Chain, ...`.

- [Lab](lab.md) - the orchestrator: chains, plugins, the run loop, output.
- [Time / TimeControl](time.md) - the simulated clock, `TimeValue`, `Distribution`.
- [Chain](chain.md) - an Anvil-backed chain with manual block control.
- [Wallet](wallet.md) - a deterministically derived EOA on a chain.
- [Contract / Pair / PendingTx](contract.md) - deploy, call, and cross-chain parity.
- [Actor](actor.md) - a funded wallet across chains with a call helper.
- [Plugin / Context](plugin.md) - the plugin protocol and the per-block context.
- [create2](create2.md) - same-address cross-chain deployment.
