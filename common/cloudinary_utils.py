"""
Cloudinary upload / delete helpers.
Includes Termux (Android) SSL certificate fix so uploads work on
localhost / Termux without a deployed server.
"""
import os
import sys

from .config import Config


# ─── Step 1: Apply SSL fix BEFORE any network import ─────────────────────────
def _apply_ssl_fix():
    """
    Force requests + urllib3 to use a known-good CA bundle.
    Works on Termux/Android, Render, local PC — everywhere.
    Priority: .env override → certifi → Termux path → Linux/macOS system paths
    """
    env_cert = (
        os.environ.get("SSL_CERT_FILE") or
        os.environ.get("REQUESTS_CA_BUNDLE")
    )
    if env_cert and os.path.exists(env_cert):
        os.environ["SSL_CERT_FILE"]      = env_cert
        os.environ["REQUESTS_CA_BUNDLE"] = env_cert
        return env_cert

    try:
        import certifi
        cert_path = certifi.where()
        os.environ["SSL_CERT_FILE"]      = cert_path
        os.environ["REQUESTS_CA_BUNDLE"] = cert_path
        return cert_path
    except ImportError:
        pass

    termux_cert = "/data/data/com.termux/files/usr/etc/tls/cert.pem"
    if os.path.exists(termux_cert):
        os.environ["SSL_CERT_FILE"]      = termux_cert
        os.environ["REQUESTS_CA_BUNDLE"] = termux_cert
        return termux_cert

    for path in [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/cert.pem",
        "/usr/local/etc/openssl/cert.pem",
    ]:
        if os.path.exists(path):
            os.environ["SSL_CERT_FILE"]      = path
            os.environ["REQUESTS_CA_BUNDLE"] = path
            return path

    return None


_cert_path = _apply_ssl_fix()
if _cert_path:
    print(f"[Cloudinary] SSL cert → {_cert_path}")
else:
    print("[Cloudinary] SSL cert → using requests default")


# ─── Step 2: Patch requests.Session to always use our CA bundle ───────────────
def _patch_requests():
    try:
        import requests
        cert = os.environ.get("REQUESTS_CA_BUNDLE")
        if not cert:
            return
        _orig_init = requests.Session.__init__

        def _new_init(self, *a, **kw):
            _orig_init(self, *a, **kw)
            self.verify = cert

        requests.Session.__init__ = _new_init
    except Exception:
        pass

_patch_requests()


# ─── Step 3: Cloudinary init ──────────────────────────────────────────────────
def _init() -> bool:
    if not Config.CLOUDINARY_CLOUD_NAME:
        return False
    try:
        import cloudinary
        import cloudinary.uploader
        cloudinary.config(
            cloud_name=Config.CLOUDINARY_CLOUD_NAME,
            api_key=Config.CLOUDINARY_API_KEY,
            api_secret=Config.CLOUDINARY_API_SECRET,
            secure=True,
        )
        return True
    except ImportError:
        print("[Cloudinary] Package not installed — run: pip install cloudinary certifi")
        return False
    except Exception as e:
        print(f"[Cloudinary] Init error: {e}")
        return False


# ─── Step 4: Upload ───────────────────────────────────────────────────────────
def upload_to_cloudinary(file_obj, resource_type: str = "auto"):
    """
    Upload a Flask FileStorage / file-like object to Cloudinary.
    resource_type: 'image' | 'video' | 'file' | 'auto'
    Returns dict on success, None on failure.
    """
    if not _init():
        return None

    import cloudinary
    import cloudinary.uploader

    type_map  = {"video": "video", "image": "image", "file": "raw"}
    cld_type  = type_map.get(resource_type, "auto")
    tmp_path  = None

    try:
        # Save stream to a temp file (works for both Flask FileStorage and raw streams)
        if hasattr(file_obj, "read") or hasattr(file_obj, "save"):
            import tempfile
            suffix = ""
            if hasattr(file_obj, "filename") and file_obj.filename:
                suffix = os.path.splitext(file_obj.filename)[-1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                if hasattr(file_obj, "save"):
                    file_obj.save(tmp.name)          # Flask FileStorage
                else:
                    tmp.write(file_obj.read())        # raw stream
                tmp_path = tmp.name
            upload_target = tmp_path
        else:
            upload_target = file_obj                  # already a path string

        result = cloudinary.uploader.upload(
            upload_target,
            resource_type=cld_type,
            folder="nexusvault",
            use_filename=True,
            unique_filename=True,
        )

        # Video thumbnail
        thumbnail_url = ""
        if resource_type == "video":
            try:
                thumbnail_url = cloudinary.CloudinaryVideo(result["public_id"]).build_url(
                    transformation=[{"width": 480, "height": 270, "crop": "fill", "format": "jpg"}]
                )
            except Exception:
                thumbnail_url = result.get("secure_url", "")

        return {
            "public_id":     result.get("public_id", ""),
            "url":           result.get("secure_url", ""),
            "thumbnail_url": thumbnail_url or result.get("secure_url", ""),
            "bytes":         result.get("bytes", 0),
            "format":        result.get("format", ""),
            "width":         result.get("width", 0),
            "height":        result.get("height", 0),
            "duration":      result.get("duration", 0),
        }

    except Exception as e:
        print(f"[Cloudinary] Upload error: {e}")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ─── Step 5: Delete ───────────────────────────────────────────────────────────
def delete_from_cloudinary(public_id: str, resource_type: str = "raw") -> bool:
    if not _init() or not public_id:
        return False
    import cloudinary.uploader
    type_map = {"video": "video", "image": "image", "file": "raw", "link": "raw"}
    cld_type = type_map.get(resource_type, resource_type)
    try:
        cloudinary.uploader.destroy(public_id, resource_type=cld_type)
        return True
    except Exception as e:
        print(f"[Cloudinary] Delete error: {e}")
        return False


# ─── Connectivity test ────────────────────────────────────────────────────────
def test_cloudinary_connection() -> dict:
    """Quick test — returns {ok, status, cert_used, error}."""
    import requests
    cert = os.environ.get("REQUESTS_CA_BUNDLE") or True
    out  = {"ok": False, "status": None, "cert_used": str(cert), "error": None}
    try:
        r = requests.get("https://api.cloudinary.com", timeout=10, verify=cert)
        out["status"] = r.status_code
        out["ok"]     = r.status_code < 500
    except Exception as e:
        out["error"] = str(e)
    return out
