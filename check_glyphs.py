from fontTools.ttLib import TTFont
import os

def check_font_coverage(font_path, chars):
    if not os.path.exists(font_path):
        return f"Font file {font_path} not found."

    font = TTFont(font_path)
    # Get the character map
    cmap = font.getBestCmap()

    results = {}
    for char in chars:
        cp = ord(char)
        results[char] = cp in cmap

    return results

chars_to_check = [
    'Ⅽ', # U+216D
    'ꓴ', # U+A4F4
    'ꓢ', # U+A4E2
    'ꓓ', # U+A4D3
    'С'  # U+0421
]

print("Checking DejaVuSans.ttf...")
res_reg = check_font_coverage("DejaVuSans.ttf", chars_to_check)
for char, present in res_reg.items():
    print(f"Char: {char} (U+{ord(char):04X}) -> {'FOUND' if present else 'MISSING'}")

print("\nChecking DejaVuSans-Bold.ttf...")
res_bold = check_font_coverage("DejaVuSans-Bold.ttf", chars_to_check)
for char, present in res_bold.items():
    print(f"Char: {char} (U+{ord(char):04X}) -> {'FOUND' if present else 'MISSING'}")
