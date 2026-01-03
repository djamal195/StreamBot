from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import os

# CONFIGURATION
# Mettre True pour le serveur (Render)
HEADLESS_MODE = True 

def normalize_title(title):
    nfd = unicodedata.normalize('NFD', title)
    title_no_accents = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    normalized = re.sub(r'[^\w\s]', ' ', title_no_accents)
    normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
    return normalized

def login_user(page, username, password):
    print("🔐 Connexion...")
    login_trigger = page.locator("#loginButtonContainer").first
    if login_trigger.is_visible():
        try:
            page.evaluate("document.querySelector('#loginButtonContainer').click()")
            time.sleep(2)
            page.fill("#login_name", username)
            time.sleep(0.5)
            page.fill("#login_password", password)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(5)
            try: page.wait_for_load_state("domcontentloaded", timeout=10000)
            except: pass
            return True
        except: return False
    print("ℹ️ Déjà connecté ou bouton absent")
    return True

def search_film(page, search_query, base_url):
    print(f"🔍 Recherche : {search_query}...")
    encoded_title = urllib.parse.quote(search_query)
    search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
    
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    except: return None
    time.sleep(2)
    
    found_url = page.evaluate("""
        (searchQuery) => {
            const container = document.getElementById('dle-content');
            if (!container) return null;
            const filmBlocks = Array.from(container.querySelectorAll('div.short.film'));
            
            for (const block of filmBlocks) {
                let titleEl = block.querySelector('a.short-poster-title') || block.querySelector('div.short-title') || block.querySelector('.short-title a');
                if (!titleEl) continue;
                
                const titleText = titleEl.innerText.trim();
                const normalize = (str) => str.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/[^\\w\\s]/g, ' ').replace(/\\s+/g, ' ').trim();
                
                if (normalize(titleText).includes(normalize(searchQuery))) {
                    const linkEl = block.querySelector('a.short-poster-title') || block.querySelector('a');
                    return linkEl ? linkEl.href : null;
                }
            }
            return null;
        }
    """, search_query)
    
    if found_url:
        print(f"✨ Trouvé : {found_url}")
        return found_url
    print("❌ Introuvable.")
    return None

def recuperer_lien_vidzy(page):
    """Extrait le lien du popup"""
    try:
        # On attend que la page du popup charge
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
        current_url = page.url
        print(f"   🌐 URL Popup : {current_url}")
        
        # VIDZY
        if "vidzy" in current_url.lower():
            return page.evaluate("document.querySelector('.container.file-details a.main-button')?.href")
        
        # FSVID / AUTRES
        try:
            page.wait_for_selector("#customDownloadSpan", timeout=8000)
            return page.evaluate("""
                () => {
                    const span = document.querySelector('#customDownloadSpan');
                    if (!span) return null;
                    const a = span.querySelector('a');
                    if (a && a.href) return a.href;
                    const onclick = span.getAttribute('onclick');
                    if (onclick) {
                        const match = onclick.match(/'(https?:\/\/[^']+)'/);
                        if (match) return match[1];
                    }
                    return null;
                }
            """)
        except: pass
        return None
    except: return None

# ==========================================
# 🔥 NOUVELLE LOGIQUE SÉRIES 🔥
# ==========================================
def extract_series_links(page, context):
    print("📺 Mode SÉRIE : Analyse des épisodes...")
    links = []
    
    # 1. On attend que la liste des épisodes soit visible
    try:
        # Sélecteur basé sur ta capture d'écran
        page.wait_for_selector(".ep-download", timeout=10000)
    except:
        print("❌ Liste épisodes introuvable (pas de .ep-download)")
        return []

    # 2. On récupère tous les boutons de téléchargement d'épisodes
    # L'ordre est important (Episode 1, 2, 3...)
    buttons = page.locator(".ep-download").all()
    count = len(buttons)
    print(f"📋 {count} épisodes détectés.")

    # ⚠️ LIMITATION POUR EVITER TIMEOUT SERVEUR
    # On prend les 10 premiers max pour commencer
    LIMIT_EPISODES = 10 
    
    for i, btn in enumerate(buttons):
        if i >= LIMIT_EPISODES: break
        
        ep_num = i + 1
        print(f"   ⬇️ Traitement Épisode {ep_num}...")
        
        try:
            # On prépare l'interception du popup
            with context.expect_page(timeout=15000) as popup_info:
                # Clic JS sur le bouton de l'épisode
                # On utilise dispatchEvent pour éviter les pubs overlays
                btn.evaluate("el => el.click()")
            
            # On récupère la nouvelle page (Popup)
            popup = popup_info.value
            
            # On extrait le lien
            lien = recuperer_lien_vidzy(popup)
            
            # On ferme le popup pour ne pas surcharger la mémoire
            popup.close()
            
            if lien:
                print(f"      ✅ Lien : {lien}")
                links.append({"episode": ep_num, "lien": lien})
            else:
                print("      ❌ Lien vide")
                links.append({"episode": ep_num, "lien": None})
                
            # Petite pause pour ne pas se faire bannir
            time.sleep(1)
            
        except Exception as e:
            print(f"      ⚠️ Erreur clic épisode {ep_num}: {e}")
            links.append({"episode": ep_num, "lien": None})

    return links

# ==========================================
# MAIN RUNNER
# ==========================================
def run_scraper(titre_film, is_serie=False, all_episodes=False):
    base_url = "https://french-stream.one/"
    
    with sync_playwright() as p:
        print("🚀 Scraper démarré...")
        browser = p.chromium.launch(
            headless=HEADLESS_MODE,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        
        try:
            page.goto(base_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            login_user(page, "Jekle19", "otf192009")
            
            film_url = search_film(page, titre_film, base_url)
            if not film_url:
                browser.close(); return None
            
            page.goto(film_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            # --- DIVERGENCE FILM / SÉRIE ---
            result = None
            
            if is_serie:
                # >>> MODE SÉRIE : On boucle sur les épisodes <<<
                result = extract_series_links(page, context)
            else:
                # >>> MODE FILM : Clic unique <<<
                if not page.locator("#downloadBtn").is_visible():
                    print("❌ Bouton introuvable"); browser.close(); return None

                print("🖱️ Clic Film...")
                
                # Gestion Popup vs Menu (Ta logique existante)
                popup_bucket = []
                page.context.on("page", lambda p: popup_bucket.append(p))
                
                page.evaluate("document.getElementById('downloadBtn').click()")
                time.sleep(3)
                
                if len(popup_bucket) > 0:
                    result = recuperer_lien_vidzy(popup_bucket[0])
                else:
                    try:
                        page.wait_for_selector("#downloadOptions", state="visible", timeout=3000)
                        page.evaluate("""
                            () => {
                                let btn = document.querySelector('div[onclick*="haute"]') || document.querySelector('div[onclick*="moyenne"]');
                                if (btn) btn.click();
                            }
                        """)
                        with page.expect_popup(timeout=15000) as popup_info:
                            pass
                        result = recuperer_lien_vidzy(popup_info.value)
                    except: pass

            browser.close()
            return result

        except Exception as e:
            print(f"❌ Erreur générale : {e}")
            browser.close()
            return None
