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
    print("🔐 Ouverture du formulaire de connexion...")
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
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except: pass
            return True
        except: return False
    print("ℹ️ Déjà connecté ou bouton absent")
    return True

def search_film(page, search_query, base_url):
    print(f"🔍 Recherche de : {search_query}...")
    encoded_title = urllib.parse.quote(search_query)
    search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
    
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
    except:
        print("❌ Timeout recherche")
        return None
    
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
                
                if (normalize(titleText) === normalize(searchQuery)) {
                    const linkEl = block.querySelector('a.short-poster-title') || block.querySelector('a');
                    return linkEl ? linkEl.href : null;
                }
            }
            return null;
        }
    """, search_query)
    
    if found_url:
        print(f"✨ Film trouvé : {found_url}")
        return found_url
    print("❌ Aucun film ne correspond exactement.")
    return None

def recuperer_lien_vidzy(page, titre_film):
    """Extrait le lien final depuis la page de l'hébergeur (Popup)"""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(3)
        current_url = page.url
        print(f"🌐 URL Popup : {current_url}")
        
        lien = None
        
        # 1. VIDZY
        if "vidzy" in current_url.lower():
            print(f"🎯 Serveur détecté : Vidzy")
            try:
                page.wait_for_selector(".container.file-details a.main-button", timeout=10000)
                lien = page.evaluate("document.querySelector('.container.file-details a.main-button')?.href")
            except: pass
        
        # 2. FSVID / AUTRES
        else:
            print(f"🎯 Serveur détecté : Fsvid/Autre")
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
            print(f"✅ Lien récupéré : {lien}")
            return lien
        else:
            print("❌ Lien introuvable sur la page finale")
            return None
    
    except Exception as e:
        print(f"❌ Erreur récupération : {e}")
        return None

def run_scraper(titre_film):
    base_url = "https://french-stream.one/"
    
    with sync_playwright() as p:
        print("🚀 Démarrage du navigateur...")
        browser = p.chromium.launch(
            headless=HEADLESS_MODE,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        
        try:
            print(f"🌐 Navigation vers {base_url}...")
            page.goto(base_url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            if not login_user(page, "Jekle19", "otf192009"):
                browser.close(); return None
            
            film_url = search_film(page, titre_film, base_url)
            if not film_url:
                browser.close(); return None
            
            page.goto(film_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
            
            print("🖱️ Clic sur le bouton de téléchargement...")
            if not page.locator("#downloadBtn").is_visible():
                print("❌ Bouton introuvable"); browser.close(); return None

            # --- GESTION INTELLIGENTE DU CLIC ---
            
            # 1. On prépare le panier pour attraper un éventuel popup (Scénario A)
            popup_bucket = []
            page.context.on("page", lambda p: popup_bucket.append(p))
            
            # 2. On clique
            page.evaluate("document.getElementById('downloadBtn').click()")
            print("✅ Bouton cliqué, analyse de la réaction...")
            
            # 3. On attend un peu pour voir ce qui se passe
            time.sleep(4)
            
            # On arrête d'écouter les nouvelles pages pour éviter le bruit
            page.context.remove_listener("page", lambda p: popup_bucket.append(p))
            
            lien_final = None
            
            # --- ANALYSE DES SCÉNARIOS ---
            
            # SCÉNARIO A : Un popup s'est ouvert tout seul ?
            if len(popup_bucket) > 0:
                print("🚀 SCÉNARIO A DÉTECTÉ : Redirection directe.")
                # Le dernier popup ouvert est probablement le bon
                popup_page = popup_bucket[-1]
                lien_final = recuperer_lien_vidzy(popup_page, titre_film)
            
            # SCÉNARIO B : Pas de popup ? Alors c'est le menu Options.
            else:
                print("🔄 SCÉNARIO B DÉTECTÉ : Menu Options.")
                try:
                    # On s'assure que le menu est visible
                    try:
                        page.wait_for_selector("#downloadOptions", state="visible", timeout=5000)
                    except:
                        # Si invisible, on force l'affichage (Hack CSS)
                        print("⚠️ Menu caché, forçage CSS...")
                        page.evaluate("document.getElementById('downloadOptions').style.display = 'block';")
                        time.sleep(1)

                    print("🎯 Sélection qualité (Haute > Moyenne)...")
                    
                    # Logique de priorité Javascript
                    quality_clicked = page.evaluate("""
                        () => {
                            let container = document.getElementById('downloadOptions');
                            if (!container) return false;
                            
                            // On cherche tous les éléments cliquables
                            let btns = Array.from(container.querySelectorAll('[onclick*="downloadFile"]'));
                            
                            // 1. Chercher HAUTE
                            let target = btns.find(el => el.getAttribute('onclick').toLowerCase().includes('haute'));
                            
                            // 2. Chercher MOYENNE (si pas haute)
                            if (!target) {
                                target = btns.find(el => el.getAttribute('onclick').toLowerCase().includes('moyenne'));
                            }
                            
                            // 3. Fallback (le premier dispo)
                            if (!target && btns.length > 0) target = btns[0];

                            if (target) { target.click(); return true; }
                            return false;
                        }
                    """)
                    
                    if quality_clicked:
                        print("✅ Qualité cliquée, attente du popup final...")
                        # Là, on doit obligatoirement avoir un popup
                        with page.expect_popup(timeout=20000) as popup_info:
                            pass
                        lien_final = recuperer_lien_vidzy(popup_info.value, titre_film)
                    else:
                        print("❌ Aucune option cliquable trouvée dans le menu.")
                
                except Exception as e:
                    print(f"❌ Erreur Scénario B : {e}")
            
            browser.close()
            return lien_final

        except Exception as e:
            print(f"❌ Erreur Générale Scraper : {e}")
            browser.close()
            return None

# Pour tester en local
if __name__ == "__main__":
    HEADLESS_MODE = False
    t = input("Film : ")
    print("Résultat :", run_scraper(t))
