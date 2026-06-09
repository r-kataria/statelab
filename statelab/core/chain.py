"""Chain wrapper: owns a web3.py client pointed at an Anvil instance, plus
deterministic wallet derivation and explicit block control.

The harness drives blocks manually via ``evm_mine``, so Anvil must run with
``--no-mining``; the chain's "blocktime" is purely a simulated quantity used by
the simulator loop to decide when to mine the next block."""
from __future__ import annotations

from typing import Optional

from web3 import HTTPProvider, Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .time import TimeValue
from .wallet import DEFAULT_MNEMONIC, Wallet, derive_account


DEFAULT_RPC_PORTS = {"earth": 8545, "mars": 8546}


class Chain:
    """An Anvil-backed EVM chain.

    Parameters
    ----------
    name:
        Logical name; used to pick a default port and for log tags.
    chain_id:
        Expected EVM chain id (asserted against the node).
    blocktime:
        Simulated block interval as a :class:`TimeValue`.
    rpc_url:
        Override; defaults to ``http://127.0.0.1:<port>`` based on ``name``.
    """

    def __init__(
        self,
        name: str,
        chain_id: int,
        blocktime: TimeValue,
        rpc_url: Optional[str] = None,
        mnemonic: str = DEFAULT_MNEMONIC,
    ) -> None:
        self.name = name
        self.chain_id = int(chain_id)
        self.blocktime = blocktime
        self.mnemonic = mnemonic
        port = DEFAULT_RPC_PORTS.get(name, 8545)
        self.rpc_url = rpc_url or f"http://127.0.0.1:{port}"
        # Anvil is fast; bump request timeout modestly for slower CI.
        self.w3 = Web3(HTTPProvider(self.rpc_url, request_kwargs={"timeout": 30}))
        # Anvil is PoA-shaped; the middleware strips the extra-data field length check.
        try:
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception:  # pragma: no cover - middleware already present
            pass
        self._wallets: dict[str, Wallet] = {}
        self._next_wallet_idx: int = 1  # 0 reserved for deployer
        self._last_block_time: int = 0  # in simulated base units
        # Verify connectivity & chain id.
        observed = self.w3.eth.chain_id
        if observed != self.chain_id:
            raise RuntimeError(
                f"chain {name}: expected chain_id={self.chain_id} but node reports {observed}"
            )
        # Deployer: account 0 of the mnemonic (matches Anvil's default funded set).
        self._deployer_account = derive_account(0, self.mnemonic)
        self.deployer = Wallet(name="deployer", chain=self, account=self._deployer_account)
        self._wallets["deployer"] = self.deployer

    # ---- wallets ------------------------------------------------------------

    def wallet(self, name: str, funded_native: int = 0) -> Wallet:
        """Return (or create) a wallet on this chain.

        ``funded_native`` is funded from ``self.deployer`` if positive AND the
        wallet's current balance is below the requested amount.
        """
        if name in self._wallets:
            w = self._wallets[name]
        else:
            acct = derive_account(self._next_wallet_idx, self.mnemonic)
            self._next_wallet_idx += 1
            w = Wallet(name=name, chain=self, account=acct)
            self._wallets[name] = w
        if funded_native > 0 and w.native_balance() < funded_native:
            deficit = funded_native - w.native_balance()
            self._send_native(self.deployer, w.address, deficit)
        return w

    def get_wallet(self, name: str) -> Optional[Wallet]:
        return self._wallets.get(name)

    # ---- block control ------------------------------------------------------

    def set_next_block_timestamp(self, unix_ts: int) -> None:
        self.w3.provider.make_request("evm_setNextBlockTimestamp", [int(unix_ts)])

    def mine(self, timestamp: Optional[int] = None) -> int:
        """Mine one block. Optionally pin its timestamp first."""
        if timestamp is not None:
            try:
                self.set_next_block_timestamp(int(timestamp))
            except Exception:
                # If the requested timestamp is <= current head, Anvil refuses;
                # fall back to a 1s bump.
                head_ts = self.w3.eth.get_block("latest")["timestamp"]
                self.set_next_block_timestamp(int(head_ts) + 1)
        self.w3.provider.make_request("evm_mine", [])
        return self.w3.eth.block_number

    def snapshot(self) -> str:
        res = self.w3.provider.make_request("evm_snapshot", [])
        return res["result"]

    def revert(self, snap_id: str) -> bool:
        res = self.w3.provider.make_request("evm_revert", [snap_id])
        return bool(res["result"])

    def set_balance(self, address: str, wei: int) -> None:
        self.w3.provider.make_request(
            "anvil_setBalance", [Web3.to_checksum_address(address), hex(int(wei))]
        )

    def impersonate(self, address: str) -> None:
        self.w3.provider.make_request(
            "anvil_impersonateAccount", [Web3.to_checksum_address(address)]
        )

    def stop_impersonating(self, address: str) -> None:
        self.w3.provider.make_request(
            "anvil_stopImpersonatingAccount", [Web3.to_checksum_address(address)]
        )

    # ---- low-level send helper ---------------------------------------------

    def _send_native(self, from_wallet: Wallet, to: str, value: int) -> str:
        nonce = self.w3.eth.get_transaction_count(from_wallet.address, "pending")
        tx = {
            "from": from_wallet.address,
            "to": Web3.to_checksum_address(to),
            "value": int(value),
            "nonce": nonce,
            "gas": 21_000,
            "gasPrice": self.w3.eth.gas_price or 1_000_000_000,
            "chainId": self.chain_id,
        }
        signed = from_wallet.account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        # mine immediately to confirm funding
        self.mine()
        self.w3.eth.wait_for_transaction_receipt(h, timeout=10)
        return h.hex()

    # ---- misc ---------------------------------------------------------------

    def head_timestamp(self) -> int:
        return self.w3.eth.get_block("latest")["timestamp"]

    def head_number(self) -> int:
        return self.w3.eth.block_number

    def __repr__(self) -> str:
        return f"Chain(name={self.name!r}, chain_id={self.chain_id}, blocktime={int(self.blocktime)})"
