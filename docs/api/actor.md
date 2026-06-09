# `Actor`

An actor is one EOA operating on one or more chains, present at the same address
on each. It holds a single key derived deterministically from its name, a
`Wallet` per chain, and a transaction helper. An actor is a primitive, not a
plugin: a plugin (such as `RandomTrader`) owns and drives one.

## Constructor

```python
Actor(*, name, chains, mnemonic=<dev mnemonic>, account_index=None)
```

- `name` - names the actor and derives its key. Two actors with different names
  get different keys; the derivation hashes the name so unrelated names do not
  collide.
- `chains` - a non-empty list of chains the actor operates on.
- `account_index` - override the derived HD index (advanced).

## Methods and attributes

- `address` - the actor's address (the same on every chain).
- `chains` - the chains the actor knows about.
- `wallet_on(chain)` - the actor's `Wallet` on a chain (registers the chain if
  new).
- `fund(*, native, chain)` - top the actor's native balance on a chain up to
  `native`.
- `call(contract, method, *args, chain=None, value=0, gas=2_000_000)` - submit a
  state-changing call signed by the actor's wallet, returning a `PendingTx`. If
  `contract` is a `Pair`, pass `chain=` to pick the side.

```python
from statelab import Actor

alice = Actor(name="alice", chains=lab.chains)
for c in lab.chains:
    alice.fund(native=10**18, chain=c)
alice.call(amm.contract, "swapExactIn", token_in, amount, 0, chain=earth).wait()
```
