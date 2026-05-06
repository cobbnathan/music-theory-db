"""Flask API for the music theory database."""
from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite_utils
from pathlib import Path

app = Flask(__name__)
CORS(app)

DB_PATH = Path(__file__).parent.parent / "data" / "music_theory.db"


def get_db() -> sqlite_utils.Database:
    return sqlite_utils.Database(DB_PATH)


@app.route("/api/search")
def search():
    q = request.args.get("q", "")
    db = get_db()
    # TODO: implement full-text search
    return jsonify({"query": q, "results": []})


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)
