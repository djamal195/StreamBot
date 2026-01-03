from flask import Flask, render_template, request, jsonify
import json
import os
import requests
import threading
import time
import random

# Import des modules locaux
from scraper import run_scraper
from tmdb_api import get_movie_info

app = Flask(__name__)
DB_FILE = "database.json"

# ==========================================
# CONFIGURATION DU BOT (REMPLIS ICI !)
# ==========================================
# Le token généré dans la page Developers Facebook
PAGE_ACCESS_TOKEN = "EAA1kj7YrrxIBQYgmLgXwZCJjHbhJzzu6ZAEBZBkbLwpQo3k6cgPqpsdMZCmOZBfZClqsP7LHCyRkEgF5FiD9KBVvkJBUlxQnfbQ6AE0nad4vnCtZAFM306H5t06goVZBPCfgpwk9FuSZCik2dejCnjHjYXPtWlwZBDYjncQJJlMzpmZCdAUxqRcZB8uflSeOKc5Xo7nzpG6Iz6NcogZDZD"
# Le mot de passe que tu as choisi dans le Webhook
VERIFY_TOKEN = "otf_secret_password"

# ==========================================
# GESTION DATABASE
# ==========================================
def load_db():
    if not os.path.exists(DB_FILE): return {}
    try:
        with open(DB_FILE, 'r') as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except: return {}

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f, indent=4)

# ==========================================
# FONCTIONS MESSENGER (API FACEBOOK)
# ==========================================
def fb_call(endpoint, payload):
    """Envoie une requête à l'API Graph de Facebook"""
    url = f"https://graph.facebook.com/v17.0/me/{endpoint}?access_token={PAGE_ACCESS_TOKEN}"
    headers = {"Content-Type": "application/json"}
    try:
        requests.post(url, headers=headers, data=json.dumps(payload))
    except Exception as e:
        print(f"Erreur FB: {e}")

def send_text(user_id, text):
    fb_call("messages", {"recipient": {"id": user_id}, "message": {"text": text}})

def send_typing(user_id):
    fb_call("messages", {"recipient": {"id": user_id}, "sender_action": "typing_on"})

def send_search_result_card(user_id, info):
    """Envoie la carte avec l'affiche et le bouton 'Générer'"""
    
    # On prépare les données pour le bouton (Titre|Année|IsSeries)
    # 1 = Série, 0 = Film
    is_series_flag = "1" if info['is_series'] else "0"
    payload_data = f"GENERATE|{info['title']}|{info['year']}|{is_series_flag}"
    
    type_media = "Série" if info['is_series'] else "Film"
    
    element = {
        "title": f"{info['title']} ({info['year']})",
        "image_url": info['poster'],
        "subtitle": f"[{type_media}] {info['overview'][:80]}...",
        "buttons": [
            {
                "type": "postback",
                "title": "🚀 LANCER",
                "payload": payload_data
            }
        ]
    }
    
    message = {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": "generic",
                "elements": [element]
            }
        }
    }
    fb_call("messages", {"recipient": {"id": user_id}, "message": message})

def send_final_link_card(user_id, title, url):
    """Envoie le bouton final vers ton site"""
    element = {
        "title": f"✅ {title} : DISPONIBLE",
        "subtitle": "Clique ci-dessous pour accéder au téléchargement.",
        "buttons": [
            {
                "type": "web_url",
                "url": url,
                "title": "📥 TÉLÉCHARGER"
            }
        ]
    }
    
    message = {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": "generic",
                "elements": [element]
            }
        }
    }
    fb_call("messages", {"recipient": {"id": user_id}, "message": message})

# ==========================================
# LOGIQUE DU BOT (INTELLIGENCE)
# ==========================================

def process_scraping_background(user_id, title, year, is_series):
    """Cette fonction tourne en arrière-plan pour ne pas bloquer le bot"""
    
    slug = f"{title.replace(' ', '-').lower()}-{year}"
    
    # 1. Vérification Cache
    db = load_db()
    if slug in db:
        send_text(user_id, "⚡ Lien trouvé dans le cache (Rapide) !")
        final_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/watch/{slug}"
        send_final_link_card(user_id, title, final_url)
        return

    # 2. Scraping
    send_text(user_id, "🕵️‍♂️ Je pirate le lien sur French-Stream, patiente environ 20-30 secondes...")
    
    # On appelle ton scraper
    if is_series:
        link_data = run_scraper(title, is_serie=True, all_episodes=True)
    else:
        link_data = run_scraper(title, is_serie=False)
    
    # 3. Résultat
    if link_data:
        # On a besoin de récupérer les infos complètes pour la DB (via TMDB)
        info = get_movie_info(title)
        
        db = load_db() # On recharge pour être sûr
        db[slug] = {
            "info": info,
            "is_series": is_series,
            "links": link_data
        }
        save_db(db)
        
        final_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/watch/{slug}"
        send_final_link_card(user_id, title, final_url)
    else:
        send_text(user_id, "❌ Désolé, je n'ai pas trouvé de lien valide sur les serveurs.")

def handle_message(user_id, text):
    print(f"Message de {user_id}: {text}")
    send_typing(user_id)
    
    # Recherche TMDB
    info = get_movie_info(text)
    
    if info:
        send_search_result_card(user_id, info)
    else:
        send_text(user_id, "❌ Film/Série introuvable. Vérifie le titre.")

def handle_postback(user_id, payload):
    print(f"Postback de {user_id}: {payload}")
    
    # Payload format: GENERATE|Titre|Année|IsSeries(0/1)
    if payload.startswith("GENERATE"):
        parts = payload.split('|')
        title = parts[1]
        year = parts[2]
        is_series = (parts[3] == "1")
        
        # On lance le travail en thread séparé (très important !)
        threading.Thread(target=process_scraping_background, args=(user_id, title, year, is_series)).start()

# ==========================================
# ROUTES FLASK
# ==========================================

@app.route('/', methods=['GET'])
def index():
    return "🤖 STREAM BOT IS RUNNING"

# Route Webhook (Connexion Facebook)
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # Vérification (GET)
    if request.method == 'GET':
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Token Invalide", 403

    # Réception Messages (POST)
    if request.method == 'POST':
        data = request.json
        if data["object"] == "page":
            for entry in data["entry"]:
                for event in entry["messaging"]:
                    user_id = event["sender"]["id"]
                    
                    if "message" in event and "text" in event["message"]:
                        handle_message(user_id, event["message"]["text"])
                    
                    elif "postback" in event:
                        handle_postback(user_id, event["postback"]["payload"])
                        
        return "EVENT_RECEIVED", 200

# Route Page de Téléchargement
@app.route('/watch/<slug>')
def watch(slug):
    db = load_db()
    if slug in db:
        return render_template('movie.html', item=db[slug])
    return "<h1>404 - Lien Expiré ou Inconnu</h1>", 404

if __name__ == '__main__':
    # Configuration auto du port pour Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
