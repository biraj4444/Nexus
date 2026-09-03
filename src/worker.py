import sys
from pathlib import Path

# Make the project root available for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from workers import wsgi

from public_site.app import create_app as create_public_app
from admin_site.app import create_app as create_admin_app


public_app = create_public_app()
admin_app = create_admin_app()

app = DispatcherMiddleware(
    public_app,
    {
        "/admin": admin_app,
    },
)

Default = wsgi.entrypoint(app)
