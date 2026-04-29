try:
    from shared_logic import resolve_raw_addr, get_portfolio_snapshot, get_price_eur
    print("Imports from shared_logic: OK")
except ImportError as e:
    print(f"ImportError: {e}")

try:
    import app0
    print("app0 syntax: OK")
except Exception as e:
    print(f"app0 error: {type(e).__name__}: {e}")

try:
    import app2VGP
    print("app2VGP syntax: OK")
except Exception as e:
    print(f"app2VGP error: {type(e).__name__}: {e}")

try:
    import app3
    print("app3 syntax: OK")
except Exception as e:
    print(f"app3 error: {type(e).__name__}: {e}")
