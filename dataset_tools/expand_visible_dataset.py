# -*- coding: utf-8 -*-
"""表示中ジャンルのお題を、外部画像URLだけで追加する。"""

import json
import os
import re
import time
from html import unescape

import requests


TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TOOLS_DIR)
JSON_FILE = os.path.join(PROJECT_DIR, "static", "dataset", "characters.json")

NOTO_TREE_URL = "https://api.github.com/repos/googlefonts/noto-emoji/git/trees/main?recursive=1"
NOTO_RAW_BASE = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/svg"
NOTO_SOURCE_BASE = "https://github.com/googlefonts/noto-emoji/blob/main/svg"
NOTO_LICENSE_URL = "https://github.com/googlefonts/noto-emoji/blob/main/svg/LICENSE"

OPENVERSE_URL = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENSES = {"cc0", "pdm", "by", "by-sa"}
OPENVERSE_WAIT_SECONDS = 3.2
OPENVERSE_IMAGES_PER_TOPIC = 2

COMMONS_URL = "https://commons.wikimedia.org/w/api.php"
COMMONS_WAIT_SECONDS = 0.3

HEADERS = {
    "User-Agent": "oekaki-yaroka-dataset/2.0 (https://oekaki.webtool-labs.com)"
}

BANNED_WORDS = {
    "person", "people", "man", "woman", "boy", "girl", "child", "children",
    "portrait", "selfie", "cosplay", "anime", "manga", "cartoon", "character",
    "figurine", "action figure", "lego", "pokemon", "doll",
}


# (日本語のお題名, Noto Emojiのファイル名に使われるコードポイント, カテゴリ)
NOTO_ITEMS = [
    # 動物
    ("ネズミ", "1f401", "動物"),
    ("ネズミの顔", "1f42d", "動物"),
    ("ラット", "1f400", "動物"),
    ("ハムスター", "1f439", "動物"),
    ("シマリス", "1f43f", "動物"),
    ("ビーバー", "1f9ab", "動物"),
    ("ハリネズミ", "1f994", "動物"),
    ("コウモリ", "1f987", "動物"),
    ("オオカミ", "1f43a", "動物"),
    ("シカ", "1f98c", "動物"),
    ("イノシシ", "1f417", "動物"),
    ("ブタ", "1f416", "動物"),
    ("ブタの顔", "1f437", "動物"),
    ("ウシ", "1f404", "動物"),
    ("ウシの顔", "1f42e", "動物"),
    ("雄牛", "1f402", "動物"),
    ("水牛", "1f403", "動物"),
    ("バイソン", "1f9ac", "動物"),
    ("ヤギ", "1f410", "動物"),
    ("ヒツジ", "1f411", "動物"),
    ("雄ヒツジ", "1f40f", "動物"),
    ("ラマ", "1f999", "動物"),
    ("キリン", "1f992", "動物"),
    ("ゾウ", "1f418", "動物"),
    ("マンモス", "1f9a3", "動物"),
    ("サイ", "1f98f", "動物"),
    ("カバ", "1f99b", "動物"),
    ("ラクダ", "1f42a", "動物"),
    ("ヒトコブラクダ", "1f42b", "動物"),
    ("カンガルー", "1f998", "動物"),
    ("スカンク", "1f9a8", "動物"),
    ("アナグマ", "1f9a1", "動物"),
    ("サル", "1f412", "動物"),
    ("ゴリラ", "1f98d", "動物"),
    ("オランウータン", "1f9a7", "動物"),
    ("イヌ", "1f415", "動物"),
    ("プードル", "1f429", "動物"),
    ("ネコ", "1f408", "動物"),
    ("トラ", "1f405", "動物"),
    ("ヒョウ", "1f406", "動物"),
    ("ウマ", "1f40e", "動物"),
    ("シマウマ", "1f993", "動物"),
    ("ニワトリ", "1f414", "動物"),
    ("オンドリ", "1f413", "動物"),
    ("七面鳥", "1f983", "動物"),
    ("アヒル", "1f986", "動物"),
    ("ワシ", "1f985", "動物"),
    ("フクロウ", "1f989", "動物"),
    ("ドードー", "1f9a4", "動物"),
    ("フラミンゴ", "1f9a9", "動物"),
    ("クジャク", "1f99a", "動物"),
    ("オウム", "1f99c", "動物"),
    ("ハクチョウ", "1f9a2", "動物"),
    ("ペンギン", "1f427", "動物"),
    ("ハト", "1f54a", "動物"),
    ("イルカ", "1f42c", "動物"),
    ("魚", "1f41f", "動物"),
    ("熱帯魚", "1f420", "動物"),
    ("フグ", "1f421", "動物"),
    ("サメ", "1f988", "動物"),
    ("クジラ", "1f40b", "動物"),
    ("潮を吹くクジラ", "1f433", "動物"),
    ("アザラシ", "1f9ad", "動物"),
    ("タコ", "1f419", "動物"),
    ("イカ", "1f991", "動物"),
    ("エビ", "1f990", "動物"),
    ("ロブスター", "1f99e", "動物"),
    ("カニ", "1f980", "動物"),
    ("カキ", "1f9aa", "動物"),
    ("クラゲ", "1fabc", "動物"),
    ("カメ", "1f422", "動物"),
    ("ワニ", "1f40a", "動物"),
    ("ヘビ", "1f40d", "動物"),
    ("トカゲ", "1f98e", "動物"),
    ("ドラゴン", "1f409", "動物"),
    ("ティラノサウルス", "1f996", "動物"),
    ("首長竜", "1f995", "動物"),

    # 昆虫など
    ("イモムシ", "1f41b", "昆虫"),
    ("カタツムリ", "1f40c", "昆虫"),
    ("コオロギ", "1f997", "昆虫"),
    ("甲虫", "1fab2", "昆虫"),
    ("ゴキブリ", "1fab3", "昆虫"),
    ("ハエ", "1fab0", "昆虫"),
    ("蚊", "1f99f", "昆虫"),
    ("ミミズ", "1fab1", "昆虫"),
    ("サソリ", "1f982", "昆虫"),
    ("クモの巣", "1f578", "昆虫"),

    # 食べ物
    ("青リンゴ", "1f34f", "食べ物"),
    ("洋ナシ", "1f350", "食べ物"),
    ("ミカン", "1f34a", "食べ物"),
    ("レモン", "1f34b", "食べ物"),
    ("スイカ", "1f349", "食べ物"),
    ("ブドウ", "1f347", "食べ物"),
    ("イチゴ", "1f353", "食べ物"),
    ("メロン", "1f348", "食べ物"),
    ("サクランボ", "1f352", "食べ物"),
    ("モモ", "1f351", "食べ物"),
    ("パイナップル", "1f34d", "食べ物"),
    ("マンゴー", "1f96d", "食べ物"),
    ("キウイ", "1f95d", "食べ物"),
    ("トマト", "1f345", "食べ物"),
    ("オリーブ", "1fad2", "食べ物"),
    ("ココナッツ", "1f965", "食べ物"),
    ("アボカド", "1f951", "食べ物"),
    ("ナス", "1f346", "食べ物"),
    ("ジャガイモ", "1f954", "食べ物"),
    ("ニンジン", "1f955", "食べ物"),
    ("トウモロコシ", "1f33d", "食べ物"),
    ("唐辛子", "1f336", "食べ物"),
    ("パプリカ", "1fad1", "食べ物"),
    ("キュウリ", "1f952", "食べ物"),
    ("葉野菜", "1f96c", "食べ物"),
    ("ブロッコリー", "1f966", "食べ物"),
    ("ニンニク", "1f9c4", "食べ物"),
    ("タマネギ", "1f9c5", "食べ物"),
    ("ピーナッツ", "1f95c", "食べ物"),
    ("豆", "1fad8", "食べ物"),
    ("クリ", "1f330", "食べ物"),
    ("ショウガ", "1fada", "食べ物"),
    ("エンドウ豆", "1fadb", "食べ物"),
    ("キノコ", "1f344", "食べ物"),
    ("パン", "1f35e", "食べ物"),
    ("クロワッサン", "1f950", "食べ物"),
    ("フランスパン", "1f956", "食べ物"),
    ("ナン", "1fad3", "食べ物"),
    ("プレッツェル", "1f968", "食べ物"),
    ("ベーグル", "1f96f", "食べ物"),
    ("パンケーキ", "1f95e", "食べ物"),
    ("ワッフル", "1f9c7", "食べ物"),
    ("チーズ", "1f9c0", "食べ物"),
    ("骨付き肉", "1f356", "食べ物"),
    ("鶏もも肉", "1f357", "食べ物"),
    ("ステーキ", "1f969", "食べ物"),
    ("ベーコン", "1f953", "食べ物"),
    ("ハンバーガー", "1f354", "食べ物"),
    ("フライドポテト", "1f35f", "食べ物"),
    ("ホットドッグ", "1f32d", "食べ物"),
    ("サンドイッチ", "1f96a", "食べ物"),
    ("タコス", "1f32e", "食べ物"),
    ("ブリトー", "1f32f", "食べ物"),
    ("タマル", "1fad4", "食べ物"),
    ("ケバブ", "1f959", "食べ物"),
    ("ファラフェル", "1f9c6", "食べ物"),
    ("卵", "1f95a", "食べ物"),
    ("目玉焼き", "1f373", "食べ物"),
    ("シチュー", "1f372", "食べ物"),
    ("フォンデュ", "1fad5", "食べ物"),
    ("サラダ", "1f957", "食べ物"),
    ("ポップコーン", "1f37f", "食べ物"),
    ("バター", "1f9c8", "食べ物"),
    ("缶詰", "1f96b", "食べ物"),
    ("弁当", "1f371", "食べ物"),
    ("せんべい", "1f358", "食べ物"),
    ("ご飯", "1f35a", "食べ物"),
    ("カレーライス", "1f35b", "食べ物"),
    ("ラーメン", "1f35c", "食べ物"),
    ("スパゲッティ", "1f35d", "食べ物"),
    ("焼き芋", "1f360", "食べ物"),
    ("おでん", "1f362", "食べ物"),
    ("寿司", "1f363", "食べ物"),
    ("天ぷら", "1f364", "食べ物"),
    ("かまぼこ", "1f365", "食べ物"),
    ("月餅", "1f96e", "食べ物"),
    ("だんご", "1f361", "食べ物"),
    ("餃子", "1f95f", "食べ物"),
    ("フォーチュンクッキー", "1f960", "食べ物"),
    ("テイクアウト弁当", "1f961", "食べ物"),
    ("アイスクリーム", "1f368", "食べ物"),
    ("かき氷", "1f367", "食べ物"),
    ("ソフトクリーム", "1f366", "食べ物"),
    ("ドーナツ", "1f369", "食べ物"),
    ("クッキー", "1f36a", "食べ物"),
    ("誕生日ケーキ", "1f382", "食べ物"),
    ("カップケーキ", "1f9c1", "食べ物"),
    ("パイ", "1f967", "食べ物"),
    ("チョコレート", "1f36b", "食べ物"),
    ("キャンディ", "1f36c", "食べ物"),
    ("ペロペロキャンディ", "1f36d", "食べ物"),
    ("プリン", "1f36e", "食べ物"),
    ("ハチミツ", "1f36f", "食べ物"),

    # 植物
    ("芽", "1f331", "植物"),
    ("常緑樹", "1f332", "植物"),
    ("ヤシの木", "1f334", "植物"),
    ("稲", "1f33e", "植物"),
    ("クローバー", "2618", "植物"),
    ("四つ葉のクローバー", "1f340", "植物"),
    ("カエデの葉", "1f341", "植物"),
    ("落ち葉", "1f342", "植物"),
    ("風に舞う葉", "1f343", "植物"),
    ("枯れ枝", "1fab9", "植物"),
    ("ヒヤシンス", "1fabb", "植物"),
    ("ハス", "1fab7", "植物"),
    ("バラ", "1f339", "植物"),
    ("しおれた花", "1f940", "植物"),
    ("ハイビスカス", "1f33a", "植物"),
    ("桜の花", "1f338", "植物"),
    ("花", "1f33c", "植物"),
    ("花束", "1f490", "植物"),
    ("白い花", "1f4ae", "植物"),

    # 風景（データ上は既存互換のため「建物」）
    ("雪山", "1f3d4", "建物"),
    ("キャンプ場", "1f3d5", "建物"),
    ("海水浴場", "1f3d6", "建物"),
    ("砂漠", "1f3dc", "建物"),
    ("無人島", "1f3dd", "建物"),
    ("国立公園", "1f3de", "建物"),
    ("スタジアム", "1f3df", "建物"),
    ("博物館", "1f3db", "建物"),
    ("家", "1f3e0", "建物"),
    ("庭のある家", "1f3e1", "建物"),
    ("オフィスビル", "1f3e2", "建物"),
    ("郵便局", "1f3e3", "建物"),
    ("病院", "1f3e5", "建物"),
    ("銀行", "1f3e6", "建物"),
    ("ホテル", "1f3e8", "建物"),
    ("コンビニ", "1f3ea", "建物"),
    ("学校", "1f3eb", "建物"),
    ("工場", "1f3ed", "建物"),
    ("日本の城", "1f3ef", "建物"),
    ("結婚式場", "1f492", "建物"),
    ("東京タワー", "1f5fc", "建物"),
    ("自由の女神", "1f5fd", "建物"),
    ("街並み", "1f3d9", "建物"),
    ("夕焼け", "1f307", "建物"),
    ("夕暮れの街", "1f306", "建物"),
    ("星空", "1f303", "建物"),
    ("天の川", "1f30c", "建物"),
    ("虹", "1f308", "建物"),
    ("大波", "1f30a", "建物"),
    ("噴水", "26f2", "建物"),
    ("キャンプ", "26fa", "建物"),
    ("温泉", "2668", "建物"),
    ("神社", "26e9", "建物"),
    ("教会", "26ea", "建物"),
    ("モスク", "1f54c", "建物"),
    ("シナゴーグ", "1f54d", "建物"),
    ("カーバ神殿", "1f54b", "建物"),
]


# 昆虫は絵文字の種類が少ないため、Openverseの写真を2枚ずつ補う。
OPENVERSE_TOPICS = [
    ("ガ", "moth insect macro", "昆虫"),
    ("アゲハチョウ", "swallowtail butterfly macro", "昆虫"),
    ("モンシロチョウ", "white butterfly insect", "昆虫"),
    ("オニヤンマ", "dragonfly insect macro", "昆虫"),
    ("イトトンボ", "damselfly insect macro", "昆虫"),
    ("ハナムグリ", "flower chafer beetle", "昆虫"),
    ("タマムシ", "jewel beetle insect", "昆虫"),
    ("ゲンゴロウ", "diving beetle insect", "昆虫"),
    ("カミキリムシ", "longhorn beetle insect", "昆虫"),
    ("ゾウムシ", "weevil insect macro", "昆虫"),
    ("ミノムシ", "bagworm insect", "昆虫"),
    ("ケムシ", "hairy caterpillar macro", "昆虫"),
    ("アブ", "horsefly insect macro", "昆虫"),
    ("ハエ", "housefly insect macro", "昆虫"),
    ("蚊", "mosquito insect macro", "昆虫"),
    ("コオロギ", "cricket insect macro", "昆虫"),
    ("キリギリス", "katydid insect", "昆虫"),
    ("ナナフシ", "stick insect macro", "昆虫"),
    ("カメムシ", "stink bug insect macro", "昆虫"),
    ("アメンボ", "water strider insect", "昆虫"),
    ("ハサミムシ", "earwig insect macro", "昆虫"),
    ("シロアリ", "termite insect macro", "昆虫"),
    ("ハチの巣", "honeycomb bees", "昆虫"),
    ("クモ", "spider macro", "昆虫"),
    ("サソリ", "scorpion animal", "昆虫"),
    ("ダンゴムシ", "pill bug macro", "昆虫"),
    ("ムカデ", "centipede macro", "昆虫"),
    ("ヤスデ", "millipede macro", "昆虫"),
    ("ミミズ", "earthworm soil", "昆虫"),
    ("カタツムリ", "snail macro", "昆虫"),
]


def load_records():
    with open(JSON_FILE, encoding="utf-8") as file:
        return json.load(file)


def save_records(records):
    with open(JSON_FILE, "w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
        file.write("\n")


def next_id(records):
    return max((record["id"] for record in records), default=0) + 1


def add_noto_items(session, records):
    response = session.get(NOTO_TREE_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    paths = {item["path"] for item in response.json().get("tree", [])}
    used_images = {record["image"] for record in records}
    added = 0
    missing = []

    for name, codepoint, category in NOTO_ITEMS:
        filename = f"emoji_u{codepoint}.svg"
        path = f"svg/{filename}"
        image_url = f"{NOTO_RAW_BASE}/{filename}"
        if image_url in used_images:
            continue
        if path not in paths:
            missing.append(filename)
            continue
        records.append({
            "id": next_id(records),
            "name": name,
            "category": category,
            "image": image_url,
            "creator": "Google / Noto Emoji contributors",
            "license": "Apache License 2.0",
            "license_url": NOTO_LICENSE_URL,
            "source": f"{NOTO_SOURCE_BASE}/{filename}",
        })
        used_images.add(image_url)
        added += 1

    save_records(records)
    print(f"Noto Emoji: {added}件追加 / {len(missing)}件見つからず")
    if missing:
        print("見つからなかったファイル: " + ", ".join(missing))
    return added


def is_banned(result):
    text = (result.get("title") or "").lower()
    for tag in result.get("tags") or []:
        text += " " + (tag.get("name") or "").lower()
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in BANNED_WORDS)


def license_label(result):
    license_code = (result.get("license") or "").lower()
    version = result.get("license_version") or ""
    if license_code == "cc0":
        return "CC0 1.0"
    if license_code == "pdm":
        return "Public Domain Mark"
    return f"CC {license_code.upper()} {version}".strip()


def valid_openverse_results(results, used_images):
    for result in results:
        image_url = result.get("url")
        width = result.get("width") or 0
        height = result.get("height") or 0
        filetype = (result.get("filetype") or "").lower()
        if not image_url or image_url in used_images:
            continue
        if (result.get("license") or "").lower() not in OPENVERSE_LICENSES:
            continue
        if width and height and min(width, height) < 400:
            continue
        if filetype in {"svg", "gif"} or is_banned(result):
            continue
        yield result


def add_openverse_items(session, records):
    used_images = {record["image"] for record in records}
    added = 0

    for index, (name, query, category) in enumerate(OPENVERSE_TOPICS, start=1):
        params = {
            "q": query,
            "license": ",".join(sorted(OPENVERSE_LICENSES)),
            "license_type": "commercial",
            "categories": "photograph",
            "page_size": 30,
        }
        response = session.get(OPENVERSE_URL, params=params, headers=HEADERS, timeout=30)
        if response.status_code == 429:
            print("Openverseのレート制限。65秒待って再試行します")
            time.sleep(65)
            response = session.get(OPENVERSE_URL, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()

        picked = 0
        for result in valid_openverse_results(response.json().get("results", []), used_images):
            records.append({
                "id": next_id(records),
                "name": name,
                "category": category,
                "image": result["url"],
                "creator": result.get("creator") or "不明",
                "license": license_label(result),
                "license_url": result.get("license_url") or "",
                "source": result.get("foreign_landing_url") or result["url"],
            })
            used_images.add(result["url"])
            added += 1
            picked += 1
            if picked >= OPENVERSE_IMAGES_PER_TOPIC:
                break

        save_records(records)
        print(f"Openverse [{index:02d}/{len(OPENVERSE_TOPICS)}] {name}: {picked}件追加")
        if index < len(OPENVERSE_TOPICS):
            time.sleep(OPENVERSE_WAIT_SECONDS)

    print(f"Openverse: 合計{added}件追加")
    return added


def plain_text(value):
    """CommonsのHTML入り作者名を短いプレーンテキストにする"""
    return unescape(re.sub(r"<[^>]+>", "", value or "")).strip() or "不明"


def commons_license_allowed(label):
    normalized = (label or "").strip().lower()
    return (
        normalized.startswith("cc by")
        or normalized.startswith("cc0")
        or normalized.startswith("public domain")
        or normalized.startswith("pdm")
    )


def add_commons_items(session, records):
    """Openverseが認証を要求したとき、Commonsから同じ昆虫写真を補う"""
    used_images = {record["image"] for record in records}
    added = 0

    for index, (name, query, category) in enumerate(OPENVERSE_TOPICS, start=1):
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 10,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": 900,
            "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist",
            "format": "json",
            "formatversion": 2,
        }
        response = session.get(COMMONS_URL, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()

        picked = 0
        pages = response.json().get("query", {}).get("pages", [])
        pages.sort(key=lambda page: page.get("index", 9999))
        for page in pages:
            image_info = (page.get("imageinfo") or [{}])[0]
            metadata = image_info.get("extmetadata") or {}
            image_url = image_info.get("thumburl") or image_info.get("url")
            license_label_value = metadata.get("LicenseShortName", {}).get("value", "")
            mime = (image_info.get("mime") or "").lower()
            width = image_info.get("thumbwidth") or image_info.get("width") or 0
            height = image_info.get("thumbheight") or image_info.get("height") or 0

            if not image_url or image_url in used_images:
                continue
            if not commons_license_allowed(license_label_value):
                continue
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            if width and height and min(width, height) < 400:
                continue

            records.append({
                "id": next_id(records),
                "name": name,
                "category": category,
                "image": image_url,
                "creator": plain_text(metadata.get("Artist", {}).get("value")),
                "license": license_label_value,
                "license_url": metadata.get("LicenseUrl", {}).get("value", ""),
                "source": image_info.get("descriptionurl") or image_info.get("url"),
            })
            used_images.add(image_url)
            added += 1
            picked += 1
            if picked >= OPENVERSE_IMAGES_PER_TOPIC:
                break

        save_records(records)
        print(f"Commons [{index:02d}/{len(OPENVERSE_TOPICS)}] {name}: {picked}件追加")
        if index < len(OPENVERSE_TOPICS):
            time.sleep(COMMONS_WAIT_SECONDS)

    print(f"Wikimedia Commons: 合計{added}件追加")
    return added


def main():
    records = load_records()
    before = len(records)
    session = requests.Session()
    noto_added = add_noto_items(session, records)
    try:
        openverse_added = add_openverse_items(session, records)
        photo_source = "Openverse"
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code not in {401, 403}:
            raise
        print("Openverseが認証を要求したため、Wikimedia Commonsへ切り替えます")
        openverse_added = add_commons_items(session, records)
        photo_source = "Wikimedia Commons"
    print(
        f"完了: {before}件 -> {len(records)}件 "
        f"(Noto {noto_added}件 / {photo_source} {openverse_added}件)"
    )


if __name__ == "__main__":
    main()
