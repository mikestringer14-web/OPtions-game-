import sys, subprocess, math
from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageEnhance

IMG = "/home/user/OPtions-game-/video-assets/gme2021/"
W, H, FPS = 720, 1280, 24
BOX = (0, 230, 720, 1180)  # foreground area x0,y0,x1,y1
BW, BH = BOX[2] - BOX[0], BOX[3] - BOX[1]
FONT = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf", 54)
SUB = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", 30)

# keyframes: (time, cx_frac, cy_frac, zoom). zoom 1 = whole image fits the box.
BEATS = [
    ("wsb-banner.jpg", 0.0, 9.3, "r/wallstreetbets", "Jan 2021",
     [(0.0, .5, .5, 1.0), (5.6, .5, .5, 1.15), (6.9, .42, .86, 1.9), (9.3, .42, .86, 2.0)]),
    ("dfv-yolo-updates-clean.jpg", 9.3, 23.6, "Roaring Kitty's YOLO", "Keith Gill, a.k.a. Roaring Kitty",
     [(9.3, .5, .5, 1.0), (15.4, .55, .45, 1.15), (16.4, .62, .76, 1.7), (18.9, .62, .76, 1.75), (20.6, .9, .83, 2.6), (23.6, .9, .83, 2.7)]),
    ("statista-saga-chart.jpg", 23.6, 39.5, "The run", "GME closing prices, Jan 2021",
     [(23.6, .5, .5, 1.0), (24.9, .25, .69, 2.4), (29.4, .26, .56, 2.4), (31.8, .52, .47, 2.3), (36.3, .6, .32, 2.2), (39.5, .62, .32, 2.3)]),
    ("gme-logo-arrow.jpg", 39.5, 55.7, "The gamma squeeze", "options pour gas on the fire",
     [(39.5, .5, .5, 1.0), (41.5, .2, .8, 2.5), (55.7, .8, .2, 2.6)]),
    ("highs-lows-table.jpg", 55.7, 67.9, "By the numbers", "Bloomberg data",
     [(55.7, .5, .5, 1.0), (57.6, .5, .5, 1.0), (58.4, .55, .31, 1.9), (60.6, .55, .31, 1.9), (61.4, .72, .59, 1.9), (65.6, .72, .59, 1.9), (66.4, .72, .82, 1.9), (67.9, .72, .82, 1.95)]),
    ("reddit-wallstreet.jpg", 67.9, 80.3, "Jan 28: buy button off", "Robinhood restricts buying",
     [(67.9, .5, .5, 1.0), (80.3, .45, .45, 1.35)]),
    ("q1-2026-results.jpg", 80.3, 92.6, "GameStop today", "Q1 results, June 2026",
     [(80.3, .5, .5, 1.0), (84.6, .5, .45, 1.05), (85.6, .5, .1, 1.9), (87.6, .5, .1, 1.9), (88.4, .82, .5, 2.6), (92.6, .82, .5, 2.6)]),
]

def ease(u):
    return u * u * (3 - 2 * u)

def at(kf, t):
    if t <= kf[0][0]:
        return kf[0][1:]
    for a, b in zip(kf, kf[1:]):
        if t <= b[0]:
            u = ease((t - a[0]) / (b[0] - a[0]))
            return tuple(x + (y - x) * u for x, y in zip(a[1:], b[1:]))
    return kf[-1][1:]

def prep(name, title, sub):
    im = Image.open(IMG + name).convert("RGB")
    iw, ih = im.size
    s = max(W / iw, H / ih)
    bg = im.resize((math.ceil(iw * s), math.ceil(ih * s)))
    l, t = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.38)
    d = ImageDraw.Draw(bg)
    d.rectangle((40, 92, 52, 196), fill=(212, 160, 60))
    d.text((70, 88), title, font=FONT, fill=(255, 255, 255))
    d.text((72, 160), sub, font=SUB, fill=(225, 205, 160))
    return im, bg

def frame(im, bg, cx, cy, z):
    iw, ih = im.size
    base = min(BW / iw, BH / ih)
    sc = base * z
    # source window that maps onto the box
    sw, sh = BW / sc, BH / sc
    x0, y0 = cx * iw - sw / 2, cy * ih - sh / 2
    # clamp so we never pan past the image when it is bigger than the box
    if sw < iw: x0 = min(max(x0, 0), iw - sw)
    else: x0 = (iw - sw) / 2
    if sh < ih: y0 = min(max(y0, 0), ih - sh)
    else: y0 = (ih - sh) / 2
    cx0, cy0 = max(x0, 0), max(y0, 0)
    cx1, cy1 = min(x0 + sw, iw), min(y0 + sh, ih)
    crop = im.crop((int(cx0), int(cy0), math.ceil(cx1), math.ceil(cy1)))
    dw, dh = max(1, round((cx1 - cx0) * sc)), max(1, round((cy1 - cy0) * sc))
    crop = crop.resize((dw, dh), Image.BILINEAR)
    f = bg.copy()
    px = BOX[0] + round((cx0 - x0) * sc)
    py = BOX[1] + round((cy0 - y0) * sc)
    f.paste(crop, (px, py))
    return f

def main(out, only=None):
    total = BEATS[-1][2]
    if only is not None:
        for t in only:
            for name, t0, t1, title, sub, kf in BEATS:
                if t0 <= t < t1:
                    im, bg = prep(name, title, sub)
                    frame(im, bg, *at(kf, t)).save(f"{out}_{t:05.1f}.jpg")
        return
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                          "-crf", "19", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    n = round(total * FPS)
    cache = {}
    for i in range(n):
        t = i / FPS
        for name, t0, t1, title, sub, kf in BEATS:
            if t0 <= t < t1 or (t >= t1 and name == BEATS[-1][0]):
                break
        if name not in cache:
            cache.clear(); cache[name] = prep(name, title, sub)
        im, bg = cache[name]
        p.stdin.write(frame(im, bg, *at(kf, t)).tobytes())
    p.stdin.close(); p.wait()

if __name__ == "__main__":
    if sys.argv[1] == "preview":
        main(sys.argv[2], [float(x) for x in sys.argv[3:]])
    else:
        main(sys.argv[1])
