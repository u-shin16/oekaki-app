# -*- coding: utf-8 -*-
"""
repair_dataset.py の search で候補が0〜1件しかなかった項目を、
条件を少し緩めて（タイトル必須ワードなし・candidate数を増やす）再検索する。

repair_state.json の該当エントリを新しい候補で置き換える（indexは0に戻す）。
"""
import re
import time

import requests

from repair_dataset import (
    API_URL, HEADERS, API_WAIT_SECONDS, BANNED_WORDS,
    license_label, is_banned, load, save, REPAIR_FILE,
)

# id: (新しい検索ワード)  ※タイトル必須ワードは課さない（is_bannedだけで足切り）
ROUND2_QUERIES = {
    9:   "rhino zoo animal",
    14:  "sloth zoo animal",
    18:  "hamster pet",
    26:  "flamingo bird zoo",
    40:  "alpaca farm animal",
    45:  "octopus sea creature",
    56:  "peacock bird zoo",
    57:  "ostrich bird zoo",
    62:  "stag beetle insect macro",
    78:  "pineapple tropical fruit",
    88:  "onion vegetable food",
    92:  "sweet corn vegetable",
    106: "ice cream scoop dessert",
    108: "chocolate bar dessert",
    109: "popcorn snack bowl",
    113: "motorcycle motorbike parked",
    128: "submarine navy ship",
    145: "watermill old building",
    150: "cello instrument music",
    151: "flute musical instrument silver",
    152: "saxophone jazz instrument",
    153: "trumpet brass band instrument",
    155: "harmonica music instrument",
    156: "accordion music instrument",
    157: "ukulele music instrument",
    158: "harp music instrument",
    159: "japanese taiko drum festival",
    160: "xylophone marimba music",
    161: "tambourine music instrument",
    164: "baseball glove mitt",
    167: "golf clubs bag equipment",
    169: "skis snow sport equipment",
    171: "bowling pins alley",
    174: "boxing gloves red",
    186: "pine cone conifer",
    187: "bamboo forest green",
    198: "wristwatch clock analog",
}

EXTRA_BANNED = BANNED_WORDS + [
    "mural", "graffiti", "stamp", "postage", "coin", "logo", "badge",
    "champagne", "cocktail", "wine glass", "drawing", "sketch", "clipart",
    "vector", "icon", "poster", "album cover", "vintage postcard",
]


def is_banned2(r):
    text = (r.get("title") or "").lower()
    for tag in r.get("tags") or []:
        text += " " + (tag.get("name") or "").lower()
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in EXTRA_BANNED)


def main():
    repair = load(REPAIR_FILE, {})
    session = requests.Session()

    for item_id, query in ROUND2_QUERIES.items():
        print(f"[id={item_id:3d}] {query}")
        params = {
            "q": query,
            "license": "cc0,pdm,by,by-sa",
            "license_type": "commercial",
            "category": "photograph",
            "per_page": 40,
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
                print("    レート制限が解除されず中断")
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
            if is_banned(r) or is_banned2(r):
                continue
            cands.append({
                "url": r["url"],
                "creator": r.get("creator") or "不明",
                "license": license_label(r),
                "license_url": r.get("license_url") or "",
                "source": r.get("foreign_landing_url") or r["url"],
                "title": (r.get("title") or "")[:80],
            })

        # 既存候補の後ろに追加する（indexは既存分の続きから）
        key = str(item_id)
        existing = repair.get(key, {"candidates": [], "index": 0})
        # 重複URLは除く
        existing_urls = {c["url"] for c in existing["candidates"]}
        new_cands = [c for c in cands if c["url"] not in existing_urls]
        repair[key] = {
            "candidates": existing["candidates"] + new_cands,
            "index": len(existing["candidates"]),  # 新しい候補の先頭から見る
        }
        save(REPAIR_FILE, repair)
        print(f"    追加候補 {len(new_cands)}件（合計 {len(repair[key]['candidates'])}件）")
        time.sleep(API_WAIT_SECONDS)

    print("round2 検索完了")


if __name__ == "__main__":
    main()
