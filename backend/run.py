"""Simple backend launcher for local development."""

import app

if __name__ == "__main__":
    app._create_roles_table()
    app._create_users_table()
    app._create_tab_sessions_table()
    app.app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

