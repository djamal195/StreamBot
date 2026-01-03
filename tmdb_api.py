import requests

# ⚠️ REMET TA CLÉ ICI
API_KEY = "84d02f22771ce209a34cfbc49dfe99de"
BASE_URL = "https://api.themoviedb.org/3"

def get_movie_info(query):
    """Cherche Films ET Séries"""
    # On utilise 'multi' pour trouver les deux
    url = f"{BASE_URL}/search/multi?api_key={API_KEY}&language=fr-FR&query={query}"
    
    try:
        r = requests.get(url)
        data = r.json()
        
        if data.get('results'):
            # On cherche le premier résultat valide (Film ou TV)
            for res in data['results']:
                media_type = res.get('media_type')
                
                # On ignore les personnes
                if media_type not in ['movie', 'tv']:
                    continue

                is_series = (media_type == 'tv')
                
                # Récupération des données (les noms changent selon le type)
                title = res.get('name') if is_series else res.get('title')
                date = res.get('first_air_date') if is_series else res.get('release_date')
                year = date.split('-')[0] if date else "N/A"
                
                poster = res.get('poster_path')
                backdrop = res.get('backdrop_path')

                return {
                    "id": res['id'],
                    "title": title,
                    "year": year,
                    "is_series": is_series,
                    "overview": res.get('overview', 'Aucune description disponible.'),
                    "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else "",
                    "backdrop": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else ""
                }
    except Exception as e:
        print(f"Erreur TMDB: {e}")
    return None

