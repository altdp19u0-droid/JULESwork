import os

files = ["app3.py", "app2VGP.py", "appDiagCoh.py", "appcons.py"]

for filename in files:
    if not os.path.exists(filename): continue
    with open(filename, 'r') as f:
        lines = f.readlines()

    new_lines = []
    skip = False
    for line in lines:
        if "def resolve_raw_addr(" in line:
            skip = True
            continue
        if skip and "return " in line:
            skip = False
            continue
        if not skip:
            new_lines.append(line)

    with open(filename, 'w') as f:
        f.writelines(new_lines)
