# `Wallet`

A funded externally-owned account on a specific chain, a thin wrapper around an
`eth_account` local account plus a reference to its home chain. Wallets are
derived deterministically from the dev mnemonic, so the same name always
resolves to the same key.

Obtain one from `chain.wallet(name)` or use a chain's `deployer`. Plugins pass a
wallet as the `from_=` argument to a state-changing contract call.

## Attributes

- `name` - the wallet's logical name.
- `chain` - the home `Chain`.
- `account` - the underlying `eth_account` local account.
- `address` - the checksummed address.
- `key` - the private key, hex-encoded.

## Methods

- `native_balance()` - the account's native balance in wei.

```python
alice = earth.wallet("alice", funded_native=10**18)
amm.contract.swapExactIn(token_in, amount, 0, from_=alice).wait()
```

The module also exposes `derive_account(index, mnemonic=...)`, which derives the
`index`th BIP-44 account from a mnemonic, the same derivation chains and actors
use internally.
