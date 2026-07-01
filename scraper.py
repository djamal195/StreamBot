from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import os

# CONFIGURATION
HEADLESS_MODE = True

def log(msg):
    print(f"[SCRAPER_LOG] {msg}", flush=True)

def login_user(page, username, password):
    log("🔐 Tentative de connexion...")
    try:
        trigger = page.locator(".topnav-account-trigger")
        trigger.wait_for(state="attached", timeout=10000)
        trigger.evaluate("el => el.click()")
        time.sleep(2)

        login_link = page.locator("a.topnav-account-item[onclick*='toggleLoginModal']")
        if login_link.count() > 0:
            login_link.evaluate("el => el.click()")
            log("🔓 Modal de connexion ouvert.")

            user_input = page.locator("#loginModal #login_name").first
            pass_input = page.locator("#loginModal #login_password").first
            
            user_input.wait_for(state="attached", timeout=5000)
            user_input.fill(username)
            pass_input.fill(password)

            page.keyboard.press("Enter")
            time.sleep(5)
            log("✅ Connexion envoyée.")
            return True
        return False
    except Exception as e:
        log(f"⚠️ Erreur Login : {e}")
        return False

def search_film(page, search_query, target_season, base_url, tmdb_poster_url=None):
    if target_season:
        queries_to_try = [f"{search_query} Saison {target_season}", search_query]
    else:
        queries_to_try = [search_query]

    for query in queries_to_try:
        log(f"🔍 Recherche : '{query}'")
        
        try:
            if not page.locator("#story").first.is_visible():
                page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
            
            search_input = page.locator("#story").first
            search_input.fill(query)
            page.keyboard.press("Enter")
            
            # Attente plus robuste
            time.sleep(4)  # Attente initiale
            
            # Attendre que le container apparaisse ou qu'il y ait des résultats
            try:
                page.wait_for_selector("#search-results-content", timeout=12000)
            except:
                log("⚠️ Premier container non trouvé, on attend plus longtemps...")
                time.sleep(5)
            
            # Vérification debug
            content_count = page.locator("#search-results-content").count()
            log(f"🔍 {content_count} container(s) #search-results-content détectés")
            
            if content_count == 0:
                log("❌ Aucun résultat visible")
                continue
                
        except Exception as e:
            log(f"⚠️ Erreur pendant la recherche : {e}")
            continue

                # === CAPTURE LÉGÈRE POUR RENDER ===
        screenshot_path = f"search_results_{int(time.time())}.png"
        try:
            results_container = page.locator("#search-results-content").last
            page.evaluate("""
                () => {
                    document.querySelectorAll('header, nav, .topnav, .navbar, .search-header').forEach(el => {
                        if (el) el.style.display = 'none';
                    });
                }
            """)
            
            # Capture avec timeout réduit + options légères
            results_container.screenshot(path=screenshot_path, timeout=15000)
            log(f"📸 Capture sauvegardée : {screenshot_path}")
        except Exception as e:
            log(f"⚠️ Erreur capture : {e}")
            try:
                page.screenshot(path=screenshot_path, full_page=False, timeout=10000)
            except:
                screenshot_path = None
                pass

        # Extraction des résultats
        items = page.evaluate("""
            () => Array.from(document.querySelectorAll('#search-results-content .search-item, .search-item')).map((item, i) => ({
                index: i + 1,
                title: item.querySelector('.search-title')?.innerText.trim() || item.innerText.trim().substring(0, 60)
            }))
        """)

        if not items:
            log("⚠️ Aucun item trouvé dans les résultats")
            continue

        return {
            "status": "selection_needed",
            "items": items,
            "screenshot_path": screenshot_path,
            "query": query
        }

    log("🛑 Aucune recherche n'a donné de résultat.")
    return {"status": "no_results"}

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

def extract_episodes_from_container(page, context, container_id, lang_name):
    log(f"📺 Analyse {lang_name} (#{container_id})...")
    links = []
    
    try:
        for sel in [f"//a[contains(text(), '{lang_name}')]", f"//ul[contains(@class, 'nav-tabs')]//a[contains(text(), '{lang_name}')]"]:
            tabs = page.locator(sel)
            if tabs.count() > 0:
                tabs.first.click()
                time.sleep(2)
                break
    except:
        pass

    container = page.locator(f"#{container_id}")
    try:
        container.wait_for(state="attached", timeout=10000)
    except:
        log(f"   ⚠️ Container non trouvé.")

    rows = container.locator(".episode-row").all()
    log(f"📋 {len(rows)} épisodes trouvés.")

    for i, row in enumerate(rows):
        ep_num = i + 1
        try:
            download_btn = row.locator(".ep-download").first
            if download_btn.count() == 0:
                links.append({"episode": ep_num, "lien": None})
                continue

            row.scroll_into_view_if_needed()
            time.sleep(1)
            download_btn.evaluate("el => el.click()")
            time.sleep(1.5)

            intermediate_link = row.evaluate("""
                () => {
                    const a = document.querySelector('.ep-dl-panel-options a.ep-dl-primary, .ep-dl-panel-options a');
                    return a ? a.href : null;
                }
            """)

            if not intermediate_link:
                links.append({"episode": ep_num, "lien": None})
                continue

            with context.expect_page(timeout=15000) as popup_info:
                page.evaluate(f"window.open('{intermediate_link}', '_blank');")
            
            popup = popup_info.value
            lien_final = recuperer_lien_vidzy(popup)
            popup.close()

            links.append({"episode": ep_num, "lien": lien_final})
            time.sleep(1.5)
        except Exception as e:
            log(f"   ❌ Ep {ep_num} erreur : {e}")
            links.append({"episode": ep_num, "lien": None})

    return links

def run_scraper(titre_film, poster_url=None, season_number=None, is_serie=False, all_episodes=False):
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
            page.goto(base_url, timeout=60000)
            time.sleep(5)

            login_user(page, "Jekle19", "c01h2bc3zp5")
            
            search_result = search_film(page, titre_film, season_number, base_url, tmdb_poster_url=poster_url)
            
            if search_result.get("status") == "selection_needed":
                browser.close()
                return search_result  # Retourne dict pour le bot

            if not search_result or search_result.get("status") == "no_results":
                browser.close()
                return None

            # Si on a un lien direct (ancien comportement)
            film_url = search_result
            page.goto(film_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)

            if is_serie:
                vf_links = extract_episodes_from_container(page, context, "vf-episodes", "VF")
                vostfr_links = extract_episodes_from_container(page, context, "vostfr-episodes", "VOSTFR")
                result = {"vf": vf_links, "vostfr": vostfr_links}
            else:
                # Logique film...
                result = None  # À compléter si besoin

            browser.close()
            return result

        except Exception as e:
            log(f"❌ ERREUR FATALE : {e}")
            browser.close()
            return None
