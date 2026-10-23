import io
import unittest
import pandas as pd
from sanctuary_app.modules.importers.importer_bleap import import_bleap_csv
from sanctuary_app.modules.trait_manager import calculate_token_balances

class TestBleapSubaccounts(unittest.TestCase):
    def test_bleap_subaccounts_import_and_balances(self):
        csv_data = """Type,Created At,Completed At,Description,Amount,Fees,Currency,Status
Top Up,2025-09-02 16:52:50,2025-09-02 16:52:55,Bank Transfer (Buy),+1000.00,0,EURA,COMPLETED
Exchange,2025-09-05 11:34:05,2025-09-05 11:34:26,Exchange EUR -> USD,99.99,0,USDC,COMPLETED
Earn Deposit,2025-09-05 11:35:19,2025-09-05 11:35:35,Earn Deposit,-100.00,0,USDC,COMPLETED
Earn Withdrawal,2025-09-05 11:37:54,2025-09-05 11:38:12,Earn Withdrawal,+1.00,0,USDC,COMPLETED
Withdrawal,2025-09-02 17:08:06,,Wallet Withdrawal,-1.00,0,USDC,COMPLETED
"""
        file_obj = io.StringIO(csv_data)
        df_sanctuary = import_bleap_csv(file_obj)

        self.assertFalse(df_sanctuary.empty)
        self.assertIn("ID du projet", df_sanctuary.columns)
        self.assertEqual(set(df_sanctuary["ID du projet"].unique()), {"BLEAP_WALLET", "BLEAP_EARN"})

        balances = calculate_token_balances(df_sanctuary)
        self.assertFalse(balances.empty)

        wallet_usdc = balances[(balances["Portefeuille"] == "Bleap Wallet") & (balances["Token"] == "USDC")]
        earn_usdc = balances[(balances["Portefeuille"] == "Bleap Earn Vault") & (balances["Token"] == "USDC")]

        self.assertFalse(wallet_usdc.empty)
        self.assertFalse(earn_usdc.empty)

        self.assertEqual(earn_usdc["Solde_Net"].values[0], 99.0)

if __name__ == "__main__":
    unittest.main()
