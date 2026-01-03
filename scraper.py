from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import os
import sys

# CONFIGURATION
HEADLESS_MODE = True 

def log(msg):
    print(msg, flush=True)

def normalize_title(title):
    nfd = unicodedata.normalize('NFD', title)
    title_no_accents = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    normalized = re.sub(r'[^\w\s]', ' ', title_no_accents)
    normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
    return normalized

def login_user(page, username, password):
    log("🔐 Connexion...")
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
    log("ℹ️ Déjà connecté ou bouton absent")
    return True

def search_film(page, search_query, target_season, base_url):
    log(f"🔍 Recherche de : {search_query}...")
    encoded_title = urllib.parse.quote(search_query)
    search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
    
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    except: return None
    time.sleep(2)
    
    log(f"🎯 CIBLE : '{search_query}' (Saison: {target_season if target_season else 'Film'})")

    # --- LOGIQUE FLEXIBLE (REGEX) ---
    found_url = page.evaluate("""
        ([searchQuery, seasonNum]) => {
            const container = document.getElementById('dle-content');
            if (!container) return null;
            const filmBlocks = Array.from(container.querySelectorAll('div.short.film'));
            
            // Fonction de nettoyage
            const normalize = (str) => str.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/[^\\w\\s]/g, ' ').replace(/\\s+/g, ' ').trim();
            const targetTitle = normalize(searchQuery);

            for (const block of filmBlocks) {
                let titleEl = block.querySelector('div.short-title') || block.querySelector('.short-title a');
                if (!titleEl) continue;
                
                let rawTitle = titleEl.innerText; // Titre avec majuscules et accents
                let cleanTitle = normalize(rawTitle);
                
                // 1. VÉRIFICATION DU TITRE PRINCIPAL
                if (!cleanTitle.includes(targetTitle)) continue;

                // 2. VÉRIFICATION SÉRIE OU FILM
                if (seasonNum) {
                    // Pour les séries, on utilise une REGEX flexible
                    // Cherche: "Saison X", "Saison 0X", "S X", "S0X", "Season X"
                    // Le [^0-9]* permet n'importe quel caractère (tiret, deux points, espace) entre le titre et la saison
                    const regex = new RegExp(`(saison|season|s)[^0-9]*0?${seasonNum}(?!\\d)`, 'i');
                    
                    if (regex.test(rawTitle)) {
                        const linkEl = block.querySelector('.short-poster') || block.querySelector('.short-title a');
                        if (linkEl && linkEl.href && !linkEl.href.includes('xfsearch')) return linkEl.href;
                    }
                } else {
                    // Pour les films (Pas de saison)
                    // On vérifie que ce n'est PAS une saison (pour ne pas cliquer sur une série par erreur)
                    if (!rawTitle.toLowerCase().includes('saison')) {
                        const linkEl = block.querySelector('.short-poster') || block.querySelector('.short-title a');
                        if (linkEl && linkEl.href && !linkEl.href.includes('xfsearch')) return linkEl.href;
                    }
                }
            }
            return null;
        }
    """, [search_query, target_season])
    
    if found_url:
        log(f"✨ Trouvé : {found_url}")
        return found_url
    log("❌ Introuvable (Aucun match flexible).")
    return None

def recuperer_lien_vidzy(page):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(2)
        current_url = page.url
        
        if "vidzy" in current_url.lower():
            return page.evaluate("document.querySelector('.container.file-details a.main-button')?.href")
        
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

def extract_series_links(page, context):
    log("📺 Mode SÉRIE : Analyse des épisodes...")
    links = []
    
    try:
        page.wait_for_selector(".ep-download", timeout=10000)
    except:
        log("❌ Liste épisodes introuvable")
        return []

    buttons = page.locator(".ep-download").all()
    count = len(buttons)
    log(f"📋 {count} épisodes détectés.")

    LIMIT_EPISODES = 10 
    
    for i, btn in enumerate(buttons):
        if i >= LIMIT_EPISODES: break
        
        ep_num = i + 1
        log(f"   ⬇️ Traitement Épisode {ep_num}...")
        
        try:
            with context.expect_page(timeout=15000) as popup_info:
                btn.evaluate("el => el.click()")
            
            popup = popup_info.value
            lien = recuperer_lien_vidzy(popup)
            popup.close()
            
            if lien:
                log(f"      ✅ Ep {ep_num} OK")
                links.append({"episode": ep_num, "lien": lien})
            else:
                links.append({"episode": ep_num, "lien": None})
            time.sleep(1) 
        except Exception as e:
            links.append({"episode": ep_num, "lien": None})

    return links

def run_scraper(titre_film, season_number=None, is_serie=False, all_episodes=False):
    base_url = "https://french-stream.one/"
    
    with sync_playwright() as p:
        log("🚀 Scraper démarré...")
        browser = p.chromium.launch(
            headless=HEADLESS_MODE,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        
        try:
            log(f"🌐 Navigation...")
            page.goto(base_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            login_user(page, "Jekle19", "otf192009")
            
            # Recherche avec la saison
            film_url = search_film(page, titre_film, season_number, base_url)
            if not film_url:
                browser.close(); return None
            
            page.goto(film_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            result = None
            
            if is_serie:
                result = extract_series_links(page, context)
            else:
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
