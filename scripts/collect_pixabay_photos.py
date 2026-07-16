#!/usr/bin/env python3
"""Pixabayからお絵描き用の写真を収集し、WebPで保存するスクリプト。"""

from __future__ import annotations

import argparse
from collections import Counter
from io import BytesIO
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from PIL import Image, ImageOps

try:
    import imagehash
except ImportError:  # imagehashが未導入でもID重複防止は使える
    imagehash = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "data" / "photo_genres.json"
PHOTOS_ROOT = PROJECT_ROOT / "static" / "photos"
PIXABAY_API_URL = "https://pixabay.com/api/"
IMAGE_EXTENSIONS = {".webp", ".jpg", ".jpeg", ".png"}
PIXABAY_TIMEOUT = (10, 30)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
REQUEST_INTERVAL_SECONDS = 0.35
MAX_PER_QUERY = 2
IMAGE_ID_PATTERN = re.compile(r"^pixabay_(\d+)(?:\.[^.]+)?$", re.IGNORECASE)


class ConfigError(Exception):
    """ジャンル設定が利用できないときのエラー。"""


def load_genres() -> list[dict[str, Any]]:
    """JSON設定を検証し、収集対象ジャンルのリストを返す。"""
    try:
        with CONFIG_PATH.open(encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"ジャンル設定を読み込めません: {CONFIG_PATH} ({error})") from error

    if not isinstance(config, list) or not config:
        raise ConfigError("ジャンル設定は1件以上の配列で指定してください")

    validated: list[dict[str, Any]] = []
    seen_genres: set[str] = set()
    for index, item in enumerate(config, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"ジャンル設定{index}がオブジェクトではありません")
        genre = item.get("genre")
        label = item.get("label")
        count = item.get("count")
        queries = item.get("queries")
        if (
            not isinstance(genre, str)
            or not genre
            or Path(genre).name != genre
            or genre.startswith(".")
        ):
            raise ConfigError(f"ジャンル設定{index}のgenreが安全なフォルダ名ではありません")
        if genre in seen_genres:
            raise ConfigError(f"ジャンル名が重複しています: {genre}")
        if not isinstance(label, str) or not label:
            raise ConfigError(f"ジャンル設定{genre}のlabelが不正です")
        if not isinstance(count, int) or count < 1:
            raise ConfigError(f"ジャンル設定{genre}のcountは1以上の整数にしてください")
        if (
            not isinstance(queries, list)
            or not queries
            or any(not isinstance(query, str) or not query.strip() for query in queries)
        ):
            raise ConfigError(f"ジャンル設定{genre}のqueriesが不正です")

        seen_genres.add(genre)
        validated.append({"genre": genre, "label": label, "count": count, "queries": queries})
    return validated


def image_files(folder: Path) -> list[Path]:
    """指定フォルダ直下にある対応画像の一覧を返す。"""
    if not folder.is_dir():
        return []
    return sorted(
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def image_id_from_filename(filename: str) -> str | None:
    """pixabay_<ID>形式のファイル名からIDを抜き出す。"""
    match = IMAGE_ID_PATTERN.match(filename)
    return match.group(1) if match else None


def load_metadata(folder: Path) -> list[dict[str, Any]]:
    """メタデータを読み込み、現在存在する画像の分だけに整理する。"""
    metadata_path = folder / "metadata.json"
    if not metadata_path.exists():
        return []
    try:
        with metadata_path.open(encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[警告] metadata.jsonを読み込めません: {metadata_path} ({error})")
        return []

    if not isinstance(raw, list):
        print(f"[警告] metadata.jsonは配列で指定してください: {metadata_path}")
        return []

    existing_names = {path.name for path in image_files(folder)}
    cleaned = [
        item for item in raw
        if (
            isinstance(item, dict)
            and isinstance(item.get("file"), str)
            and item.get("file") in existing_names
        )
    ]
    return cleaned


def write_metadata(folder: Path, metadata: list[dict[str, Any]]) -> None:
    """ジャンルのメタデータをJSONで保存する。"""
    metadata_path = folder / "metadata.json"
    temporary_path = folder / "metadata.json.tmp"
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temporary_path, metadata_path)


def prune_existing_duplicates(folder: Path, limit: int = MAX_PER_QUERY) -> int:
    """既存metadataの検索語ごとの超過分を削除し、残す枚数を上限内にする。"""
    metadata = load_metadata(folder)
    query_counts: Counter[str] = Counter()
    kept: list[dict[str, Any]] = []
    removed_count = 0

    for item in metadata:
        query = str(item.get("query", "")).strip()
        if not query or query_counts[query] < limit:
            kept.append(item)
            if query:
                query_counts[query] += 1
            continue

        filename = item.get("file")
        if isinstance(filename, str) and Path(filename).name == filename:
            image_path = folder / filename
            if image_path.is_file():
                image_path.unlink()
                print(f"[削除] 種類上限超過：{query} / {filename}")
                removed_count += 1

    if removed_count:
        write_metadata(folder, kept)
    return removed_count


def prune_global_duplicates(genres: list[dict[str, Any]]) -> int:
    """ジャンルをまたぐ同じPixabay IDの重複を、先のジャンルを優先して削除する。"""
    seen_ids: set[str] = set()
    removed_count = 0

    for genre_config in genres:
        folder = PHOTOS_ROOT / genre_config["genre"]
        metadata = load_metadata(folder)
        kept: list[dict[str, Any]] = []

        for item in metadata:
            filename = item.get("file")
            photo_id = str(item.get("id", "")).strip()
            if not photo_id.isdigit() and isinstance(filename, str):
                photo_id = image_id_from_filename(filename) or ""

            if not photo_id or photo_id not in seen_ids:
                kept.append(item)
                if photo_id:
                    seen_ids.add(photo_id)
                continue

            if isinstance(filename, str) and Path(filename).name == filename:
                image_path = folder / filename
                if image_path.is_file():
                    image_path.unlink()
                    print(
                        f"[削除] ジャンル間重複：{genre_config['genre']} / {filename}"
                    )
                    removed_count += 1

        if len(kept) != len(metadata):
            write_metadata(folder, kept)

    return removed_count


def existing_ids_outside(folder: Path) -> set[str]:
    """指定フォルダ以外に保存済みのPixabay IDを集める。"""
    known_ids: set[str] = set()
    if not PHOTOS_ROOT.is_dir():
        return known_ids

    for other_folder in PHOTOS_ROOT.iterdir():
        if not other_folder.is_dir() or other_folder == folder:
            continue
        for path in image_files(other_folder):
            photo_id = image_id_from_filename(path.name)
            if photo_id:
                known_ids.add(photo_id)
        for item in load_metadata(other_folder):
            photo_id = str(item.get("id", "")).strip()
            if photo_id.isdigit():
                known_ids.add(photo_id)
    return known_ids


def save_image_as_webp(content: bytes, destination: Path) -> None:
    """画像を回転補正・RGB化・縮小してWebPへ変換する。"""
    temporary_path = destination.with_suffix(".webp.tmp")
    try:
        with Image.open(BytesIO(content)) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            image.save(temporary_path, format="WEBP", quality=85, method=6)
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def query_pixabay(api_key: str, query: str, per_page: int, page: int = 1) -> list[dict[str, Any]]:
    """Pixabay APIから写真候補を取得する。"""
    params = {
        "key": api_key,
        "q": query,
        "image_type": "photo",
        "safesearch": "true",
        "order": "popular",
        "per_page": min(max(per_page, 3), 200),
        "page": page,
    }
    try:
        response = requests.get(PIXABAY_API_URL, params=params, timeout=PIXABAY_TIMEOUT)
    except requests.RequestException as error:
        print(f"[警告] API通信失敗：{query} ({error})")
        return []
    if response.status_code != 200:
        print(f"[警告] APIエラー：{query} HTTP {response.status_code}")
        return []
    try:
        payload = response.json()
    except ValueError:
        print(f"[警告] APIのJSON応答が不正です：{query}")
        return []
    hits = payload.get("hits", [])
    return hits if isinstance(hits, list) else []


def download_image(url: str) -> bytes | None:
    """画像URLを検証し、画像バイナリを取得する。"""
    try:
        response = requests.get(url, timeout=PIXABAY_TIMEOUT)
    except requests.RequestException as error:
        print(f"[警告] 画像通信失敗：{error}")
        return None
    if response.status_code != 200:
        print(f"[警告] 画像取得失敗：HTTP {response.status_code}")
        return None
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if not content_type.startswith("image/"):
        print(f"[警告] 画像ではない応答をスキップ：Content-Type={content_type or 'なし'}")
        return None
    if len(response.content) > MAX_DOWNLOAD_BYTES:
        print(f"[警告] 画像サイズが大きすぎるためスキップ：{len(response.content)} bytes")
        return None
    return response.content


def make_hash(content: bytes) -> Any | None:
    """画像の知覚ハッシュを作る。imagehash未導入時はID判定だけにする。"""
    if imagehash is None:
        return None
    try:
        with Image.open(BytesIO(content)) as image:
            return imagehash.phash(image)
    except Exception:
        return None


def existing_hashes(folder: Path) -> list[Any]:
    """既存画像の知覚ハッシュを読み込む。"""
    if imagehash is None:
        return []
    hashes = []
    for path in image_files(folder):
        try:
            with Image.open(path) as image:
                hashes.append(imagehash.phash(image))
        except Exception:
            print(f"[警告] 既存画像のハッシュ作成失敗：{path}")
    return hashes


def is_near_duplicate(candidate_hash: Any | None, known_hashes: list[Any]) -> bool:
    """知覚ハッシュが近い画像を重複候補として判定する。"""
    if candidate_hash is None:
        return False
    return any(candidate_hash - known_hash <= 5 for known_hash in known_hashes)


def store_candidate(
    folder: Path,
    photo: dict[str, Any],
    query: str,
    known_ids: set[str],
    query_counts: Counter[str],
    known_hashes: list[Any],
    metadata_by_file: dict[str, dict[str, Any]],
    force: bool,
) -> bool:
    """候補写真を1枚保存し、成功したかを返す。"""
    photo_id = str(photo.get("id", "")).strip()
    if not photo_id.isdigit():
        print("[警告] 画像IDがない候補をスキップ")
        return False
    filename = f"pixabay_{photo_id}.webp"
    destination = folder / filename
    if query_counts[query] >= MAX_PER_QUERY:
        print(f"[スキップ] 種類上限（{MAX_PER_QUERY}枚）：{query}")
        return False
    if photo_id in known_ids and not (force and destination.exists()):
        print(f"[スキップ] 重複ID：{photo_id}")
        return False
    if destination.exists() and not force:
        print(f"[スキップ] 既存ファイル：{destination}")
        known_ids.add(photo_id)
        return False

    url = photo.get("largeImageURL") or photo.get("webformatURL")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        print(f"[警告] 画像URLがないためスキップ：{photo_id}")
        return False
    content = download_image(url)
    if content is None:
        print(f"[警告] 画像保存失敗：{photo_id}")
        return False

    candidate_hash = make_hash(content)
    if not (force and destination.exists()) and is_near_duplicate(candidate_hash, known_hashes):
        print(f"[スキップ] ほぼ同じ画像：{photo_id}")
        return False
    try:
        save_image_as_webp(content, destination)
    except Exception as error:
        print(f"[警告] 画像変換失敗：{photo_id} ({error})")
        return False

    known_ids.add(photo_id)
    query_counts[query] += 1
    if candidate_hash is not None:
        known_hashes.append(candidate_hash)
    metadata_by_file[filename] = {
        "id": int(photo_id),
        "file": filename,
        "page_url": photo.get("pageURL", ""),
        "user": photo.get("user", ""),
        "tags": photo.get("tags", ""),
        "query": query,
    }
    print(f"[保存] {destination}")
    return True


def collect_genre(
    api_key: str,
    genre_config: dict[str, Any],
    count: int,
    force: bool,
    prune_duplicates: bool = False,
) -> int:
    """1ジャンル分を複数検索語から収集する。"""
    genre = genre_config["genre"]
    label = genre_config["label"]
    queries = genre_config["queries"]
    folder = PHOTOS_ROOT / genre
    folder.mkdir(parents=True, exist_ok=True)
    if prune_duplicates:
        prune_existing_duplicates(folder)
    current_files = image_files(folder)
    current_count = len(current_files)
    metadata = load_metadata(folder)
    metadata_by_file = {
        item["file"]: item for item in metadata
        if isinstance(item.get("file"), str) and item.get("file")
    }
    query_counts: Counter[str] = Counter(
        str(item["query"]).strip() for item in metadata
        if isinstance(item.get("query"), str) and item["query"].strip()
    )
    known_ids = existing_ids_outside(folder)
    known_ids.update({
        str(item.get("id")) for item in metadata
        if str(item.get("id", "")).isdigit()
    })
    known_ids.update(
        image_id for image_id in (image_id_from_filename(path.name) for path in current_files)
        if image_id is not None
    )
    known_hashes = existing_hashes(folder)

    print(f"[開始] {label}：目標{count}枚")
    print(f"[現在] 保存済み{current_count}枚")
    if current_count >= count and not force:
        write_metadata(folder, list(metadata_by_file.values()))
        print(f"[完了] {label}：現在{current_count}枚")
        return current_count

    # 検索語ごとの目標を分け、まずは各語から均等に取得する。
    base, remainder = divmod(count, len(queries))
    query_goals = [base + (1 if index < remainder else 0) for index in range(len(queries))]
    saved_count = current_count
    requested_ids: set[str] = set()
    for query, query_goal in zip(queries, query_goals):
        if saved_count >= count and not force:
            break
        per_page = min(200, max(query_goal * 2, 10))
        print(f"[検索] {query}：{query_goal}枚取得予定")
        hits = query_pixabay(api_key, query, per_page)
        if not hits:
            print(f"[警告] 画像が取得できなかった検索語：{query}")
        query_saved = 0
        for photo in hits:
            photo_id = str(photo.get("id", ""))
            if photo_id in requested_ids:
                continue
            requested_ids.add(photo_id)
            if saved_count >= count and not (force and photo_id in known_ids):
                break
            if not force and saved_count >= count:
                break
            if query_saved >= query_goal and saved_count < count:
                break
            if store_candidate(
                folder, photo, query, known_ids, query_counts, known_hashes,
                metadata_by_file, force,
            ):
                saved_count = len(image_files(folder))
                query_saved += 1
        time.sleep(REQUEST_INTERVAL_SECONDS)

    # 重複が多くて不足した場合は、各検索語の2ページ目以降で補う。
    page = 2
    while saved_count < count:
        progress = False
        for query in queries:
            if saved_count >= count:
                break
            print(f"[検索] {query}：追加候補（{page}ページ目）")
            hits = query_pixabay(api_key, query, max(20, count // len(queries)), page)
            for photo in hits:
                photo_id = str(photo.get("id", ""))
                if photo_id in requested_ids:
                    continue
                requested_ids.add(photo_id)
                if store_candidate(
                    folder, photo, query, known_ids, query_counts, known_hashes,
                    metadata_by_file, force,
                ):
                    saved_count = len(image_files(folder))
                    progress = True
                    if saved_count >= count:
                        break
            time.sleep(REQUEST_INTERVAL_SECONDS)
        if not progress:
            break
        page += 1
        if page > 5:
            break

    metadata_by_file = {
        filename: item for filename, item in metadata_by_file.items()
        if (folder / filename).is_file()
    }
    write_metadata(folder, list(metadata_by_file.values()))
    final_count = len(image_files(folder))
    print(f"[完了] {label}：現在{final_count}枚")
    return final_count


def parse_args(genres: list[dict[str, Any]]) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(description="Pixabayからお絵描き用写真を収集します")
    parser.add_argument("--genre", choices=[item["genre"] for item in genres])
    parser.add_argument("--count", type=int, help="指定ジャンルの目標枚数")
    parser.add_argument("--force", action="store_true", help="同じIDの既存WebPを上書きする")
    parser.add_argument(
        "--prune-duplicates",
        action="store_true",
        help=f"既存の同じ種類を{MAX_PER_QUERY}枚まで整理してから追加する",
    )
    args = parser.parse_args()
    if args.count is not None and args.count < 1:
        parser.error("--countは1以上にしてください")
    return args


def main() -> int:
    """全ジャンルまたは指定ジャンルの写真収集を実行する。"""
    try:
        genres = load_genres()
        args = parse_args(genres)
    except ConfigError as error:
        print(f"[エラー] {error}", file=sys.stderr)
        return 1

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        print("[エラー] PIXABAY_API_KEYが.envに設定されていません", file=sys.stderr)
        print(f"       {PROJECT_ROOT / '.env.example'} を参考に.envを作成してください", file=sys.stderr)
        return 1
    if imagehash is None:
        print("[警告] imagehash未導入のため、IDによる重複防止だけを使用します")

    selected = genres if args.genre is None else [item for item in genres if item["genre"] == args.genre]
    if args.prune_duplicates:
        removed_count = prune_global_duplicates(genres)
        if removed_count:
            print(f"[整理] ジャンル間重複を{removed_count}枚削除しました")

    results: list[tuple[str, int]] = []
    for item in selected:
        target = args.count if args.count is not None else item["count"]
        results.append((
            item["label"],
            collect_genre(api_key, item, target, args.force, args.prune_duplicates),
        ))

    print("\n===== 収集結果 =====")
    for label, total in results:
        print(f"{label}：{total}枚")
    print(f"合計：{sum(total for _, total in results)}枚")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
