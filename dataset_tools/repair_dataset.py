# -*- coding: utf-8 -*-
"""
データセットの不良項目を差し替える修理ツール

目視チェックで「お題と画像が合っていない」と判明した項目を、
より厳しい条件で再検索して差し替える。

使い方（3ステップを繰り返す）
  1. python3 repair_dataset.py search   … 不良項目をAPIで再検索して候補を貯める（API消費はここだけ）
  2. python3 repair_dataset.py propose  … 現在の候補画像をレビュー用シートに出力（目視チェック用）
  3. だめな候補があれば
     python3 repair_dataset.py reject 4 15 39 … その項目は次の候補に切り替え → 2へ戻る
  4. 全部OKになったら
     python3 repair_dataset.py apply    … state.json と characters.json に反映

前回の検索結果（最大30候補/項目）をキャッシュするので、
reject→propose のやり直しではAPIを消費しない。
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
REPAIR_FILE = os.path.join(TOOLS_DIR, "repair_state.json")
JSON_FILE = os.path.join(PROJECT_DIR, "static", "dataset", "characters.json")

# レビュー用の一時画像置き場（データセット本体には保存しない）
REVIEW_DIR = os.environ.get(
    "REVIEW_DIR",
    "/private/tmp/claude-501/-Users-yushin-seisaku-app-oekaki/051639da-850a-45f6-b5a5-18208db601e2/scratchpad/review",
)

API_URL = "https://api.openverse.org/v1/images/"
HEADERS = {"User-Agent": "hakushi-akande-dataset/1.0 (school festival drawing game)"}
API_WAIT_SECONDS = 3.2

# 人物・キャラ・絵画・模型など「写真のお題」に不向きなもののNGワード
BANNED_WORDS = [
    "person", "people", "man", "woman", "boy", "girl", "child", "children",
    "kid", "human", "portrait", "face", "selfie", "model", "wedding", "bride",
    "cosplay", "anime", "manga", "cartoon", "comic", "character", "characters",
    "figurine", "action figure", "lego", "pokemon", "pikachu", "mario",
    "disney", "mickey", "hello kitty", "sanrio", "ghibli", "doll",
    "silhouette", "costume", "painting", "drawing", "illustration", "sketch",
    "statue", "sculpture", "mural", "poster", "sign", "advertisement",
    "skull", "skeleton", "taxidermy", "museum", "cemetery", "grave",
    "abandoned", "ruins", "catalog", "stamp", "graffiti", "artwork",
    "miniature", "carving", "book", "cover",
]

# ============================================================
# 差し替え対象：{id: (新しい検索ワード, タイトル/タグに必須の単語リスト)}
# 必須単語のどれかがタイトルかタグに入っている画像だけを候補にする
# ============================================================
REPAIRS = {
    4:   ("tiger stripes wildlife",        ["tiger"]),
    5:   ("african elephant safari",       ["elephant"]),
    9:   ("white rhinoceros grassland",    ["rhino"]),
    12:  ("koala eucalyptus tree",         ["koala"]),
    13:  ("kangaroo grassland australia",  ["kangaroo"]),
    14:  ("sloth hanging branch",          ["sloth"]),
    15:  ("hedgehog animal garden",        ["hedgehog"]),
    18:  ("hamster pet rodent",            ["hamster"]),
    19:  ("golden retriever dog",          ["dog", "retriever"]),
    24:  ("polar bear ice snow",           ["polar bear"]),
    26:  ("pink flamingo wading bird",     ["flamingo"]),
    29:  ("macaw parrot colorful",         ["parrot", "macaw"]),
    30:  ("mute swan lake white",          ["swan"]),
    35:  ("pig piglet farm animal",        ["pig", "piglet"]),
    39:  ("camel desert dromedary",        ["camel"]),
    40:  ("alpaca fluffy white",           ["alpaca"]),
    42:  ("humpback whale ocean",          ["whale"]),
    43:  ("shark swimming underwater",     ["shark"]),
    44:  ("green sea turtle swimming",     ["turtle"]),
    45:  ("octopus tentacles underwater",  ["octopus"]),
    47:  ("crab claws shore",              ["crab"]),
    52:  ("green frog pond amphibian",     ["frog"]),
    54:  ("crocodile reptile water",       ["crocodile", "alligator"]),
    56:  ("peacock tail feathers display", ["peacock"]),
    57:  ("ostrich bird long neck",        ["ostrich"]),
    61:  ("rhinoceros beetle horn insect", ["beetle"]),
    62:  ("stag beetle mandibles",         ["stag beetle"]),
    66:  ("honeybee flower pollen macro",  ["bee"]),
    69:  ("cicada insect tree",            ["cicada"]),
    70:  ("black ant insect macro",        ["ant"]),
    72:  ("firefly lightning bug",         ["firefly", "lightning bug"]),
    74:  ("banana bunch yellow fruit",     ["banana"]),
    78:  ("pineapple whole tropical fruit", ["pineapple"]),
    79:  ("ripe peaches fruit",            ["peach"]),
    87:  ("raw potatoes vegetable",        ["potato"]),
    88:  ("onions bulb vegetable",         ["onion"]),
    89:  ("fresh broccoli green",          ["broccoli"]),
    90:  ("orange pumpkin autumn",         ["pumpkin"]),
    91:  ("purple eggplant vegetable",     ["eggplant", "aubergine"]),
    92:  ("corn cob kernels husk",         ["corn"]),
    95:  ("croissant pastry bakery",       ["croissant"]),
    96:  ("sandwich bread lunch",          ["sandwich"]),
    97:  ("cheeseburger burger bun",       ["burger"]),
    103: ("glazed donuts sprinkles",       ["donut", "doughnut"]),
    105: ("pancakes stack syrup",          ["pancake"]),
    106: ("ice cream cone scoop",          ["ice cream"]),
    107: ("chocolate chip cookies",        ["cookie"]),
    108: ("chocolate bar cocoa pieces",    ["chocolate"]),
    109: ("popcorn bowl snack",            ["popcorn"]),
    111: ("fried egg sunny side up",       ["fried egg", "egg"]),
    112: ("bicycle parked wall",           ["bicycle", "bike"]),
    113: ("motorcycle parked road",        ["motorcycle", "motorbike"]),
    114: ("classic car vintage red",       ["car"]),
    115: ("london double decker bus",      ["bus"]),
    119: ("ambulance emergency vehicle",   ["ambulance"]),
    120: ("train locomotive railway",      ["train"]),
    122: ("shinkansen bullet train japan", ["shinkansen", "bullet train"]),
    123: ("airplane jet flying sky",       ["airplane", "aircraft", "plane"]),
    124: ("helicopter flying rotor",       ["helicopter"]),
    128: ("submarine navy harbor",         ["submarine"]),
    130: ("excavator digger construction", ["excavator", "digger"]),
    131: ("rocket launch pad space",       ["rocket"]),
    135: ("five storied pagoda japan",     ["pagoda"]),
    138: ("skyscraper glass building city", ["skyscraper", "tower"]),
    140: ("torii gate shrine japan",       ["torii"]),
    142: ("ferris wheel amusement park",   ["ferris wheel"]),
    143: ("greenhouse glass house plants", ["greenhouse"]),
    145: ("watermill water wheel",         ["mill", "water wheel"]),
    147: ("grand piano keys black",        ["piano"]),
    148: ("acoustic guitar wooden",        ["guitar"]),
    150: ("cello classical instrument",    ["cello"]),
    151: ("flute silver woodwind",         ["flute"]),
    152: ("saxophone brass gold",          ["saxophone", "sax"]),
    153: ("trumpet brass instrument",      ["trumpet"]),
    155: ("harmonica blues instrument",    ["harmonica"]),
    156: ("accordion folk instrument",     ["accordion"]),
    157: ("ukulele wooden instrument",     ["ukulele"]),
    158: ("harp strings golden",           ["harp"]),
    159: ("taiko japanese drum",           ["taiko", "drum"]),
    160: ("xylophone marimba mallets",     ["xylophone", "marimba"]),
    161: ("tambourine percussion",         ["tambourine"]),
    164: ("baseball glove leather ball",   ["glove", "mitt"]),
    167: ("golf clubs irons bag",          ["golf club", "golf"]),
    168: ("skateboard deck wheels",        ["skateboard"]),
    169: ("skis ski poles snow",           ["ski"]),
    170: ("snowboard on snow",             ["snowboard"]),
    171: ("bowling pins lane",             ["bowling"]),
    174: ("red boxing gloves",             ["boxing glove", "boxing"]),
    176: ("surfboard beach sand",          ["surfboard"]),
    179: ("tulip field colorful flowers",  ["tulip"]),
    180: ("cherry blossom branch pink",    ["cherry blossom", "sakura", "blossom"]),
    181: ("morning glory blue flower",     ["morning glory"]),
    182: ("hydrangea blue flower bush",    ["hydrangea"]),
    186: ("pine cone conifer branch",      ["pine cone", "pinecone"]),
    187: ("bamboo grove green stalks",     ["bamboo"]),
    198: ("wristwatch analog dial",        ["watch"]),
    199: ("red umbrella rain",             ["umbrella"]),
}


# ============================================================
# 共通処理
# ============================================================

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
    """タイトル＋タグをまとめた検索用テキスト"""
    text = (r.get("title") or "").lower()
    for tag in r.get("tags") or []:
        text += " " + (tag.get("name") or "").lower()
    return text


def is_banned(r):
    text = text_of(r)
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in BANNED_WORDS)


def has_required(r, required):
    """必須単語（どれか1つ）がタイトルかタグに含まれるか"""
    text = text_of(r)
    return any(w in text for w in required)


def all_used_urls(state, repair):
    """データセット全体＋確定済み候補で使用中のURL一覧（重複防止）"""
    urls = {rec["image"] for rec in state["done"].values()}
    for ent in repair.values():
        cands = ent.get("candidates", [])
        idx = ent.get("index", 0)
        if idx < len(cands):
            urls.add(cands[idx]["url"])
    return urls


# ============================================================
# search：不良項目を再検索して候補リストを貯める（APIを使うのはここだけ）
# ============================================================

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

        # 条件を満たす候補だけを貯める
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


# ============================================================
# propose：現在の候補をダウンロードしてレビュー用シートを作る
# （画像はレビュー用の一時フォルダにだけ置く。データセットには保存しない）
# ============================================================

def is_grayscale(img):
    """白黒写真かどうかをざっくり判定（彩度の平均が低ければ白黒とみなす）"""
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

        # ダウンロード済みで候補も変わっていなければスキップ
        if ent.get("fetched_index") == ent["index"] and os.path.exists(path):
            ok.append(item_id)
            continue

        # 使えない候補（DL失敗・白黒・重複）は自動で次へ進む
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

    # レビュー用のコンタクトシートを作る
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


# ============================================================
# reject：指定した項目を次の候補に切り替える
# ============================================================

def cmd_reject(ids):
    repair = load(REPAIR_FILE, {})
    for item_id in ids:
        key = str(item_id)
        if key in repair:
            repair[key]["index"] += 1
            print(f"id={item_id}: 次の候補へ（index={repair[key]['index']}）")
    save(REPAIR_FILE, repair)


# ============================================================
# apply：確定した候補を state.json と characters.json に反映する
# ============================================================

def cmd_apply():
    state = load(STATE_FILE, None)
    repair = load(REPAIR_FILE, {})

    by_id = {rec["id"]: (query, rec) for query, rec in
             ((q, r) for q, r in state["done"].items())}
    applied = 0
    for key, ent in repair.items():
        item_id = int(key)
        cands = ent["candidates"]
        idx = ent.get("fetched_index", ent["index"])
        if idx >= len(cands):
            print(f"id={item_id}: 候補がないためスキップ")
            continue
        cand = cands[idx]
        _, rec = by_id[item_id]
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
        cmd_apply()
    else:
        print("使い方: repair_dataset.py search|propose|reject <id...>|apply")
