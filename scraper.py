from playwright.sync_api import sync_playwright
import time
import os

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

def search_film(page, search_query, target_season, base_url):
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
            
            time.sleep(4)
            page.wait_for_selector("#search-results-content", timeout=15000)
            time.sleep(3)
        except Exception as e:
            log(f"⚠️ Erreur recherche : {e}")
            continue

        screenshot_path = f"search_results_{int(time.time())}.png"
        try:
            results_container = page.locator("#search-results-content").last
            page.evaluate("""
                () => {
                    document.querySelectorAll('header, nav, .topnav, .navbar').forEach(el => {
                        if (el) el.style.display = 'none';
                    });
                }
            """)
            results_container.screenshot(path=screenshot_path)
            log(f"📸 Capture sauvegardée : {screenshot_path}")
        except Exception as e:
            log(f"⚠️ Erreur capture : {e}")

        items = page.evaluate("""
            () => Array.from(document.querySelectorAll('#search-results-content .search-item')).map((item, i) => ({
                index: i + 1,
                title: item.querySelector('.search-title')?.innerText.trim() || 'Sans titre'
            }))
        """)

        return {
            "status": "selection_needed",
            "items": items,
            "screenshot_path": screenshot_path,
            "query": query
        }

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
            
            search_result = search_film(page, titre_film, season_number, base_url)
            
            if isinstance(search_result, dict) and search_result.get("status") == "selection_needed":
                browser.close()
                return search_result

            if not search_result:
                browser.close()
                return None

            film_url = search_result
            page.goto(film_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)

            result = None
            if is_serie:
                result = {"vf": [], "vostfr": []}
            else:
                try:
                    page.click("#downloadBtn")
                    page.wait_for_selector("#downloadOptions", timeout=10000)
                    with page.expect_popup(timeout=10000) as popup_info:
                        page.locator("#downloadOptions div").first.click()
                    popup = popup_info.value
                    result = recuperer_lien_vidzy(popup)
                    popup.close()
                except Exception as e:
                    log(f"Erreur film : {e}")

            browser.close()
            return result

        except Exception as e:
            log(f"❌ ERREUR FATALE : {e}")
            browser.close()
            return None
