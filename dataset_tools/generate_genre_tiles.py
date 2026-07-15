# -*- coding: utf-8 -*-
"""
ホーム画面の「ジャンル」タイル画像を作るスクリプト

やること
  1. characters.json から各ジャンルの代表となる1件を選ぶ
  2. 正方形に切り抜き → 暗くする → ジャンル名の文字を焼き込む
  3. static/genre_tiles/ にWebPで保存する
     （pokemon.webp, all.webp, animal.webp, insect.webp, food.webp,
       vehicle.webp, building.webp, instrument.webp, sports.webp,
       plant.webp, tool.webp）

「ぜんぶ」タイルだけは、4ジャンルのミニ写真を2x2に組み合わせたコラージュにする
（1枚の写真だと「ぜんぶ」感が出ないため）。

「ポケモン」タイルは、PokeAPIの公式アートワーク（ピカチュウ, 図鑑No.25）を使う。

使い方
  $ python3 dataset_tools/generate_genre_tiles.py
"""

import io
import os

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TOOLS_DIR)
OUT_DIR = os.path.join(PROJECT_DIR, "static", "genre_tiles")
DATASET_JSON = os.path.join(PROJECT_DIR, "static", "dataset", "characters.json")

SIZE = 400  # タイル画像の一辺（px）
HEADERS = {"User-Agent": "hakushi-akande-dataset/1.0 (school festival drawing game)"}

# 日本語フォント（Mac標準のヒラギノ丸ゴシックを使う）
FONT_PATH = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"

PIKACHU_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
    "sprites/pokemon/other/official-artwork/25.png"
)

# characters.json の id → (出力ファイル名, タイルに書く文字, 文字サイズ)
# 文字サイズは「スポーツ用品」のような長い名前だけ小さくしている
#
# タイルに使う元画像は「その物1つだけが写っている」ものを優先する
# （ポケモンのタイルが単体キャラなので、他のジャンルも見た目をそろえるため）。
# ただし「建物」は景色ごと描くジャンルなので、あえて背景込みの写真のままにしている。
CATEGORY_JOBS = [
    (20,  "animal",     "動物",        56),  # レッサーパンダ(背景が騒がしい)→ネコ(単体)
    (65,  "insect",     "昆虫",        56),  # 元々単体なのでそのまま
    (111, "food",       "食べ物",      48),  # ドーナツ山盛り→目玉焼き(単体)
    (112, "vehicle",    "乗り物",      48),  # 新幹線+田園風景→自転車(単体)
    (140, "building",   "建物",        56),  # 建物は景色ごとでOKなのでそのまま
    (148, "instrument", "楽器",        56),  # 元々単体なのでそのまま
    (163, "sports",     "スポーツ用品", 36),  # サッカーボール+スタジアム→バスケ(単体)
    (192, "plant",      "植物",        56),  # ヒマワリ畑(景色)→ユリ(単体)
    (200, "tool",       "道具",        56),  # 元々単体なのでそのまま
]

# 「ぜんぶ」タイルのコラージュに使う4件（ネコ・目玉焼き・自転車・ユリ）
COLLAGE_IDS = [20, 111, 112, 192]


def square_crop(img, size):
    """中央を正方形に切り抜いて size x size にリサイズする"""
    img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    return img.crop((left, top, left + side, top + side)).resize(
        (size, size), Image.LANCZOS
    )


def darken(img):
    """明るさを35%に落とし、さらに半透明の黒を重ねて文字が映える暗さにする"""
    darkened = ImageEnhance.Brightness(img.convert("RGB")).enhance(0.35).convert("RGBA")
    overlay = Image.new("RGBA", darkened.size, (0, 0, 0, 110))
    darkened.alpha_composite(overlay)
    return darkened


def draw_label(img, label, font_size):
    """画像の中央に、白文字＋黒縁取りでラベルを書き込む"""
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, font_size)
    bbox = draw.textbbox((0, 0), label, font=font, stroke_width=4)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (img.width - tw) / 2 - bbox[0]
    y = (img.height - th) / 2 - bbox[1]
    draw.text((x, y), label, font=font, fill="white", stroke_width=4, stroke_fill="black")
    return img


def fetch_image(url):
    res = requests.get(url, headers=HEADERS, timeout=30)
    res.raise_for_status()
    return Image.open(io.BytesIO(res.content))


def main():
    import json

    os.makedirs(OUT_DIR, exist_ok=True)
    dataset = {item["id"]: item for item in json.load(open(DATASET_JSON, encoding="utf-8"))}

    # ---------- ポケモン ----------
    pika = fetch_image(PIKACHU_URL)
    tile = draw_label(darken(square_crop(pika, SIZE)), "ポケモン", 64)
    tile.convert("RGB").save(f"{OUT_DIR}/pokemon.webp", "WEBP", quality=85)
    print("pokemon.webp 作成")

    # ---------- 各ジャンル ----------
    for item_id, filename, label, font_size in CATEGORY_JOBS:
        item = dataset[item_id]
        img = fetch_image(item["image"])
        tile = draw_label(darken(square_crop(img, SIZE)), label, font_size)
        tile.convert("RGB").save(f"{OUT_DIR}/{filename}.webp", "WEBP", quality=85)
        print(f"{filename}.webp 作成（{item['name']}）")

    # ---------- ぜんぶ（4ジャンルのコラージュ） ----------
    half = SIZE // 2
    collage = Image.new("RGB", (SIZE, SIZE))
    for i, item_id in enumerate(COLLAGE_IDS):
        img = fetch_image(dataset[item_id]["image"])
        cropped = square_crop(img, half)
        x, y = (i % 2) * half, (i // 2) * half
        collage.paste(cropped, (x, y))
    tile = draw_label(darken(collage), "ぜんぶ", 56)
    tile.convert("RGB").save(f"{OUT_DIR}/all.webp", "WEBP", quality=85)
    print("all.webp 作成（コラージュ）")

    print("完了！")


if __name__ == "__main__":
    main()
