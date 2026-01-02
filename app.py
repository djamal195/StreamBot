from flask import Flask, render_template, request, jsonify
import json
import os
import requests
import threading
from scraper import run_scraper
from tmdb_api import get_movie_info

app = Flask(__name__)
DB_FILE = "filmdb.json"

# ==========================================
# CONFIGURATION FACEBOOK
# ==========================================
# Le token que tu as copié sur Facebook Developers
PAGE_ACCESS_TOKEN = "EAA1kj7YrrxIBQcvXq3M8YJZAiNAtsAU6oX1LdatiJ1QQiZBxIA6FQBaE2vIfs6lxTdoj809jOTotZBZAZBVGlFZCjEmuVbcOe2awlt7u0ZCiGF9XfkiWrU6oAwURaF7JjUs47LMaepzp5C4TnbB7aF15zD0FESFAZAbkgbmPFKuHMdv1Wp342sCdMwJEmO3QUZBp8jlRXyE9AogZDZD"
# Un mot de passe que tu inventes pour la sécurité (ex: otf_secret_123)
VERIFY_TOKEN = "otf200919"

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
    return "<h1>🤖 BOT MESSENGER ACTIF</h1>"

# ==========================================
# 1. LE WEBHOOK (L'OREILLE DU BOT)
# ==========================================
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # A. Vérification Facebook (C'est Facebook qui teste si tu es là)
    if request.method == 'GET':
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Erreur de vérification", 403

    # B. Réception des messages
    if request.method == 'POST':
        data = request.json
        if data.get("object") == "page":
            for entry in data["entry"]:
                for event in entry["messaging"]:
                    sender_id = event["sender"]["id"]
                    
                    if "message" in event and "text" in event["message"]:
                        user_text = event["message"]["text"]
                        # On lance la recherche en thread séparé pour répondre vite
                        threading.Thread(target=handle_message, args=(sender_id, user_text)).start()
            
            return "EVENT_RECEIVED", 200
    return "OK", 200

# ==========================================
# 2. LOGIQUE DU BOT (CERVEAU)
# ==========================================
def send_fb_message(recipient_id, text):
    """Envoie un texte simple"""
    params = {"access_token": PAGE_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}
    data = json.dumps({
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    })
    requests.post("https://graph.facebook.com/v12.0/me/messages", params=params, headers=headers, data=data)

def send_fb_card(recipient_id, movie_data):
    """Envoie une jolie carte avec bouton"""
    params = {"access_token": PAGE_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}
    
    # URL de la page de téléchargement (On construit le slug ici)
    slug = f"{movie_data['title'].replace(' ', '-').lower()}-{movie_data['year']}-{movie_data['id']}"
    # L'URL doit pointer vers ton serveur Render
    # ATTENTION : Remplace par ton VRAI lien Render
    website_url = f"https://streambot-tv9s.onrender.com/watch/{slug}"
    
    data = json.dumps({
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "generic",
                    "elements": [{
                        "title": f"{movie_data['title']} ({movie_data['year']})",
                        "image_url": movie_data['poster'],
                        "subtitle": "Clique ci-dessous pour télécharger 👇",
                        "buttons": [
                            {
                                "type": "web_url",
                                "url": website_url,
                                "title": "📥 TÉLÉCHARGER"
                            },
                            {
                                "type": "postback",
                                "title": f"Générer: {slug}", # Hack pour passer les infos
                                "payload": "GENERATE"
                            }
                        ]
                    }]
                }
            }
        }
    })
    requests.post("https://graph.facebook.com/v12.0/me/messages", params=params, headers=headers, data=data)

def handle_message(sender_id, text):
    """Traite le message de l'utilisateur"""
    print(f"Message reçu de {sender_id}: {text}")
    
    # 1. Recherche sur TMDB
    send_fb_message(sender_id, f"🔎 Je cherche '{text}' sur les serveurs...")
    movie_info = get_movie_info(text)
    
    if movie_info:
        # 2. On lance le scraping en arrière-plan (PRE-LOADING)
        # On ne fait pas attendre l'utilisateur, on commence à chercher le lien tout de suite
        # Mais on lui envoie déjà la carte pour qu'il clique
        
        # On sauvegarde les infos de base
        slug = f"{movie_info['title'].replace(' ', '-').lower()}-{movie_info['year']}-{movie_info['id']}"
        db = load_db()
        
        if slug not in db:
            # Si pas en base, on lance le scraper
            send_fb_message(sender_id, "⏳ Film trouvé ! Je pirate le lien, patiente 20 secondes...")
            link = run_scraper(movie_info['title'])
            
            if link:
                db[slug] = {"info": movie_info, "link": link}
                save_db(db)
                send_fb_card(sender_id, movie_info)
            else:
                send_fb_message(sender_id, "❌ Désolé, ce film est introuvable sur les serveurs French-Stream.")
        else:
            # Déjà en cache
            send_fb_card(sender_id, movie_info)
            
    else:
        send_fb_message(sender_id, "❌ Film introuvable. Essaie de bien écrire le titre.")

# ... (GARDE LA PARTIE @app.route('/watch') COMME AVANT) ...
# ... (Copie-colle la fonction watch et le main du code précédent ici) ...
@app.route('/watch/<slug>')
def watch(slug):
    db = load_db()
    if slug in db:
        return render_template('movie.html', movie=db[slug])
    return "<h1>Lien en cours de génération ou introuvable... Rafraichissez dans 10s.</h1>", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


