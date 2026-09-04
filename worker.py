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
