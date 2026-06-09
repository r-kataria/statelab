from statelab.core.wallet import DEFAULT_MNEMONIC, derive_account


def test_derive_account_is_deterministic():
    a = derive_account(0, DEFAULT_MNEMONIC)
    b = derive_account(0, DEFAULT_MNEMONIC)
    assert a.address == b.address


def test_account_zero_is_anvil_first_dev_account():
    # Anvil's default first account for the standard test mnemonic.
    acct = derive_account(0, DEFAULT_MNEMONIC)
    assert acct.address == "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
