from flask import Flask, render_template, request, jsonify
import json
import os
from scraper import run_scraper
from tmdb_api import get_movie_info

app = Flask(__name__)
DB_FILE = "database.json"

def load_db():
    if not os.path.exists(DB_FILE): return {}
    try:
        with open(DB_FILE, 'r') as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except: return {}

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f, indent=4)

@app.route('/')
def home():
    return "<h1>🤖 OTF STREAM BOT - ONLINE</h1>"

# API 1 : Recherche
@app.route('/api/search', methods=['GET'])
def search():
    query = request.args.get('q')
    info = get_movie_info(query)
    if info: return jsonify({"status": "found", "data": info})
    return jsonify({"status": "not_found"})

# API 2 : Génération
@app.route('/api/generate', methods=['POST'])
def generate():
    data = request.json
    title = data['title']
    slug = f"{title.replace(' ', '-').lower()}-{data['year']}"
    
    db = load_db()
    if slug in db:
        return jsonify({"url": f"{request.host_url}watch/{slug}", "cached": True})

    # Scraping
    link = run_scraper(title)
    
    if link:
        db[slug] = {"info": data, "link": link}
        save_db(db)
        return jsonify({"url": f"{request.host_url}watch/{slug}", "status": "success"})
    else:
        return jsonify({"status": "error"})

# API 3 : Page de téléchargement
@app.route('/watch/<slug>')
def watch(slug):
    db = load_db()
    if slug in db:
        return render_template('movie.html', movie=db[slug])
    return "Film introuvable", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)