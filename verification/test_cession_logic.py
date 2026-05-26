import shared_logic as sl

def test_cession_logic():
    # Case 1: Imposable Sell (Correct)
    r1 = {"Amount": -1.0, "Asset": "BTC", "Imposable": True, "Category": "Vente"}
    assert sl.is_cession_imposable_robust(r1) == True

    # Case 2: Imposable Buy (Should be False)
    r2 = {"Amount": 1.0, "Asset": "BTC", "Imposable": True, "Category": "Achat"}
    assert sl.is_cession_imposable_robust(r2) == False

    # Case 3: Sell not marked imposable but category is Vente (Correct)
    r3 = {"Amount": -1.0, "Asset": "BTC", "Imposable": False, "Category": "Vente (Crypto -> Banque)"}
    assert sl.is_cession_imposable_robust(r3) == True

    # Case 4: EUR outflow (Should be False)
    r4 = {"Amount": -100.0, "Asset": "EUR", "Imposable": True, "Category": "Vente"}
    assert sl.is_cession_imposable_robust(r4) == False

    # Case 5: Spam (Should be False)
    r5 = {"Amount": -1.0, "Asset": "BTC", "Imposable": True, "Audit_Status": "Spam"}
    assert sl.is_cession_imposable_robust(r5) == False

    print("✅ All cession logic tests passed!")

if __name__ == "__main__":
    test_cession_logic()
