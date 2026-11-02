"""Legible cafe / bakery menu boards, rendered with PIL and a real font (S10/S6 review: the image-generated menus had blurry, illegible text).

    python3 gen_menu_boards.py [out_dir]     # -> prop_textures/menu_pil_dark_01..08.png (chalkboard) and menu_pil_light_01..08.png (kraft / cream board), 2048 x 1092

Invented items and plausible KRW prices; Korean + English; header, two columns of items with price, thin rules, a small footer. Korean glyphs from WenQuanYi Zen Hei.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/jarvis/project/robomituba/data/venue_refs/prop_textures")
KO = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"; LB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"; LR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H = 2048, 1092
COFFEE = [("아메리카노", "Americano", 4500), ("카페라떼", "Cafe Latte", 5000), ("바닐라 라떼", "Vanilla Latte", 5500), ("카푸치노", "Cappuccino", 5000), ("플랫화이트", "Flat White", 5500),
          ("콜드브루", "Cold Brew", 5500), ("에스프레소", "Espresso", 3800), ("아포가토", "Affogato", 6500), ("말차 라떼", "Matcha Latte", 5800), ("카페모카", "Mocha", 5500),
          ("제주 감귤 에이드", "Citrus Ade", 6000), ("얼그레이 티", "Earl Grey", 5000)]
BAKERY = [("크루아상", "Croissant", 3800), ("소금빵", "Salt Bread", 3500), ("바게트", "Baguette", 4200), ("에그타르트", "Egg Tart", 3200), ("초코 머핀", "Choco Muffin", 3600),
          ("시나몬 롤", "Cinnamon Roll", 4300), ("마카롱", "Macaron", 2500), ("레몬 케이크", "Lemon Cake", 6500), ("에클레어", "Eclair", 4800), ("치즈 케이크", "Cheese Cake", 6800),
          ("단팥빵", "Red Bean Bun", 3000), ("모닝 세트", "Morning Set", 7500)]
HEAD = [("오늘의 메뉴", "TODAY'S MENU"), ("커피 & 티", "COFFEE & TEA"), ("베이커리", "BAKERY"), ("달콤한 시간", "SWEET TIME"), ("메뉴", "MENU")]


def font(path, size):
    return ImageFont.truetype(path, size)


def one(i, dark):
    r = random.Random(500 + i + (0 if dark else 100))
    items = r.sample(BAKERY if i % 2 else COFFEE, 8) if True else []
    ko_h, en_h = r.choice(HEAD)
    if dark:
        bg = [(30, 34, 33), (24, 28, 30), (36, 30, 26), (20, 30, 28)][i % 4]; ink = (238, 236, 226); sub = (190, 190, 180); acc = [(240, 200, 120), (150, 210, 190), (240, 150, 140), (170, 200, 240)][i % 4]
    else:
        bg = [(236, 228, 210), (246, 242, 232), (214, 190, 150), (240, 236, 226)][i % 4]; ink = (36, 32, 30); sub = (95, 88, 80); acc = [(170, 70, 50), (40, 100, 80), (60, 80, 140), (150, 90, 30)][i % 4]
    im = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(im)
    for _ in range(40 if dark else 0):                                      # faint chalk dust
        x, y = r.randint(0, W), r.randint(0, H); d.ellipse((x, y, x + r.randint(20, 90), y + r.randint(8, 40)), fill=tuple(min(255, c + 6) for c in bg))
    d.rectangle((30, 30, W - 30, H - 30), outline=sub, width=4)
    d.text((W // 2, 120), ko_h, font=font(KO, 120), fill=acc, anchor="mm")
    d.text((W // 2, 215), en_h, font=font(LB, 62), fill=ink, anchor="mm")
    d.line((W // 2 - 280, 270, W // 2 + 280, 270), fill=acc, width=5)
    for col in range(2):
        x0 = 110 + col * (W // 2 - 20); x1 = x0 + W // 2 - 220
        for k in range(4):
            ko, en, pr = items[col * 4 + k]; y = 350 + k * 165
            d.text((x0, y), ko, font=font(KO, 66), fill=ink, anchor="lm")
            d.text((x0, y + 62), en, font=font(LR, 40), fill=sub, anchor="lm")
            d.text((x1, y), f"{pr:,}", font=font(LB, 62), fill=acc, anchor="rm")
            d.line((x0, y + 100, x1, y + 100), fill=sub, width=2)
    d.text((W // 2, H - 80), r.choice(("모든 음료 사이즈업 +500원", "오전 8시 ~ 오후 9시", "Please ask for oat milk", "Ask us about today's special")), font=font(KO, 44), fill=sub, anchor="mm")
    return im


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for i in range(8):
        one(i, True).save(OUT / f"menu_pil_dark_{i + 1:02d}.png"); one(i, False).save(OUT / f"menu_pil_light_{i + 1:02d}.png")
    print("wrote 16 menu boards to", OUT)
