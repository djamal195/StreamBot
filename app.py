from flask import Flask, render_template, request, jsonify
import json
import os
import requests
import threading
import time
import random
import re
from scraper import run_scraper
from tmdb_api import get_movie_info

app = Flask(__name__)
DB_FILE = "database.json"

PAGE_ACCESS_TOKEN = "EAA1kj7YrrxIBQU1uaYs9ZCaWzljLrhwaZAyaaAFJdHbryb9uEZA9EuyGixG4oOvJqRTzoNZChKHB2aHZBwWRMZBQxXncPyJnT4AoLsdBn9w9BJ1N7ZBtXVOe60rua7Li3JPF2Ha0OPEyxXZCmnzBuufagdKONIoYmZCwv6tWlY3VZCfRZCPOpy4gNjXu9NRyeylY50OAXU7QYRJEQZDZD"
VERIFY_TOKEN = "otf_secret_password"

def load_db():
    if not os.path.exists(DB_FILE): return {}
    try:
        with open(DB_FILE, 'r') as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except: return {}

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f, indent=4)

# --- FONCTIONS MESSENGER ---
def fb_call(endpoint, payload):
    url = f"https://graph.facebook.com/v17.0/me/{endpoint}?access_token={PAGE_ACCESS_TOKEN}"
    headers = {"Content-Type": "application/json"}
    try: requests.post(url, headers=headers, data=json.dumps(payload))
    except Exception as e: print(f"Erreur FB: {e}")

def send_text(user_id, text):
    fb_call("messages", {"recipient": {"id": user_id}, "message": {"text": text}})

def send_choice_card(user_id, user_text):
    """Demande si c'est un Film ou une Série"""
    # On passe le texte original dans le payload pour le récupérer après
    element = {
        "title": f"Recherche : {user_text}",
        "subtitle": "Est-ce un Film ou une Série ?",
        "buttons": [
            {"type": "postback", "title": "🎬 C'EST UN FILM", "payload": f"TYPE|FILM|{user_text}"},
            {"type": "postback", "title": "📺 C'EST UNE SÉRIE", "payload": f"TYPE|SERIE|{user_text}"}
        ]
    }
    message = {"attachment": {"type": "template", "payload": {"template_type": "generic", "elements": [element]}}}
    fb_call("messages", {"recipient": {"id": user_id}, "message": message})

def send_movie_card(user_id, info, season_num=None):
    """Envoie la carte de confirmation"""
    is_series_flag = "1" if info['is_series'] else "0"
    season_str = str(season_num) if season_num else "0"
    
    # Payload: GENERATE | Titre | Année | IsSerie | SeasonNum
    payload_data = f"GENERATE|{info['title']}|{info['year']}|{is_series_flag}|{season_str}"
    
    subtitle = f"Série (Saison {season_num})" if season_num else f"Film ({info['year']})"
    
    element = {
        "title": info['title'],
        "image_url": info['poster'],
        "subtitle": subtitle + "\n" + info['overview'][:60] + "...",
        "buttons": [{"type": "postback", "title": "🚀 LANCER", "payload": payload_data}]
    }
    message = {"attachment": {"type": "template", "payload": {"template_type": "generic", "elements": [element]}}}
    fb_call("messages", {"recipient": {"id": user_id}, "message": message})

def send_final_link(user_id, url):
    element = {
        "title": "✅ TÉLÉCHARGEMENT PRÊT",
        "subtitle": "Cliquez ci-dessous pour accéder à vos fichiers.",
        "buttons": [{"type": "web_url", "url": url, "title": "📥 ACCÉDER"}]
    }
    message = {"attachment": {"type": "template", "payload": {"template_type": "generic", "elements": [element]}}}
    fb_call("messages", {"recipient": {"id": user_id}, "message": message})

# --- LOGIQUE INTELLIGENTE ---
def extract_season_number(text):
    """Extrait le chiffre à la fin (ex: 'Stranger Things 4' -> 4)"""
    match = re.search(r'(\d+)$', text.strip())
    if match:
        number = match.group(1)
        # On nettoie le titre (on enlève le chiffre)
        title_clean = text[:match.start()].strip()
        return title_clean, number
    return text, "1" # Par défaut Saison 1 si pas de chiffre

def process_background(user_id, title, year, is_series, season_num):
    slug = f"{title.replace(' ', '-').lower()}-{year}"
    if is_series and season_num:
        slug += f"-s{season_num}" # Slug unique par saison
    
    db = load_db()
    if slug in db:
        send_text(user_id, "⚡ Trouvé dans le cache !")
        url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/watch/{slug}"
        send_final_link(user_id, url)
        return

    send_text(user_id, "🕵️‍♂️ Recherche et extraction en cours... (20s)")
    
    # APPEL AU SCRAPER
    if is_series:
        # On passe le titre propre et le numéro de saison
        links = run_scraper(title, season_number=season_num, is_serie=True, all_episodes=True)
    else:
        links = run_scraper(title, is_serie=False)
    
    if links:
        info = get_movie_info(title)
        db = load_db()
        db[slug] = {"info": info, "is_series": is_series, "links": links, "season": season_num}
        save_db(db)
        
        url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/watch/{slug}"
        send_final_link(user_id, url)
    else:
        send_text(user_id, "❌ Introuvable sur les serveurs.")

# --- HANDLERS ---
def handle_message(user_id, text):
    print(f"MSG: {text}")
    # Etape 1 : On demande le type
    send_choice_card(user_id, text)

def handle_postback(user_id, payload):
    print(f"PB: {payload}")
    parts = payload.split('|')
    action = parts[0]
    
    if action == "TYPE":
        # Etape 2 : Traitement après choix Film/Série
        media_type = parts[1] # FILM ou SERIE
        raw_text = parts[2]
        
        if media_type == "FILM":
            # Recherche TMDB directe
            info = get_movie_info(raw_text)
            if info: send_movie_card(user_id, info, season_num=None)
            else: send_text(user_id, "❌ Film introuvable sur TMDB.")
            
        elif media_type == "SERIE":
            # Extraction du numéro de saison
            clean_title, season_num = extract_season_number(raw_text)
            info = get_movie_info(clean_title)
            if info: 
                # On force le type Série dans l'objet info
                info['is_series'] = True
                send_movie_card(user_id, info, season_num=season_num)
            else: send_text(user_id, "❌ Série introuvable.")

    elif action == "GENERATE":
        # Etape 3 : Lancement
        title = parts[1]
        year = parts[2]
        is_series = (parts[3] == "1")
        season_num = parts[4] if parts[4] != "0" else None
        
        threading.Thread(target=process_background, args=(user_id, title, year, is_series, season_num)).start()

# --- SERVER ---
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get("hub.verify_token") == VERIFY_TOKEN: return request.args.get("hub.challenge")
        return "Bad Token", 403
    if request.method == 'POST':
        data = request.json
        if data["object"] == "page":
            for entry in data["entry"]:
                for event in entry["messaging"]:
                    uid = event["sender"]["id"]
                    if "message" in event: handle_message(uid, event["message"]["text"])
                    elif "postback" in event: handle_postback(uid, event["postback"]["payload"])
        return "OK", 200

@app.route('/watch/<slug>')
def watch(slug):
    db = load_db()
    if slug in db: return render_template('movie.html', item=db[slug])
    return "404", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
