# -*- coding: utf-8 -*-
"""
「単体の物だけが写っている画像」に差し替える第2次修理ツール

repair_dataset.py（お題と画像のミスマッチ修理）とは別の観点。
今回は「絵が正しくても、複数の個体・人物が写っていて描きにくい」項目を
単体（または単体扱いできる自然なまとまり）の写真に差し替える。

「建物」カテゴリは景色ごと描くジャンルなので対象外。

使い方は repair_dataset.py と同じ3ステップ（別のstateファイルを使うので混ざらない）
  1. python3 repair_single.py search
  2. python3 repair_single.py propose
  3. python3 repair_single.py reject <id...>  → 2へ戻る
  4. python3 repair_single.py apply
"""

import io
import json
import os
import re
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFont, ImageStat

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TOOLS_DIR)
STATE_FILE = os.path.join(TOOLS_DIR, "state.json")
REPAIR_FILE = os.path.join(TOOLS_DIR, "repair_single_state.json")
JSON_FILE = os.path.join(PROJECT_DIR, "static", "dataset", "characters.json")

REVIEW_DIR = os.environ.get(
    "REVIEW_DIR",
    "/private/tmp/claude-501/-Users-yushin-seisaku-app-oekaki/051639da-850a-45f6-b5a5-18208db601e2/scratchpad/review_single",
)

API_URL = "https://api.openverse.org/v1/images/"
HEADERS = {"User-Agent": "hakushi-akande-dataset/1.0 (school festival drawing game)"}
API_WAIT_SECONDS = 3.2

BANNED_WORDS = [
    "person", "people", "man", "woman", "boy", "girl", "child", "children",
    "kid", "human", "portrait photographer", "selfie", "model", "wedding", "bride",
    "cosplay", "anime", "manga", "cartoon", "comic", "character", "characters",
    "figurine", "action figure", "lego", "pokemon", "pikachu", "mario",
    "disney", "mickey", "hello kitty", "sanrio", "ghibli", "doll",
    "silhouette", "costume", "painting", "drawing", "illustration", "sketch",
    "statue", "sculpture", "mural", "poster", "sign", "advertisement",
    "skull", "skeleton", "taxidermy", "museum", "cemetery", "grave",
    "abandoned", "ruins", "catalog", "stamp", "graffiti", "artwork",
    "miniature", "carving", "book", "cover",
    # 今回追加：複数・群れを示す語（単体じゃないものを弾く）
    "group", "herd", "flock", "pack", "colony", "crowd", "many", "several",
    "pair of", "couple of", "family of", "collection", "bunch of people",
]

# ============================================================
# 差し替え対象：{id: (検索ワード, タイトル/タグに必須の単語リスト)}
# 「単体の1個体・1個」が写っている写真を狙うクエリにしている
# ============================================================
REPAIRS = {
    # ---- 動物 ----
    3:   ("single lion",         ["lion"]),
    5:   ("single elephant",     ["elephant"]),
    7:   ("single zebra",        ["zebra"]),
    8:   ("single hippo",        ["hippo"]),
    24:  ("single polarbear",    ["polar bear"]),
    26:  ("single flamingo",     ["flamingo"]),
    34:  ("single cow",          ["cow"]),
    35:  ("single pig",          ["pig"]),
    43:  ("single shark",        ["shark"]),
    49:  ("single seal",         ["seal"]),
    58:  ("single meerkat",      ["meerkat"]),
    # ---- 食べ物 ----
    73:  ("single apple",        ["apple"]),
    75:  ("single strawberry",   ["strawberry"]),
    76:  ("single watermelon",   ["watermelon"]),
    78:  ("single pineapple",    ["pineapple"]),
    79:  ("single peach",        ["peach"]),
    80:  ("single orange",       ["orange"]),
    81:  ("single lemon",        ["lemon"]),
    82:  ("cherry stem",         ["cherry", "cherries"]),
    85:  ("single tomato",       ["tomato"]),
    86:  ("single carrot",       ["carrot"]),
    87:  ("single potato",       ["potato"]),
    88:  ("single onion",        ["onion"]),
    90:  ("single pumpkin",      ["pumpkin"]),
    91:  ("single eggplant",     ["eggplant", "aubergine"]),
    92:  ("corn cob",            ["corn"]),
    93:  ("single mushroom",     ["mushroom"]),
    95:  ("single croissant",    ["croissant"]),
    103: ("single donut",        ["donut", "doughnut"]),
    107: ("single cookie",       ["cookie"]),
    # ---- 乗り物 ----
    126: ("single sailboat",     ["yacht", "sailboat", "sailing"]),
    129: ("single tractor",      ["tractor"]),
    # ---- 楽器 ----
    157: ("single ukulele",      ["ukulele"]),
    159: ("taiko drum",          ["taiko", "drum"]),
    # ---- スポーツ用品 ----
    166: ("single shuttlecock",  ["shuttlecock"]),
    167: ("golf clubs",          ["golf"]),
    170: ("single snowboard",    ["snowboard"]),
    173: ("ping pong",           ["table tennis", "ping pong", "paddle"]),
    174: ("boxing gloves",       ["boxing glove", "boxing gloves"]),
    176: ("single surfboard",    ["surfboard"]),
    # ---- 植物 ----
    177: ("single sunflower",    ["sunflower"]),
    178: ("single rose",         ["rose"]),
    179: ("single tulip",        ["tulip"]),
    180: ("cherry blossom",      ["cherry blossom", "sakura", "blossom"]),
    181: ("morning glory",       ["morning glory"]),
    182: ("hydrangea flower",    ["hydrangea"]),
    184: ("single cactus",       ["cactus"]),
    185: ("maple leaf",          ["maple"]),
    186: ("single pinecone",     ["pine cone", "pinecone"]),
    187: ("bamboo stalk",        ["bamboo"]),
    189: ("water lily",          ["water lily", "lily pad", "lotus"]),
    190: ("lavender stem",       ["lavender"]),
    # ---- 道具 ----
    198: ("single wristwatch",   ["watch"]),
    199: ("single umbrella",     ["umbrella"]),
    # ---- 昆虫 ----
    67:  ("single grasshopper",  ["grasshopper"]),
    69:  ("single cicada",       ["cicada"]),
    70:  ("ant macro",           ["ant"]),
    71:  ("single snail",        ["snail"]),
}


def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def license_label(r):
    lic = (r.get("license") or "").lower()
    ver = r.get("license_version") or ""
    if lic == "cc0":
        return "CC0 1.0"
    if lic == "pdm":
        return "Public Domain Mark"
    if lic in ("by", "by-sa"):
        return f"CC {lic.upper()} {ver}".strip()
    return lic


def text_of(r):
    text = (r.get("title") or "").lower()
    for tag in r.get("tags") or []:
        text += " " + (tag.get("name") or "").lower()
    return text


def is_banned(r):
    text = text_of(r)
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in BANNED_WORDS)


def has_required(r, required):
    text = text_of(r)
    return any(w in text for w in required)


def all_used_urls(state, repair):
    urls = {rec["image"] for rec in state["done"].values()}
    for ent in repair.values():
        cands = ent.get("candidates", [])
        idx = ent.get("index", 0)
        if idx < len(cands):
            urls.add(cands[idx]["url"])
    return urls


def cmd_search():
    repair = load(REPAIR_FILE, {})
    session = requests.Session()

    todo = [i for i in REPAIRS if str(i) not in repair]
    print(f"再検索する項目: {len(todo)}件")

    for item_id in todo:
        query, required = REPAIRS[item_id]
        print(f"[id={item_id:3d}] {query}")
        params = {
            "q": query,
            "license": "cc0,pdm,by,by-sa",
            "license_type": "commercial",
            "category": "photograph",
            "per_page": 30,
        }
        try:
            for attempt in range(3):
                res = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
                if res.status_code == 429:
                    print(f"    レート制限。65秒待ちます…（{attempt + 1}回目）")
                    time.sleep(65)
                    continue
                res.raise_for_status()
                break
            else:
                print("    レート制限が解除されず中断。後でもう一度実行してください。")
                return
            results = res.json().get("results", [])
        except Exception as e:
            print(f"    検索失敗: {e}")
            time.sleep(API_WAIT_SECONDS)
            continue

        cands = []
        for r in results:
            if not r.get("url"):
                continue
            if (r.get("license") or "").lower() not in ("cc0", "pdm", "by", "by-sa"):
                continue
            w, h = r.get("width") or 0, r.get("height") or 0
            if w and h and min(w, h) < 400:
                continue
            if (r.get("filetype") or "").lower() in ("svg", "gif"):
                continue
            if is_banned(r) or not has_required(r, required):
                continue
            cands.append({
                "url": r["url"],
                "creator": r.get("creator") or "不明",
                "license": license_label(r),
                "license_url": r.get("license_url") or "",
                "source": r.get("foreign_landing_url") or r["url"],
                "title": (r.get("title") or "")[:80],
            })
        repair[str(item_id)] = {"candidates": cands, "index": 0}
        save(REPAIR_FILE, repair)
        print(f"    候補 {len(cands)}件")
        time.sleep(API_WAIT_SECONDS)

    print("search 完了")


def is_grayscale(img):
    hsv = img.convert("HSV")
    sat = ImageStat.Stat(hsv).mean[1]
    return sat < 18


def cmd_propose():
    state = load(STATE_FILE, None)
    repair = load(REPAIR_FILE, {})
    os.makedirs(REVIEW_DIR, exist_ok=True)
    session = requests.Session()

    by_id = {rec["id"]: rec for rec in state["done"].values()}
    used = all_used_urls(state, repair)

    ok, exhausted = [], []
    for key, ent in sorted(repair.items(), key=lambda kv: int(kv[0])):
        item_id = int(key)
        cands = ent["candidates"]
        path = os.path.join(REVIEW_DIR, f"{item_id:03d}.jpg")

        if ent.get("fetched_index") == ent["index"] and os.path.exists(path):
            ok.append(item_id)
            continue

        while ent["index"] < len(cands):
            cand = cands[ent["index"]]
            if cand["url"] in used and ent.get("fetched_index") != ent["index"]:
                ent["index"] += 1
                continue
            try:
                res = session.get(cand["url"], headers=HEADERS, timeout=45)
                res.raise_for_status()
                img = Image.open(io.BytesIO(res.content)).convert("RGB")
                if is_grayscale(img):
                    print(f"[id={item_id}] 候補{ent['index']}は白黒 → 次へ")
                    ent["index"] += 1
                    continue
                img.thumbnail((400, 400))
                img.save(path, "JPEG", quality=85)
                ent["fetched_index"] = ent["index"]
                used.add(cand["url"])
                ok.append(item_id)
                break
            except Exception as e:
                print(f"[id={item_id}] 候補{ent['index']}のDL失敗（{e}）→ 次へ")
                ent["index"] += 1
        else:
            exhausted.append(item_id)
        save(REPAIR_FILE, repair)

    font = None
    for p in ["/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
              "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]:
        try:
            font = ImageFont.truetype(p, 16)
            break
        except Exception:
            pass

    cell, label_h, cols = 200, 24, 5
    ids = sorted(ok)
    per_sheet = cols * 5
    for s in range(0, len(ids), per_sheet):
        batch = ids[s:s + per_sheet]
        rows = (len(batch) + cols - 1) // cols
        sheet = Image.new("RGB", (cell * cols, (cell + label_h) * rows), "white")
        dr = ImageDraw.Draw(sheet)
        for i, item_id in enumerate(batch):
            x, y = (i % cols) * cell, (i // cols) * (cell + label_h)
            img = Image.open(os.path.join(REVIEW_DIR, f"{item_id:03d}.jpg"))
            img = img.resize((cell, cell))
            sheet.paste(img, (x, y))
            name = by_id[item_id]["name"]
            dr.text((x + 4, y + cell + 3), f"{item_id:03d} {name}", fill="black", font=font)
        n = s // per_sheet + 1
        out = os.path.join(REVIEW_DIR, f"review_{n:02d}.png")
        sheet.save(out)
        print("シート:", out)

    if exhausted:
        print("候補が尽きた項目:", exhausted)
    print(f"propose 完了（候補あり: {len(ok)}件 / 候補切れ: {len(exhausted)}件）")


def cmd_reject(ids):
    repair = load(REPAIR_FILE, {})
    for item_id in ids:
        key = str(item_id)
        if key in repair:
            repair[key]["index"] += 1
            print(f"id={item_id}: 次の候補へ（index={repair[key]['index']}）")
    save(REPAIR_FILE, repair)


def cmd_apply(ids=None):
    """ids を指定すればその項目だけ反映（Noneなら候補があるもの全部）"""
    state = load(STATE_FILE, None)
    repair = load(REPAIR_FILE, {})

    by_id = {rec["id"]: rec for rec in state["done"].values()}
    applied = 0
    for key, ent in repair.items():
        item_id = int(key)
        if ids is not None and item_id not in ids:
            continue
        cands = ent["candidates"]
        idx = ent.get("fetched_index", ent["index"])
        if idx >= len(cands):
            print(f"id={item_id}: 候補がないためスキップ")
            continue
        cand = cands[idx]
        rec = by_id[item_id]
        rec.update({
            "image": cand["url"],
            "creator": cand["creator"],
            "license": cand["license"],
            "license_url": cand["license_url"],
            "source": cand["source"],
        })
        applied += 1

    save(STATE_FILE, state)
    records = sorted(state["done"].values(), key=lambda r: r["id"])
    records = [{k: v for k, v in r.items() if not k.startswith("_")} for r in records]
    save(JSON_FILE, records)
    print(f"apply 完了：{applied}件を差し替え、characters.json を再生成しました")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "search":
        cmd_search()
    elif cmd == "propose":
        cmd_propose()
    elif cmd == "reject":
        cmd_reject([int(x) for x in sys.argv[2:]])
    elif cmd == "apply":
        ids = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else None
        cmd_apply(ids)
    else:
        print("使い方: repair_single.py search|propose|reject <id...>|apply [id...]")
