"""
Database wrapper — MongoDB Atlas with automatic JSON-file fallback.
All public methods return plain dicts (ObjectId / datetime serialised to str).
"""
import os
import json
import uuid
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path

try:
    from pymongo import MongoClient, DESCENDING, ASCENDING
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    from bson import ObjectId
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False
    ObjectId = None

from .config import Config

# ─── JSON fallback directory ──────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def _load(col: str):
    p = DATA_DIR / f"{col}.json"
    if not p.exists():
        p.write_text("[]", encoding="utf-8")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(col: str, data: list):
    p = DATA_DIR / f"{col}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _serial(obj):
    """Recursively stringify ObjectId / datetime."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_serial(o) for o in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "_id":
                out["_id"] = str(v)
            elif isinstance(v, datetime):
                out[k] = v.isoformat()
            elif isinstance(v, (dict, list)):
                out[k] = _serial(v)
            else:
                out[k] = v
        return out
    if hasattr(obj, "isoformat"):          # datetime duck-type
        return obj.isoformat()
    return obj


def _new_id():
    return uuid.uuid4().hex[:24]


# ─── Simple query matcher for JSON store ─────────────────────────────────────

def _match(doc: dict, query: dict) -> bool:
    for key, value in query.items():
        if key == "$or":
            if not any(_match(doc, q) for q in value):
                return False
        elif key == "$and":
            if not all(_match(doc, q) for q in value):
                return False
        elif isinstance(value, dict):
            doc_val = doc.get(key)
            for op, op_val in value.items():
                if op == "$regex":
                    flags = re.IGNORECASE if value.get("$options", "") == "i" else 0
                    if doc_val is None or not re.search(op_val, str(doc_val), flags):
                        return False
                elif op == "$in":
                    if doc_val not in op_val:
                        return False
                elif op == "$nin":
                    if doc_val in op_val:
                        return False
                elif op == "$ne":
                    if doc_val == op_val:
                        return False
                elif op == "$gt":
                    if not (doc_val is not None and doc_val > op_val):
                        return False
                elif op == "$exists":
                    if op_val and key not in doc:
                        return False
                    if not op_val and key in doc:
                        return False
        else:
            if doc.get(key) != value:
                return False
    return True


# ─── Database class ───────────────────────────────────────────────────────────

class Database:
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = Database()
        return cls._instance

    def __init__(self):
        self._mongo = False
        self._db = None

        if MONGO_AVAILABLE and Config.MONGO_URI:
            try:
                client = MongoClient(Config.MONGO_URI, serverSelectionTimeoutMS=3000)
                client.admin.command("ismaster")
                db_name = Config.MONGO_URI.rstrip("/").split("/")[-1] or "nexusvault"
                self._db = client[db_name]
                self._mongo = True
                print("✅  Connected to MongoDB")
                self._create_indexes()
            except Exception as e:
                print(f"⚠️   MongoDB unavailable ({e}), using JSON fallback")
        else:
            print("📁  Using JSON file storage (data/ directory)")

        self._seed()

    # ── Indexes ───────────────────────────────────────────────────────────────
    def _create_indexes(self):
        if not self._mongo:
            return
        c = self._db.items
        c.create_index([("created_at", DESCENDING)])
        c.create_index([("type", ASCENDING)])
        c.create_index([("category_slug", ASCENDING)])
        c.create_index([("zone_slug", ASCENDING)])
        c.create_index([("is_approved", ASCENDING)])
        try:
            c.create_index([("title", "text"), ("description", "text"), ("tags", "text")])
        except Exception:
            pass

    # ── Seed ──────────────────────────────────────────────────────────────────
    def _seed(self):
        if self.count("categories", {}) == 0:
            cats = [
                {"name": "Official",     "slug": "official",     "icon": "🏛️", "color": "#1a73e8", "sort_order": 1, "description": "Curated official content"},
                {"name": "Public",       "slug": "public",       "icon": "🌐", "color": "#34a853", "sort_order": 2, "description": "Community-uploaded content"},
                {"name": "High Demand",  "slug": "high-demand",  "icon": "🔥", "color": "#ff6b00", "sort_order": 3, "description": "Most requested resources"},
                {"name": "Events",       "slug": "events",       "icon": "📅", "color": "#9c27b0", "sort_order": 4, "description": "Events & announcements"},
                {"name": "Technology",   "slug": "technology",   "icon": "💻", "color": "#00bcd4", "sort_order": 5, "description": "Tech resources & tools"},
                {"name": "Education",    "slug": "education",    "icon": "📚", "color": "#4caf50", "sort_order": 6, "description": "Learning & tutorials"},
                {"name": "Entertainment","slug": "entertainment","icon": "🎭", "color": "#e91e63", "sort_order": 7, "description": "Fun & entertainment"},
                {"name": "News",         "slug": "news",         "icon": "📰", "color": "#607d8b", "sort_order": 8, "description": "News sources"},
                {"name": "Tools",        "slug": "tools",        "icon": "🛠️", "color": "#ff5722", "sort_order": 9, "description": "Useful online tools"},
                {"name": "Downloads",    "slug": "downloads",    "icon": "⬇️", "color": "#795548", "sort_order": 10,"description": "Files & downloads"},
            ]
            for c in cats:
                c["created_at"] = datetime.utcnow()
                self.insert("categories", c)

        if self.count("zones", {}) == 0:
            zones = [
                {"name": "Global",        "slug": "global",         "country": "World",  "parent_slug": None,    "flag_emoji": "🌍", "description": "International content",  "sort_order": 1},
                {"name": "India",         "slug": "india",          "country": "India",  "parent_slug": None,    "flag_emoji": "🇮🇳","description": "All India content",      "sort_order": 2},
                {"name": "Assam",         "slug": "india-assam",    "country": "India",  "parent_slug": "india", "flag_emoji": "🏔️", "description": "Assam, Northeast India", "sort_order": 3},
                {"name": "Mumbai",        "slug": "india-mumbai",   "country": "India",  "parent_slug": "india", "flag_emoji": "🏙️", "description": "Mumbai, Maharashtra",    "sort_order": 4},
                {"name": "Delhi",         "slug": "india-delhi",    "country": "India",  "parent_slug": "india", "flag_emoji": "🏛️", "description": "New Delhi",             "sort_order": 5},
                {"name": "Uttar Pradesh", "slug": "india-up",       "country": "India",  "parent_slug": "india", "flag_emoji": "🌾", "description": "Uttar Pradesh",          "sort_order": 6},
                {"name": "Bihar",         "slug": "india-bihar",    "country": "India",  "parent_slug": "india", "flag_emoji": "🌿", "description": "Bihar",                  "sort_order": 7},
                {"name": "Kolkata",       "slug": "india-kolkata",  "country": "India",  "parent_slug": "india", "flag_emoji": "🌸", "description": "Kolkata, West Bengal",   "sort_order": 8},
                {"name": "Chennai",       "slug": "india-chennai",  "country": "India",  "parent_slug": "india", "flag_emoji": "🏖️", "description": "Chennai, Tamil Nadu",    "sort_order": 9},
                {"name": "Bangalore",     "slug": "india-bangalore","country": "India",  "parent_slug": "india", "flag_emoji": "💻", "description": "Bangalore, Karnataka",   "sort_order": 10},
                {"name": "United States", "slug": "usa",            "country": "USA",    "parent_slug": None,    "flag_emoji": "🇺🇸","description": "USA content",            "sort_order": 11},
                {"name": "United Kingdom","slug": "uk",             "country": "UK",     "parent_slug": None,    "flag_emoji": "🇬🇧","description": "UK content",             "sort_order": 12},
                {"name": "Europe",        "slug": "europe",         "country": "Europe", "parent_slug": None,    "flag_emoji": "🇪🇺","description": "European content",       "sort_order": 13},
            ]
            for z in zones:
                z["created_at"] = datetime.utcnow()
                self.insert("zones", z)

        if self.count("items", {}) == 0:
            now = datetime.utcnow()
            samples = [
                {"title": "Google Search", "description": "The world's most popular search engine. Instantly search the entire web.", "type": "link", "source_type": "admin", "category_slug": "official", "zone_slug": "global", "url": "https://google.com", "thumbnail_url": "https://www.google.com/images/branding/googlelogo/2x/googlelogo_color_272x92dp.png", "tags": ["search","google","web"], "is_featured": True},
                {"title": "Wikipedia — Free Encyclopedia", "description": "Free online encyclopedia with 60+ million articles in 300+ languages.", "type": "link", "source_type": "admin", "category_slug": "education", "zone_slug": "global", "url": "https://wikipedia.org", "thumbnail_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/80/Wikipedia-logo-v2.svg/200px-Wikipedia-logo-v2.svg.png", "tags": ["encyclopedia","knowledge","education"], "is_featured": True},
                {"title": "GitHub — Code Hosting", "description": "The world's largest open-source code platform. Host and collaborate on any project.", "type": "link", "source_type": "admin", "category_slug": "technology", "zone_slug": "global", "url": "https://github.com", "thumbnail_url": "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png", "tags": ["code","git","programming","open-source"], "is_featured": True},
                {"title": "YouTube", "description": "Watch, upload, and share videos. Largest video-sharing platform on the internet.", "type": "link", "source_type": "admin", "category_slug": "entertainment", "zone_slug": "global", "url": "https://youtube.com", "thumbnail_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/YouTube_full-color_icon_%282017%29.svg/200px-YouTube_full-color_icon_%282017%29.svg.png", "tags": ["video","streaming","entertainment"], "is_featured": True},
                {"title": "Stack Overflow", "description": "Q&A platform for developers. Find answers to any programming problem.", "type": "link", "source_type": "admin", "category_slug": "technology", "zone_slug": "global", "url": "https://stackoverflow.com", "thumbnail_url": "https://cdn.sstatic.net/Sites/stackoverflow/Img/logo.png", "tags": ["programming","qa","developer"], "is_featured": False},
                {"title": "Internet Archive", "description": "Digital library of free books, movies, software, music, websites and more.", "type": "link", "source_type": "admin", "category_slug": "education", "zone_slug": "global", "url": "https://archive.org", "thumbnail_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/84/Internet_Archive_logo_and_wordmark.svg/200px-Internet_Archive_logo_and_wordmark.svg.png", "tags": ["archive","books","free","library"], "is_featured": False},
                {"title": "MDN Web Docs", "description": "The definitive web developer reference. HTML, CSS, JavaScript documentation.", "type": "link", "source_type": "admin", "category_slug": "technology", "zone_slug": "global", "url": "https://developer.mozilla.org", "thumbnail_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/98/MDN_Web_Docs.svg/200px-MDN_Web_Docs.svg.png", "tags": ["web","html","css","javascript","docs"], "is_featured": False},
                {"title": "Project Gutenberg — Free eBooks", "description": "70,000+ free eBooks — public domain classics available instantly.", "type": "link", "source_type": "admin", "category_slug": "downloads", "zone_slug": "global", "url": "https://gutenberg.org", "thumbnail_url": "", "tags": ["ebooks","books","free","download"], "is_featured": False},
                {"title": "Assam Government Portal", "description": "Official Assam state government portal. Access all citizen services online.", "type": "link", "source_type": "admin", "category_slug": "official", "zone_slug": "india-assam", "url": "https://assam.gov.in", "thumbnail_url": "", "tags": ["assam","government","official","india"], "is_featured": False},
                {"title": "Government of India", "description": "Official portal of the Indian government. All central government services.", "type": "link", "source_type": "admin", "category_slug": "official", "zone_slug": "india", "url": "https://india.gov.in", "thumbnail_url": "", "tags": ["india","government","official"], "is_featured": False},
                {"title": "FreeCodeCamp", "description": "Learn to code for free. 3,000+ hours of curriculum — HTML, JS, Python, and more.", "type": "link", "source_type": "admin", "category_slug": "education", "zone_slug": "global", "url": "https://freecodecamp.org", "thumbnail_url": "", "tags": ["coding","free","learning","programming"], "is_featured": False},
                {"title": "Canva — Design Tool", "description": "Free graphic design platform. Create stunning visuals, presentations, and more.", "type": "link", "source_type": "admin", "category_slug": "tools", "zone_slug": "global", "url": "https://canva.com", "thumbnail_url": "", "tags": ["design","graphics","free","tool"], "is_featured": False},
            ]
            for s in samples:
                s.update({"views": 0, "downloads": 0, "uploader_name": "admin", "is_approved": True, "cloudinary_id": "", "cloudinary_url": "", "extra_details": {}, "created_at": now, "updated_at": now})
                if "thumbnail_url" not in s:
                    s["thumbnail_url"] = ""
                self.insert("items", s)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def insert(self, col: str, doc: dict) -> str:
        doc = deepcopy(doc)
        if self._mongo:
            result = self._db[col].insert_one(doc)
            return str(result.inserted_id)
        else:
            doc["_id"] = _new_id()
            store = _load(col)
            store.append(doc)
            _save(col, store)
            return doc["_id"]

    def find_one(self, col: str, query: dict):
        if self._mongo:
            return _serial(self._db[col].find_one(query))
        store = _load(col)
        for d in store:
            if _match(d, query):
                return _serial(d)
        return None

    def find(self, col: str, query: dict = None, sort=None, skip: int = 0, limit: int = None):
        query = query or {}
        if self._mongo:
            cursor = self._db[col].find(query)
            if sort:
                cursor = cursor.sort(sort)
            else:
                cursor = cursor.sort("created_at", DESCENDING)
            if skip:
                cursor = cursor.skip(skip)
            if limit:
                cursor = cursor.limit(limit)
            return _serial(list(cursor))
        store = _load(col)
        results = [d for d in store if _match(d, query)]
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        if skip:
            results = results[skip:]
        if limit:
            results = results[:limit]
        return _serial(results)

    def update(self, col: str, query: dict, update: dict):
        if self._mongo:
            if not any(k.startswith("$") for k in update):
                update = {"$set": update}
            return self._db[col].update_many(query, update).modified_count
        store = _load(col)
        count = 0
        for i, d in enumerate(store):
            if _match(d, query):
                if "$set" in update:
                    store[i].update(update["$set"])
                elif "$inc" in update:
                    for k, v in update["$inc"].items():
                        store[i][k] = store[i].get(k, 0) + v
                else:
                    store[i].update(update)
                count += 1
        _save(col, store)
        return count

    def delete(self, col: str, query: dict):
        if self._mongo:
            return self._db[col].delete_many(query).deleted_count
        store = _load(col)
        new = [d for d in store if not _match(d, query)]
        _save(col, new)
        return len(store) - len(new)

    def count(self, col: str, query: dict = None):
        query = query or {}
        if self._mongo:
            return self._db[col].count_documents(query)
        return sum(1 for d in _load(col) if _match(d, query))

    def search(self, col: str, term: str, extra: dict = None):
        """Full-text search across title, description, tags."""
        term = term.strip()
        extra = extra or {}
        if self._mongo:
            # Try MongoDB text search first
            try:
                q = {"$text": {"$search": term}}
                q.update(extra)
                results = list(self._db[col].find(q).sort("created_at", DESCENDING))
                if results:
                    return _serial(results)
            except Exception:
                pass
            # Fallback to regex
            q = {"$and": [
                {"$or": [
                    {"title": {"$regex": term, "$options": "i"}},
                    {"description": {"$regex": term, "$options": "i"}},
                ]},
                extra,
            ]} if extra else {"$or": [
                {"title": {"$regex": term, "$options": "i"}},
                {"description": {"$regex": term, "$options": "i"}},
            ]}
            return _serial(list(self._db[col].find(q).sort("created_at", DESCENDING)))
        t = term.lower()
        results = []
        for d in _load(col):
            if (t in d.get("title", "").lower() or
                t in d.get("description", "").lower() or
                any(t in tag.lower() for tag in d.get("tags", []))):
                if _match(d, extra):
                    results.append(d)
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return _serial(results)


def get_db() -> Database:
    return Database.get()
