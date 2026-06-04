import os
from datetime import datetime
from pymongo import MongoClient

_client = MongoClient(os.environ["MONGO_URI"])
_db = _client["kinolar"]

movies_col   = _db["movies"]
channels_col = _db["channels"]
stats_col    = _db["stats"]


# ─── Movies ───────────────────────────────────────────────
def get_movies() -> dict:
    return {m["code"]: m for m in movies_col.find({}, {"_id": 0})}


def get_movie(code: str) -> dict | None:
    return movies_col.find_one({"code": code.upper()}, {"_id": 0})


def save_movie(code: str, file_id: str, caption: str, file_type: str):
    code = code.upper()
    existing = get_movie(code) or {}
    movies_col.update_one(
        {"code": code},
        {"$set": {
            "file_id": file_id,
            "caption": caption,
            "file_type": file_type,
            "code": code,
            "is_series": False,
            "parts": [],
            "downloads": existing.get("downloads", 0),
        }},
        upsert=True,
    )


def save_series(code: str, caption: str):
    code = code.upper()
    existing = get_movie(code) or {}
    movies_col.update_one(
        {"code": code},
        {"$set": {
            "file_id": "",
            "caption": caption,
            "file_type": "series",
            "code": code,
            "is_series": True,
            "parts": existing.get("parts", []),
            "downloads": existing.get("downloads", 0),
        }},
        upsert=True,
    )


def add_series_part(code: str, file_id: str, file_type: str) -> int:
    code = code.upper()
    movies_col.update_one(
        {"code": code},
        {"$push": {"parts": {"file_id": file_id, "file_type": file_type}}},
    )
    movie = get_movie(code)
    return len(movie.get("parts", [])) if movie else 0


def remove_series_part(code: str, part_index: int) -> bool:
    code = code.upper()
    movie = get_movie(code)
    if not movie or not movie.get("is_series"):
        return False
    parts = movie.get("parts", [])
    if part_index < 0 or part_index >= len(parts):
        return False
    parts.pop(part_index)
    movies_col.update_one({"code": code}, {"$set": {"parts": parts}})
    return True


def inc_downloads(code: str):
    movies_col.update_one({"code": code.upper()}, {"$inc": {"downloads": 1}})


def delete_movie(code: str) -> bool:
    result = movies_col.delete_one({"code": code.upper()})
    return result.deleted_count > 0


def search_movies(query: str) -> list[dict]:
    query = query.upper()
    return list(movies_col.find(
        {"$or": [
            {"code": {"$regex": query}},
            {"caption": {"$regex": query, "$options": "i"}},
        ]},
        {"_id": 0}
    ))


# ─── Channels ─────────────────────────────────────────────
def get_channels() -> dict:
    return {c["id"]: c for c in channels_col.find({}, {"_id": 0})}


def add_channel(channel_id: str, title: str, link: str):
    channels_col.update_one(
        {"id": channel_id},
        {"$set": {"id": channel_id, "title": title, "link": link}},
        upsert=True,
    )


def remove_channel(channel_id: str) -> bool:
    result = channels_col.delete_one({"id": channel_id})
    return result.deleted_count > 0


# ─── Stats ────────────────────────────────────────────────
def get_stats() -> dict:
    doc = stats_col.find_one({"_id": "main"}) or {}
    return {
        "users":    doc.get("users", {}),
        "requests": doc.get("requests", 0),
    }


def register_user(user_id: int, username: str, full_name: str):
    uid = str(user_id)
    stats_col.update_one(
        {"_id": "main"},
        {"$setOnInsert": {f"users.{uid}": None}},
        upsert=True,
    )
    stats_col.update_one(
        {"_id": "main", f"users.{uid}": {"$exists": False}},
        {"$set": {f"users.{uid}": {
            "id": user_id,
            "username": username,
            "full_name": full_name,
            "joined": datetime.now().isoformat(),
        }}},
    )


def inc_requests():
    stats_col.update_one(
        {"_id": "main"},
        {"$inc": {"requests": 1}},
        upsert=True,
    )