import os
import sys
try:
    from PIL import Image
except Exception as e:
    print("Pillow not installed:", e)
    sys.exit(1)

script_dir = os.path.dirname(os.path.abspath(__file__))
# If this script lives in a `build` subfolder, project root is its parent.
if os.path.basename(script_dir).lower() == 'build':
    proj_root = os.path.dirname(script_dir)
else:
    proj_root = script_dir

logo = os.path.join(proj_root, "logo.png")
ico = os.path.join(proj_root, "build", "logo.ico")

if not os.path.exists(logo):
    print("logo.png not found in project root; skipping icon conversion")
    sys.exit(0)

try:
    im = Image.open(logo)
    im.save(ico, format='ICO', sizes=[(256,256),(128,128),(64,64)])
    print("Wrote", ico)
    sys.exit(0)
except Exception as e:
    print("Icon conversion failed:", e)
    sys.exit(2)
