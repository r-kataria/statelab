"""StateLab: a programmable, multi-chain EVM simulator built on Anvil."""
from __future__ import annotations

from .core.actor import Actor
from .core.chain import Chain
from .core.contract import Contract, Pair, PendingTx
from .core.lab import Lab
from .core.plugin import Context, Plugin, make_plugin_rng
from .core.time import Distribution, TimeControl, TimeValue
from .core.wallet import Wallet
from .plugins.amm import SimpleAMM
from .plugins.bridge import PendingBridgeTx, RelayBridge
from .plugins.monitor import Monitor
from .plugins.token import ERC20, BridgeableToken, Token
from .plugins.trader import RandomTrader

__version__ = "0.1.0"

# ``Time(12)`` -> ``TimeValue(12)`` convenience clock.
Time = TimeControl()

__all__ = [
    "Lab", "Time", "TimeControl", "TimeValue", "Distribution",
    "Chain", "Wallet", "Contract", "Pair", "PendingTx",
    "Actor", "Plugin", "Context", "make_plugin_rng",
    "RelayBridge", "PendingBridgeTx", "BridgeableToken", "ERC20",
    "Token", "SimpleAMM", "Monitor", "RandomTrader",
]
