# Bundled plugins

StateLab ships five plugins, all importable from the top-level package. Each
page covers its constructor, key methods, and a usage snippet.

- [token](token.md) - `Token` (plain ERC-20), `BridgeableToken` (cross-chain),
  and the `ERC20` helper.
- [bridge](bridge.md) - `RelayBridge`, a two-chain bridge with a redundant,
  optionally lossy relay, plus the `PendingBridgeTx` handle.
- [amm](amm.md) - `SimpleAMM`, a constant-product market maker.
- [monitor](monitor.md) - `Monitor`, sampling a callable into `monitors.csv`.
- [trader](trader.md) - `RandomTrader`, a coin-flipping swap actor.

To write your own, see [../writing-a-plugin.md](../writing-a-plugin.md). The
lane-options plugin ships as a separate package and is documented with its own
code.
