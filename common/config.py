import os
from pathlib import Path

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "nexusvault-dev-secret-2024")
    MONGO_URI = os.environ.get("MONGO_URI", "")

    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "NexusAdmin@2024")

    ITEMS_PER_PAGE = int(os.environ.get("ITEMS_PER_PAGE", 24))
    MAX_CONTENT_LENGTH = 512 * 1024 * 1024  # 512 MB
