from flask import Flask, render_template, request
import json
import os
import requests
import threading
from scraper import run_scraper
from tmdb_api import get_movie_info
from pymongo import MongoClient
from datetime import datetime

app = Flask(__name__)

# MongoDB
MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["streambot"]
collection = db["contents"]

PAGE_ACCESS_TOKEN = "EAA1kj7YrrxIBQU1uaYs9ZCaWzljLrhwaZAyaaAFJdHbryb9uEZA9EuyGixG4oOvJqRTzoNZChKHB2aHZBwWRMZBQxXncPyJnT4AoLsdBn9w9BJ1N7ZBtXVOe60rua7Li3JPF2Ha0OPEyxXZCmnzBuufagdKONIoYmZCwv6tWlY3VZCfRZCPOpy4gNjXu9NRyeylY50OAXU7QYRJEQZDZD"
VERIFY_TOKEN = "otf_secret_password"

def fb_call(endpoint, payload):
    url = f"https://graph.facebook.com/v17.0/me/{endpoint}?access_token={PAGE_ACCESS_TOKEN}"
    try:
        requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload))
    except Exception as e:
        print(f"Erreur FB: {e}")

def send_text(user_id, text):
    fb_call("messages", {"recipient": {"id": user_id}, "message": {"text": text}})

def send_choice_card(user_id, user_text):
    element = {
        "title": f"Recherche : {user_text}",
        "subtitle": "Est-ce un Film ou une Série ?",
        "buttons": [
            {"type": "postback", "title": "🎬 C'EST UN FILM", "payload": f"TYPE|FILM|{user_text}"},
            {"type": "postback", "title": "📺 C'EST UNE SÉRIE", "payload": f"TYPE|SERIE|{user_text}"}
        ]
    }
    fb_call("messages", {
        "recipient": {"id": user_id},
        "message": {"attachment": {"type": "template", "payload": {"template_type": "generic", "elements": [element]}}}
    })

def send_movie_card(user_id, info, season_num=None):
    is_series_flag = "1" if info.get('is_series') else "0"
    season_str = str(season_num) if season_num else "0"
    payload_data = f"GENERATE|{info['title']}|{info.get('year','')}|{is_series_flag}|{season_str}"
    
    subtitle = f"Série (Saison {season_num})" if season_num else f"Film ({info.get('year','')})"
    
    element = {
        "title": info['title'],
        "image_url": info.get('poster'),
        "subtitle": subtitle + "\n" + info.get('overview', '')[:80] + "...",
        "buttons": [{"type": "postback", "title": "🚀 LANCER", "payload": payload_data}]
    }
    fb_call("messages", {
        "recipient": {"id": user_id},
        "message": {"attachment": {"type": "template", "payload": {"template_type": "generic", "elements": [element]}}}
    })

def send_final_link(user_id, url):
    element = {
        "title": "✅ TÉLÉCHARGEMENT PRÊT",
        "subtitle": "Cliquez ci-dessous",
        "buttons": [{"type": "web_url", "url": url, "title": "📥 ACCÉDER"}]
    }
    fb_call("messages", {
        "recipient": {"id": user_id},
        "message": {"attachment": {"type": "template", "payload": {"template_type": "generic", "elements": [element]}}}
    })

def extract_season_number(text):
    match = re.search(r'(\d+)$', text.strip())
    if match:
        return text[:match.start()].strip(), match.group(1)
    return text, "1"

def process_background(user_id, title, year, is_series, season_num):
    slug = f"{title.replace(' ', '-').lower()}-{year}"
    if is_series and season_num:
        slug += f"-s{season_num}"

    if collection.find_one({"slug": slug}):
        send_text(user_id, "⚡ Déjà dans la base !")
        url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/watch/{slug}"
        send_final_link(user_id, url)
        return

    send_text(user_id, "🕵️‍♂️ Recherche en cours...")

    if is_series:
        result = run_scraper(title, season_number=season_num, is_serie=True)
    else:
        result = run_scraper(title, is_serie=False)

    if isinstance(result, dict) and result.get("status") == "selection_needed":
        screenshot = result.get("screenshot_path")
        send_text(user_id, f"🔍 Plusieurs résultats trouvés pour '{title}'.")
        if screenshot and os.path.exists(screenshot):
            # Envoi de l'image (à adapter selon ton domaine)
            image_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/{screenshot}"
            fb_call("messages", {
                "recipient": {"id": user_id},
                "message": {"attachment": {"type": "image", "payload": {"url": image_url}}}
            })
        send_text(user_id, "Réponds avec le numéro du bon résultat.")
        return

    if result:
        info = get_movie_info(title)
        data = {
            "slug": slug,
            "title": title,
            "year": year,
            "is_series": is_series,
            "season": season_num,
            "info": info,
            "links": result,
            "created_at": datetime.utcnow()
        }
        collection.insert_one(data)
        
        url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/watch/{slug}"
        send_final_link(user_id, url)
    else:
        send_text(user_id, "❌ Contenu introuvable.")

# Webhook et routes (à compléter selon ton besoin)
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # ... ton code webhook actuel
    pass

@app.route('/watch/<slug>')
def watch(slug):
    item = collection.find_one({"slug": slug})
    if item:
        return render_template('movie.html', item=item)
    return "404", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
