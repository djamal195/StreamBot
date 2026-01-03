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
    # --- STRATÉGIE DE RECHERCHE ---
    if target_season:
        # On essaie le format EXACT du site en premier
        queries_to_try = [
            f"{search_query} - Saison {target_season}", # Format officiel (Stranger Things - Saison 4)
            f"{search_query} Saison {target_season}",   # Format sans tiret
            search_query                                # Titre seul (Fallback)
        ]
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
        
        # --- ANALYSE DES RÉSULTATS ---
        found_href = page.evaluate("""
            ([searchQuery, seasonNum, originalTitle]) => {
                const container = document.getElementById('dle-content');
                if (!container) return { status: "NO_CONTAINER" };
                
                const filmBlocks = Array.from(container.querySelectorAll('div.short.film'));
                if (filmBlocks.length === 0) return { status: "NO_BLOCKS" };

                // Nettoyage agressif : remplace tout ce qui n'est pas lettre/chiffre par un espace
                // Donc "Stranger Things - Saison 4" devient "stranger things   saison 4"
                const normalize = (str) => str.toLowerCase()
                                              .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
                                              .replace(/[^a-z0-9]/g, ' ') 
                                              .replace(/\\s+/g, ' ')
                                              .trim();
                
                const targetBase = normalize(originalTitle);
                const allTitlesSeen = [];

                for (const block of filmBlocks) {
                    let titleEl = block.querySelector('div.short-title') || block.querySelector('.short-title a');
                    if (!titleEl) continue;
                    
                    let rawTitle = titleEl.innerText;
                    let cleanTitle = normalize(rawTitle);
                    allTitlesSeen.push(rawTitle);

                    let isMatch = false;

                    // --- LOGIQUE SÉRIE ---
                    if (seasonNum) {
                        // 1. On vérifie si le titre de base est présent
                        if (cleanTitle.includes(targetBase)) {
                            
                            // 2. On vérifie la saison avec une Regex flexible
                            // Cherche: "saison 4", "s04", "s4" (le tiret a été remplacé par espace via normalize)
                            const regexSaison = new RegExp(`(saison|s)\\s*0?${seasonNum}(?!\\d)`, 'i');
                            
                            if (regexSaison.test(cleanTitle)) {
                                isMatch = true;
                            }
                        }
                    } 
                    // --- LOGIQUE FILM ---
                    else {
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
        
        # Si pas trouvé, on boucle pour essayer la requête suivante
        log(f"⚠️ Pas trouvé avec '{query}'.")

    log("❌ Introuvable après tous les essais.")
    # On affiche ce qu'il a vu lors de la dernière tentative pour comprendre
    if found_href['status'] == "NOT_FOUND":
        log(f"   Titres vus : {found_href.get('titles', [])[:5]}...")
        
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
    log("📺 Mode SÉRIE : Extraction...")
    links = []
    
    try:
        page.wait_for_selector(".ep-download", timeout=10000)
    except:
        log("❌ Liste épisodes introuvable")
        return []

    buttons = page.locator(".ep-download").all()
    count = len(buttons)
    log(f"📋 {count} épisodes trouvés.")

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
                log(f"   ⚠️ Ep {ep_num} vide")
                links.append({"episode": ep_num, "lien": None})
            
            time.sleep(0.5)
            
        except Exception as e:
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
                result = extract_series_links(page, context)
                if not result:
                    log("⚠️ Aucun lien d'épisode récupéré.")
            else:
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
