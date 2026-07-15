# -*- coding: utf-8 -*-
"""
Openverse APIを使った「お題画像データセット」自動作成スクリプト

やること（全自動）
  1. Openverse APIで各お題を検索（商用利用可のライセンスだけに絞る）
  2. 条件に合う画像を1枚選ぶ
  3. 画像はローカルに保存せず「画像URL」だけを記録する
  4. 作者・ライセンス・元URLを入れた characters.json を生成
     （アプリは image のURLを直接表示する）

使い方
  $ python3 dataset_tools/build_dataset.py

  途中で止まっても、もう一度実行すれば続きから再開できます
  （進捗は dataset_tools/state.json に保存されます）

ライセンスの方針（文化祭での有料展示＝商用利用を想定）
  - cc0  : CC0（権利放棄）
  - pdm  : パブリックドメインマーク
  - by   : CC BY（クレジット表記が必要）
  - by-sa: CC BY-SA（クレジット表記＋同条件で共有）
  ※ NC（非営利限定）と ND（改変禁止）は使わない
"""

import json
import os
import re
import time

import requests

# ============================================================
# 設定
# ============================================================

# このスクリプトがあるフォルダとプロジェクトのフォルダ
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TOOLS_DIR)

# 出力先：Flaskからそのまま配信できるように static/dataset/ に置く
OUT_DIR = os.path.join(PROJECT_DIR, "static", "dataset")
STATE_FILE = os.path.join(TOOLS_DIR, "state.json")      # 進捗の保存先
JSON_FILE = os.path.join(OUT_DIR, "characters.json")    # 完成したデータの一覧

TARGET_COUNT = 200      # 集めたい枚数
MIN_SOURCE_SIZE = 400   # 元画像の最低サイズ（小さすぎる画像は除外）

API_URL = "https://api.openverse.org/v1/images/"
# 商用利用できるライセンスだけを対象にする
LICENSES = "cc0,pdm,by,by-sa"
# Openverseの匿名利用は約20回/分の制限があるので、検索1回ごとに少し待つ
API_WAIT_SECONDS = 3.2

HEADERS = {"User-Agent": "oekaki-yaroka-dataset/1.0 (school festival drawing game)"}

# 人物・キャラクターらしき画像を除外するためのNGワード
# （タイトル・タグにこれらが含まれていたらスキップする）
BANNED_WORDS = [
    "person", "people", "man", "woman", "boy", "girl", "child", "children",
    "kid", "human", "portrait", "face", "selfie", "model", "wedding", "bride",
    "cosplay", "anime", "manga", "cartoon", "comic", "character", "characters",
    "figurine", "action figure", "lego", "pokemon", "pikachu", "mario",
    "disney", "mickey", "hello kitty", "sanrio", "ghibli", "doll",
]

# ============================================================
# お題リスト（日本語名, 検索ワード（英語）, カテゴリ）
# 失敗する項目があっても200種そろうように、予備を含めて多めに定義
# ============================================================
ITEMS = [
    # ---------- 動物 ----------
    ("レッサーパンダ", "red panda", "動物"),
    ("ジャイアントパンダ", "giant panda bear", "動物"),
    ("ライオン", "lion", "動物"),
    ("トラ", "tiger", "動物"),
    ("ゾウ", "elephant", "動物"),
    ("キリン", "giraffe", "動物"),
    ("シマウマ", "zebra", "動物"),
    ("カバ", "hippopotamus", "動物"),
    ("サイ", "rhinoceros", "動物"),
    ("ゴリラ", "gorilla", "動物"),
    ("チンパンジー", "chimpanzee", "動物"),
    ("コアラ", "koala", "動物"),
    ("カンガルー", "kangaroo", "動物"),
    ("ナマケモノ", "sloth animal", "動物"),
    ("ハリネズミ", "hedgehog", "動物"),
    ("リス", "squirrel", "動物"),
    ("ウサギ", "rabbit", "動物"),
    ("ハムスター", "hamster", "動物"),
    ("イヌ", "dog", "動物"),
    ("ネコ", "cat", "動物"),
    ("キツネ", "fox", "動物"),
    ("オオカミ", "wolf", "動物"),
    ("クマ", "brown bear", "動物"),
    ("シロクマ", "polar bear", "動物"),
    ("ペンギン", "penguin", "動物"),
    ("フラミンゴ", "flamingo", "動物"),
    ("フクロウ", "owl", "動物"),
    ("ワシ", "eagle", "動物"),
    ("インコ", "parrot", "動物"),
    ("ハクチョウ", "swan", "動物"),
    ("アヒル", "duck", "動物"),
    ("ニワトリ", "rooster chicken", "動物"),
    ("ウマ", "horse", "動物"),
    ("ウシ", "cow cattle", "動物"),
    ("ブタ", "pig", "動物"),
    ("ヒツジ", "sheep", "動物"),
    ("ヤギ", "goat", "動物"),
    ("シカ", "deer", "動物"),
    ("ラクダ", "camel", "動物"),
    ("アルパカ", "alpaca", "動物"),
    ("イルカ", "dolphin", "動物"),
    ("クジラ", "whale", "動物"),
    ("サメ", "shark", "動物"),
    ("ウミガメ", "sea turtle", "動物"),
    ("タコ", "octopus", "動物"),
    ("クラゲ", "jellyfish", "動物"),
    ("カニ", "crab", "動物"),
    ("ラッコ", "sea otter", "動物"),
    ("アザラシ", "seal animal", "動物"),
    ("カワウソ", "otter", "動物"),
    ("カメレオン", "chameleon", "動物"),
    ("カエル", "frog", "動物"),
    ("ヘビ", "snake", "動物"),
    ("ワニ", "crocodile", "動物"),
    ("トカゲ", "lizard", "動物"),
    ("クジャク", "peacock", "動物"),
    ("ダチョウ", "ostrich", "動物"),
    ("ミーアキャット", "meerkat", "動物"),
    ("カピバラ", "capybara", "動物"),
    ("アライグマ", "raccoon", "動物"),
    # ---------- 昆虫など ----------
    ("カブトムシ", "rhinoceros beetle", "昆虫"),
    ("クワガタムシ", "stag beetle", "昆虫"),
    ("チョウ", "butterfly", "昆虫"),
    ("トンボ", "dragonfly", "昆虫"),
    ("テントウムシ", "ladybug", "昆虫"),
    ("ミツバチ", "honeybee", "昆虫"),
    ("バッタ", "grasshopper", "昆虫"),
    ("カマキリ", "praying mantis", "昆虫"),
    ("セミ", "cicada", "昆虫"),
    ("アリ", "ant macro", "昆虫"),
    ("カタツムリ", "snail", "昆虫"),
    ("ホタル", "firefly insect", "昆虫"),
    # ---------- 食べ物 ----------
    ("リンゴ", "red apple fruit", "食べ物"),
    ("バナナ", "banana fruit", "食べ物"),
    ("イチゴ", "strawberry fruit", "食べ物"),
    ("スイカ", "watermelon", "食べ物"),
    ("ブドウ", "grapes fruit", "食べ物"),
    ("パイナップル", "pineapple", "食べ物"),
    ("モモ", "peach fruit", "食べ物"),
    ("オレンジ", "orange fruit", "食べ物"),
    ("レモン", "lemon fruit", "食べ物"),
    ("サクランボ", "cherries fruit", "食べ物"),
    ("キウイ", "kiwi fruit", "食べ物"),
    ("メロン", "melon fruit", "食べ物"),
    ("トマト", "tomato vegetable", "食べ物"),
    ("ニンジン", "carrot vegetable", "食べ物"),
    ("ジャガイモ", "potato vegetable", "食べ物"),
    ("タマネギ", "onion vegetable", "食べ物"),
    ("ブロッコリー", "broccoli", "食べ物"),
    ("カボチャ", "pumpkin", "食べ物"),
    ("ナス", "eggplant", "食べ物"),
    ("トウモロコシ", "corn cob", "食べ物"),
    ("キノコ", "mushroom", "食べ物"),
    ("パン", "bread loaf", "食べ物"),
    ("クロワッサン", "croissant", "食べ物"),
    ("サンドイッチ", "sandwich", "食べ物"),
    ("ハンバーガー", "hamburger", "食べ物"),
    ("ピザ", "pizza", "食べ物"),
    ("スパゲッティ", "spaghetti pasta", "食べ物"),
    ("カレーライス", "curry rice", "食べ物"),
    ("寿司", "sushi", "食べ物"),
    ("ラーメン", "ramen noodles", "食べ物"),
    ("おにぎり", "onigiri rice ball", "食べ物"),
    ("ドーナツ", "donut", "食べ物"),
    ("ケーキ", "birthday cake", "食べ物"),
    ("パンケーキ", "pancakes", "食べ物"),
    ("アイスクリーム", "ice cream cone", "食べ物"),
    ("クッキー", "cookies", "食べ物"),
    ("チョコレート", "chocolate bar", "食べ物"),
    ("ポップコーン", "popcorn", "食べ物"),
    ("フライドポテト", "french fries", "食べ物"),
    ("目玉焼き", "fried egg", "食べ物"),
    # ---------- 乗り物 ----------
    ("自転車", "bicycle", "乗り物"),
    ("オートバイ", "motorcycle", "乗り物"),
    ("自動車", "vintage car", "乗り物"),
    ("バス", "bus vehicle", "乗り物"),
    ("トラック", "truck vehicle", "乗り物"),
    ("消防車", "fire truck", "乗り物"),
    ("パトカー", "police car", "乗り物"),
    ("救急車", "ambulance", "乗り物"),
    ("電車", "train railway", "乗り物"),
    ("蒸気機関車", "steam locomotive", "乗り物"),
    ("新幹線", "shinkansen bullet train", "乗り物"),
    ("飛行機", "airplane", "乗り物"),
    ("ヘリコプター", "helicopter", "乗り物"),
    ("熱気球", "hot air balloon", "乗り物"),
    ("ヨット", "sailboat", "乗り物"),
    ("フェリー", "ferry ship", "乗り物"),
    ("潜水艦", "submarine", "乗り物"),
    ("トラクター", "tractor", "乗り物"),
    ("ショベルカー", "excavator", "乗り物"),
    ("ロケット", "rocket launch", "乗り物"),
    # ---------- 建物 ----------
    ("城", "castle", "建物"),
    ("灯台", "lighthouse", "建物"),
    ("風車", "windmill", "建物"),
    ("五重塔", "pagoda", "建物"),
    ("教会", "church building", "建物"),
    ("橋", "bridge river", "建物"),
    ("高層ビル", "skyscraper", "建物"),
    ("ログハウス", "log cabin", "建物"),
    ("鳥居", "torii gate", "建物"),
    ("ピラミッド", "pyramid egypt", "建物"),
    ("観覧車", "ferris wheel", "建物"),
    ("温室", "greenhouse", "建物"),
    ("納屋", "barn farm", "建物"),
    ("水車小屋", "watermill", "建物"),
    ("テント", "camping tent", "建物"),
    # ---------- 楽器 ----------
    ("ピアノ", "grand piano", "楽器"),
    ("ギター", "acoustic guitar", "楽器"),
    ("バイオリン", "violin", "楽器"),
    ("チェロ", "cello", "楽器"),
    ("フルート", "flute instrument", "楽器"),
    ("サックス", "saxophone", "楽器"),
    ("トランペット", "trumpet", "楽器"),
    ("ドラムセット", "drum kit", "楽器"),
    ("ハーモニカ", "harmonica", "楽器"),
    ("アコーディオン", "accordion", "楽器"),
    ("ウクレレ", "ukulele", "楽器"),
    ("ハープ", "harp instrument", "楽器"),
    ("太鼓", "taiko drum", "楽器"),
    ("木琴", "xylophone", "楽器"),
    ("タンバリン", "tambourine", "楽器"),
    # ---------- スポーツ用品 ----------
    ("サッカーボール", "soccer ball", "スポーツ用品"),
    ("バスケットボール", "basketball ball", "スポーツ用品"),
    ("野球グローブ", "baseball glove", "スポーツ用品"),
    ("テニスラケット", "tennis racket", "スポーツ用品"),
    ("バドミントンのシャトル", "badminton shuttlecock", "スポーツ用品"),
    ("ゴルフクラブ", "golf club", "スポーツ用品"),
    ("スケートボード", "skateboard", "スポーツ用品"),
    ("スキー板", "skis snow", "スポーツ用品"),
    ("スノーボード", "snowboard", "スポーツ用品"),
    ("ボウリングのピン", "bowling pins", "スポーツ用品"),
    ("ダーツ", "dartboard", "スポーツ用品"),
    ("卓球ラケット", "table tennis paddle", "スポーツ用品"),
    ("ボクシンググローブ", "boxing gloves", "スポーツ用品"),
    ("ラグビーボール", "rugby ball", "スポーツ用品"),
    ("サーフボード", "surfboard", "スポーツ用品"),
    # ---------- 植物 ----------
    ("ヒマワリ", "sunflower", "植物"),
    ("バラ", "rose flower", "植物"),
    ("チューリップ", "tulip flower", "植物"),
    ("サクラ", "cherry blossom", "植物"),
    ("アサガオ", "morning glory flower", "植物"),
    ("アジサイ", "hydrangea", "植物"),
    ("タンポポ", "dandelion", "植物"),
    ("サボテン", "cactus", "植物"),
    ("モミジ", "maple leaves autumn", "植物"),
    ("マツボックリ", "pine cone", "植物"),
    ("竹", "bamboo forest", "植物"),
    ("ヤシの木", "palm tree", "植物"),
    ("スイレン", "water lily", "植物"),
    ("ラベンダー", "lavender field", "植物"),
    ("コスモス", "cosmos flower", "植物"),
    ("ユリ", "lily flower", "植物"),
    ("盆栽", "bonsai tree", "植物"),
    ("多肉植物", "succulent plant", "植物"),
    ("シダ", "fern plant", "植物"),
    ("オリーブの木", "olive tree", "植物"),
    # ---------- 道具・日用品 ----------
    ("メガネ", "eyeglasses", "道具"),
    ("腕時計", "wristwatch", "道具"),
    ("傘", "umbrella", "道具"),
    ("カメラ", "vintage camera", "道具"),
    ("ランタン", "lantern", "道具"),
    ("やかん", "kettle", "道具"),
    ("ティーポット", "teapot", "道具"),
    ("マグカップ", "coffee mug", "道具"),
    ("ハサミ", "scissors", "道具"),
    ("鉛筆", "pencils", "道具"),
    ("本", "old books", "道具"),
    ("椅子", "wooden chair", "道具"),
    ("長靴", "rain boots", "道具"),
    ("麦わら帽子", "straw hat", "道具"),
    ("リュックサック", "backpack", "道具"),
    ("望遠鏡", "telescope", "道具"),
    ("地球儀", "globe map", "道具"),
    ("砂時計", "hourglass", "道具"),
    ("古い鍵", "old key", "道具"),
    ("郵便ポスト", "mailbox", "道具"),
]

# ============================================================
# ライセンス表示用のヘルパー
# ============================================================

def license_label(result):
    """APIの結果から「CC BY 2.0」のような表示用文字列を作る"""
    lic = (result.get("license") or "").lower()
    ver = result.get("license_version") or ""
    if lic == "cc0":
        return "CC0 1.0"
    if lic == "pdm":
        return "Public Domain Mark"
    if lic in ("by", "by-sa"):
        return f"CC {lic.upper()} {ver}".strip()
    return lic  # 想定外はそのまま


def is_banned(result):
    """タイトル・タグにNGワード（人物・キャラクター系）が含まれるか"""
    text = (result.get("title") or "").lower()
    for tag in result.get("tags") or []:
        text += " " + (tag.get("name") or "").lower()
    # 単語の境界で判定する（catがcategoryに反応しないように）
    for word in BANNED_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return True
    return False


# ============================================================
# 手順1：Openverse APIで検索
# ============================================================

def search_openverse(session, query):
    """お題1つぶんをOpenverseで検索して、結果リストを返す"""
    params = {
        "q": query,
        "license": LICENSES,            # 商用利用可のライセンスだけ
        "license_type": "commercial",   # 念押しで商用利用可のみ
        "category": "photograph",       # 写真のみ（イラスト＝キャラ混入を避ける）
        "per_page": 20,
    }
    for attempt in range(3):
        res = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
        if res.status_code == 429:
            # レート制限に当たったら1分ちょっと待って再挑戦
            print(f"    レート制限。65秒待ちます…（{attempt + 1}回目）")
            time.sleep(65)
            continue
        res.raise_for_status()
        return res.json().get("results", [])
    raise RuntimeError("レート制限が解除されませんでした（明日再実行してください）")


def pick_result(results, used_urls):
    """検索結果から、条件に合う最初の1枚を選ぶ"""
    for r in results:
        url = r.get("url")
        if not url or url in used_urls:
            continue  # URLなし・別のお題で使用済みはスキップ
        # ライセンスの再確認（API任せにせず自分でもチェック）
        if (r.get("license") or "").lower() not in ("cc0", "pdm", "by", "by-sa"):
            continue
        # 小さすぎる画像はスキップ
        w, h = r.get("width") or 0, r.get("height") or 0
        if w and h and min(w, h) < MIN_SOURCE_SIZE:
            continue
        # SVGやGIFはスキップ（写真だけ欲しい）
        ft = (r.get("filetype") or "").lower()
        if ft in ("svg", "gif"):
            continue
        # 人物・キャラクターらしきものはスキップ
        if is_banned(r):
            continue
        return r
    return None


# ============================================================
# 進捗の保存・読み込み（途中から再開できるように）
# ============================================================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "failed": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================
# 手順4：characters.json の生成
# ============================================================

def write_json(state):
    """集めたデータを id 順に並べて characters.json に書き出す"""
    records = sorted(state["done"].values(), key=lambda r: r["id"])
    # 「_」で始まる内部管理用の項目はJSONに入れない
    cleaned = [{k: v for k, v in r.items() if not k.startswith("_")} for r in records]
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print(f"JSONを書き出しました: {JSON_FILE}（{len(cleaned)}件）")


# ============================================================
# メイン処理
# ============================================================

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    state = load_state()
    session = requests.Session()

    # すでに使った画像URL（同じ画像を2つのお題で使わないため）
    used_urls = {rec["image"] for rec in state["done"].values()}

    done_count = len(state["done"])
    print(f"開始：{done_count} / {TARGET_COUNT} 件 取得済み")

    for name, query, category in ITEMS:
        if len(state["done"]) >= TARGET_COUNT:
            break  # 200種そろったら終了
        if query in state["done"] or query in state["failed"]:
            continue  # 前回実行ぶんはスキップ（再開機能）

        print(f"[{len(state['done']) + 1:3d}/{TARGET_COUNT}] {name}（{query}）")

        try:
            results = search_openverse(session, query)
        except RuntimeError as e:
            # レート制限で続行不可能：進捗を保存して終了
            print(f"中断: {e}")
            break
        except Exception as e:
            print(f"    検索失敗: {e}")
            state["failed"].append(query)
            save_state(state)
            time.sleep(API_WAIT_SECONDS)
            continue

        time.sleep(API_WAIT_SECONDS)  # レート制限対策の待ち時間

        chosen = pick_result(results, used_urls)
        if chosen is None:
            print("    条件に合う画像が見つかりませんでした")
            state["failed"].append(query)
            save_state(state)
            continue

        # 通し番号を割り当てて記録（画像はダウンロードせずURLだけ保存）
        next_id = len(state["done"]) + 1
        state["done"][query] = {
            "id": next_id,
            "name": name,
            "category": category,
            "image": chosen["url"],  # 画像のURL（アプリはこれを直接表示する）
            "creator": chosen.get("creator") or "不明",
            "license": license_label(chosen),
            "license_url": chosen.get("license_url") or "",
            "source": chosen.get("foreign_landing_url") or chosen.get("url"),
        }
        used_urls.add(chosen["url"])
        save_state(state)
        print(f"    OK → id={next_id}（{state['done'][query]['license']} / {state['done'][query]['creator']}）")

    # 最後にJSONを書き出す
    write_json(state)

    got = len(state["done"])
    if got >= TARGET_COUNT:
        print(f"完了！ {got}種類の画像がそろいました 🎉")
    else:
        print(f"現在 {got} / {TARGET_COUNT} 件。もう一度実行すると続きから再開します。")
        print(f"（失敗したお題: {len(state['failed'])}件）")


if __name__ == "__main__":
    main()
