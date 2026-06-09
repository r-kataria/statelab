# `Chain`

An Anvil-backed EVM chain with manual block control. The harness mines blocks
explicitly, so Anvil must run with `--no-mining`, and a chain's `blocktime` is
the simulated interval the run loop uses to decide when to mine. Obtain a
`Chain` from `lab.chain(...)` rather than constructing one directly.

## Construction

`lab.chain(name, chain_id, blocktime, rpc_url=None)` connects to a node,
verifies its chain id against the node, resets it, and returns the `Chain`. The
names `earth` and `mars` default to ports 8545 and 8546; any other name
defaults to port 8545 unless `rpc_url` is given.

## Attributes

- `name`, `chain_id`, `blocktime` - as registered.
- `deployer` - account 0 of the mnemonic, prefunded by Anvil; signs deployments
  by default.
- `w3` - the underlying `web3.Web3` client.

## Wallets

- `wallet(name, funded_native=0)` - return (or create) a named wallet on this
  chain, optionally topping its native balance up to `funded_native` from the
  deployer.
- `get_wallet(name)` - the wallet for a name, or `None`.

## Block and state control

- `mine(timestamp=None)` - mine one block, optionally pinning its timestamp;
  returns the new block number.
- `set_next_block_timestamp(unix_ts)` - pin the next block's timestamp.
- `head_number()` / `head_timestamp()` - the latest block number / timestamp.
- `snapshot()` / `revert(snap_id)` - Anvil state snapshot and revert.
- `set_balance(address, wei)` - set an account's native balance.
- `impersonate(address)` / `stop_impersonating(address)` - Anvil impersonation.
