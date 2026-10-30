"""Simple backend launcher for local development."""

import app

if __name__ == "__main__":
    app._initialize_sqlite()
    app.app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

