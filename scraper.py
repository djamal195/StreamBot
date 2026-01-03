from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import os

# ==========================================
# CONFIGURATION
# ==========================================
# Mettre True pour le serveur (Render)
# Mettre False pour tester sur ton PC
HEADLESS_MODE = True 

# Identifiants French-Stream
LOGIN_USER = "Jekle19"
LOGIN_PASS = "otf192009"

def normalize_title(title):
    """Normalise le titre pour comparaison stricte"""
    nfd = unicodedata.normalize('NFD', title)
    title_no_accents = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    normalized = re.sub(r'[^\w\s]', ' ', title_no_accents)
    normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
    return normalized

def login_user(page, username, password):
    """Connexion au site avec gestion des overlays"""
    print("🔐 Ouverture du formulaire de connexion...")
    # On vérifie si le bouton est là
    if page.locator("#loginButtonContainer").is_visible():
        try:
            # Clic JS pour éviter les interceptions
            page.evaluate("document.querySelector('#loginButtonContainer').click()")
            time.sleep(2)
            
            page.fill("#login_name", username)
            time.sleep(0.5)
            page.fill("#login_password", password)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(5)
            
            # On attend un peu que le rechargement se fasse
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except: pass
            
            # Vérification basique
            is_logged = page.evaluate("() => !document.querySelector('#loginButtonContainer')")
            if is_logged:
                print("✅ Connexion réussie !")
                return True
        except Exception as e:
            print(f"⚠️ Erreur login: {e}")
            return False
            
    print("ℹ️ Déjà connecté ou bouton absent")
    return True

def search_film(page, search_query, base_url):
    """Cherche un film via l'URL et comparaison stricte du titre"""
    print(f"🔍 Recherche de : {search_query}...")
    
    encoded_title = urllib.parse.quote(search_query)
    search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
    
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    except:
        print("❌ Timeout recherche")
        return None
        
    time.sleep(2)
    
    # Logique de recherche précise injectée en JS
    found_url = page.evaluate("""
        (searchQuery) => {
            const container = document.getElementById('dle-content');
            if (!container) return null;
            const filmBlocks = Array.from(container.querySelectorAll('div.short.film'));
            
            for (const block of filmBlocks) {
                let titleEl = block.querySelector('a.short-poster-title');
                if (!titleEl) titleEl = block.querySelector('div.short-title');
                if (!titleEl) titleEl = block.querySelector('.short-title a');
                
                if (!titleEl) continue;
                
                const titleText = titleEl.innerText.trim();
                
                const normalize = (str) => {
                    return str.toLowerCase()
                        .normalize('NFD')
                        .replace(/[\\u0300-\\u036f]/g, '')
                        .replace(/[^\\w\\s]/g, ' ')
                        .replace(/\\s+/g, ' ')
                        .trim();
                };
                
                if (normalize(titleText).includes(normalize(searchQuery))) {
                    const linkEl = block.querySelector('a.short-poster-title');
                    if (linkEl && linkEl.href) return linkEl.href;
                    
                    const allLinks = Array.from(block.querySelectorAll('a'));
                    const movieLink = allLinks.find(l => l.href && (l.href.includes('/films/') || l.href.includes('/series/')));
                    if (movieLink) return movieLink.href;
                }
            }
            return null;
        }
    """, search_query)
    
    if found_url:
        print(f"✨ Trouvé : {found_url}")
        return found_url
    print("❌ Aucun film ne correspond exactement.")
    return None

def recuperer_lien_vidzy(page, contexte_titre=""):
    """Extrait le lien final depuis la page de l'hébergeur (Popup)"""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(3)
        current_url = page.url
        print(f"   🌐 URL Popup ({contexte_titre}) : {current_url}")
        
        lien = None
        
        # 1. VIDZY
        if "vidzy" in current_url.lower():
            try:
                page.wait_for_selector(".container.file-details a.main-button", timeout=10000)
                lien = page.evaluate("document.querySelector('.container.file-details a.main-button')?.href")
            except: pass
        
        # 2. FSVID / AUTRES
        else:
            try:
                page.wait_for_selector("#customDownloadSpan", timeout=15000)
                lien = page.evaluate("""
                    () => {
                        const span = document.querySelector('#customDownloadSpan');
                        if (!span) return null;
                        
                        // Priorité 1: Balise A
                        const a = span.querySelector('a');
                        if (a && a.href) return a.href;
                        
                        // Priorité 2: Onclick
                        const onclick = span.getAttribute('onclick');
                        if (onclick) {
                            const match = onclick.match(/'(https?:\/\/[^']+)'/);
                            if (match) return match[1];
                        }
                        return null;
                    }
                """)
            except: pass
        
        if lien:
            print(f"   ✅ Lien récupéré : {lien}")
            return lien
        else:
            print("   ❌ Lien introuvable sur la page finale")
            return None
    
    except Exception as e:
        print(f"   ❌ Erreur récupération : {e}")
        return None

def download_all_episodes(page, context, serie_url):
    """Télécharge tous les épisodes d'une série"""
    print("📺 Téléchargement de TOUS les épisodes...")
    
    # 1. Attente de la liste
    try:
        page.wait_for_selector(".ep-download", timeout=10000)
    except:
        print("❌ Liste épisodes introuvable")
        return []

    # 2. Comptage
    episodes_count = page.evaluate("document.querySelectorAll('.ep-download').length")
    print(f"📋 {episodes_count} épisode(s) trouvé(s)")
    
    all_links = []
    
    # LIMITATION POUR RENDER (Évite le timeout du serveur)
    LIMIT_EPISODES = 10
    
    # 3. Boucle sur les épisodes
    for i in range(1, min(episodes_count + 1, LIMIT_EPISODES + 1)):
        print(f"\n--- Épisode {i} ---")
        
        # Sécurité : Retour page série si perdu
        if page.url != serie_url and "french-stream" not in page.url:
            print(f"🔙 Retour à la page série...")
            page.goto(serie_url)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
        
        try:
            # On prépare l'interception du popup AVANT de cliquer
            with context.expect_page(timeout=15000) as popup_info:
                # Clic JS sur le i-ème bouton (index i-1)
                page.evaluate(f"""
                    const eps = document.querySelectorAll('.ep-download');
                    if (eps[{i-1}]) eps[{i-1}].click();
                """)
            
            # On gère le popup
            popup_page = popup_info.value
            lien = recuperer_lien_vidzy(popup_page, f"Ep {i}")
            
            # Important : Fermer le popup pour économiser la RAM
            popup_page.close()
            
            if lien:
                all_links.append({"episode": i, "lien": lien})
            else:
                all_links.append({"episode": i, "lien": None})
            
            # Petite pause anti-ban
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ Erreur Épisode {i} : {e}")
            all_links.append({"episode": i, "lien": None})
    
    return all_links

# ==========================================
# FONCTION PRINCIPALE (APPELÉE PAR APP.PY)
# ==========================================
def run_scraper(titre_film, is_serie=False, episode_num=1, all_episodes=False, season_number=None):
    base_url = "https://french-stream.one/"
    
    with sync_playwright() as p:
        print("🚀 Démarrage du navigateur...")
        # Lancement optimisé pour Docker/Render
        browser = p.chromium.launch(
            headless=HEADLESS_MODE,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        
        # Bloqueur de pubs réseau (Allège la page)
        context.route("**/*", lambda route: route.abort() 
            if any(x in route.request.url for x in ["googleads", "doubleclick", "popads", "adsystem"]) 
            else route.continue_())
            
        page = context.new_page()
        
        try:
            print(f"🌐 Navigation vers {base_url}...")
            page.goto(base_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            # 1. Login
            if not login_user(page, LOGIN_USER, LOGIN_PASS):
                browser.close(); return None
            
            # 2. Recherche
            search_query = titre_film
            # Si c'est une série avec saison, on ne cherche que le titre pour atterrir sur la page série
            # (La sélection de saison se fait après)
            
            film_url = search_film(page, search_query, base_url)
            if not film_url:
                print("🛑 Film non trouvé. Fermeture.")
                browser.close(); return None
            
            # 3. Accès à la page du contenu
            page.goto(film_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
            
            # --- BRANCHE SÉRIE ---
            if is_serie:
                print(f"📺 Mode SÉRIE détecté")
                
                # Gestion des Saisons
                if season_number:
                    print(f"🔄 Recherche de la Saison {season_number}...")
                    season_found = page.evaluate(f"""
                        () => {{
                            // Cherche dans les boutons/liens qui pourraient être des saisons
                            const candidates = Array.from(document.querySelectorAll('.accordion-button, .season-item, [data-season], a'));
                            for (const btn of candidates) {{
                                const txt = (btn.innerText || btn.textContent || '').toLowerCase();
                                // Recherche de "saison X" ou "sX"
                                if (txt.includes('saison {season_number}') || 
                                    txt.includes('season {season_number}') || 
                                    txt.trim() === '{season_number}') {{
                                    btn.click();
                                    return true;
                                }}
                            }}
                            return false;
                        }}
                    """)
                    if season_found:
                        print(f"✅ Saison {season_number} sélectionnée")
                        time.sleep(2)
                    else:
                        print(f"⚠️ Saison {season_number} pas trouvée explicitement (peut-être déjà active ?)")

                # Extraction
                if all_episodes:
                    lien_final = download_all_episodes(page, context, film_url)
                else:
                    # Si on veut juste un épisode spécifique (pas utilisé par ton app.py actuel mais utile au cas où)
                    lien_final = [] # Placeholder
                    
            # --- BRANCHE FILM ---
            else:
                print("🎬 Mode FILM détecté")
                print("🖱️ Clic sur le bouton de téléchargement...")
                
                if not page.locator("#downloadBtn").is_visible():
                    print("❌ Bouton introuvable"); browser.close(); return None

                # Préparation écouteur popup
                popup_bucket = []
                page.context.on("page", lambda p: popup_bucket.append(p))
                
                # Clic JS sur le bouton Download
                page.evaluate("document.getElementById('downloadBtn').click()")
                print("✅ Bouton cliqué...")
                
                # On attend de voir ce qui se passe (Popup ou Menu)
                time.sleep(4)
                
                # On arrête d'écouter
                page.context.remove_listener("page", lambda p: popup_bucket.append(p))
                
                lien_final = None
                
                # SCÉNARIO A : Popup direct
                if len(popup_bucket) > 0:
                    print("🚀 SCÉNARIO A : Popup direct")
                    lien_final = recuperer_lien_vidzy(popup_bucket[0], titre_film)
                
                # SCÉNARIO B : Menu Options
                else:
                    print("🔄 SCÉNARIO B : Menu Options")
                    try:
                        # Forçage affichage menu si caché
                        page.evaluate("""
                            const menu = document.getElementById('downloadOptions');
                            if(menu) { menu.style.display = 'block'; menu.style.visibility = 'visible'; }
                        """)
                        
                        # Clic Intelligent Qualité
                        quality_clicked = page.evaluate("""
                            () => {
                                let btn = document.querySelector('div[onclick*="haute"]') || document.querySelector('div[onclick*="moyenne"]');
                                if (btn) { btn.click(); return true; }
                                return false;
                            }
                        """)
                        
                        if quality_clicked:
                            print("✅ Qualité cliquée, attente popup...")
                            with page.expect_popup(timeout=15000) as popup_info:
                                pass
                            lien_final = recuperer_lien_vidzy(popup_info.value, titre_film)
                        else:
                            print("❌ Pas d'option de qualité trouvée")
                            
                    except Exception as e:
                        print(f"❌ Erreur Scénario B: {e}")

            browser.close()
            return lien_final
            
        except Exception as e:
            print(f"❌ ERREUR GÉNÉRALE : {e}")
            import traceback
            traceback.print_exc()
            browser.close()
            return None

# Test local
if __name__ == "__main__":
    HEADLESS_MODE = False
    print("Test Scraper...")
    # t = input("Titre : ")
    # print(run_scraper(t))
