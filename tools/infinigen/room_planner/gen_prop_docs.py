"""Generate the paper textures of the prop set: doc_NN (business letters/reports), form_NN (forms with fields and tick boxes) and
nbpage_NN (ruled notebook pages with handwriting-like scribble) into data/venue_refs/prop_textures. Pure PIL; run with any python3.

    python3 gen_prop_docs.py [out_dir]
"""
import random, sys, glob
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/jarvis/project/robomituba/data/venue_refs/prop_textures")
W, H = 1240, 1754
WORDS = ("order delivery pallet invoice dispatch shipment quarterly review schedule inventory supplier contract payment account "
         "customer service report summary budget forecast approval meeting agenda minutes action item deadline policy safety "
         "training equipment maintenance location warehouse retail clinic patient appointment referral prescription total balance "
         "quantity reference notes please confirm attached regards update status priority team project milestone").split()
FONTS = [f for f in glob.glob("/usr/share/fonts/**/*.ttf", recursive=True) if "DejaVuSans." in f or "LiberationSans-Regular" in f] or [None]
BOLD = [f for f in glob.glob("/usr/share/fonts/**/*.ttf", recursive=True) if "DejaVuSans-Bold" in f or "LiberationSans-Bold" in f] or [None]


def font(path, size):
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except OSError:
        return ImageFont.load_default()


def sentence(r, n):
    return " ".join(r.choice(WORDS) for _ in range(n)).capitalize() + "."


def paragraph(d, x, y, w, r, f, lines, fill=(40, 40, 44), lh=34):
    for _ in range(lines):
        words, line = [], ""
        while True:
            cand = (line + " " + r.choice(WORDS)).strip()
            if d.textlength(cand, font=f) > w * r.uniform(0.86, 1.0):
                break
            line = cand
        d.text((x, y), line, font=f, fill=fill); y += lh
    return y


def finish(im, r):
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    px = im.load()
    for _ in range(2500):                                         # faint paper speckle
        x, y = r.randrange(im.width), r.randrange(im.height); v = r.randrange(-10, 4); c = px[x, y]
        px[x, y] = tuple(max(0, min(255, k + v)) for k in c)
    return im


def doc(n):
    r = random.Random(1000 + n); im = Image.new("RGB", (W, H), (250, 250, 247)); d = ImageDraw.Draw(im)
    acc = r.choice(((30, 90, 160), (160, 40, 40), (20, 110, 90), (90, 60, 140), (200, 120, 20)))
    f_b, f_n, f_s, f_t = font(BOLD[0], 54), font(FONTS[0], 27), font(FONTS[0], 22), font(BOLD[0], 30)
    d.rectangle((0, 0, W, 150), fill=acc); d.rectangle((90, 40, 170, 110), fill=(255, 255, 255)); d.text((200, 52), r.choice(
        ("NORTHGATE LOGISTICS", "BRIGHTON & CO", "HALEWOOD CLINIC", "MERIDIAN OFFICE", "TIDEMARK SUPPLY")), font=f_b, fill=(255, 255, 255))
    y = 210; d.text((90, y), sentence(r, r.randint(3, 5))[:-1].upper(), font=f_t, fill=acc); y += 70
    for blk in range(r.randint(2, 3)):
        y = paragraph(d, 90, y, W - 180, r, f_n, r.randint(5, 9)) + 28
        if blk == 0 and r.random() < 0.7:                          # a table
            cols = r.randint(3, 5); cw = (W - 180) // cols; rows = r.randint(4, 7)
            for ri in range(rows):
                for ci in range(cols):
                    x0 = 90 + ci * cw
                    d.rectangle((x0, y, x0 + cw, y + 46), outline=(150, 150, 150), fill=(238, 241, 245) if ri == 0 else None)
                    d.text((x0 + 10, y + 9), r.choice(WORDS).title() if ri == 0 or ci == 0 else f"{r.randint(1, 999)}.{r.randint(10, 99)}", font=f_s, fill=(50, 50, 55))
                y += 46
            y += 36
    for k in range(r.randint(0, 3)):
        d.ellipse((98, y + 9, 112, y + 23), fill=acc); d.text((130, y), sentence(r, 6), font=f_n, fill=(40, 40, 44)); y += 40
    if r.random() < 0.6:                                           # signature line
        d.line((90, H - 220, 480, H - 220), fill=(60, 60, 60), width=2); d.text((90, H - 205), "Authorised signature", font=f_s, fill=(90, 90, 90))
        sx = 120
        for _ in range(14):
            d.line((sx, H - 245, sx + 14, H - 262 + r.randint(-14, 14)), fill=(20, 40, 120), width=3); sx += 18
    if r.random() < 0.4:
        d.rectangle((W - 360, H - 320, W - 100, H - 180), outline=(170, 40, 40), width=6); d.text((W - 330, H - 280), "RECEIVED", font=f_t, fill=(170, 40, 40))
    return finish(im, r)


def form(n):
    r = random.Random(2000 + n); im = Image.new("RGB", (W, H), (251, 251, 248)); d = ImageDraw.Draw(im)
    f_b, f_n, f_s = font(BOLD[0], 40), font(FONTS[0], 26), font(FONTS[0], 21)
    d.text((90, 70), r.choice(("Patient intake form", "Delivery note", "Visitor log", "Stock count sheet", "Order form")), font=f_b, fill=(25, 40, 90))
    y = 170
    for row in range(r.randint(9, 13)):
        d.text((90, y), r.choice(WORDS).title() + ":", font=f_n, fill=(50, 50, 55))
        d.line((330, y + 32, W - 100, y + 32), fill=(120, 120, 120), width=2)
        if r.random() < 0.7:
            x = 340
            for _ in range(r.randint(4, 14)):                      # handwriting-like scribble
                d.line((x, y + 22, x + 9, y + 8 + r.randint(0, 12)), fill=(25, 35, 120), width=3); x += 11
        y += 74
    for k in range(r.randint(3, 5)):
        d.rectangle((100, y + 6, 132, y + 38), outline=(60, 60, 60), width=3)
        if r.random() < 0.6:
            d.line((106, y + 22, 116, y + 34), fill=(25, 35, 120), width=4); d.line((116, y + 34, 130, y + 8), fill=(25, 35, 120), width=4)
        d.text((160, y + 6), sentence(r, 4), font=f_s, fill=(50, 50, 55)); y += 56
    return finish(im, r)


def nbpage(n):
    r = random.Random(3000 + n); im = Image.new("RGB", (W, H), (252, 251, 244)); d = ImageDraw.Draw(im)
    for y in range(150, H - 60, 46):
        d.line((0, y, W, y), fill=(185, 205, 225), width=2)
    d.line((150, 0, 150, H), fill=(225, 120, 120), width=3)
    ink = r.choice(((25, 35, 120), (20, 20, 25), (30, 90, 50)))
    for line in range(r.randint(8, 24)):
        y = 140 + line * 46; x = 175; n_words = r.randint(3, 8)
        for _ in range(n_words):
            for _ in range(r.randint(3, 8)):
                d.line((x, y + 8 + r.randint(0, 6), x + 6, y - 14 + r.randint(-4, 4)), fill=ink, width=3); x += 11
            x += 22
            if x > W - 180:
                break
    return finish(im, r)


MENU = (("Espresso", 3.2), ("Americano", 3.0), ("Flat white", 3.8), ("Latte", 4.0), ("Cappuccino", 3.9), ("Mocha", 4.4), ("Cold brew", 4.2), ("Green tea", 3.4),
        ("Croissant", 3.5), ("Muffin", 3.2), ("Cheesecake", 5.2), ("Toast", 4.8), ("Bagel", 4.5), ("Sandwich", 6.5), ("Soup of the day", 5.9), ("Cookie", 2.4))
CHALK_COL = ((236, 236, 228), (240, 214, 120), (150, 210, 235), (240, 160, 170))


def menu(n, dark):
    r = random.Random(4000 + n); w, h = 1500, 800
    bg = (32, 36, 34) if dark else (238, 234, 224); ink = (236, 236, 228) if dark else (30, 30, 32)
    im = Image.new("RGB", (w, h), bg); d = ImageDraw.Draw(im)
    for _ in range(2400):                                           # chalk dust / paper grain
        x, y = r.randrange(w), r.randrange(h); a = r.randrange(8, 26)
        d.point((x, y), fill=tuple(min(255, c + a) if dark else max(0, c - a) for c in bg))
    f_h, f_i = font(BOLD[0], 70), font(FONTS[0], 40)
    title = r.choice(("COFFEE & TEA", "TODAY'S MENU", "DRINKS", "CAFE MENU", "BAKERY"))
    d.text((w // 2 - d.textlength(title, font=f_h) / 2, 40), title, font=f_h, fill=r.choice(CHALK_COL) if dark else ink)
    d.line((140, 135, w - 140, 135), fill=ink, width=3)
    items = r.sample(MENU[:8], 5) + r.sample(MENU[8:], 5)
    for col in range(2):
        x0 = 90 + col * 700
        d.text((x0, 150), "Drinks" if col == 0 else "Food", font=font(BOLD[0], 38), fill=r.choice(CHALK_COL) if dark else ink)
        for i, (name, price) in enumerate(items[col * 5:col * 5 + 5]):
            y = 215 + i * 105
            d.text((x0, y), name, font=f_i, fill=ink); ptxt = f"{price:.1f}"
            d.text((x0 + 560 - d.textlength(ptxt, font=f_i), y), ptxt, font=f_i, fill=ink)
            for xx in range(int(x0 + d.textlength(name, font=f_i)) + 14, int(x0 + 540 - d.textlength(ptxt, font=f_i)), 14):
                d.point((xx, y + 34), fill=ink)
    for _ in range(4):                                               # a doodle: cup, steam, star
        cx, cy = r.randrange(120, w - 120), r.randrange(660, 760)
        d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), outline=r.choice(CHALK_COL) if dark else ink, width=3)
    return finish(im, r)


HEADERS = {"grocery": ("FOOD", "DAIRY", "SNACKS", "DRINKS", "BAKERY", "FROZEN", "DELI", "SOUP"),
           "pharmacy": ("VITAMINS", "COLD & FLU", "FIRST AID", "SKIN CARE", "BABY", "PAIN RELIEF"),
           "boutique": ("NEW IN", "SALE", "SHOES", "BAGS", "SCARVES", "ACCESSORIES")}
HEAD_BG = ((30, 120, 70), (190, 40, 40), (30, 80, 150), (225, 150, 30), (20, 110, 110), (90, 55, 130), (40, 40, 44))


def header(word, bg, n):
    """An aisle header sign: a flat coloured board with the word in a bold typeface (the hand-drawn stroke font read as 'odd lettering')."""
    r = random.Random(7000 + n); w, h = 1400, 400
    im = Image.new("RGB", (w, h), bg); d = ImageDraw.Draw(im)
    d.rectangle((14, 14, w - 15, h - 15), outline=tuple(min(255, c + 70) for c in bg), width=6)
    size = 250
    while True:
        f = font(BOLD[0], size)
        if d.textlength(word, font=f) <= w - 200 or size <= 60:
            break
        size -= 8
    tw = d.textlength(word, font=f)
    d.text(((w - tw) / 2, (h - size) / 2 - size * 0.12), word, font=f, fill=(246, 246, 240))
    return finish(im, r)


def pos(venue, n):
    """A register screen: product tiles on the left, the current order, total and a PAY button on the right, for the shop's own goods."""
    items = {"boutique": (("T-shirt", 24.0), ("Jeans", 59.0), ("Scarf", 18.0), ("Socks", 7.5), ("Cap", 15.0), ("Belt", 22.0)),
             "pharmacy": (("Vitamin C", 9.9), ("Pain relief", 6.4), ("Bandages", 3.2), ("Cough syrup", 8.7), ("Sunscreen", 12.5), ("Tooth paste", 4.2)),
             "grocery": (("Milk", 1.8), ("Bread", 2.4), ("Chips", 2.1), ("Soda", 1.6), ("Apples", 3.2), ("Coffee", 5.9))}[venue]
    r = random.Random(8000 + n + len(venue)); w, h = 1500, 800
    im = Image.new("RGB", (w, h), (24, 28, 36)); d = ImageDraw.Draw(im)
    f_b, f_m, f_s = font(BOLD[0], 54), font(FONTS[0], 40), font(FONTS[0], 30)
    d.rectangle((0, 0, w, 90), fill=(36, 42, 54)); d.text((40, 18), {"boutique": "Atelier POS", "pharmacy": "Pharma POS", "grocery": "QuickShop POS"}[venue], font=f_b, fill=(230, 235, 240))
    cols = ((60, 130, 200), (70, 160, 110), (200, 130, 50), (150, 90, 180), (190, 70, 80), (60, 150, 160))
    r.shuffle(list(cols)); items = list(items); r.shuffle(items)
    for k, (name, price) in enumerate(items):
        x, y = 40 + (k % 2) * 440, 130 + (k // 2) * 205
        d.rounded_rectangle((x, y, x + 410, y + 185), radius=22, fill=cols[k])
        d.text((x + 24, y + 28), name, font=f_m, fill=(255, 255, 255)); d.text((x + 24, y + 112), f"{price:.2f}", font=f_b, fill=(255, 255, 255))
    d.rectangle((960, 90, w, h), fill=(32, 38, 48)); d.text((990, 110), "Current order", font=f_m, fill=(210, 215, 222))
    total = 0.0
    for k, (name, price) in enumerate(items[:3]):
        q = r.randint(1, 2); total += q * price; y = 190 + k * 80
        d.text((990, y), f"{name}", font=f_s, fill=(230, 235, 240)); d.text((990, y + 36), f"x{q}", font=f_s, fill=(150, 160, 170))
        pt = f"{q * price:.2f}"; d.text((w - 50 - d.textlength(pt, font=f_s), y), pt, font=f_s, fill=(230, 235, 240))
    d.line((990, 470, w - 40, 470), fill=(90, 100, 112), width=2)
    d.text((990, 490), "TOTAL", font=f_m, fill=(210, 215, 222)); tt = f"{total:.2f}"; d.text((w - 50 - d.textlength(tt, font=f_b), 480), tt, font=f_b, fill=(255, 255, 255))
    d.rounded_rectangle((990, 620, w - 40, 760), radius=24, fill=(60, 170, 90)); d.text((1190, 650), "PAY", font=f_b, fill=(255, 255, 255))
    return finish(im, r)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for n in range(1, 9):
        doc(n).save(OUT / f"doc_{n:02d}.png")
    for n in range(1, 4):
        form(n).save(OUT / f"form_{n:02d}.png")
    for n in range(1, 5):
        nbpage(n).save(OUT / f"nbpage_{n:02d}.png")
    for n in range(1, 5):
        menu(n, True).save(OUT / f"menu_dark_{n:02d}.png")
    for n in range(1, 3):
        menu(n, False).save(OUT / f"menu_light_{n:02d}.png")
    for v, words in HEADERS.items():
        for n, wd in enumerate(words, 1):
            header(wd, HEAD_BG[(n * 3 + len(v)) % len(HEAD_BG)], n + 10 * len(v)).save(OUT / f"header_{v}_{n:02d}.png")
    for v in ("boutique", "pharmacy", "grocery"):
        for n in range(1, 4):
            pos(v, n).save(OUT / f"pos_{v}_{n:02d}.png")
    print("wrote", len(list(OUT.glob("doc_*.png"))), "doc,", len(list(OUT.glob("form_*.png"))), "form,", len(list(OUT.glob("nbpage_*.png"))), "nbpage")
