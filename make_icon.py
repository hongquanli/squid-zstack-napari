"""Generate icon.ico (white wireframe box with green blobs) for the desktop shortcut."""
from PIL import Image, ImageDraw
import random

S = 256
img = Image.new("RGBA", (S, S), (20, 20, 24, 255))
d = ImageDraw.Draw(img)
random.seed(3)
for _ in range(40):
    x, y, r = random.uniform(70, 190), random.uniform(80, 200), random.uniform(6, 13)
    d.ellipse((x - r, y - r, x + r, y + r), fill=(40, random.randint(170, 255), 40, 255))
f = [(50, 90), (170, 90), (170, 210), (50, 210)]
b = [(p[0] + 40, p[1] - 45) for p in f]
w = (255, 255, 255, 255)
for quad in (f, b):
    d.line(quad + [quad[0]], fill=w, width=6)
for p, q in zip(f, b):
    d.line([p, q], fill=w, width=6)
for i in range(1, 4):
    x = 50 + i * 30
    d.line([(x, 210), (x, 222)], fill=w, width=4)
img.save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
