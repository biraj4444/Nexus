"""
NexusVault database wrapper.

Cloudflare Workers:
    Uses Cloudflare D1 through the DB binding.

Local/non-Workers:
    Uses the existing JSON files in data/.

The public API intentionally remains compatible with the old
MongoDB/JSON wrapper:
    insert()
    find_one()
    find()
    update()
    delete()
    count()
    search()
"""

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .config import Config

try:
    from flask import request
except ImportError:
    request = None

try:
    from pyodide.ffi import run_sync
except ImportError:
    run_sync = None


DATA_DIR = Path(__file__).parent.parent / "data"


def _new_id():
    return uuid.uuid4().hex[:24]


def _now():
    return datetime.utcnow().isoformat()


def _json(value):
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, bool):
        return 1 if value else 0

    if isinstance(value, datetime):
        return value.isoformat()

    return value


def _decode_value(key, value):
    """
    Convert SQLite values back into the shape expected by the Flask app.
    """

    if key in ("tags", "extra_details"):
        if value is None:
            return [] if key == "tags" else {}

        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return [] if key == "tags" else {}

    if key in ("is_featured", "is_approved"):
        return bool(value)

    return value


def _row(row):
    if row is None:
        return None

    result = dict(row)

    # D1 uses `id`, while the old Mongo wrapper exposed `_id`.
    if "id" in result:
        result["_id"] = str(result["id"])

    for key in list(result):
        result[key] = _decode_value(key, result[key])

    return result


def _rows(rows):
    return [_row(r) for r in rows]


# ─────────────────────────────────────────────────────────────
# JSON fallback
# ─────────────────────────────────────────────────────────────

def _load(col):
    DATA_DIR.mkdir(exist_ok=True)

    p = DATA_DIR / f"{col}.json"

    if not p.exists():
        p.write_text("[]", encoding="utf-8")

    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(col, data):
    DATA_DIR.mkdir(exist_ok=True)

    p = DATA_DIR / f"{col}.json"

    p.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def _match(doc, query):
    for key, value in query.items():

        if key == "$or":
            if not any(_match(doc, q) for q in value):
                return False
            continue

        if key == "$and":
            if not all(_match(doc, q) for q in value):
                return False
            continue

        # Mongo `_id` compatibility
        actual_key = "id" if key == "_id" else key

        doc_val = doc.get(actual_key)

        if isinstance(value, dict):

            for op, op_val in value.items():

                if op == "$options":
                    continue

                if op == "$regex":
                    flags = 0

                    if value.get("$options", "") == "i":
                        flags = re.IGNORECASE

                    if doc_val is None:
                        return False

                    if not re.search(
                        op_val,
                        str(doc_val),
                        flags,
                    ):
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
                    if not (
                        doc_val is not None
                        and doc_val > op_val
                    ):
                        return False

                elif op == "$exists":
                    exists = actual_key in doc

                    if op_val and not exists:
                        return False

                    if not op_val and exists:
                        return False

        else:
            if doc_val != value:
                return False

    return True


# ─────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────

class Database:

    _instance = None

    def __init__(self):
        self._seeded = False

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()

        return cls._instance

    # ─────────────────────────────────────────────────────────
    # Cloudflare environment
    # ─────────────────────────────────────────────────────────

    def _env(self):
        """
        Get Cloudflare Worker environment from Flask's WSGI
        environment.

        Cloudflare exposes bindings through:
            request.environ["workers.env"]
        """

        if request is None:
            return None

        try:
            return request.environ.get("workers.env")
        except Exception:
            return None

    def _d1(self):
        env = self._env()

        if env is None:
            return None

        try:
            return env.DB
        except Exception:
            return None

    def _is_d1(self):
        return self._d1() is not None

    def _run(self, awaitable):
        """
        Bridge an async Cloudflare API into the synchronous Flask
        handler.
        """

        if run_sync is None:
            raise RuntimeError(
                "Cloudflare run_sync is unavailable"
            )

        return run_sync(awaitable)

    # ─────────────────────────────────────────────────────────
    # D1 helpers
    # ─────────────────────────────────────────────────────────

    def _d1_rows(self, sql, params=()):
        db = self._d1()

        if db is None:
            return []

        stmt = db.prepare(sql)

        if params:
            stmt = stmt.bind(*params)

        result = self._run(stmt.run())

        try:
            return list(result.results)
        except Exception:
            return []

    def _d1_first(self, sql, params=()):
        db = self._d1()

        if db is None:
            return None

        stmt = db.prepare(sql)

        if params:
            stmt = stmt.bind(*params)

        result = self._run(stmt.first())

        if result is None:
            return None

        return dict(result)

    def _d1_write(self, sql, params=()):
        db = self._d1()

        if db is None:
            return 0

        stmt = db.prepare(sql)

        if params:
            stmt = stmt.bind(*params)

        result = self._run(stmt.run())

        try:
            return int(result.meta.changes)
        except Exception:
            return 1

    # ─────────────────────────────────────────────────────────
    # Column mapping
    # ─────────────────────────────────────────────────────────

    COLUMNS = {
        "categories": [
            "id",
            "name",
            "slug",
            "icon",
            "color",
            "sort_order",
            "description",
            "created_at",
        ],

        "zones": [
            "id",
            "name",
            "slug",
            "country",
            "parent_slug",
            "flag_emoji",
            "description",
            "sort_order",
            "created_at",
        ],

        "items": [
            "id",
            "title",
            "description",
            "type",
            "source_type",
            "category_slug",
            "zone_slug",
            "url",
            "thumbnail_url",
            "tags",
            "is_featured",
            "views",
            "downloads",
            "uploader_name",
            "is_approved",
            "cloudinary_id",
            "cloudinary_url",
            "extra_details",
            "created_at",
            "updated_at",
        ],

        "discussions": [
            "id",
            "item_id",
            "parent_id",
            "username",
            "content",
            "created_at",
        ],
    }

    JSON_COLUMNS = {
        "items": {
            "tags",
            "extra_details",
        }
    }

    BOOL_COLUMNS = {
        "items": {
            "is_featured",
            "is_approved",
        }
    }

    # ─────────────────────────────────────────────────────────
    # Query builder
    # ─────────────────────────────────────────────────────────

    def _field(self, key):
        if key == "_id":
            return "id"

        if key not in self.COLUMNS.get(self._current_col, []):
            raise ValueError(
                f"Invalid database field: {key}"
            )

        return key

    def _condition(self, key, value):
        field = self._field(key)

        if not isinstance(value, dict):
            return f'"{field}" = ?', [self._sql_value(key, value)]

        clauses = []
        params = []

        for op, op_value in value.items():

            if op == "$options":
                continue

            if op == "$regex":
                # SQLite regexp() is not consistently available.
                # LIKE gives us portable substring matching.
                clauses.append(
                    f'LOWER(CAST("{field}" AS TEXT)) LIKE ?'
                )

                params.append(
                    "%" + str(op_value).lower() + "%"
                )

            elif op == "$in":
                values = list(op_value)

                if not values:
                    clauses.append("1 = 0")
                else:
                    placeholders = ",".join(
                        "?" for _ in values
                    )

                    clauses.append(
                        f'"{field}" IN ({placeholders})'
                    )

                    params.extend(
                        self._sql_value(key, v)
                        for v in values
                    )

            elif op == "$nin":
                values = list(op_value)

                if not values:
                    continue

                placeholders = ",".join(
                    "?" for _ in values
                )

                clauses.append(
                    f'"{field}" NOT IN ({placeholders})'
                )

                params.extend(
                    self._sql_value(key, v)
                    for v in values
                )

            elif op == "$ne":
                clauses.append(
                    f'"{field}" != ?'
                )

                params.append(
                    self._sql_value(key, op_value)
                )

            elif op == "$gt":
                clauses.append(
                    f'"{field}" > ?'
                )

                params.append(
                    self._sql_value(key, op_value)
                )

            elif op == "$exists":
                if op_value:
                    clauses.append(
                        f'"{field}" IS NOT NULL'
                    )
                else:
                    clauses.append(
                        f'"{field}" IS NULL'
                    )

        if not clauses:
            return "1 = 1", []

        return " AND ".join(clauses), params

    def _where(self, query):
        if not query:
            return "", []

        parts = []
        params = []

        for key, value in query.items():

            if key == "$or":
                subparts = []

                for subquery in value:
                    sql, p = self._where(subquery)

                    subparts.append(
                        sql[6:] if sql.startswith("WHERE ") else sql
                    )

                    params.extend(p)

                parts.append(
                    "(" + " OR ".join(subparts) + ")"
                )

            elif key == "$and":
                subparts = []

                for subquery in value:
                    sql, p = self._where(subquery)

                    subparts.append(
                        sql[6:] if sql.startswith("WHERE ") else sql
                    )

                    params.extend(p)

                parts.append(
                    "(" + " AND ".join(subparts) + ")"
                )

            else:
                sql, p = self._condition(key, value)

                parts.append(sql)
                params.extend(p)

        return (
            "WHERE " + " AND ".join(parts),
            params,
        )

    def _sql_value(self, key, value):
        if key == "_id":
            key = "id"

        if key in self.JSON_COLUMNS.get(
            self._current_col,
            set(),
        ):
            return _json(value)

        if key in self.BOOL_COLUMNS.get(
            self._current_col,
            set(),
        ):
            return 1 if value else 0

        if isinstance(value, datetime):
            return value.isoformat()

        return value

    # ─────────────────────────────────────────────────────────
    # Seed
    # ─────────────────────────────────────────────────────────

    def _ensure_seeded(self):
        if self._seeded:
            return

        self._seeded = True

        try:
            if self.count("categories", {}) == 0:
                self._seed_categories()

            if self.count("zones", {}) == 0:
                self._seed_zones()

            if self.count("items", {}) == 0:
                self._seed_items()

        except Exception as e:
            self._seeded = False
            print(f"⚠️ Database seed failed: {e}")

    def _seed_categories(self):
        cats = [
            ("Official", "official", "🏛️", "#1a73e8", 1, "Curated official content"),
            ("Public", "public", "🌐", "#34a853", 2, "Community-uploaded content"),
            ("High Demand", "high-demand", "🔥", "#ff6b00", 3, "Most requested resources"),
            ("Events", "events", "📅", "#9c27b0", 4, "Events & announcements"),
            ("Technology", "technology", "💻", "#00bcd4", 5, "Tech resources & tools"),
            ("Education", "education", "📚", "#4caf50", 6, "Learning & tutorials"),
            ("Entertainment", "entertainment", "🎭", "#e91e63", 7, "Fun & entertainment"),
            ("News", "news", "📰", "#607d8b", 8, "News sources"),
            ("Tools", "tools", "🛠️", "#ff5722", 9, "Useful online tools"),
            ("Downloads", "downloads", "⬇️", "#795548", 10, "Files & downloads"),
        ]

        for name, slug, icon, color, order, desc in cats:
            self.insert(
                "categories",
                {
                    "name": name,
                    "slug": slug,
                    "icon": icon,
                    "color": color,
                    "sort_order": order,
                    "description": desc,
                    "created_at": datetime.utcnow(),
                },
                _skip_seed=True,
            )

    def _seed_zones(self):
        zones = [
            ("Global", "global", "World", None, "🌍", "International content", 1),
            ("India", "india", "India", None, "🇮🇳", "All India content", 2),
            ("Assam", "india-assam", "India", "india", "🏔️", "Assam, Northeast India", 3),
            ("Mumbai", "india-mumbai", "India", "india", "🏙️", "Mumbai, Maharashtra", 4),
            ("Delhi", "india-delhi", "India", "india", "🏛️", "New Delhi", 5),
            ("Uttar Pradesh", "india-up", "India", "india", "🌾", "Uttar Pradesh", 6),
            ("Bihar", "india-bihar", "India", "india", "🌿", "Bihar", 7),
            ("Kolkata", "india-kolkata", "India", "india", "🌸", "Kolkata, West Bengal", 8),
            ("Chennai", "india-chennai", "India", "india", "🏖️", "Chennai, Tamil Nadu", 9),
            ("Bangalore", "india-bangalore", "India", "india", "💻", "Bangalore, Karnataka", 10),
            ("United States", "usa", "USA", None, "🇺🇸", "USA content", 11),
            ("United Kingdom", "uk", "UK", None, "🇬🇧", "UK content", 12),
            ("Europe", "europe", "Europe", None, "🇪🇺", "European content", 13),
        ]

        for name, slug, country, parent, flag, desc, order in zones:
            self.insert(
                "zones",
                {
                    "name": name,
                    "slug": slug,
                    "country": country,
                    "parent_slug": parent,
                    "flag_emoji": flag,
                    "description": desc,
                    "sort_order": order,
                    "created_at": datetime.utcnow(),
                },
                _skip_seed=True,
            )

    def _seed_items(self):
        now = datetime.utcnow()

        samples = [
            {
                "title": "Google Search",
                "description": "The world's most popular search engine. Instantly search the entire web.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "official",
                "zone_slug": "global",
                "url": "https://google.com",
                "thumbnail_url": "https://www.google.com/images/branding/googlelogo/2x/googlelogo_color_272x92dp.png",
                "tags": ["search", "google", "web"],
                "is_featured": True,
            },
            {
                "title": "Wikipedia — Free Encyclopedia",
                "description": "Free online encyclopedia with 60+ million articles in 300+ languages.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "education",
                "zone_slug": "global",
                "url": "https://wikipedia.org",
                "thumbnail_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/80/Wikipedia-logo-v2.svg/200px-Wikipedia-logo-v2.svg.png",
                "tags": ["encyclopedia", "knowledge", "education"],
                "is_featured": True,
            },
            {
                "title": "GitHub — Code Hosting",
                "description": "The world's largest open-source code platform. Host and collaborate on any project.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "technology",
                "zone_slug": "global",
                "url": "https://github.com",
                "thumbnail_url": "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
                "tags": ["code", "git", "programming", "open-source"],
                "is_featured": True,
            },
            {
                "title": "YouTube",
                "description": "Watch, upload, and share videos. Largest video-sharing platform on the internet.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "entertainment",
                "zone_slug": "global",
                "url": "https://youtube.com",
                "thumbnail_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/YouTube_full-color_icon_%282017%29.svg/200px-YouTube_full-color_icon_%282017%29.svg.png",
                "tags": ["video", "streaming", "entertainment"],
                "is_featured": True,
            },
            {
                "title": "Stack Overflow",
                "description": "Q&A platform for developers. Find answers to any programming problem.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "technology",
                "zone_slug": "global",
                "url": "https://stackoverflow.com",
                "thumbnail_url": "https://cdn.sstatic.net/Sites/stackoverflow/Img/logo.png",
                "tags": ["programming", "qa", "developer"],
            },
            {
                "title": "Internet Archive",
                "description": "Digital library of free books, movies, software, music, websites and more.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "education",
                "zone_slug": "global",
                "url": "https://archive.org",
                "thumbnail_url": "",
                "tags": ["archive", "books", "free", "library"],
            },
            {
                "title": "MDN Web Docs",
                "description": "The definitive web developer reference. HTML, CSS, JavaScript documentation.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "technology",
                "zone_slug": "global",
                "url": "https://developer.mozilla.org",
                "thumbnail_url": "",
                "tags": ["web", "html", "css", "javascript", "docs"],
            },
            {
                "title": "Project Gutenberg — Free eBooks",
                "description": "70,000+ free eBooks — public domain classics available instantly.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "downloads",
                "zone_slug": "global",
                "url": "https://gutenberg.org",
                "thumbnail_url": "",
                "tags": ["ebooks", "books", "free", "download"],
            },
            {
                "title": "Assam Government Portal",
                "description": "Official Assam state government portal. Access all citizen services online.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "official",
                "zone_slug": "india-assam",
                "url": "https://assam.gov.in",
                "thumbnail_url": "",
                "tags": ["assam", "government", "official", "india"],
            },
            {
                "title": "Government of India",
                "description": "Official portal of the Indian government. All central government services.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "official",
                "zone_slug": "india",
                "url": "https://india.gov.in",
                "thumbnail_url": "",
                "tags": ["india", "government", "official"],
            },
            {
                "title": "FreeCodeCamp",
                "description": "Learn to code for free. 3,000+ hours of curriculum — HTML, JS, Python, and more.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "education",
                "zone_slug": "global",
                "url": "https://freecodecamp.org",
                "thumbnail_url": "",
                "tags": ["coding", "free", "learning", "programming"],
            },
            {
                "title": "Canva — Design Tool",
                "description": "Free graphic design platform. Create stunning visuals, presentations, and more.",
                "type": "link",
                "source_type": "admin",
                "category_slug": "tools",
                "zone_slug": "global",
                "url": "https://canva.com",
                "thumbnail_url": "",
                "tags": ["design", "graphics", "free", "tool"],
            },
        ]

        for item in samples:
            item.update(
                {
                    "views": 0,
                    "downloads": 0,
                    "uploader_name": "admin",
                    "is_approved": True,
                    "cloudinary_id": "",
                    "cloudinary_url": "",
                    "extra_details": {},
                    "created_at": now,
                    "updated_at": now,
                }
            )

            self.insert(
                "items",
                item,
                _skip_seed=True,
            )

    # ─────────────────────────────────────────────────────────
    # INSERT
    # ─────────────────────────────────────────────────────────

    def insert(self, col, doc, _skip_seed=False):
        if not _skip_seed:
            self._ensure_seeded()

        doc = deepcopy(doc)

        # Cloudflare D1
        if self._is_d1():

            self._current_col = col

            data = {}

            for field in self.COLUMNS[col]:

                if field == "id":
                    continue

                value = doc.get(field)

                if value is None:
                    continue

                data[field] = self._sql_value(field, value)

            row_id = str(doc.get("_id") or doc.get("id") or _new_id())

            fields = ["id"] + list(data.keys())
            values = [row_id] + list(data.values())

            placeholders = ",".join(
                "?" for _ in values
            )

            sql = (
                f'INSERT INTO "{col}" '
                f'({",".join(chr(34)+f+chr(34) for f in fields)}) '
                f'VALUES ({placeholders})'
            )

            self._d1_write(sql, values)

            return row_id

        # JSON fallback
        doc["_id"] = str(
            doc.get("_id") or _new_id()
        )

        store = _load(col)
        store.append(doc)
        _save(col, store)

        return doc["_id"]

    # ─────────────────────────────────────────────────────────
    # FIND ONE
    # ─────────────────────────────────────────────────────────

    def find_one(self, col, query):
        self._ensure_seeded()

        if self._is_d1():

            self._current_col = col

            where, params = self._where(query)

            row = self._d1_first(
                f'SELECT * FROM "{col}" {where} LIMIT 1',
                params,
            )

            return _row(row)

        for doc in _load(col):
            if _match(doc, query):
                result = deepcopy(doc)

                if "_id" in result:
                    result["_id"] = str(result["_id"])

                return result

        return None

    # ─────────────────────────────────────────────────────────
    # FIND
    # ─────────────────────────────────────────────────────────

    def find(
        self,
        col,
        query=None,
        sort=None,
        skip=0,
        limit=None,
    ):
        self._ensure_seeded()

        query = query or {}

        if self._is_d1():

            self._current_col = col

            where, params = self._where(query)

            order = 'ORDER BY "created_at" DESC'

            if sort:
                try:
                    sort_field, direction = sort[0]

                    if sort_field == "_id":
                        sort_field = "id"

                    direction_sql = (
                        "DESC"
                        if direction < 0
                        else "ASC"
                    )

                    order = (
                        f'ORDER BY "{sort_field}" '
                        f'{direction_sql}'
                    )
                except Exception:
                    pass

            sql = (
                f'SELECT * FROM "{col}" '
                f'{where} '
                f'{order}'
            )

            if skip:
                sql += f" OFFSET {int(skip)}"

            if limit:
                sql += f" LIMIT {int(limit)}"

            rows = self._d1_rows(sql, params)

            return _rows(rows)

        results = [
            deepcopy(d)
            for d in _load(col)
            if _match(d, query)
        ]

        results.sort(
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )

        if skip:
            results = results[skip:]

        if limit:
            results = results[:limit]

        return results

    # ─────────────────────────────────────────────────────────
    # UPDATE
    # ─────────────────────────────────────────────────────────

    def update(self, col, query, update):
        self._ensure_seeded()

        if self._is_d1():

            self._current_col = col

            if not any(
                k.startswith("$")
                for k in update
            ):
                update = {"$set": update}

            if "$set" in update:
                changes = update["$set"]

            elif "$inc" in update:

                existing = self.find(
                    col,
                    query,
                )

                count = 0

                for row in existing:
                    sets = {}

                    for key, amount in update[
                        "$inc"
                    ].items():
                        sets[key] = (
                            row.get(key, 0) + amount
                        )

                    count += self.update(
                        col,
                        {"_id": row["_id"]},
                        sets,
                    )

                return count

            else:
                changes = update

            assignments = []
            params = []

            for key, value in changes.items():

                if key == "_id":
                    key = "id"

                if key not in self.COLUMNS[col]:
                    continue

                assignments.append(
                    f'"{key}" = ?'
                )

                params.append(
                    self._sql_value(key, value)
                )

            if not assignments:
                return 0

            where, where_params = self._where(
                query
            )

            params.extend(where_params)

            sql = (
                f'UPDATE "{col}" SET '
                f'{",".join(assignments)} '
                f'{where}'
            )

            return self._d1_write(
                sql,
                params,
            )

        store = _load(col)
        count = 0

        for i, doc in enumerate(store):

            if not _match(doc, query):
                continue

            if "$set" in update:
                store[i].update(
                    update["$set"]
                )

            elif "$inc" in update:
                for key, value in update[
                    "$inc"
                ].items():
                    store[i][key] = (
                        store[i].get(key, 0)
                        + value
                    )

            else:
                store[i].update(update)

            count += 1

        _save(col, store)

        return count

    # ─────────────────────────────────────────────────────────
    # DELETE
    # ─────────────────────────────────────────────────────────

    def delete(self, col, query):
        self._ensure_seeded()

        if self._is_d1():

            self._current_col = col

            where, params = self._where(query)

            return self._d1_write(
                f'DELETE FROM "{col}" {where}',
                params,
            )

        store = _load(col)

        new = [
            d for d in store
            if not _match(d, query)
        ]

        _save(col, new)

        return len(store) - len(new)

    # ─────────────────────────────────────────────────────────
    # COUNT
    # ─────────────────────────────────────────────────────────

    def count(self, col, query=None):
        query = query or {}

        if self._is_d1():

            self._current_col = col

            where, params = self._where(query)

            row = self._d1_first(
                f'SELECT COUNT(*) AS count '
                f'FROM "{col}" {where}',
                params,
            )

            return int(
                row["count"]
                if row
                else 0
            )

        return sum(
            1
            for d in _load(col)
            if _match(d, query)
        )

    # ─────────────────────────────────────────────────────────
    # SEARCH
    # ─────────────────────────────────────────

    def search(self, col, term, extra=None):
        self._ensure_seeded()

        term = term.strip()
        extra = extra or {}

        if self._is_d1():

            self._current_col = col

            search_columns = []

            if col == "items":
                search_columns = [
                    "title",
                    "description",
                    "tags",
                ]
            elif col == "categories":
                search_columns = [
                    "name",
                    "description",
                ]
            elif col == "zones":
                search_columns = [
                    "name",
                    "description",
                    "country",
                ]
            elif col == "discussions":
                search_columns = [
                    "content",
                    "username",
                ]

            if not search_columns:
                return self.find(
                    col,
                    extra,
                )

            clauses = []

            params = []

            for field in search_columns:

                clauses.append(
                    f'LOWER(CAST("{field}" AS TEXT)) LIKE ?'
                )

                params.append(
                    "%" + term.lower() + "%"
                )

            search_sql = (
                "("
                + " OR ".join(clauses)
                + ")"
            )

            where, where_params = self._where(
                extra
            )

            if where:
                where_sql = (
                    where
                    + " AND "
                    + search_sql
                )
            else:
                where_sql = (
                    "WHERE "
                    + search_sql
                )

            params.extend(where_params)

            rows = self._d1_rows(
                f'SELECT * FROM "{col}" '
                f'{where_sql} '
                f'ORDER BY "created_at" DESC',
                params,
            )

            return _rows(rows)

        t = term.lower()

        results = []

        for doc in _load(col):

            title = str(
                doc.get("title", "")
            ).lower()

            description = str(
                doc.get("description", "")
            ).lower()

            tags = doc.get("tags", [])

            tag_match = any(
                t in str(tag).lower()
                for tag in tags
            )

            if (
                t in title
                or t in description
                or tag_match
            ):
                if _match(doc, extra):
                    results.append(
                        deepcopy(doc)
                    )

        results.sort(
            key=lambda x: x.get(
                "created_at",
                "",
            ),
            reverse=True,
        )

        return results


def get_db():
    return Database.get()
