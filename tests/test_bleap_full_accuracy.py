import io
import unittest
import pandas as pd
from sanctuary_app.modules.importers.importer_bleap import import_bleap_csv
from sanctuary_app.modules.sanctuary_manager import save_to_sanctuary

RAW_USER_CSV = """Type,Created At,Completed At,Description,Amount,Fees,Currency,Status
Exchange,2026-04-10 00:10:43,2026-04-10 00:10:53,Exchange EUR -> EUR,0.21,0 EUR,EURE,COMPLETED
Earn Withdrawal,2026-04-10 00:09:55,2026-04-10 00:10:02,Earn Withdrawal,+0.21,0 EUR,EUR,COMPLETED
Exchange,2026-03-03 23:06:34,2026-03-03 23:06:51,Exchange EUR -> EUR,1.00,0 EURE,EUR,COMPLETED
Earn Deposit,2025-12-29 12:58:15,2025-12-29 12:58:28,Earn Deposit,-4 472.00,0 USDC,USDC,COMPLETED
Earn Withdrawal,2025-12-29 12:57:21,2025-12-29 12:57:34,Earn Withdrawal,+4 471.00,0 USD,USD,COMPLETED
Withdrawal,2025-12-29 10:41:18,,Wallet Withdrawal,-6 000.00,0 USDC,USDC,COMPLETED
Earn Withdrawal,2025-12-29 10:39:21,2025-12-29 10:39:38,Earn Withdrawal,+6 000.00,0 USD,USD,COMPLETED
Deposit,2025-12-29 05:24:49,2025-12-29 05:24:50,Wallet Deposit,+1.00,0 USDC,USDC,COMPLETED
Top Up,2025-11-28 06:12:11,2025-11-28 06:14:44,Bank Transfer (Buy),+301.09,0 USDC,USDC,COMPLETED
Withdrawal,2025-11-27 13:09:27,,Wallet Withdrawal,-120.00,0 USDC,USDC,COMPLETED
Earn Withdrawal,2025-11-27 13:04:07,2025-11-27 13:04:29,Earn Withdrawal,+120.00,0 USD,USD,COMPLETED
Earn Deposit,2025-11-12 11:37:03,2025-11-12 11:37:14,Earn Deposit,-1 731.11,0 USDC,USDC,COMPLETED
Exchange,2025-11-12 11:35:38,2025-11-12 11:35:55,Exchange EUR -> USD,1 730.32,0 USDC,USDC,COMPLETED
Top Up,2025-11-12 11:32:16,2025-11-12 11:32:21,Bank Transfer (Buy),+1 500.00,0 EURA,EURA,COMPLETED
Earn Deposit,2025-11-05 20:48:08,2025-11-05 20:48:31,Earn Deposit,-1 143.00,0 USDC,USDC,COMPLETED
Exchange,2025-11-05 20:46:45,2025-11-05 20:47:03,Exchange EUR -> USD,1 142.76,0 USDC,USDC,COMPLETED
Earn Withdrawal,2025-11-05 20:43:53,2025-11-05 20:45:48,Earn Withdrawal,+998.00,0 EUR,EUR,COMPLETED
Earn Withdrawal,2025-11-05 17:32:04,2025-11-05 17:32:22,Earn Withdrawal,+1.00,0 EUR,EUR,COMPLETED
Top Up,2025-11-04 18:48:12,2025-11-04 18:50:22,Bank Transfer (Buy),+606.84,0 USDC,USDC,COMPLETED
Earn Deposit,2025-11-04 18:42:09,2025-11-04 18:43:47,Earn Deposit,-1 000.00,0 EURA,EURA,COMPLETED
Top Up,2025-11-04 18:27:38,2025-11-04 18:27:43,Bank Transfer (Buy),+1 000.00,0 EURA,EURA,COMPLETED
Off-Ramp,2025-11-03 20:22:22,,Bank Transfer (Sell),-1.15,0 USDC,USDC,CANCELLED
Withdrawal,2025-09-15 12:06:44,,Wallet Withdrawal,-0.0004421,0 ETH,ETH,COMPLETED
Trade,2025-09-15 12:04:42,2025-09-15 12:04:57,Trade USD -> ETH,0.00044225,0 ETH,ETH,COMPLETED
Withdrawal,2025-09-15 11:57:18,,Wallet Withdrawal,-1.00,0 USDC,USDC,COMPLETED
Earn Withdrawal,2025-09-15 11:37:54,2025-09-15 11:38:12,Earn Withdrawal,+1.00,0 USD,USD,COMPLETED
Deposit,2025-09-15 11:26:51,2025-09-15 11:26:52,Wallet Deposit,+0.99,0 USDC,USDC,COMPLETED
Bridge,2025-09-11 23:23:21,2025-09-11 23:25:39,Bridge Transfer,1.05,0 USDC,USDC,COMPLETED
Bridge,2025-09-11 15:47:33,,Bridge Transfer,0,0 USDC,USDC,CANCELLED
Bridge,2025-09-11 15:24:25,,Bridge Transfer,0,0 USDC,USDC,CANCELLED
Bridge,2025-09-11 15:23:15,,Bridge Transfer,0,0 USDC,USDC,CANCELLED
Bridge,2025-09-11 15:09:55,,Bridge Transfer,0,0 USDC,USDC,CANCELLED
Bridge,2025-09-11 14:55:37,,Bridge Transfer,0,0 USDC,USDC,CANCELLED
Bridge,2025-09-10 04:04:47,,Bridge Transfer,0,0 USDC,USDC,CANCELLED
Earn Withdrawal,2025-09-05 16:08:57,2025-09-05 16:09:26,Earn Withdrawal,+1.00,0 USD,USD,COMPLETED
Earn Deposit,2025-09-05 14:20:05,2025-09-05 14:20:46,Earn Deposit,-7 002.00,0 USDC,USDC,COMPLETED
Exchange,2025-09-05 14:17:44,2025-09-05 14:18:04,Exchange EUR -> USD,7 002.99,0 USDC,USDC,COMPLETED
Top Up,2025-09-05 14:16:39,2025-09-05 14:16:44,Bank Transfer (Buy),+6 000.00,0 EURA,EURA,COMPLETED
Earn Deposit,2025-09-05 12:00:36,2025-09-05 12:00:51,Earn Deposit,-490.47,0 USDC,USDC,COMPLETED
Exchange,2025-09-05 11:58:47,2025-09-05 11:59:05,Exchange EUR -> USD,489.99,0 USDC,USDC,COMPLETED
Earn Deposit,2025-09-05 11:35:19,2025-09-05 11:35:35,Earn Deposit,-100.00,0 USDC,USDC,COMPLETED
Exchange,2025-09-05 11:34:05,2025-09-05 11:34:26,Exchange EUR -> USD,99.99,0 USDC,USDC,COMPLETED
Top Up,2025-09-05 11:33:12,2025-09-05 11:33:17,Bank Transfer (Buy),+510.00,0 EURA,EURA,COMPLETED
Top Up,2025-09-03 18:54:43,2025-09-03 18:56:35,Bank Transfer (Buy),+578.54,0 USDC,USDC,COMPLETED
Top Up,2025-09-03 18:47:48,2025-09-03 18:50:11,Bank Transfer (Buy),+3.49,0 USDC,USDC,COMPLETED
Off-Ramp,2025-09-02 21:32:32,2025-09-02 21:32:53,Bank Transfer (Sell),-4.00,0 EUR,EUR,COMPLETED
Top Up,2025-09-02 20:55:14,2025-09-02 20:59:46,Bank Transfer (Buy),+3.47,0 USDC,USDC,COMPLETED
Exchange,2025-09-02 17:44:57,2025-09-02 17:45:16,Exchange USD -> EUR,1.71,0 EURA,EURA,COMPLETED
Withdrawal,2025-09-02 17:08:06,,Wallet Withdrawal,-1.00,0 USDC,USDC,COMPLETED
Exchange,2025-09-02 16:53:56,2025-09-02 16:54:14,Exchange EUR -> USD,3.49,0 USDC,USDC,COMPLETED
Top Up,2025-09-02 16:52:50,2025-09-02 16:52:55,Bank Transfer (Buy),+5.00,0 EURA,EURA,COMPLETED
Top Up,2025-09-02 15:49:43,2025-09-02 15:49:47,Bank Transfer (Buy),+1.00,0 EURA,EURA,COMPLETED
"""

class TestBleapFullAccuracy(unittest.TestCase):
    def test_bleap_import_exact_row_count_and_values(self):
        file_obj = io.StringIO(RAW_USER_CSV.strip())
        df_imported = import_bleap_csv(file_obj)

        # 52 input rows = 52 output rows
        self.assertEqual(len(df_imported), 52)

        # Verify specific amounts with spaces
        earn_dep_4472 = df_imported[df_imported["Date de la transaction"] == "2025-12-29 12:58:15"]
        self.assertEqual(earn_dep_4472["Montant d'origine"].values[0], -4472.0)

        exchange_1730 = df_imported[df_imported["Date de la transaction"] == "2025-11-12 11:35:38"]
        self.assertEqual(exchange_1730["Montant d'origine"].values[0], 1730.32)

        topup_6000 = df_imported[df_imported["Date de la transaction"] == "2025-09-05 14:16:39"]
        self.assertEqual(topup_6000["Montant d'origine"].values[0], 6000.0)

    def test_bleap_sanctuary_deduplication_preserves_all_rows(self):
        file_obj = io.StringIO(RAW_USER_CSV.strip())
        df_imported = import_bleap_csv(file_obj)

        paths = save_to_sanctuary(df_imported, 2025, "Bleap_Test_Acc", auto_dispatch_year=True)
        self.assertTrue(len(paths) >= 1)

        total_saved_rows = 0
        for p in paths:
            df_p = pd.read_csv(p, encoding="utf-8-sig")
            total_saved_rows += len(df_p)

        self.assertEqual(total_saved_rows, 52)

if __name__ == "__main__":
    unittest.main()
