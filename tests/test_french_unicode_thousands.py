import io
import unittest
import pandas as pd
from sanctuary_app.modules.importers.importer_bleap import import_bleap_csv, _clean_numeric

TEST_FRENCH_UNICODE_CSV = """Type,Created At,Completed At,Description,Amount,Fees,Currency,Status
Earn Deposit,2025-12-29 12:58:15,2025-12-29 12:58:28,Earn Deposit,-4\u202f472.00,0 USDC,USDC,COMPLETED
Earn Withdrawal,2025-12-29 12:57:21,2025-12-29 12:57:34,Earn Withdrawal,+4\u202f471.00,0 USD,USD,COMPLETED
Withdrawal,2025-12-29 10:41:18,,Wallet Withdrawal,-6\u202f000.00,0 USDC,USDC,COMPLETED
Earn Withdrawal,2025-12-29 10:39:21,2025-12-29 10:39:38,Earn Withdrawal,+6\u202f000.00,0 USD,USD,COMPLETED
Earn Deposit,2025-11-12 11:37:03,2025-11-12 11:37:14,Earn Deposit,-1\u202f731.11,0 USDC,USDC,COMPLETED
Exchange,2025-11-12 11:35:38,2025-11-12 11:35:55,Exchange EUR -> USD,1\u202f730.32,0 USDC,USDC,COMPLETED
Top Up,2025-11-12 11:32:16,2025-11-12 11:32:21,Bank Transfer (Buy),+1\u202f500.00,0 EURA,EURA,COMPLETED
Earn Deposit,2025-11-05 20:48:08,2025-11-05 20:48:31,Earn Deposit,-1\u202f143.00,0 USDC,USDC,COMPLETED
Exchange,2025-11-05 20:46:45,2025-11-05 20:47:03,Exchange EUR -> USD,1\u202f142.76,0 USDC,USDC,COMPLETED
Earn Deposit,2025-11-04 18:42:09,2025-11-04 18:43:47,Earn Deposit,-1\u202f000.00,0 EURA,EURA,COMPLETED
Top Up,2025-11-04 18:27:38,2025-11-04 18:27:43,Bank Transfer (Buy),+1\u202f000.00,0 EURA,EURA,COMPLETED
Earn Deposit,2025-09-05 14:20:05,2025-09-05 14:20:46,Earn Deposit,-7\u202f002.00,0 USDC,USDC,COMPLETED
Exchange,2025-09-05 14:17:44,2025-09-05 14:18:04,Exchange EUR -> USD,7\u202f002.99,0 USDC,USDC,COMPLETED
Top Up,2025-09-05 14:16:39,2025-09-05 14:16:44,Bank Transfer (Buy),+6\u202f000.00,0 EURA,EURA,COMPLETED
"""

class TestFrenchUnicodeThousands(unittest.TestCase):
    def test_clean_numeric_narrow_no_break_space(self):
        self.assertEqual(_clean_numeric("-4\u202f472.00"), -4472.0)
        self.assertEqual(_clean_numeric("+4\u202f471.00"), 4471.0)
        self.assertEqual(_clean_numeric("-6\u202f000.00"), -6000.0)
        self.assertEqual(_clean_numeric("+6\u202f000.00"), 6000.0)
        self.assertEqual(_clean_numeric("-1\u202f731.11"), -1731.11)
        self.assertEqual(_clean_numeric("1\u202f730.32"), 1730.32)
        self.assertEqual(_clean_numeric("+1\u202f500.00"), 1500.0)
        self.assertEqual(_clean_numeric("7\u202f002.99"), 7002.99)

    def test_clean_numeric_excel_apostrophe_prefix(self):
        self.assertEqual(_clean_numeric("'+1.00"), 1.0)
        self.assertEqual(_clean_numeric("'-7\u202f002.00"), -7002.0)
        self.assertEqual(_clean_numeric("'+6\u202f000.00"), 6000.0)
        self.assertEqual(_clean_numeric("'-120.00"), -120.0)

    def test_import_bleap_french_unicode_csv(self):
        file_obj = io.StringIO(TEST_FRENCH_UNICODE_CSV)
        df_imported = import_bleap_csv(file_obj)

        self.assertEqual(len(df_imported), 14)

        # Ensure NO rows have Montant d'origine == 0
        zero_rows = df_imported[df_imported["Montant d'origine"] == 0]
        self.assertEqual(len(zero_rows), 0)

        ex_7002 = df_imported[df_imported["Date de la transaction"] == "2025-09-05 14:17:44"]
        self.assertEqual(ex_7002["Montant d'origine"].values[0], 7002.99)
        self.assertTrue(ex_7002["Montant du relevé"].values[0] > 0)

        dep_4472 = df_imported[df_imported["Date de la transaction"] == "2025-12-29 12:58:15"]
        self.assertEqual(dep_4472["Montant d'origine"].values[0], -4472.0)
        self.assertTrue(dep_4472["Montant du relevé"].values[0] < 0)

if __name__ == "__main__":
    unittest.main()
