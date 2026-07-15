# -*- coding: utf-8 -*-
"""
おえかきやろか - スピードドローイング用タイマーアプリ（Flask本体）

ランダムなキャラクターのお題を出してくれるサーバーです。
初期実装は「ポケモン」（PokeAPIを使用）ですが、
将来ほかのアニメ・ゲームのキャラクターも追加できるように
「データソース」を登録して切り替えられる設計にしています。
"""

import json
import os
import random
import ssl
import urllib.request
import urllib.error

from flask import Flask, jsonify, render_template, request

# HTTPS通信に使うSSL設定
# Pythonの環境によってはルート証明書が見つからず
# 「CERTIFICATE_VERIFY_FAILED」エラーになることがあるので、
# certifi（証明書のパッケージ）が入っていればそちらを優先して使う
try:
    import certifi
    _ssl_context = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_context = ssl.create_default_context()

app = Flask(__name__)

# ============================================================
# データソースの仕組み（拡張ポイント）
# ------------------------------------------------------------
# 新しい作品を追加したいときは、
#   1. 「ランダムに1体取得する関数」を作る
#   2. 下の SOURCES 辞書に登録する
# だけでOKです。フロント側は /api/character?source=名前 で呼べます。
# ============================================================

# ---------- ポケモン（PokeAPI） ----------

# PokeAPIに登録されている全国図鑑の最大ID（2024年時点で1025体）
POKEMON_MAX_ID = 1025

# 一度取得したポケモンを覚えておくキャッシュ（毎回PokeAPIに聞かなくて済む）
# キー: 図鑑ID, 値: {"id": ..., "name": ..., "image": ...}
_pokemon_cache = {}


def _fetch_json(url):
    """URLからJSONを取得して辞書にして返す小さなヘルパー関数"""
    req = urllib.request.Request(url, headers={"User-Agent": "oekaki-shiyoka/1.0"})
    with urllib.request.urlopen(req, timeout=10, context=_ssl_context) as res:
        return json.loads(res.read().decode("utf-8"))


def get_random_pokemon(exclude_ids, category=None):
    """
    ランダムなポケモンを1体取得する

    exclude_ids: すでに出題したポケモンのIDのリスト（連続・重複を防ぐため）
    category   : ポケモンには使わない（他のデータソースと引数をそろえるためだけの飾り）
    戻り値: {"id": 図鑑ID, "name": 日本語名, "image": 画像URL}
    """
    # 出題済みを除いたIDの中からランダムに選ぶ
    candidates = [i for i in range(1, POKEMON_MAX_ID + 1) if i not in exclude_ids]
    if not candidates:
        # 全部出題し終わったら（ほぼ起きないけど）全体から選び直す
        candidates = list(range(1, POKEMON_MAX_ID + 1))

    pokemon_id = random.choice(candidates)

    # キャッシュにあればそれを返す（高速化）
    if pokemon_id in _pokemon_cache:
        return _pokemon_cache[pokemon_id]

    # ポケモンの「種族」情報から日本語名を取得する
    species = _fetch_json(f"https://pokeapi.co/api/v2/pokemon-species/{pokemon_id}")

    # names配列の中から日本語（ja）の名前を探す
    name = species.get("name", "???")  # 見つからないときは英語名で代用
    for entry in species.get("names", []):
        if entry.get("language", {}).get("name") == "ja":
            name = entry.get("name")
            break

    # 公式イラストの画像URL（IDから直接組み立てられる）
    image = (
        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
        f"sprites/pokemon/other/official-artwork/{pokemon_id}.png"
    )

    character = {"id": pokemon_id, "name": name, "image": image}
    _pokemon_cache[pokemon_id] = character  # キャッシュに保存
    return character


# ---------- お題データセット（Openverse由来。動物・食べ物・乗り物など） ----------

# static/dataset/characters.json を一度だけ読み込んでメモリに置いておく
# （id・name・category・image・creator・license・source を持つリスト）
_dataset_cache = None


def _load_dataset():
    """お題データセットのJSONを読み込む（2回目以降はキャッシュを返す）"""
    global _dataset_cache
    if _dataset_cache is None:
        path = os.path.join(app.root_path, "static", "dataset", "characters.json")
        with open(path, encoding="utf-8") as f:
            _dataset_cache = json.load(f)
    return _dataset_cache


# データは残すけれど、ホーム画面のジャンル選択には出さないカテゴリ
HIDDEN_GENRE_CATEGORIES = {"スポーツ用品", "スポーツ用具", "道具", "楽器"}


def get_dataset_categories():
    """ホーム画面に表示するジャンル名を、登場順の重複なしリストで返す"""
    seen = []
    for item in _load_dataset():
        category = item["category"]
        if category in HIDDEN_GENRE_CATEGORIES:
            continue
        if category not in seen:
            seen.append(category)
    return seen


class DatasetEmptyError(Exception):
    """指定されたジャンルにお題が1件も無かったときのエラー"""


def get_random_dataset_item(exclude_ids, category=None):
    """
    お題データセットからランダムに1件取得する

    exclude_ids: すでに出題した id のリスト（連続・重複を防ぐため）
    category   : ジャンル名（動物・食べ物など）。None または "all" なら全ジャンルから選ぶ
    戻り値: {"id": ..., "name": ..., "image": ...}
    """
    items = _load_dataset()
    if category and category != "all":
        items = [it for it in items if it["category"] == category]

    if not items:
        raise DatasetEmptyError(f"ジャンル「{category}」のお題が見つかりません")

    candidates = [it for it in items if it["id"] not in exclude_ids]
    if not candidates:
        # そのジャンルを出し尽くしたら、同じジャンルの中から選び直す
        candidates = items

    chosen = random.choice(candidates)
    return {"id": chosen["id"], "name": chosen["name"], "image": chosen["image"]}


# ---------- データソースの登録表 ----------
# 将来ここに "onepiece": get_random_onepiece などを追加していく
SOURCES = {
    "pokemon": get_random_pokemon,
    "dataset": get_random_dataset_item,
}


# ============================================================
# ルーティング（URLと処理の対応）
# ============================================================

@app.route("/")
def index():
    """トップページ（アプリ本体の画面）を表示する"""
    return render_template("index.html")


@app.route("/api/character")
def api_character():
    """
    汎用キャラクター取得API（将来の拡張用の本体）

    クエリパラメータ:
      source   : データソース名（省略時は pokemon）
      category : ジャンル名（dataset専用。動物・食べ物など。省略時は全ジャンル）
      exclude  : 出題済みIDをカンマ区切りで渡す（例: exclude=25,133）
    """
    source_name = request.args.get("source", "pokemon")
    category = request.args.get("category")

    # 登録されていないデータソースが指定されたらエラーを返す
    if source_name not in SOURCES:
        return jsonify({"error": f"未対応のデータソースです: {source_name}"}), 400

    # exclude=1,2,3 のような文字列を数字のリストに変換する
    exclude_ids = []
    exclude_param = request.args.get("exclude", "")
    for part in exclude_param.split(","):
        if part.strip().isdigit():
            exclude_ids.append(int(part.strip()))

    try:
        character = SOURCES[source_name](exclude_ids, category=category)
        return jsonify(character)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # PokeAPIに繋がらないときなど（ネットワークエラー）
        # 原因調査できるように、サーバーのログに詳細を残す
        app.logger.exception("キャラクター取得に失敗: %s", e)
        return jsonify({"error": "キャラクターの取得に失敗しました。通信環境を確認してください。"}), 502
    except DatasetEmptyError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pokemon")
def api_pokemon():
    """
    ポケモン専用API（仕様どおりのエンドポイント）
    中身は /api/character?source=pokemon と同じ処理を使い回す
    """
    return api_character()


@app.route("/api/genres")
def api_genres():
    """
    ホーム画面に表示するジャンル一覧を返す
    （ホーム画面のジャンル選択ボタンを作るのに使う）
    """
    return jsonify({"categories": get_dataset_categories()})


# ============================================================
# アプリの起動（このファイルを直接実行したときだけ動く）
#   $ python app.py
#   → http://127.0.0.1:5000 をブラウザで開く
# ============================================================
if __name__ == "__main__":
    # debug=True にすると、コードを直したとき自動で再起動してくれる
    app.run(debug=True, host="0.0.0.0", port=5000)
