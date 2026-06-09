"""CREATE2 same-address deployment primitive.

Deploys arbitrary creation code at an identical address on every chain via a
shared ``BridgeableERC20Factory`` (CREATE2). Extracted from the original
``Sim.deploy_pair`` machinery. Domain-specific constructor encoding (e.g. the
BridgeableERC20 peer scheme) lives in the calling plugin, not here.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from web3 import Web3

from .build import load_artifact
from .contract import Contract, Pair

_FACTORY_PKG = "statelab.contracts"
_FACTORY_SOL = "BridgeableERC20Factory.sol"
_FACTORY_NAME = "BridgeableERC20Factory"


def salt_from_name(name: str) -> bytes:
    """Deterministic 32-byte CREATE2 salt from a name."""
    return hashlib.sha256(("statelab-salt:" + name).encode("utf-8")).digest()


class Create2Deployer:
    """Deploys creation code at a parity address across a fixed chain set."""

    def __init__(self, chains: list[Any]) -> None:
        if not chains:
            raise ValueError("Create2Deployer: chains must be non-empty")
        self._chains = list(chains)
        self._factory_artifact = load_artifact(
            package=_FACTORY_PKG, sol_file=_FACTORY_SOL, contract_name=_FACTORY_NAME)
        self._factory_pair: Optional[Pair] = None

    def _ensure_factory(self) -> Pair:
        if self._factory_pair is not None:
            return self._factory_pair
        self._require_matching_nonces()
        deployed: dict[str, Contract] = {}
        expected: Optional[str] = None
        for chain in self._chains:
            c = Contract.deploy(chain, self._factory_artifact,
                                contract_name=_FACTORY_NAME, from_=chain.deployer)
            if expected is None:
                expected = c.address
            elif c.address != expected:
                raise RuntimeError(
                    f"create2: factory landed at different addresses "
                    f"({expected} vs {c.address} on {chain.name})")
            deployed[chain.name] = c
        self._factory_pair = Pair("create2-factory", deployed)
        return self._factory_pair

    def _require_matching_nonces(self) -> None:
        nonces = {
            c.name: c.w3.eth.get_transaction_count(c.deployer.address)
            for c in self._chains
        }
        if len(set(nonces.values())) > 1:
            raise RuntimeError(
                f"create2: deployer nonces differ across chains: {nonces}; "
                f"cannot achieve factory-address parity (deploy the bridge/factory "
                f"before any asymmetric per-chain transactions)")

    def deploy_pair(self, name: str, creation_code: bytes, abi: list,
                    contract_name: str, salt: Optional[bytes] = None) -> Pair:
        """Deploy ``creation_code`` at the same address on every chain."""
        factory = self._ensure_factory()
        salt_bytes = salt if salt is not None else salt_from_name(name)
        predicted = self._predict(factory, salt_bytes, creation_code)
        deployed: dict[str, Contract] = {}
        for chain in self._chains:
            fac = factory.on(chain)
            # Use _make_caller directly: the factory ABI has a function literally
            # named "deploy", but getattr(fac, "deploy") would resolve to the
            # Contract.deploy classmethod (it's in the class __dict__, so __getattr__
            # never fires). The private path targets the ABI function instead.
            deploy_fn = fac._make_caller("deploy", fac._fn_abis["deploy"])
            tx = deploy_fn(salt_bytes, creation_code, from_=chain.deployer)
            tx.wait()
            if tx.status != 1:
                raise RuntimeError(
                    f"create2: deploy failed on {chain.name}: receipt={tx.receipt}")
            deployed[chain.name] = Contract(chain, predicted, abi, name=contract_name)
        return Pair(name, deployed)

    def _predict(self, factory: Pair, salt: bytes, creation_code: bytes) -> str:
        first = factory.on(self._chains[0])
        predicted = Web3.to_checksum_address(first.predict(salt, creation_code))
        for chain in self._chains[1:]:
            here = Web3.to_checksum_address(factory.on(chain).predict(salt, creation_code))
            if here != predicted:
                raise RuntimeError(
                    f"create2: prediction differs across chains "
                    f"({predicted} vs {here} on {chain.name})")
        return predicted
