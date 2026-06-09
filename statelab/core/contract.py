"""Deployed-contract wrapper with ABI-driven attribute access.

``Contract.deploy`` takes a precompiled artifact dict (``{"abi", "bytecode"}``),
deploys it, and exposes every ABI function as an attribute. State-modifying
calls return a :class:`PendingTx`; view/pure calls return the decoded value.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from web3 import Web3
from web3.contract.contract import ContractFunction

from .wallet import Wallet

log = logging.getLogger("statelab")


@dataclass
class PendingTx:
    """Handle returned by state-modifying contract calls.

    ``wait()`` advances chain blocks (mining locally) until the transaction
    has a receipt, then decodes ``return_value`` from the function ABI.
    """
    tx_hash: bytes
    chain: Any  # Chain (forward ref)
    contract: "Contract"
    function: Optional[ContractFunction] = None
    fn_name: Optional[str] = None
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    receipt: Any = None
    return_value: Any = None
    _waited: bool = False

    def wait(self, max_blocks: int = 100, timeout: float = 30.0) -> "PendingTx":
        """Mine blocks until the tx is included; populate receipt + return_value.

        On a no-mining chain there is nothing to wait for besides our own
        ``evm_mine`` calls, so once ``max_blocks`` mines have failed to land
        the tx we raise rather than fall through to ``wait_for_transaction_receipt``
        which would block uselessly for ``timeout`` seconds.
        """
        if self._waited:
            return self
        w3 = self.chain.w3
        log.debug("PendingTx.wait start tx=%s chain=%s", self.tx_hash.hex()[:10], self.chain.name)
        mined = 0
        for i in range(max_blocks):
            try:
                self.receipt = w3.eth.get_transaction_receipt(self.tx_hash)
                if self.receipt is not None:
                    log.debug("PendingTx.wait got receipt tx=%s after %d mines", self.tx_hash.hex()[:10], mined)
                    break
            except Exception:
                pass
            self.chain.mine()
            mined += 1
            if mined and mined % 20 == 0:
                log.warning("PendingTx.wait stuck tx=%s chain=%s mined=%d (no receipt yet)",
                                 self.tx_hash.hex()[:10], self.chain.name, mined)
        if self.receipt is None:
            log.error("PendingTx.wait NEVER LANDED tx=%s chain=%s after %d mines",
                           self.tx_hash.hex()[:10], self.chain.name, mined)
            raise RuntimeError(
                f"PendingTx.wait: tx {self.tx_hash.hex()} on chain {self.chain.name} "
                f"never landed after {mined} mines"
            )
        # Decode return value via eth_call against the same block + state.
        if self.function is not None and self.receipt is not None:
            try:
                block_num = self.receipt.blockNumber
                # Replay the call against the parent block to recover return data.
                self.return_value = self.function.call(
                    {"from": self.receipt["from"]}, block_identifier=block_num - 1
                )
            except Exception:
                self.return_value = None
        self._waited = True
        return self

    @property
    def status(self) -> Optional[int]:
        return None if self.receipt is None else int(self.receipt["status"])

    @property
    def events(self) -> list[dict]:
        """Decoded events from this tx's receipt."""
        if self.receipt is None:
            return []
        out = []
        for log in self.receipt["logs"]:
            for evname, evobj in self.contract.events.items():
                try:
                    decoded = evobj.process_log(log)
                    out.append({"name": evname, "args": dict(decoded["args"])})
                    break
                except Exception:
                    continue
        return out


class Contract:
    """A deployed contract with ABI-driven attribute wrapping.

    Use :meth:`deploy` to build + deploy + wrap in one call. The instance
    exposes every ABI function as an attribute; state-modifying calls return
    :class:`PendingTx` (require ``from_=wallet``), view/pure calls return the
    decoded value directly.
    """

    def __init__(self, chain, address: str, abi: list, name: str = "Contract") -> None:
        self.chain = chain
        self.address = Web3.to_checksum_address(address)
        self.abi = abi
        self.name = name
        self._w3_contract = chain.w3.eth.contract(address=self.address, abi=abi)
        # Index ABI for quick attribute lookup.
        self._fn_abis: dict[str, dict] = {}
        for entry in abi:
            if entry.get("type") == "function":
                self._fn_abis[entry["name"]] = entry
        self.events: dict[str, Any] = {
            e["name"]: getattr(self._w3_contract.events, e["name"])()
            for e in abi
            if e.get("type") == "event"
        }

    # ---- deployment ---------------------------------------------------------

    @classmethod
    def deploy(
        cls,
        chain,
        artifact: dict,
        constructor_args: Optional[list] = None,
        contract_name: Optional[str] = None,
        from_: Optional[Wallet] = None,
        value: int = 0,
        gas: int = 6_000_000,
    ) -> "Contract":
        """Deploy a contract from a precompiled artifact dict and wrap it."""
        art = artifact
        abi = art["abi"]
        bytecode = art["bytecode"]["object"] if isinstance(art["bytecode"], dict) else art["bytecode"]
        deployer = from_ or chain.deployer
        w3 = chain.w3
        Factory = w3.eth.contract(abi=abi, bytecode=bytecode)
        nonce = w3.eth.get_transaction_count(deployer.address, "pending")
        tx = Factory.constructor(*(constructor_args or [])).build_transaction({
            "from": deployer.address,
            "nonce": nonce,
            "gas": int(gas),
            "gasPrice": w3.eth.gas_price or 1_000_000_000,
            "chainId": chain.chain_id,
            "value": int(value),
        })
        signed = deployer.account.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        chain.mine()
        receipt = w3.eth.wait_for_transaction_receipt(h, timeout=30)
        if int(receipt["status"]) != 1:
            raise RuntimeError(f"deploy failed: status={receipt['status']}")
        cname = contract_name or "Contract"
        return cls(chain, receipt["contractAddress"], abi, name=cname)

    # ---- ABI auto-wrap ------------------------------------------------------

    def __getattr__(self, item: str) -> Callable[..., Any]:
        # Called only when normal attribute lookup fails.
        fn_abi = self.__dict__.get("_fn_abis", {}).get(item)
        if fn_abi is None:
            raise AttributeError(f"{self.name} has no function {item!r}")
        return self._make_caller(item, fn_abi)

    def _make_caller(self, name: str, fn_abi: dict) -> Callable[..., Any]:
        is_view = fn_abi.get("stateMutability") in ("view", "pure")

        def caller(*args, from_: Optional[Wallet] = None,
                   value: int = 0, gas: int = 2_000_000, **kwargs) -> Any:
            w3 = self.chain.w3
            fn = getattr(self._w3_contract.functions, name)(*args)
            if is_view:
                return fn.call({"from": from_.address if from_ else self.chain.deployer.address})
            if from_ is None:
                raise ValueError(
                    f"{self.name}.{name}: state-modifying call requires from_=Wallet(...)"
                )
            nonce = w3.eth.get_transaction_count(from_.address, "pending")
            tx = fn.build_transaction({
                "from": from_.address,
                "nonce": nonce,
                "gas": int(gas),
                "gasPrice": w3.eth.gas_price or 1_000_000_000,
                "chainId": self.chain.chain_id,
                "value": int(value),
            })
            signed = from_.account.sign_transaction(tx)
            h = w3.eth.send_raw_transaction(signed.raw_transaction)
            return PendingTx(
                tx_hash=h,
                chain=self.chain,
                contract=self,
                function=fn,
                fn_name=name,
                args=args,
                kwargs=kwargs,
            )

        caller.__name__ = name
        caller.__qualname__ = f"{self.name}.{name}"
        return caller

    def __dir__(self) -> list[str]:  # so REPL completion works
        return sorted(set(list(self.__dict__.keys()) + list(self._fn_abis.keys())))

    def __repr__(self) -> str:
        return f"Contract(name={self.name!r}, address={self.address}, chain={self.chain.name!r})"


class Pair:
    """A pair of identically-addressed deployments across chains.

    Provides ergonomic accessors:
        pair.earth, pair.mars          # by canonical chain name
        pair.on(chain)                 # generically
        pair.address                   # shared CREATE2 address
    """

    def __init__(self, name: str, contracts: dict[str, Contract]) -> None:
        if not contracts:
            raise ValueError("Pair requires at least one Contract")
        addrs = {c.address for c in contracts.values()}
        if len(addrs) != 1:
            raise ValueError(
                f"Pair {name!r}: contracts do not share an address: "
                f"{ {n: c.address for n, c in contracts.items()} }"
            )
        self.name = name
        self._by_chain: dict[str, Contract] = dict(contracts)
        self.address = next(iter(addrs))

    def on(self, chain) -> Contract:
        cname = chain.name if hasattr(chain, "name") else str(chain)
        if cname not in self._by_chain:
            raise KeyError(f"Pair {self.name!r} has no instance on chain {cname!r}")
        return self._by_chain[cname]

    @property
    def earth(self) -> Contract:
        return self.on_name("earth")

    @property
    def mars(self) -> Contract:
        return self.on_name("mars")

    def on_name(self, chain_name: str) -> Contract:
        if chain_name not in self._by_chain:
            raise KeyError(f"Pair {self.name!r} has no instance on chain {chain_name!r}")
        return self._by_chain[chain_name]

    def __iter__(self):
        return iter(self._by_chain.values())

    def __repr__(self) -> str:
        return (f"Pair(name={self.name!r}, address={self.address}, "
                f"chains={list(self._by_chain.keys())})")
