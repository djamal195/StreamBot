from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import os

# ==========================================
# CONFIGURATION
# ==========================================
# Mettre True pour le serveur (Render)
# Mettre False pour tester sur ton PC et voir le navigateur
HEADLESS_MODE = True 

def normalize_title(title):
    """Normalise le titre pour comparaison stricte"""
    nfd = unicodedata.normalize('NFD', title)
    title_no_accents = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    normalized = re.sub(r'[^\w\s]', ' ', title_no_accents)
    normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
    return normalized

def login_user(page, username, password):
    """Connexion au site"""
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
            # Attente chargement
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except: pass
            return True
        except: return False
    print("ℹ️ Déjà connecté ou bouton absent")
    return True

def search_film(page, search_query, base_url):
    """Cherche un film via l'URL et comparaison stricte du titre"""
    print(f"🔍 Recherche de : {search_query}...")
    encoded_title = urllib.parse.quote(search_query)
    search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
    
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    except:
        print("❌ Timeout recherche")
        return None
        
    time.sleep(2)
    
    found_url = page.evaluate("""
        (searchQuery) => {
            const container = document.getElementById('dle-content');
            if (!container) return null;
            const filmBlocks = Array.from(container.querySelectorAll('div.short.film'));
            
            for (const block of filmBlocks) {
                let titleEl = block.querySelector('a.short-poster-title');
                if (!titleEl) titleEl = block.querySelector('div.short-title');
                if (!titleEl) titleEl = block.querySelector('.short-title a');
                
                if (!titleEl) continue;
                
                const titleText = titleEl.innerText.trim();
                
                const normalize = (str) => {
                    return str.toLowerCase()
                        .normalize('NFD')
                        .replace(/[\\u0300-\\u036f]/g, '')
                        .replace(/[^\\w\\s]/g, ' ')
                        .replace(/\\s+/g, ' ')
                        .trim();
                };
                
                if (normalize(titleText) === normalize(searchQuery)) {
                    const linkEl = block.querySelector('a.short-poster-title');
                    if (linkEl && linkEl.href) return linkEl.href;
                    
                    const allLinks = Array.from(block.querySelectorAll('a'));
                    const movieLink = allLinks.find(l => l.href && (l.href.includes('/films/') || l.href.includes('/series/')));
                    if (movieLink) return movieLink.href;
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
    """Récupère le lien vidzy ou fsvid et le retourne"""
    try:
        print("⏳ Attente de la redirection vers vidzy/fsvid...")
        max_wait = 15
        wait_count = 0
        while wait_count < max_wait:
            current_url = page.url.lower()
            if "vidzy" in current_url or "fsvid" in current_url or "fsvidcdn" in current_url:
                print(f"✅ Redirection détectée vers : {page.url}")
                break
            time.sleep(1)
            wait_count += 1
        
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(3)
        
        current_url = page.url
        print(f"🌐 URL actuelle : {current_url}")
        
        lien = None
        
        # 1. VIDZY
        if "vidzy" in current_url.lower():
            print(f"🎯 Serveur détecté : Vidzy")
            try:
                page.wait_for_selector(".container.file-details a.main-button", timeout=20000)
                lien = page.evaluate("""
                    () => {
                        const a = document.querySelector(".container.file-details a.main-button");
                        return a ? a.href : null;
                    }
                """)
            except Exception as e:
                print(f"⚠️ Erreur sélecteur Vidzy : {e}")
        
        # 2. FSVID / AUTRES
        else:
            print(f"🎯 Serveur détecté : Fsvid/Autre")
            try:
                page.wait_for_selector("#customDownloadSpan", timeout=20000)
                lien = page.evaluate("""
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
            except Exception as e:
                print(f"⚠️ Erreur sélecteur Fsvid : {e}")
        
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
    """Fonction principale appelée par app.py"""
    base_url = "https://french-stream.one/"
    
    with sync_playwright() as p:
        print("🚀 Démarrage du navigateur...")
        # Configuration robuste pour Docker/Render
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

            popup_detected = False
            popup_page = None
            
            def on_popup(popup):
                nonlocal popup_detected, popup_page
                popup_detected = True
                popup_page = popup
                print("🚀 Popup détecté !")
            
            page.context.on("page", on_popup)
            
            # Clic
            page.evaluate("document.getElementById('downloadBtn').click()")
            print("✅ Bouton cliqué...")
            
            time.sleep(5)
            page.context.remove_listener("page", on_popup)
            
            lien_final = None
            
            # SCENARIO A : Popup direct vers vidzy/fsvid
            if popup_detected and popup_page:
                print("🚀 SCÉNARIO A : Popup direct détecté")
                lien_final = recuperer_lien_vidzy(popup_page, titre_film)
            
            # SCENARIO B : Menu Options
            else:
                print("🔄 SCÉNARIO B : Menu Options")
                try:
                    # Force visible si caché
                    page.evaluate("""
                        const menu = document.getElementById('downloadOptions');
                        if(menu) { 
                            menu.style.display = 'block'; 
                            menu.style.visibility = 'visible'; 
                            menu.style.opacity = '1';
                        }
                    """)
                    
                    time.sleep(2)
                    
                    try:
                        page.wait_for_selector("#downloadOptions", state="visible", timeout=5000)
                        print("✅ Menu downloadOptions visible")
                    except:
                        print("⚠️ Menu non visible mais on continue...")

                    print("🎯 Sélection qualité (priorité : haute > moyenne)...")
                    
                    quality_clicked = page.evaluate("""
                        () => {
                            // Chercher 'haute' en priorité
                            let btn = Array.from(document.querySelectorAll('[onclick*="downloadFile"]'))
                                .find(el => el.getAttribute('onclick').includes("'haute'"));
                            
                            if (btn) {
                                console.log("Qualité HAUTE trouvée !");
                                btn.click();
                                return 'haute';
                            }
                            
                            // Sinon chercher 'moyenne'
                            btn = Array.from(document.querySelectorAll('[onclick*="downloadFile"]'))
                                .find(el => el.getAttribute('onclick').includes("'moyenne'"));
                            
                            if (btn) {
                                console.log("Qualité MOYENNE trouvée !");
                                btn.click();
                                return 'moyenne';
                            }
                            
                            return null;
                        }
                    """)
                    
                    if quality_clicked:
                        print(f"✅ Qualité '{quality_clicked}' cliquée, attente popup...")
                        
                        try:
                            with page.expect_popup(timeout=15000) as popup_info:
                                pass
                            quality_popup = popup_info.value
                            print("✅ Popup de qualité ouvert")
                            lien_final = recuperer_lien_vidzy(quality_popup, titre_film)
                        except Exception as e:
                            print(f"❌ Erreur attente popup : {e}")
                    else:
                        print("❌ Pas d'option de qualité trouvée (ni haute ni moyenne)")
                
                except Exception as e:
                    print(f"❌ Erreur Scénario B : {e}")
            
            browser.close()
            return lien_final
        
        except Exception as e:
            print(f"❌ Erreur générale : {e}")
            browser.close()
            return None

# Pour tester en local seulement
if __name__ == "__main__":
    HEADLESS_MODE = False # Pour voir le test
    t = input("Film : ")
    print("Résultat :", run_scraper(t))
