from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import os
import sys

# CONFIGURATION
# True pour le serveur, False pour tester sur PC
HEADLESS_MODE = True 

def log(msg):
    print(f"[SCRAPER_LOG] {msg}", flush=True)

def normalize_title(title):
    nfd = unicodedata.normalize('NFD', title)
    title_no_accents = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    normalized = re.sub(r'[^\w\s]', ' ', title_no_accents)
    normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
    return normalized

def login_user(page, username, password):
    log("🔐 Tentative de connexion...")
    if page.locator("#loginButtonContainer").is_visible():
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
            log("✅ Login envoyé.")
            return True
        except Exception as e:
            log(f"⚠️ Erreur Login : {e}")
            return False
    log("ℹ️ Déjà connecté ou bouton absent")
    return True

def search_film(page, search_query, target_season, base_url):
    if target_season:
        queries_to_try = [f"{search_query} Saison {target_season}", search_query]
    else:
        queries_to_try = [search_query]

    for query in queries_to_try:
        log(f"🔍 Essai recherche : '{query}'")
        encoded_title = urllib.parse.quote(query)
        search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
        
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        except:
            log("❌ Timeout chargement page recherche.")
            continue
        
        time.sleep(2)
        
        found_href = page.evaluate("""
            ([searchQuery, seasonNum, originalTitle]) => {
                const container = document.getElementById('dle-content');
                if (!container) return { status: "NO_CONTAINER" };
                
                const filmBlocks = Array.from(container.querySelectorAll('div.short.film'));
                if (filmBlocks.length === 0) return { status: "NO_BLOCKS" };

                const normalize = (str) => str.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/[^a-z0-9\\s]/g, ' ').replace(/\\s+/g, ' ').trim();
                
                const targetFull = normalize(searchQuery); 
                const targetBase = normalize(originalTitle);
                const allTitlesSeen = [];

                for (const block of filmBlocks) {
                    let titleEl = block.querySelector('div.short-title') || block.querySelector('.short-title a');
                    if (!titleEl) continue;
                    
                    let rawTitle = titleEl.innerText;
                    let cleanTitle = normalize(rawTitle);
                    allTitlesSeen.push(rawTitle);

                    let isMatch = false;

                    if (seasonNum) {
                        if (cleanTitle.includes(targetBase)) {
                            const regexSaison = new RegExp(`(saison|s| )\\s*0?${seasonNum}(?!\\d)`, 'i');
                            if (regexSaison.test(cleanTitle)) isMatch = true;
                        }
                        if (cleanTitle.includes(normalize(targetBase + " saison " + seasonNum))) isMatch = true;
                    } else {
                        if (cleanTitle === targetBase || cleanTitle.includes(targetBase)) {
                            if (!cleanTitle.includes("saison")) isMatch = true;
                        }
                    }

                    if (isMatch) {
                        const linkEl = block.querySelector('.short-poster') || block.querySelector('.short-title a');
                        if (linkEl && linkEl.href && !linkEl.href.includes('xfsearch')) {
                            return { status: "FOUND", url: linkEl.href, title: rawTitle };
                        }
                    }
                }
                return { status: "NOT_FOUND", titles: allTitlesSeen };
            }
        """, [query, target_season, search_query])
        
        if found_href['status'] == "FOUND":
            log(f"✨ Match confirmé : {found_href['title']}")
            return found_href['url']
        
        log(f"⚠️ Pas trouvé avec '{query}'...")

    log("❌ Introuvable après tous les essais.")
    return None

def recuperer_lien_vidzy(page):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
        
        if "vidzy" in page.url:
            return page.evaluate("document.querySelector('.container.file-details a.main-button')?.href")
        
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

# --- NOUVELLE FONCTION D'EXTRACTION PAR ZONE ---
def extract_episodes_from_container(page, context, container_id, lang_name):
    """Extrait les épisodes d'un conteneur spécifique (VF ou VOSTFR)"""
    log(f"📺 Analyse de la zone {lang_name} (#{container_id})...")
    links = []
    
    # Vérifier si le conteneur existe
    is_present = page.locator(f"#{container_id}").is_visible()
    if not is_present:
        log(f"⚠️ Zone {lang_name} introuvable ou vide.")
        return []

    # On cible uniquement les boutons DANS ce conteneur
    # On utilise le sélecteur composé : #ID .ep-download
    buttons = page.locator(f"#{container_id} .ep-download").all()
    count = len(buttons)
    log(f"📋 {count} épisodes trouvés pour {lang_name}.")

    # BOUCLE ILLIMITÉE (Attention aux timeouts Render !)
    for i, btn in enumerate(buttons):
        ep_num = i + 1
        
        # On force un petit scroll pour charger l'élément si besoin
        try: btn.scroll_into_view_if_needed()
        except: pass

        try:
            # Préparation popup
            with context.expect_page(timeout=10000) as popup_info:
                btn.evaluate("el => el.click()")
            
            popup = popup_info.value
            lien = recuperer_lien_vidzy(popup)
            popup.close()
            
            if lien:
                log(f"   ✅ {lang_name} Ep {ep_num} OK")
                links.append({"episode": ep_num, "lien": lien})
            else:
                log(f"   ⚠️ {lang_name} Ep {ep_num} Vide")
                links.append({"episode": ep_num, "lien": None})
            
            # Pause minime pour aller vite mais pas trop
            time.sleep(0.5)
            
        except Exception as e:
            log(f"   ❌ Erreur {lang_name} Ep {ep_num}: {e}")
            links.append({"episode": ep_num, "lien": None})

    return links

def run_scraper(titre_film, season_number=None, is_serie=False, all_episodes=False):
    base_url = "https://french-stream.one/"
    
    with sync_playwright() as p:
        log(f"🚀 Scraper Lancé (Série: {is_serie}, Saison: {season_number})")
        browser = p.chromium.launch(
            headless=HEADLESS_MODE,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        
        try:
            log("🌐 Navigation...")
            page.goto(base_url, timeout=60000)
            
            login_user(page, "Jekle19", "otf192009")
            
            # Recherche
            film_url = search_film(page, titre_film, season_number, base_url)
            if not film_url:
                log("🛑 Arrêt : Page introuvable.")
                browser.close(); return None
            
            log(f"🌐 Navigation page : {film_url}")
            page.goto(film_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            result = None
            
            if is_serie:
                # --- NOUVELLE LOGIQUE SÉRIES (VF + VOSTFR) ---
                log("🔄 Démarrage extraction Multi-Langue...")
                
                # 1. Extraction VF
                vf_links = extract_episodes_from_container(page, context, "vf-episodes", "VF")
                
                # 2. Extraction VOSTFR
                vostfr_links = extract_episodes_from_container(page, context, "vostfr-episodes", "VOSTFR")
                
                # On retourne un objet structuré
                result = {
                    "vf": vf_links,
                    "vostfr": vostfr_links
                }
                
                # Petit check
                count_vf = len(vf_links)
                count_vost = len(vostfr_links)
                log(f"✅ Terminé : {count_vf} VF et {count_vost} VOSTFR récupérés.")

            else:
                # --- LOGIQUE FILM (Inchangée) ---
                if not page.locator("#downloadBtn").is_visible():
                    log("❌ Bouton introuvable"); browser.close(); return None

                popup_bucket = []
                page.context.on("page", lambda p: popup_bucket.append(p))
                page.evaluate("document.getElementById('downloadBtn').click()")
                time.sleep(3)
                
                if len(popup_bucket) > 0:
                    result = recuperer_lien_vidzy(popup_bucket[0])
                else:
                    try:
                        page.wait_for_selector("#downloadOptions", state="visible", timeout=3000)
                        page.evaluate("document.querySelector(\"div[onclick*='moyenne']\").click()")
                        with page.expect_popup(timeout=15000) as popup_info:
                            pass
                        result = recuperer_lien_vidzy(popup_info.value)
                    except: pass

            browser.close()
            return result

        except Exception as e:
            log(f"❌ ERREUR FATALE : {e}")
            browser.close()
            return None
