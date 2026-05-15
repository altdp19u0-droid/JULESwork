
import shared_logic as sl
import json
import os

def test_standardization():
    # Setup owners
    owners = {"0x123": "My Wallet", "0xabc": "CEX"}
    sl.save_owner_accounts(owners)

    test_cases = [
        "0x123",
        "My Wallet",
        "0x123 (My Wallet)",
        "Unknown",
        "0x456 (New Label)",
        "CEX (0xabc)"
    ]

    print("Standardization Tests:")
    for tc in test_cases:
        res = sl.standardize_address_string(tc)
        print(f"'{tc}' -> '{res}'")

if __name__ == "__main__":
    test_standardization()
