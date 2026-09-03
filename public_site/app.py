import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, redirect, url_for, jsonify, abort, flash
from datetime import datetime
from common.db import get_db
from common.config import Config
from common.cloudinary_utils import upload_to_cloudinary


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)
    app.secret_key = Config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

    # ── Context ───────────────────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        db = get_db()
        return dict(
            nav_categories=db.find("categories", {}, sort=[("sort_order", 1)]),
            site_name="NexusVault",
            year=datetime.now().year,
        )

    # ── Home ──────────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        db = get_db()
        page = request.args.get("page", 1, type=int)
        per_page = Config.ITEMS_PER_PAGE
        skip = (page - 1) * per_page

        featured = db.find("items", {"is_approved": True, "is_featured": True}, limit=6)
        items = db.find("items", {"is_approved": True}, skip=skip, limit=per_page)
        total = db.count("items", {"is_approved": True})
        total_pages = max(1, (total + per_page - 1) // per_page)

        stats = {
            "total":  total,
            "links":  db.count("items", {"type": "link",  "is_approved": True}),
            "videos": db.count("items", {"type": "video", "is_approved": True}),
            "images": db.count("items", {"type": "image", "is_approved": True}),
            "files":  db.count("items", {"type": "file",  "is_approved": True}),
        }
        return render_template("index.html", featured=featured, items=items,
                               page=page, total_pages=total_pages, total=total,
                               stats=stats, active="home")

    # ── Category ──────────────────────────────────────────────────────────────
    @app.route("/category/<slug>")
    def category(slug):
        db = get_db()
        cat = db.find_one("categories", {"slug": slug})
        if not cat:
            abort(404)

        page = request.args.get("page", 1, type=int)
        itype = request.args.get("type")
        per_page = Config.ITEMS_PER_PAGE
        skip = (page - 1) * per_page

        q = {"is_approved": True, "category_slug": slug}
        if itype:
            q["type"] = itype

        items = db.find("items", q, skip=skip, limit=per_page)
        total = db.count("items", q)
        total_pages = max(1, (total + per_page - 1) // per_page)

        return render_template("category.html", category=cat, items=items,
                               page=page, total_pages=total_pages, total=total,
                               itype=itype, active="cat-" + slug)

    # ── Zone / Server ─────────────────────────────────────────────────────────
    @app.route("/zone/<slug>")
    def zone(slug):
        db = get_db()
        z = db.find_one("zones", {"slug": slug})
        if not z:
            abort(404)

        page = request.args.get("page", 1, type=int)
        per_page = Config.ITEMS_PER_PAGE
        skip = (page - 1) * per_page

        q = {"is_approved": True, "zone_slug": slug}
        items = db.find("items", q, skip=skip, limit=per_page)
        total = db.count("items", q)
        total_pages = max(1, (total + per_page - 1) // per_page)

        return render_template("zone.html", zone=z, items=items,
                               page=page, total_pages=total_pages, total=total,
                               active="servers")

    # ── Servers list ──────────────────────────────────────────────────────────
    @app.route("/servers")
    def servers():
        db = get_db()
        all_zones = db.find("zones", {}, sort=[("sort_order", 1)])
        top = [z for z in all_zones if not z.get("parent_slug")]
        subs = {}
        for z in all_zones:
            if z.get("parent_slug"):
                subs.setdefault(z["parent_slug"], []).append(z)
        counts = {z["slug"]: db.count("items", {"zone_slug": z["slug"], "is_approved": True})
                  for z in all_zones}
        return render_template("servers.html", top_zones=top, sub_zones=subs,
                               zone_counts=counts, active="servers")

    # ── New uploads ───────────────────────────────────────────────────────────
    @app.route("/new")
    def new():
        db = get_db()
        page = request.args.get("page", 1, type=int)
        per_page = Config.ITEMS_PER_PAGE
        skip = (page - 1) * per_page
        items = db.find("items", {"is_approved": True}, skip=skip, limit=per_page)
        total = db.count("items", {"is_approved": True})
        total_pages = max(1, (total + per_page - 1) // per_page)
        return render_template("new.html", items=items, page=page,
                               total_pages=total_pages, total=total, active="new")

    # ── Upload ────────────────────────────────────────────────────────────────
    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        db = get_db()
        cats = db.find("categories", {}, sort=[("sort_order", 1)])
        zones = db.find("zones",      {}, sort=[("sort_order", 1)])
        err = success = None

        if request.method == "POST":
            itype    = request.form.get("type", "link")
            title    = request.form.get("title", "").strip()
            desc     = request.form.get("description", "").strip()
            cat_slug = request.form.get("category_slug", "public")
            z_slug   = request.form.get("zone_slug", "global")
            tags     = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]
            uploader = request.form.get("uploader_name", "Anonymous").strip() or "Anonymous"

            if not title:
                err = "Title is required."
            else:
                item = dict(
                    title=title, description=desc, type=itype,
                    source_type="public", category_slug=cat_slug, zone_slug=z_slug,
                    tags=tags, uploader_name=uploader,
                    is_approved=False, is_featured=False,
                    views=0, downloads=0,
                    url="", thumbnail_url="", cloudinary_id="", cloudinary_url="",
                    extra_details={},
                    created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
                )
                if itype == "link":
                    item["url"] = request.form.get("url", "").strip()
                    item["thumbnail_url"] = request.form.get("thumbnail_url", "").strip()
                else:
                    file = request.files.get("file")
                    ext_url = request.form.get("external_url", "").strip()
                    if file and file.filename:
                        res = upload_to_cloudinary(file, itype)
                        if res:
                            item.update(cloudinary_id=res["public_id"],
                                        cloudinary_url=res["url"], url=res["url"],
                                        thumbnail_url=res.get("thumbnail_url", res["url"]))
                        else:
                            err = "Upload failed — check Cloudinary config."
                    elif ext_url:
                        item["url"] = ext_url
                        item["thumbnail_url"] = request.form.get("thumbnail_url", "").strip()
                    else:
                        err = "Provide a file or an external URL."

                if not err:
                    db.insert("items", item)
                    success = True

        return render_template("upload.html", categories=cats, zones=zones,
                               error=err, success=success, active="upload")

    # ── Item detail ───────────────────────────────────────────────────────────
    @app.route("/item/<item_id>")
    def item_detail(item_id):
        db = get_db()
        item = db.find_one("items", {"_id": item_id, "is_approved": True})
        if not item:
            abort(404)
        db.update("items", {"_id": item_id}, {"$inc": {"views": 1}})
        item["views"] = item.get("views", 0) + 1

        discs = db.find("discussions", {"item_id": item_id, "parent_id": None})
        for d in discs:
            d["replies"] = db.find("discussions", {"parent_id": d["_id"]})

        related = [r for r in db.find("items",
                   {"is_approved": True, "category_slug": item.get("category_slug", "")},
                   limit=8) if r["_id"] != item_id][:4]

        cat  = db.find_one("categories", {"slug": item.get("category_slug", "")})
        zone = db.find_one("zones",      {"slug": item.get("zone_slug", "")})

        return render_template("item.html", item=item, discussions=discs,
                               related=related, category=cat, zone=zone, active="")

    # ── Add discussion ────────────────────────────────────────────────────────
    @app.route("/item/<item_id>/discuss", methods=["POST"])
    def add_discussion(item_id):
        db = get_db()
        if not db.find_one("items", {"_id": item_id, "is_approved": True}):
            abort(404)
        msg = request.form.get("message", "").strip()
        if not msg:
            return redirect(url_for("item_detail", item_id=item_id))
        db.insert("discussions", {
            "item_id":   item_id,
            "username":  (request.form.get("username") or "Anonymous").strip(),
            "message":   msg,
            "parent_id": request.form.get("parent_id") or None,
            "created_at": datetime.utcnow(),
        })
        return redirect(url_for("item_detail", item_id=item_id) + "#disc-section")

    # ── Search ────────────────────────────────────────────────────────────────
    @app.route("/search")
    def search():
        db = get_db()
        q        = request.args.get("q", "").strip()
        itype    = request.args.get("type")
        cat_slug = request.args.get("category")
        z_slug   = request.args.get("zone")
        page     = request.args.get("page", 1, type=int)
        per_page = Config.ITEMS_PER_PAGE
        items = []; total = 0

        if q:
            extra = {"is_approved": True}
            if itype:    extra["type"] = itype
            if cat_slug: extra["category_slug"] = cat_slug
            if z_slug:   extra["zone_slug"] = z_slug
            all_res = db.search("items", q, extra)
            total   = len(all_res)
            skip    = (page - 1) * per_page
            items   = all_res[skip: skip + per_page]

        total_pages = max(1, (total + per_page - 1) // per_page)
        zones = db.find("zones", {}, sort=[("sort_order", 1)])
        return render_template("search.html", items=items, q=q,
                               page=page, total_pages=total_pages, total=total,
                               itype=itype, cat_slug=cat_slug, z_slug=z_slug,
                               zones=zones, active="search")

    # ── Download ──────────────────────────────────────────────────────────────
    @app.route("/download/<item_id>")
    def download(item_id):
        db = get_db()
        item = db.find_one("items", {"_id": item_id, "is_approved": True})
        if not item:
            abort(404)
        db.update("items", {"_id": item_id}, {"$inc": {"downloads": 1}})
        target = item.get("cloudinary_url") or item.get("url", "")
        if target:
            return redirect(target)
        abort(404)


    # ── Cloudinary connectivity test (Termux helper) ──────────────────────────
    @app.route("/test-cloudinary")
    def test_cloudinary():
        from common.cloudinary_utils import test_cloudinary_connection
        import os
        result = test_cloudinary_connection()
        return jsonify({
            "cloudinary_configured": bool(Config.CLOUDINARY_CLOUD_NAME),
            "cloud_name": Config.CLOUDINARY_CLOUD_NAME or "(not set)",
            "ssl_cert_file": os.environ.get("SSL_CERT_FILE", "(not set)"),
            "requests_ca_bundle": os.environ.get("REQUESTS_CA_BUNDLE", "(not set)"),
            "connectivity_test": result,
            "hint": "If ok=false on Termux: export SSL_CERT_FILE=$PREFIX/etc/tls/cert.pem && export REQUESTS_CA_BUNDLE=$PREFIX/etc/tls/cert.pem then restart server."
        })

    # ── API stats ─────────────────────────────────────────────────────────────
    @app.route("/api/stats")
    def api_stats():
        db = get_db()
        return jsonify({
            "total":  db.count("items", {"is_approved": True}),
            "links":  db.count("items", {"type": "link",  "is_approved": True}),
            "videos": db.count("items", {"type": "video", "is_approved": True}),
            "images": db.count("items", {"type": "image", "is_approved": True}),
            "files":  db.count("items", {"type": "file",  "is_approved": True}),
            "categories": db.count("categories", {}),
            "zones":  db.count("zones", {}),
        })

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    return app


if __name__ == "__main__":
    create_app().run(port=5001, debug=True)
