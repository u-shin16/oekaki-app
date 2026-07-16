# -*- coding: utf-8 -*-
"""
おえかきやろか - スピードドローイング用タイマーアプリ（Flask本体）

ランダムなお題を出してくれるサーバーです。
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
import urllib.parse

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


def _fetch_json(url, timeout=10):
    """URLからJSONを取得して辞書にして返す小さなヘルパー関数"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "oekaki-yaroka/1.0 (https://oekaki.webtool-labs.com)",
            "AIC-User-Agent": "oekaki-yaroka/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context) as res:
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
_dataset_cache_mtime = None


def _load_dataset():
    """お題データセットを読み込み、ファイル更新時だけキャッシュを作り直す"""
    global _dataset_cache, _dataset_cache_mtime
    path = os.path.join(app.root_path, "static", "dataset", "characters.json")
    current_mtime = os.path.getmtime(path)
    if _dataset_cache is None or current_mtime != _dataset_cache_mtime:
        with open(path, encoding="utf-8") as f:
            _dataset_cache = json.load(f)
        _dataset_cache_mtime = current_mtime
    return _dataset_cache


# データは残すけれど、ホーム画面のジャンル選択には出さないカテゴリ
HIDDEN_GENRE_CATEGORIES = {"スポーツ用品", "スポーツ用具", "道具", "楽器", "乗り物", "キャラクター"}

# データ内のカテゴリ名と、画面に出すカテゴリ名が違うもの
DISPLAY_CATEGORY_NAMES = {"建物": "風景"}

# 画面から送られてくるカテゴリ名を、データ内のカテゴリ名に戻す対応表
DATASET_CATEGORY_ALIASES = {"風景": "建物"}

# まだデータが空でも、ホーム画面には先に置いておくジャンル
EMPTY_DISPLAY_CATEGORIES = []

PHOTO_GENRE_CONFIG_PATH = os.path.join(app.root_path, "data", "photo_genres.json")
PHOTO_QUERY_LABELS_PATH = os.path.join(app.root_path, "data", "photo_query_labels.json")
PHOTO_DIR = os.path.join(app.root_path, "static", "photos")
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PHOTO_CATEGORY_ALIASES = {"植物": "自然", "風景": "自然"}
PHOTO_CATEGORY_QUERY_FILTERS = {
    "植物": {
        "flower", "tree", "garden", "cherry blossom", "bamboo", "palm tree",
        "cactus", "mushroom", "fern", "rose", "sunflower", "tulip",
    },
    "風景": {
        "mountain", "waterfall", "ocean", "river", "sunset", "forest",
        "volcano", "island", "beach", "desert", "lake", "snow", "glacier",
        "canyon", "cave", "meadow", "field", "jungle", "rainforest",
        "autumn leaves", "lightning", "rainbow", "cloud", "starry sky", "moon",
        "sunrise", "aurora", "fog", "storm", "waves", "stream", "cliff",
        "valley", "hill", "coral reef", "ocean waves", "spring", "winter landscape",
    },
}
_photo_genres_cache = None
_photo_genres_cache_mtime = None
_photo_query_labels_cache = None
_photo_query_labels_mtime = None


def _is_illustration_item(item):
    """Noto Emoji API由来のSVGイラストだけを判定する"""
    image = (item.get("image") or "").lower()
    source = (item.get("source") or "").lower()
    return image.endswith(".svg") or "noto-emoji" in image or "noto-emoji" in source


def _load_illustration_dataset():
    """イラストモードで出題するデータだけを返す"""
    return [item for item in _load_dataset() if _is_illustration_item(item)]


def _display_category(category):
    return DISPLAY_CATEGORY_NAMES.get(category, category)


def _load_photo_genres():
    """写真ジャンル設定を読み込む。設定が壊れている場合は空配列にする"""
    global _photo_genres_cache, _photo_genres_cache_mtime
    try:
        current_mtime = os.path.getmtime(PHOTO_GENRE_CONFIG_PATH)
    except OSError:
        return []
    if _photo_genres_cache is not None and current_mtime == _photo_genres_cache_mtime:
        return _photo_genres_cache

    try:
        with open(PHOTO_GENRE_CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        app.logger.exception("写真ジャンル設定を読み込めません")
        _photo_genres_cache = []
        _photo_genres_cache_mtime = current_mtime
        return _photo_genres_cache

    if not isinstance(config, list):
        app.logger.error("写真ジャンル設定は配列で指定してください")
        config = []
    _photo_genres_cache = [
        item for item in config
        if isinstance(item, dict)
        and isinstance(item.get("genre"), str)
        and os.path.basename(item["genre"]) == item["genre"]
        and not item["genre"].startswith(".")
        and isinstance(item.get("label"), str)
    ]
    _photo_genres_cache_mtime = current_mtime
    return _photo_genres_cache


def _photo_genre_config(category):
    """画面ラベルまたはフォルダ名から安全な写真ジャンル設定を探す"""
    category = PHOTO_CATEGORY_ALIASES.get(category, category)
    for item in _load_photo_genres():
        if category in {item.get("genre"), item.get("label")}:
            return item
    return None


def _load_photo_query_labels():
    """写真の検索語を日本語のお題名へ変換する対応表を読み込む"""
    global _photo_query_labels_cache, _photo_query_labels_mtime
    try:
        current_mtime = os.path.getmtime(PHOTO_QUERY_LABELS_PATH)
    except OSError:
        return {}
    if (
        _photo_query_labels_cache is not None
        and current_mtime == _photo_query_labels_mtime
    ):
        return _photo_query_labels_cache

    try:
        with open(PHOTO_QUERY_LABELS_PATH, encoding="utf-8") as f:
            labels = json.load(f)
    except (OSError, json.JSONDecodeError):
        app.logger.exception("写真のお題名対応表を読み込めません")
        labels = {}

    _photo_query_labels_cache = labels if isinstance(labels, dict) else {}
    _photo_query_labels_mtime = current_mtime
    return _photo_query_labels_cache


def _photo_display_name(config, query):
    """写真の検索語を日本語のお題名にする"""
    labels = _load_photo_query_labels().get(config["genre"], {})
    if isinstance(query, str) and isinstance(labels, dict):
        display_name = labels.get(query.strip())
        if isinstance(display_name, str) and display_name.strip():
            return display_name
    return f"{config['label']}の写真"


def _local_photo_categories():
    """写真が1枚以上ある設定済みジャンルの表示ラベルを返す"""
    categories = []
    for item in _load_photo_genres():
        if _local_photo_files(item["genre"]):
            categories.append(item["label"])
    return categories


def _local_photo_files(genre):
    """設定済みジャンルフォルダ内の画像ファイル一覧を返す"""
    config = _photo_genre_config(genre)
    if config is None:
        return []
    folder = os.path.join(PHOTO_DIR, config["genre"])
    if not os.path.isdir(folder):
        return []

    files = []
    for root, _, names in os.walk(folder):
        for name in names:
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in PHOTO_EXTENSIONS:
                continue
            files.append(os.path.join(root, name))
    return sorted(files)


def _local_photo_candidates(category=None):
    """ローカル写真モードの候補を、既存データと同じ形に整える"""
    requested_category = category
    if category and category != "all":
        config = _photo_genre_config(category)
        configs = [config] if config else []
    else:
        configs = _load_photo_genres()

    candidates = []
    static_root = os.path.join(app.root_path, "static")
    for config in configs:
        genre = config["genre"]
        label = config["label"]
        metadata_by_file = {}
        metadata_path = os.path.join(PHOTO_DIR, genre, "metadata.json")
        try:
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
            if isinstance(metadata, list):
                metadata_by_file = {
                    item.get("file"): item
                    for item in metadata
                    if isinstance(item, dict) and isinstance(item.get("file"), str)
                }
        except (OSError, json.JSONDecodeError):
            app.logger.warning("写真メタデータを読み込めません: %s", metadata_path)
        for path in _local_photo_files(genre):
            try:
                if os.path.commonpath([static_root, path]) != static_root:
                    continue
            except ValueError:
                continue
            rel_static_path = os.path.relpath(path, static_root)
            url_path = "/static/" + "/".join(
                urllib.parse.quote(part, safe="") for part in rel_static_path.split(os.sep)
            )
            photo_id = "photo:" + rel_static_path.replace(os.sep, "/")
            metadata = metadata_by_file.get(os.path.basename(path), {})
            query = metadata.get("query")
            query_filter = PHOTO_CATEGORY_QUERY_FILTERS.get(requested_category)
            if query_filter is not None and query not in query_filter:
                continue
            name = _photo_display_name(config, query)
            candidates.append({
                "id": photo_id,
                "name": name,
                "category": label,
                "image": url_path,
            })
    return candidates


def get_dataset_categories(mode="illustration"):
    """ホーム画面に表示するジャンル名を、登場順の重複なしリストで返す"""
    if mode == "photo":
        return _local_photo_categories()

    seen = []
    for item in _load_illustration_dataset():
        category = item["category"]
        if category in HIDDEN_GENRE_CATEGORIES:
            continue
        display_category = _display_category(category)
        if display_category not in seen:
            seen.append(display_category)
    for category in EMPTY_DISPLAY_CATEGORIES:
        if category not in seen:
            seen.append(category)
    return seen


class DatasetEmptyError(Exception):
    """指定されたジャンルにお題が1件も無かったときのエラー"""


def get_random_dataset_item(exclude_ids, category=None, mode="illustration"):
    """
    お題データセットからランダムに1件取得する

    exclude_ids: すでに出題した id のリスト（連続・重複を防ぐため）
    category   : ジャンル名（動物・食べ物など）。None または "all" なら全ジャンルから選ぶ
    戻り値: {"id": ..., "name": ..., "image": ...}
    """
    if mode == "photo":
        return get_random_local_photo(exclude_ids, category=category)

    items = _load_illustration_dataset()
    if category and category != "all":
        if category in EMPTY_DISPLAY_CATEGORIES:
            raise DatasetEmptyError(f"ジャンル「{category}」はまだお題がありません")
        dataset_category = DATASET_CATEGORY_ALIASES.get(category, category)
        if category in HIDDEN_GENRE_CATEGORIES or dataset_category in HIDDEN_GENRE_CATEGORIES:
            raise DatasetEmptyError(f"ジャンル「{category}」のお題が見つかりません")
        items = [it for it in items if it["category"] == dataset_category]

    if not items:
        raise DatasetEmptyError(f"ジャンル「{category}」のお題が見つかりません")

    candidates = [it for it in items if it["id"] not in exclude_ids]
    if not candidates:
        # そのジャンルを出し尽くしたら、同じジャンルの中から選び直す
        candidates = items

    chosen = random.choice(candidates)
    return {"id": chosen["id"], "name": chosen["name"], "image": chosen["image"]}


def get_random_local_photo(exclude_ids, category=None):
    """ローカル写真フォルダからランダムに1件取得する"""
    items = _local_photo_candidates(category)
    if not items:
        target = f"ジャンル「{category}」" if category and category != "all" else "写真フォルダ"
        raise DatasetEmptyError(f"{target}に写真がありません")

    excluded = {str(item_id) for item_id in exclude_ids}
    candidates = [item for item in items if str(item["id"]) not in excluded]
    if not candidates:
        candidates = items

    chosen = random.choice(candidates)
    return {"id": chosen["id"], "name": chosen["name"], "image": chosen["image"]}


# ---------- 名画（シカゴ美術館・メトロポリタン美術館） ----------

ARTIC_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
MET_SEARCH_URL = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT_URL = "https://collectionapi.metmuseum.org/public/collection/v1/objects"

# 最初の4人を高い重みで選び、そのほかの著名作家も少し混ぜる
FAMOUS_ARTISTS = (
    ("Vincent van Gogh", "ゴッホ", 6),
    ("Claude Monet", "モネ", 6),
    ("Pierre-Auguste Renoir", "ルノワール", 6),
    ("Katsushika Hokusai", "葛飾北斎", 6),
    ("Utagawa Hiroshige", "歌川広重", 1),
    ("Edgar Degas", "ドガ", 1),
    ("Paul Cézanne", "セザンヌ", 1),
    ("Johannes Vermeer", "フェルメール", 1),
    ("Rembrandt", "レンブラント", 1),
)

# APIの検索結果や作品情報だけをメモリに保持する。画像ファイルは保存しない。
_artic_artwork_cache = {}
_met_search_cache = {}
_met_object_cache = {}


def _format_artwork_name(title, artist_label):
    """お題名に作品名と画家名をまとめる"""
    return f"{title or '無題'}（{artist_label}）"


def _choose_unseen_artwork(candidates, exclude_ids):
    """出題済み作品を避け、候補が一巡したら全候補から選び直す"""
    if not candidates:
        return None
    excluded = {str(item_id) for item_id in exclude_ids}
    unseen = [item for item in candidates if str(item["id"]) not in excluded]
    return random.choice(unseen or candidates)


def _get_artic_artwork(artist_query, artist_label, exclude_ids):
    """シカゴ美術館からパブリックドメインかつ画像付きの作品を1件返す"""
    if artist_query not in _artic_artwork_cache:
        search = {
            "q": artist_query,
            "limit": 40,
            "fields": "id,title,image_id,artist_title,is_public_domain",
            "query": {
                "bool": {
                    "must": [
                        {"term": {"is_public_domain": True}},
                        {"exists": {"field": "image_id"}},
                    ]
                }
            },
        }
        query = urllib.parse.urlencode(
            {"params": json.dumps(search, separators=(",", ":"), ensure_ascii=False)}
        )
        payload = _fetch_json(f"{ARTIC_SEARCH_URL}?{query}")
        iiif_url = payload.get("config", {}).get("iiif_url", "").rstrip("/")
        artist_key = artist_query.casefold()
        candidates = []

        for item in payload.get("data", []):
            artist_name = item.get("artist_title") or ""
            image_id = item.get("image_id")
            if (
                item.get("is_public_domain") is not True
                or not image_id
                or not iiif_url
                or artist_key not in artist_name.casefold()
            ):
                continue

            candidates.append({
                "id": f"artic-{item['id']}",
                "title": item.get("title") or "無題",
                "artist": artist_name,
                "image": (
                    f"{iiif_url}/{urllib.parse.quote(str(image_id), safe='')}"
                    "/full/843,/0/default.jpg"
                ),
                "museum": "シカゴ美術館",
                "public_domain": True,
                "image_fit": "contain",
            })

        _artic_artwork_cache[artist_query] = candidates

    chosen = _choose_unseen_artwork(_artic_artwork_cache[artist_query], exclude_ids)
    if chosen is None:
        return None
    result = dict(chosen)
    result["name"] = _format_artwork_name(result["title"], artist_label)
    return result


def _get_met_object_ids(artist_query):
    """メトロポリタン美術館の作家別検索結果を取得する"""
    if artist_query not in _met_search_cache:
        query = urllib.parse.urlencode({
            "hasImages": "true",
            "artistOrCulture": "true",
            "q": artist_query,
        })
        payload = _fetch_json(f"{MET_SEARCH_URL}?{query}")
        _met_search_cache[artist_query] = payload.get("objectIDs") or []
    return _met_search_cache[artist_query]


def _get_met_artwork(artist_query, artist_label, exclude_ids):
    """メトロポリタン美術館からパブリックドメインかつ画像付きの作品を1件返す"""
    # 検索上位に絞ることで、同名語に反応した関連性の低い作品を避ける。
    object_ids = list(_get_met_object_ids(artist_query))[:40]
    excluded = {str(item_id) for item_id in exclude_ids}
    random.shuffle(object_ids)
    object_ids.sort(key=lambda object_id: f"met-{object_id}" in excluded)

    # 検索APIは著作権情報を返さないため、詳細APIで条件を確認する。
    for object_id in object_ids[:8]:
        if object_id not in _met_object_cache:
            try:
                payload = _fetch_json(f"{MET_OBJECT_URL}/{object_id}", timeout=6)
            except (urllib.error.URLError, TimeoutError, OSError):
                # 個別作品の応答が遅い場合は、同じ検索結果の次候補へ進む。
                continue
            artist_name = payload.get("artistDisplayName") or ""
            primary_image = payload.get("primaryImage") or ""
            if (
                payload.get("isPublicDomain") is True
                and primary_image
                and artist_query.casefold() in artist_name.casefold()
            ):
                _met_object_cache[object_id] = {
                    "id": f"met-{object_id}",
                    "title": payload.get("title") or "無題",
                    "artist": artist_name,
                    "image": payload.get("primaryImageSmall") or primary_image,
                    "museum": "メトロポリタン美術館",
                    "public_domain": True,
                    "image_fit": "contain",
                }
            else:
                _met_object_cache[object_id] = None

        chosen = _met_object_cache[object_id]
        if chosen is not None:
            result = dict(chosen)
            result["name"] = _format_artwork_name(result["title"], artist_label)
            return result
    return None


def get_random_artwork(exclude_ids, category=None):
    """2館のAPIから、著名作家を優先して条件に合う作品を1件取得する"""
    first_artist = random.choices(
        FAMOUS_ARTISTS,
        weights=[artist[2] for artist in FAMOUS_ARTISTS],
        k=1,
    )[0]
    remaining_artists = [artist for artist in FAMOUS_ARTISTS if artist != first_artist]
    random.shuffle(remaining_artists)
    artists = [first_artist, *remaining_artists]

    if category == "artic":
        providers = [_get_artic_artwork]
    elif category == "met":
        providers = [_get_met_artwork]
    else:
        providers = [_get_artic_artwork, _get_met_artwork]
        random.shuffle(providers)
    last_network_error = None

    for index, (artist_query, artist_label, _weight) in enumerate(artists):
        artist_providers = providers if index % 2 == 0 else list(reversed(providers))
        for provider in artist_providers:
            try:
                artwork = provider(artist_query, artist_label, exclude_ids)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_network_error = error
                continue
            if artwork is not None:
                return artwork

    if last_network_error is not None:
        raise last_network_error
    raise DatasetEmptyError("条件に合う名画が見つかりませんでした")


# ---------- データソースの登録表 ----------
# 将来ここに "onepiece": get_random_onepiece などを追加していく
SOURCES = {
    "pokemon": get_random_pokemon,
    "dataset": get_random_dataset_item,
    "art": get_random_artwork,
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
    汎用お題取得API（将来の拡張用の本体）

    クエリパラメータ:
      source   : データソース名（pokemon・dataset・art。省略時は pokemon）
      mode     : dataset専用。illustration または photo
      category : ジャンル名（dataset専用。動物・食べ物など。省略時は全ジャンル）
      museum   : 美術館名（art専用。artic または met）
      exclude  : 出題済みIDをカンマ区切りで渡す（例: exclude=25,133）
    """
    source_name = request.args.get("source", "pokemon")
    category = request.args.get("category")
    museum = request.args.get("museum")
    mode = request.args.get("mode", "illustration")

    # 登録されていないデータソースが指定されたらエラーを返す
    if source_name not in SOURCES:
        return jsonify({"error": f"未対応のデータソースです: {source_name}"}), 400

    # 数字IDは数値にし、artic-123 のような外部API用IDは文字列のまま扱う
    exclude_ids = []
    exclude_param = request.args.get("exclude", "")
    for part in exclude_param.split(","):
        item_id = part.strip()
        if item_id.isdigit():
            exclude_ids.append(int(item_id))
        elif item_id:
            exclude_ids.append(item_id)

    try:
        if source_name == "dataset":
            character = get_random_dataset_item(exclude_ids, category=category, mode=mode)
        else:
            source_category = museum if source_name == "art" else category
            character = SOURCES[source_name](exclude_ids, category=source_category)
        return jsonify(character)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # PokeAPIに繋がらないときなど（ネットワークエラー）
        # 原因調査できるように、サーバーのログに詳細を残す
        app.logger.exception("お題の取得に失敗: %s", e)
        return jsonify({"error": "お題の取得に失敗しました。通信環境を確認してください。"}), 502
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
    mode = request.args.get("mode", "illustration")
    return jsonify({"categories": get_dataset_categories(mode=mode)})


# ============================================================
# アプリの起動（このファイルを直接実行したときだけ動く）
#   $ python app.py
#   → http://127.0.0.1:5000 をブラウザで開く
# ============================================================
if __name__ == "__main__":
    # debug=True にすると、コードを直したとき自動で再起動してくれる
    app.run(debug=True, host="0.0.0.0", port=5000)
