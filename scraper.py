from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import os
import sys

# CONFIGURATION
# True pour le serveur, False pour test PC
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

def search_film(page, search_query, target_season, base_url, target_poster_url=None):
    # Extraction de l'ID de l'image (ex: abc123.jpg) depuis l'URL TMDB
    target_poster_id = target_poster_url.split('/')[-1] if target_poster_url else None
    if target_poster_id:
        log(f"🖼️ Comparaison par poster activée (ID: {target_poster_id})")

    # Stratégie de recherche
    if target_season:
        queries_to_try = [
            f"{search_query} - Saison {target_season}",
            f"{search_query} Saison {target_season}",
            search_query
        ]
    else:
        queries_to_try = [search_query]

    for query in queries_to_try:
        log(f"🔍 Essai recherche : '{query}'")
        
        try:
            # 1. On s'assure d'être sur la page avec la barre de recherche
            if not page.locator("#story").first.is_visible():
                page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
            
            # 2. On cible le premier champ #story
            search_input = page.locator("#story").first
            search_input.click()
            search_input.fill("") 
            search_input.fill(query)
            
            # On simule l'appui sur Entrée
            page.keyboard.press("Enter")
            
            # 3. Attente du container présent (attached)
            container_locator = page.locator("#search-results-content").first
            container_locator.wait_for(state="attached", timeout=10000)
            
            # On laisse 2 secondes pour que l'AJAX remplisse le container
            time.sleep(2)
            
        except Exception as e:
            log(f"⚠️ Erreur lors de la manipulation de la recherche : {e}")
            continue
        
        # --- ANALYSE DES RÉSULTATS (AVEC POSTER + TITRE) ---
        found_href = page.evaluate("""
            ([searchQuery, seasonNum, originalTitle, targetPosterId]) => {
                const containers = Array.from(document.querySelectorAll('#search-results-content'));
                const container = containers.find(c => c.querySelectorAll('.search-item').length > 0) || containers[0];
                
                if (!container) return { status: "NO_CONTAINER" };
                
                const items = Array.from(container.querySelectorAll('.search-item'));
                if (items.length === 0) return { status: "NO_BLOCKS" };

                const normalize = (str) => str.toLowerCase()
                                              .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
                                              .replace(/[^a-z0-9\\s]/g, ' ') 
                                              .replace(/\\s+/g, ' ')
                                              .trim();
                
                const targetBase = normalize(originalTitle);

                for (const item of items) {
                    const titleEl = item.querySelector('.search-title');
                    if (!titleEl) continue;
                    
                    const rawTitle = titleEl.innerText;
                    const cleanTitle = normalize(rawTitle);

                    // --- RÉCUPÉRATION DU POSTER DU RÉSULTAT ---
                    const imgEl = item.querySelector('.search-poster img');
                    const currentPosterUrl = imgEl ? imgEl.src : "";
                    const currentPosterId = currentPosterUrl.split('/').pop();

                    let isMatch = false;

                    // PRIORITÉ 1 : Comparaison par Poster ID (si disponible)
                    if (targetPosterId && currentPosterId && targetPosterId !== "N/A") {
                        if (currentPosterId === targetPosterId) {
                            isMatch = true;
                        }
                    }

                    // PRIORITÉ 2 : Fallback sur le Titre (si pas de match poster ou pas de poster fourni)
                    if (!isMatch) {
                        if (seasonNum) {
                            if (cleanTitle.includes(targetBase)) {
                                const regexSaison = new RegExp(`(saison|s| )\\\\s*0?${seasonNum}(?!\\\\d)`, 'i');
                                if (regexSaison.test(cleanTitle)) isMatch = true;
                            }
                        } else {
                            if (cleanTitle.includes(targetBase) && !cleanTitle.includes("saison")) {
                                isMatch = true;
                            }
                        }
                    }

                    if (isMatch) {
                        const onclickVal = item.getAttribute('onclick') || "";
                        const match = onclickVal.match(/location\\.href='([^']+)'/);
                        if (match && match[1]) {
                            return { status: "FOUND", path: match[1], title: rawTitle };
                        }
                    }
                }
                return { status: "NOT_FOUND" };
            }
        """, [query, target_season, search_query, target_poster_id]) 
        
        if found_href['status'] == "FOUND":
            full_url = base_url.rstrip('/') + found_href['path']
            log(f"✨ Match confirmé : {found_href['title']}")
            return full_url
        
        log(f"⚠️ Pas trouvé avec '{query}' (Container vide ou pas de match).")

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
    try:
        # On vérifie si l'ID existe sur la page
        is_visible = page.locator(f"#{container_id}").count() > 0
        if not is_visible:
            log(f"ℹ️ Zone {lang_name} introuvable sur cette page.")
            return []
    except:
        return []

    # On cible uniquement les boutons DANS ce conteneur
    # Le sélecteur est : #id_du_conteneur .ep-download
    buttons = page.locator(f"#{container_id} .ep-download").all()
    count = len(buttons)
    log(f"📋 {count} épisodes trouvés pour {lang_name}.")

    if count == 0:
        return []

    # BOUCLE ILLIMITÉE (On prend tout)
    for i, btn in enumerate(buttons):
        ep_num = i + 1
        
        # On force un petit scroll pour charger l'élément si besoin
        try: btn.scroll_into_view_if_needed()
        except: pass

        try:
            # Préparation popup
            with context.expect_page(timeout=10000) as popup_info:
                # Clic JS sur le bouton
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
            
            # Pause minime pour ne pas DDOS le site
            time.sleep(0.5)
            
        except Exception as e:
            log(f"   ❌ Erreur {lang_name} Ep {ep_num}: {e}")
            links.append({"episode": ep_num, "lien": None})

    return links

def run_scraper(titre_film, season_number=None, is_serie=False, all_episodes=False, , tmdb_poster_url=None):
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
            film_url = search_film(page, titre_film, season_number, base_url, tmdb_poster_url)
            
            if not film_url:
                log("🛑 Arrêt : Page introuvable.")
                browser.close(); return None
            
            log(f"🌐 Navigation page : {film_url}")
            page.goto(film_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            result = None
            
            if is_serie:
                # --- LOGIQUE SÉRIES (VF + VOSTFR) ---
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
                
                count_vf = len(vf_links)
                count_vost = len(vostfr_links)
                log(f"✅ Terminé : {count_vf} VF et {count_vost} VOSTFR récupérés.")

            else:
                # --- LOGIQUE FILM ---
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
