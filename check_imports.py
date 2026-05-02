import sys
import os

files = [
    "app.py", "app0.py", "app1.py", "app2.py", "app2VGP.py", "app3.py",
    "appBleap.py", "appDiagCoh.py", "appNeverless.py", "appPriceFix.py",
    "appPropri.py", "appcons.py", "main.py"
]

for f in files:
    if not os.path.exists(f):
        print(f"File {f} not found")
        continue
    print(f"Checking {f}...")
    with open(f, "r", encoding="utf-8") as file:
        content = file.read()
        if "from shared_logic import" in content:
            # Extract import line
            start = content.find("from shared_logic import")
            end = content.find(")", start) + 1 if "(" in content[start:start+100] else content.find("\n", start)
            import_statement = content[start:end]
            print(f"  {import_statement}")

            # Try to execute the import
            try:
                exec(import_statement)
                print(f"  OK")
            except ImportError as e:
                print(f"  ERROR: {e}")
            except Exception as e:
                print(f"  OTHER ERROR: {e}")
