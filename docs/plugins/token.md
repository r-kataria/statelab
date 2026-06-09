# token plugin

The token plugin ships two plugin classes and one helper:

- **`Token`** - a plain single-chain ERC-20.
- **`BridgeableToken`** - an ERC-20 deployed at the same address on every chain,
  moved cross-chain by burn-on-source / mint-on-destination.
- **`ERC20`** - a thin convenience wrapper around a deployed plain ERC-20,
  used internally by `Token` and available for non-bridged scenarios.

All three are importable from the top level: `from statelab import Token,
BridgeableToken, ERC20`.

## `Token`

A plain ERC-20 as a plugin. Its `setup` deploys the shipped `ERC20.sol` artifact
on one chain and mints the initial supply to that chain's deployer.

```python
Token(name_, symbol, chain, supply=0, plugin_name=None)
```

- `name_`, `symbol` - the ERC-20 name and symbol.
- `chain` - the chain to deploy on.
- `supply` - initial supply minted to the deployer.
- `plugin_name` - overrides the plugin name (defaults to `"erc20:<symbol>"`).

Key members (available after `setup`):

- `address` - the deployed token address.
- `contract` - the underlying ABI-wrapped `Contract`.
- `balance_of(who)` - balance of a wallet or address.
- `approve(owner_wallet, spender, amount)` - approve a spender, signed by
  `owner_wallet`, and wait.

```python
from statelab import Lab, SimpleAMM, Time, Token

WAD = 10**18
with Lab(seed=1, duration=Time(60), outdir="out/tok") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    tx = lab.use(Token("TokenX", "TKX", chain=earth, supply=10**24))
    ty = lab.use(Token("TokenY", "TKY", chain=earth, supply=10**24))
    lab.use(SimpleAMM(earth, tx, ty, initial_liquidity=(1_000 * WAD, 1_000 * WAD)))
```

## `BridgeableToken`

A `BridgeableERC20` deployed at an identical address on every registered chain
through `lab.create2`, with each side's cross-chain peer wired to the shared
address. Token movement burns on the source chain and mints on the destination,
routed through a `RelayBridge`.

```python
BridgeableToken(name_, symbol, bridge, supply_per_chain=0, plugin_name=None)
```

- `name_`, `symbol` - the ERC-20 name and symbol.
- `bridge` - the `RelayBridge` plugin instance that carries the mint message.
- `supply_per_chain` - supply minted to the deployer on each chain. It must be
  the same on every chain, because address parity requires byte-identical
  creation code.
- `plugin_name` - overrides the plugin name (defaults to `"token:<symbol>"`).

Key members:

- `on(chain)` - the token `Contract` on a given chain.
- `balance_of(who, chain)` - balance on a given chain.
- `bridge_token(actor, amount, to_chain, src_chain)` - burn `amount` on
  `src_chain` and route the mint to `to_chain` through the bridge; returns a
  `PendingBridgeTx` whose `wait_delivery()` drives the clock until it lands.

```python
from statelab import Actor, BridgeableToken, Lab, RelayBridge, Time

WAD = 10**18
with Lab(seed=7, duration=Time(60 * 60), outdir="out/bridge") as lab:
    earth = lab.chain("earth", chain_id=31337, blocktime=Time(12))
    mars  = lab.chain("mars",  chain_id=31338, blocktime=Time(12))

    bridge = lab.use(RelayBridge(earth, mars, delay=Time(24)))
    tkx = lab.use(BridgeableToken("TokenX", "TKX", bridge=bridge,
                                  supply_per_chain=1000 * WAD))
    # Inside a plugin's on_block, with an Actor `alice` funded on both chains:
    #   tkx.on(earth).transfer(alice.address, 100 * WAD, from_=earth.deployer).wait()
    #   tkx.bridge_token(alice, 100 * WAD, to_chain=mars, src_chain=earth)
```

Register the `RelayBridge` and the `BridgeableToken` before any asymmetric
per-chain transactions, so the deployer nonces stay equal and the bridge and
token land at parity addresses.

## `ERC20` helper

Wraps a deployed plain ERC-20 with the common entry points and forwards anything
else to the underlying contract. Deploy with the classmethod:

```python
ERC20.deploy(chain, name, symbol, supply=0, from_=None)
```

It exposes `balanceOf`, `allowance`, `totalSupply`, `symbol`, and the mutators
`send`, `transferFrom`, `approve`, `mint` (each of which submits and waits), plus
`contract` for the underlying `Contract`.
