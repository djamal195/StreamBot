from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import os

# CONFIGURATION
# Mettre True pour le serveur (Render)
HEADLESS_MODE = True 

# Identifiants
LOGIN_USER = "Jekle19"
LOGIN_PASS = "otf192009"

def log(msg):
    """Fonction pour forcer l'affichage des logs sur Render"""
    print(msg, flush=True)

def normalize_title(title):
    nfd = unicodedata.normalize('NFD', title)
    title_no_accents = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    normalized = re.sub(r'[^\w\s]', ' ', title_no_accents)
    normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
    return normalized

def login_user(page):
    log("🔐 Connexion...")
    login_trigger = page.locator("#loginButtonContainer").first
    if login_trigger.is_visible():
        try:
            page.evaluate("document.querySelector('#loginButtonContainer').click()")
            time.sleep(2)
            page.fill("#login_name", LOGIN_USER)
            time.sleep(0.5)
            page.fill("#login_password", LOGIN_PASS)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(5)
            try: page.wait_for_load_state("domcontentloaded", timeout=10000)
            except: pass
            return True
        except Exception as e:
            log(f"⚠️ Erreur Login (non critique) : {e}")
            return False
    log("ℹ️ Déjà connecté ou bouton absent")
    return True

def search_film(page, search_query, base_url):
    log(f"🔍 Recherche de : {search_query}...")
    encoded_title = urllib.parse.quote(search_query)
    search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
    
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    except: return None
    time.sleep(2)
    
    # Logique stricte : On cherche le titre exact
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
        log(f"✨ Trouvé : {found_url}")
        return found_url
    
    log("❌ Introuvable dans la recherche.")
    return None

def recuperer_lien_vidzy(page):
    """Extrait le lien du popup"""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(2)
        current_url = page.url
        
        # VIDZY
        if "vidzy" in current_url.lower():
            return page.evaluate("document.querySelector('.container.file-details a.main-button')?.href")
        
        # FSVID / AUTRES
        try:
            page.wait_for_selector("#customDownloadSpan", timeout=10000)
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
# 🔥 LOGIQUE SÉRIES (AMÉLIORÉE) 🔥
# ==========================================
def extract_series_links(page, context):
    log("📺 Mode SÉRIE : Analyse des épisodes...")
    links = []
    
    # 1. On attend que la liste des épisodes soit visible
    try:
        page.wait_for_selector(".ep-download", timeout=10000)
    except:
        log("❌ Liste épisodes introuvable (Selecteur .ep-download échoué)")
        return []

    # 2. On récupère les handles des boutons
    buttons = page.locator(".ep-download").all()
    count = len(buttons)
    log(f"📋 {count} épisodes détectés.")

    LIMIT_EPISODES = 10 
    
    for i, btn in enumerate(buttons):
        if i >= LIMIT_EPISODES: break
        
        ep_num = i + 1
        log(f"   ⬇️ Traitement Épisode {ep_num}...")
        
        try:
            # On prépare l'interception du popup
            with context.expect_page(timeout=15000) as popup_info:
                # Clic JS sur le bouton de l'épisode (plus fiable que .click())
                btn.evaluate("el => el.click()")
            
            popup = popup_info.value
            lien = recuperer_lien_vidzy(popup)
            popup.close()
            
            if lien:
                log(f"      ✅ Ep {ep_num} OK")
                links.append({"episode": ep_num, "lien": lien})
            else:
                log(f"      ❌ Ep {ep_num} vide")
                links.append({"episode": ep_num, "lien": None})
                
            time.sleep(1)
            
        except Exception as e:
            log(f"      ⚠️ Erreur technique Ep {ep_num}: {e}")
            links.append({"episode": ep_num, "lien": None})

    return links

# ==========================================
# MAIN RUNNER
# ==========================================
def run_scraper(titre_film, is_serie=False, all_episodes=False):
    base_url = "https://french-stream.one/"
    
    with sync_playwright() as p:
        log("🚀 Scraper démarré...")
        
        # --- CONFIGURATION FURTIVE (IMPORTANT) ---
        browser = p.chromium.launch(
            headless=HEADLESS_MODE,
            args=[
                "--disable-blink-features=AutomationControlled", 
                "--no-sandbox", 
                "--disable-dev-shm-usage"
            ]
        )
        
        # On définit un User-Agent de vrai PC pour tromper le site
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        page = context.new_page()
        
        try:
            log(f"🌐 Navigation...")
            page.goto(base_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            login_user(page)
            
            film_url = search_film(page, titre_film, base_url)
            if not film_url:
                browser.close(); return None
            
            page.goto(film_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            result = None
            
            if is_serie:
                # Mode Série
                result = extract_series_links(page, context)
            else:
                # Mode Film
                if not page.locator("#downloadBtn").is_visible():
                    log("❌ Bouton introuvable"); browser.close(); return None

                log("🖱️ Clic Film...")
                
                popup_bucket = []
                page.context.on("page", lambda p: popup_bucket.append(p))
                
                page.evaluate("document.getElementById('downloadBtn').click()")
                time.sleep(3)
                
                if len(popup_bucket) > 0:
                    log("   -> Popup direct")
                    result = recuperer_lien_vidzy(popup_bucket[0])
                else:
                    log("   -> Menu Options")
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
            log(f"❌ Erreur générale : {e}")
            browser.close()
            return None
