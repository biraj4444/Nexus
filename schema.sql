PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    icon TEXT DEFAULT '',
    color TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS zones (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    country TEXT DEFAULT '',
    parent_slug TEXT,
    flag_emoji TEXT DEFAULT '',
    description TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    type TEXT DEFAULT 'link',
    source_type TEXT DEFAULT '',
    category_slug TEXT DEFAULT '',
    zone_slug TEXT DEFAULT '',
    url TEXT DEFAULT '',
    thumbnail_url TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    is_featured INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    downloads INTEGER DEFAULT 0,
    uploader_name TEXT DEFAULT '',
    is_approved INTEGER DEFAULT 0,
    cloudinary_id TEXT DEFAULT '',
    cloudinary_url TEXT DEFAULT '',
    extra_details TEXT DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS discussions (
    id TEXT PRIMARY KEY,
    item_id TEXT DEFAULT '',
    parent_id TEXT,
    username TEXT DEFAULT '',
    content TEXT DEFAULT '',
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_categories_sort
ON categories(sort_order);

CREATE INDEX IF NOT EXISTS idx_zones_sort
ON zones(sort_order);

CREATE INDEX IF NOT EXISTS idx_items_created
ON items(created_at);

CREATE INDEX IF NOT EXISTS idx_items_category
ON items(category_slug);

CREATE INDEX IF NOT EXISTS idx_items_zone
ON items(zone_slug);

CREATE INDEX IF NOT EXISTS idx_items_approved
ON items(is_approved);

CREATE INDEX IF NOT EXISTS idx_discussions_item
ON discussions(item_id);

CREATE INDEX IF NOT EXISTS idx_discussions_parent
ON discussions(parent_id);
