"""Remove white background from mascot.jpg, save as mascot.png with transparency."""
from PIL import Image
import numpy as np
import os

BASE = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(BASE, "static", "mascot.jpg")
dst = os.path.join(BASE, "static", "mascot.png")

img = Image.open(src).convert("RGBA")
data = np.array(img)

r, g, b, a = data[:,:,0], data[:,:,1], data[:,:,2], data[:,:,3]

# White/near-white → fully transparent
white_mask = (r > 210) & (g > 210) & (b > 210)
data[white_mask, 3] = 0

# Soft edge: off-white → semi-transparent
near_white = (r > 185) & (g > 185) & (b > 185) & ~white_mask
data[near_white, 3] = (data[near_white, 3] * 0.4).astype(np.uint8)

result = Image.fromarray(data)
result.save(dst)
print(f"Done: {dst} ({result.size[0]}x{result.size[1]})")
