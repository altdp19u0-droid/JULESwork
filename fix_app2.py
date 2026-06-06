import os

filepath = 'app2.py'
with open(filepath, 'r') as f:
    lines = f.readlines()

new_lines = []
skip_mode = False
bonus_seen = False

for line in lines:
    if 'with st.expander("💎 Registre des Tokens Bonus"):' in line:
        if bonus_seen:
            skip_mode = True
            continue
        else:
            bonus_seen = True

    if skip_mode:
        if 'with st.expander("🌐 Circuits Externes"):' in line:
            skip_mode = False
        else:
            continue

    new_lines.append(line)

with open(filepath, 'w') as f:
    f.writelines(new_lines)
