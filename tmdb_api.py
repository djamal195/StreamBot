import requests

# ⚠️ METS TA CLÉ API TMDB ICI
API_KEY = "84d02f22771ce209a34cfbc49dfe99de"
BASE_URL = "https://api.themoviedb.org/3"

def get_movie_info(query):
    """Cherche un film sur TMDB et renvoie les détails"""
    url = f"{BASE_URL}/search/movie?api_key={API_KEY}&language=fr-FR&query={query}"
    try:
        r = requests.get(url)
        data = r.json()
        if data['results']:
            first = data['results'][0]
            # On récupère l'image en haute qualité
            poster_path = first.get('poster_path')
            backdrop_path = first.get('backdrop_path')
            
            return {
                "id": first['id'],
                "title": first['title'],
                "year": first.get('release_date', 'N/A').split('-')[0],
                "overview": first.get('overview', 'Aucune description.'),
                "poster": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "",
                "backdrop": f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else ""
            }
    except Exception as e:
        print(f"❌ Erreur TMDB: {e}")
    return None