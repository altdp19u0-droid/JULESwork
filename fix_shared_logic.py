import pandas as pd
import os
import shared_logic as sl

# Check if valid_assets.json exists, if not create a basic one with EURA and common coins
if not os.path.exists("valid_assets.json"):
    import json
    with open("valid_assets.json", "w") as f:
        json.dump(["BTC", "ETH", "USDC", "USDT", "EURA", "EURC", "SOL", "LINK"], f)
