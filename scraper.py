from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import os
import sys

# CONFIGURATION
HEADLESS_MODE = True 

# Fonction de log forcé (pour voir sur Render)
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
    log(f"🔍 Recherche URL pour : {search_query} (Saison: {target_season})")
    
    # Nettoyage du titre pour l'URL
    encoded_title = urllib.parse.quote(search_query)
    search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
    
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    except:
        log("❌ Timeout chargement page recherche.")
        return None
    
    time.sleep(2)
    
    # --- LOGIQUE DE SÉLECTION DÉTAILLÉE ---
    log("🧐 Analyse des résultats de recherche...")
    
    # On récupère les infos depuis le navigateur
    found_href = page.evaluate("""
        ([searchQuery, seasonNum]) => {
            const container = document.getElementById('dle-content');
            if (!container) return "NO_CONTAINER";
            
            const filmBlocks = Array.from(container.querySelectorAll('div.short.film'));
            if (filmBlocks.length === 0) return "NO_BLOCKS";

            const normalize = (str) => str.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/[^\\w\\s]/g, ' ').replace(/\\s+/g, ' ').trim();
            const targetTitle = normalize(searchQuery);
            
            // Logique de recherche
            for (const block of filmBlocks) {
                let titleEl = block.querySelector('div.short-title') || block.querySelector('.short-title a');
                if (!titleEl) continue;
                
                let rawTitle = titleEl.innerText;
                let cleanTitle = normalize(rawTitle);
                
                // Pour une SÉRIE, on cherche "Titre" ET "Saison X"
                if (seasonNum) {
                    // On vérifie si le titre correspond
                    if (cleanTitle.includes(targetTitle)) {
                        // On vérifie si la saison correspond
                        // Regex pour trouver "Saison 4", "S4", "Season 4"
                        const seasonRegex = new RegExp(`(saison|season|s)[^0-9]*0?${seasonNum}(?!\\d)`, 'i');
                        
                        if (seasonRegex.test(rawTitle)) {
                            const linkEl = block.querySelector('.short-poster') || block.querySelector('.short-title a');
                            if (linkEl && linkEl.href) return linkEl.href;
                        }
                    }
                } 
                // Pour un FILM
                else {
                    if (cleanTitle === targetTitle || cleanTitle.includes(targetTitle)) {
                        const linkEl = block.querySelector('.short-poster') || block.querySelector('.short-title a');
                        if (linkEl && linkEl.href) return linkEl.href;
                    }
                }
            }
            return null;
        }
    """, [search_query, target_season])
    
    if found_href == "NO_CONTAINER":
        log("❌ Erreur : Conteneur #dle-content introuvable.")
        return None
    if found_href == "NO_BLOCKS":
        log("❌ Erreur : Aucun bloc film trouvé dans la page.")
        return None
    if found_href:
        log(f"✨ Page Série trouvée : {found_href}")
        return found_href
    
    log(f"❌ Aucun titre ne correspond à '{search_query}' Saison '{target_season}'")
    
    # DEBUG : Affiche les titres trouvés pour comprendre l'erreur
    titres_visibles = page.locator(".short-title").all_inner_texts()
    log(f"   -> Titres vus sur la page : {titres_visibles[:5]}")
    
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

def extract_series_links(page, context):
    log("📺 Début extraction des épisodes...")
    links = []
    
    # 1. Vérification présence liste
    try:
        page.wait_for_selector(".ep-download", timeout=10000)
    except:
        log("❌ CRITIQUE : Aucun bouton '.ep-download' trouvé sur la page.")
        # Debug: Prendre une capture si ça échoue ici
        # page.screenshot(path="debug_no_eps.png")
        return []

    # 2. Comptage
    buttons = page.locator(".ep-download").all()
    count = len(buttons)
    log(f"📋 {count} épisodes détectés.")

    LIMIT_EPISODES = 10 
    
    for i, btn in enumerate(buttons):
        if i >= LIMIT_EPISODES: break
        ep_num = i + 1
        
        try:
            with context.expect_page(timeout=10000) as popup_info:
                btn.evaluate("el => el.click()")
            
            popup = popup_info.value
            lien = recuperer_lien_vidzy(popup)
            popup.close()
            
            if lien:
                log(f"   ✅ Ep {ep_num} OK")
                links.append({"episode": ep_num, "lien": lien})
            else:
                log(f"   ⚠️ Ep {ep_num} lien vide")
                links.append({"episode": ep_num, "lien": None})
            
            time.sleep(0.5)
            
        except Exception as e:
            log(f"   ❌ Erreur Ep {ep_num}: {e}")
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
            
            # Recherche avec gestion Saison
            film_url = search_film(page, titre_film, season_number, base_url)
            
            if not film_url:
                log("🛑 Arrêt : Page introuvable.")
                browser.close(); return None
            
            # Navigation vers la page Série/Film
            log(f"🌐 Navigation vers la page : {film_url}")
            page.goto(film_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            result = None
            
            if is_serie:
                # Extraction des épisodes
                result = extract_series_links(page, context)
                if not result:
                    log("⚠️ La liste des épisodes est vide après extraction.")
            else:
                # Mode Film (inchangé)
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
