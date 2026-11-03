"""CPJudge Web Application Server Entrypoint.

Can be run:
- Directly with Python: python run.py
- With Gunicorn: gunicorn -w 4 -b 0.0.0.0:5000 "run:app"
"""
import os
from cpjudge.app import create_app

env = os.environ.get("FLASK_ENV", "development")
app = create_app(env)

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    app.run(host=host, port=port, debug=(env == "development"))
