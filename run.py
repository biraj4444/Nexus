#!/usr/bin/env python3
"""
NexusVault — Universal Collection Platform
Public Site  → http://localhost:5001
Admin Panel  → http://localhost:5002

Admin Login:
  Username : admin
  Password : NexusAdmin@2024
"""
import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_public():
    from public_site.app import create_app
    app = create_app()
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False, threaded=True)


def run_admin():
    from admin_site.app import create_app
    app = create_app()
    app.run(host="0.0.0.0", port=5002, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    print("=" * 60)
    print("  ⬡  NexusVault — Universal Collection Platform")
    print("=" * 60)
    print("  📡  Public Site  →  http://localhost:5001")
    print("  🔐  Admin Panel  →  http://localhost:5002")
    print("  Admin user: admin / NexusAdmin@2024")
    print("=" * 60)

    t1 = threading.Thread(target=run_public, name="Public", daemon=True)
    t2 = threading.Thread(target=run_admin, name="Admin", daemon=True)
    t1.start()
    t2.start()
    try:
        t1.join()
        t2.join()
    except KeyboardInterrupt:
        print("\n🛑  Shutting down NexusVault …")
        sys.exit(0)
