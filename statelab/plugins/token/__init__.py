"""Bridgeable token plugin + a plain ERC20 helper (StateLab plugin).

This package ships two things:

* :class:`ERC20`: a thin convenience wrapper around a deployed ``ERC20``
  contract, kept for non-bridged token scenarios. ``ERC20.deploy`` loads the
  shipped artifact and forwards the constructor args.
* :class:`BridgeableToken`: a :class:`~statelab.core.plugin.Plugin` that
  deploys a ``BridgeableERC20`` at the same address on every chain via
  ``lab.create2`` and wires each side's cross-chain peer. Token movement is
  burn-on-source / mint-on-destination, routed by a :class:`RelayBridge`.

CREATE2 address parity requires byte-identical creation code on every chain.
The constructor therefore takes ``peerChainId=0`` / ``peerToken=address(0)``
(the peer is wired afterwards via ``setPeer``) and the same ``bridge`` address
and ``supply_per_chain`` on each chain. The ``RelayBridge`` plugin guarantees
the bridge address matches, and ``supply_per_chain`` must not be varied per
chain or parity breaks.
"""
from __future__ import annotations

from typing import Optional

from eth_abi import encode as abi_encode
from web3 import Web3

from ...core.build import load_artifact
from ...core.contract import Contract
from ...core.create2 import salt_from_name
from ...core.plugin import Plugin
from ...core.wallet import Wallet


# ====================================================================== #
# ERC20 helper (plain, non-bridged token)
# ====================================================================== #

class ERC20:
    """Thin convenience wrapper around a deployed plain ``ERC20`` contract.

    The wrapper exposes the common entry points by name and forwards
    everything else to the underlying ABI-driven :class:`Contract`, so e.g.
    ``erc20.totalSupply()`` works without explicit plumbing.
    """

    def __init__(self, contract: Contract) -> None:
        self._c = contract
        self.address = contract.address
        self.chain = contract.chain

    # ---- deployment ---------------------------------------------------------

    @classmethod
    def deploy(
        cls,
        chain,
        name: str,
        symbol: str,
        supply: int = 0,
        from_: Optional[Wallet] = None,
    ) -> "ERC20":
        """Deploy the shipped ``ERC20.sol`` artifact and wrap it."""
        artifact = load_artifact(
            package="statelab.plugins.token",
            sol_file="ERC20.sol",
            contract_name="ERC20",
        )
        contract = Contract.deploy(
            chain,
            artifact,
            constructor_args=[name, symbol, int(supply)],
            from_=from_,
        )
        # artifact name is "ERC20"; rename for nicer repr.
        contract.name = symbol
        return cls(contract)

    # ---- views --------------------------------------------------------------

    def balanceOf(self, who) -> int:
        addr = who.address if hasattr(who, "address") else who
        return int(self._c.balanceOf(Web3.to_checksum_address(addr)))

    def allowance(self, owner, spender) -> int:
        o = owner.address if hasattr(owner, "address") else owner
        s = spender.address if hasattr(spender, "address") else spender
        return int(self._c.allowance(Web3.to_checksum_address(o),
                                     Web3.to_checksum_address(s)))

    def totalSupply(self) -> int:
        return int(self._c.totalSupply())

    @property
    def symbol(self) -> str:
        return self._c.symbol()

    # ---- mutators -----------------------------------------------------------

    def send(self, to, amount: int, from_: Wallet):
        """Transfer ``amount`` tokens from ``from_`` to ``to`` and wait."""
        addr = to.address if hasattr(to, "address") else to
        return self._c.transfer(
            Web3.to_checksum_address(addr), int(amount), from_=from_
        ).wait()

    def transferFrom(self, src, dst, amount: int, from_: Wallet):
        sa = src.address if hasattr(src, "address") else src
        da = dst.address if hasattr(dst, "address") else dst
        return self._c.transferFrom(
            Web3.to_checksum_address(sa),
            Web3.to_checksum_address(da),
            int(amount),
            from_=from_,
        ).wait()

    def approve(self, spender, amount: int, from_: Wallet):
        addr = spender.address if hasattr(spender, "address") else spender
        return self._c.approve(
            Web3.to_checksum_address(addr), int(amount), from_=from_
        ).wait()

    def mint(self, to, amount: int, from_: Wallet):
        """Public mint helper. Anyone can call; harness-only contract."""
        addr = to.address if hasattr(to, "address") else to
        return self._c.mint(
            Web3.to_checksum_address(addr), int(amount), from_=from_
        ).wait()

    # ---- escape hatch to the underlying Contract ----------------------------

    @property
    def contract(self) -> Contract:
        return self._c

    def __repr__(self) -> str:
        return (f"ERC20(symbol={self._c.name!r}, address={self.address}, "
                f"chain={self.chain.name!r})")


# ====================================================================== #
# BridgeableToken plugin
# ====================================================================== #

class BridgeableToken(Plugin):
    """A ``BridgeableERC20`` deployed at the same address on every chain.

    ``setup`` builds byte-identical creation code (the bridge address is shared
    across chains, and ``peerChainId``/``peerToken`` are held at zero), deploys
    a CREATE2 pair via ``lab.create2``, then wires each side's peer to the
    shared address. ``bridge_token`` burns on the source side and routes the
    mint through the :class:`RelayBridge`.
    """

    def __init__(self, name_, symbol, bridge, supply_per_chain=0,
                 plugin_name=None):
        self.name = plugin_name or f"token:{symbol}"
        self.token_name = name_
        self.symbol = symbol
        self.bridge = bridge            # a RelayBridge plugin instance
        self.supply_per_chain = int(supply_per_chain)
        self.pair = None

    def setup(self, lab):
        art = load_artifact(package="statelab.plugins.token",
                            sol_file="BridgeableERC20.sol",
                            contract_name="BridgeableERC20")
        # bridge address must be identical across chains (RelayBridge asserts this)
        bridge_addr = self.bridge.address_on(lab.chains[0])
        creation = self._creation_code(art, bridge_addr)
        self.pair = lab.create2.deploy_pair(
            self.symbol, creation, art["abi"], "BridgeableERC20",
            salt=salt_from_name(self.name))
        # wire peers (same address on both sides by CREATE2 parity)
        for chain in lab.chains:
            tx = self.pair.on(chain).setPeer(self.pair.address, from_=chain.deployer)
            tx.wait()
            if tx.status != 1:
                raise RuntimeError(
                    f"BridgeableToken.setup: setPeer failed on {chain.name}")

    def _creation_code(self, art, bridge_addr):
        bytecode = art["bytecode"]["object"]
        if bytecode.startswith("0x"):
            bytecode = bytecode[2:]
        # ctor: (name, symbol, initialSupply, bridge, peerChainId=0, peerToken=0)
        # peerChainId/peerToken held to 0 for creation-code parity across chains.
        args = abi_encode(
            ["string", "string", "uint256", "address", "uint256", "address"],
            [self.token_name, self.symbol, self.supply_per_chain,
             Web3.to_checksum_address(bridge_addr), 0, "0x" + "0" * 40])
        return bytes.fromhex(bytecode) + args

    def on(self, chain):
        return self.pair.on(chain)

    def balance_of(self, who, chain):
        addr = who.address if hasattr(who, "address") else who
        return int(self.on(chain).balanceOf(Web3.to_checksum_address(addr)))

    def bridge_token(self, actor, amount, to_chain, src_chain):
        # The bridge is two-chain, so the destination is implied by src_chain;
        # validate to_chain agrees rather than silently ignoring it.
        expected_dst = (self.bridge.b if src_chain.name == self.bridge.a.name
                        else self.bridge.a)
        if to_chain.name != expected_dst.name:
            raise ValueError(
                f"bridge_token: to_chain {to_chain.name!r} is not the bridge peer "
                f"of src_chain {src_chain.name!r} (expected {expected_dst.name!r})")
        src_token = self.on(src_chain)
        wallet = actor.wallet_on(src_chain)
        return self.bridge.bridge_token_via(
            src_token, actor.address, int(amount), src_chain, wallet)


# ====================================================================== #
# Token plugin (plain single-chain ERC20)
# ====================================================================== #

class Token(Plugin):
    """A plain single-chain ERC20 as a plugin. The chain deployer holds the
    initial supply (the ERC20 constructor mints it to the deployer)."""

    def __init__(self, name_, symbol, chain, supply=0, plugin_name=None):
        self.name = plugin_name or f"erc20:{symbol}"
        self.token_name = name_
        self.symbol = symbol
        self.chain = chain
        self.supply = int(supply)
        self.erc20 = None

    def setup(self, lab):
        self.erc20 = ERC20.deploy(self.chain, self.token_name, self.symbol, self.supply)

    @property
    def address(self):
        return self.erc20.address

    @property
    def contract(self):
        return self.erc20.contract

    def balance_of(self, who):
        return self.erc20.balanceOf(who)

    def approve(self, owner_wallet, spender, amount):
        # Delegate to the ERC20 helper rather than re-implementing the
        # checksum/int/.wait() logic (keeps one approve implementation).
        return self.erc20.approve(spender, int(amount), from_=owner_wallet)
