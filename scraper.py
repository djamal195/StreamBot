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
            except: pass
        
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

def download_episode(page, episode_num=1):
    """Gère le téléchargement d'un épisode de série"""
    print(f"📺 Téléchargement de l'épisode {episode_num}...")
    
    try:
        # Attendre que les épisodes soient chargés
        page.wait_for_selector(".ep-download", timeout=10000)
        time.sleep(2)
        
        # Compter les épisodes disponibles
        episodes_count = page.evaluate("""
            () => {
                return document.querySelectorAll('.ep-download').length;
            }
        """)
        
        print(f"📋 {episodes_count} épisode(s) disponible(s)")
        
        if episode_num > episodes_count:
            print(f"❌ L'épisode {episode_num} n'existe pas (max: {episodes_count})")
            return None
        
        # Préparer la détection du popup
        popup_detected = False
        popup_page = None
        
        def on_popup(popup):
            nonlocal popup_detected, popup_page
            popup_detected = True
            popup_page = popup
            print(f"🎉 Popup épisode {episode_num} détecté!")
        
        page.context.on("page", on_popup)
        
        # Cliquer sur l'épisode spécifique (index 0-based)
        print(f"🖱️ Clic sur l'épisode {episode_num}...")
        page.evaluate(f"""
            () => {{
                const episodes = document.querySelectorAll('.ep-download');
                if (episodes[{episode_num - 1}]) {{
                    episodes[{episode_num - 1}].click();
                }}
            }}
        """)
        
        time.sleep(2)
        
        # Attendre le popup (max 10 secondes)
        max_wait = 10
        waited = 0
        while waited < max_wait and not popup_detected:
            time.sleep(1)
            waited += 1
        
        page.context.remove_listener("page", on_popup)
        
        if popup_detected and popup_page:
            print("✅ Popup ouvert, extraction du lien...")
            return recuperer_lien_vidzy(popup_page, f"Episode {episode_num}")
        else:
            print("❌ Aucun popup détecté pour cet épisode")
            return None
    
    except Exception as e:
        print(f"❌ Erreur téléchargement épisode : {e}")
        return None

def download_all_episodes(page):
    """Télécharge tous les épisodes d'une série"""
    print("📺 Téléchargement de TOUS les épisodes...")
    
    try:
        # Attendre que les épisodes soient chargés
        page.wait_for_selector(".ep-download", timeout=10000)
        time.sleep(2)
        
        # Compter les épisodes disponibles
        episodes_count = page.evaluate("""
            () => {
                return document.querySelectorAll('.ep-download').length;
            }
        """)
        
        print(f"📋 {episodes_count} épisode(s) trouvé(s)")
        
        all_links = []
        
        # Boucler sur chaque épisode
        for i in range(1, episodes_count + 1):
            print(f"\n--- Épisode {i}/{episodes_count} ---")
            
            # Préparer la détection du popup
            popup_detected = False
            popup_page = None
            
            def on_popup(popup):
                nonlocal popup_detected, popup_page
                popup_detected = True
                popup_page = popup
                print(f"🎉 Popup épisode {i} détecté!")
            
            page.context.on("page", on_popup)
            
            # Cliquer sur l'épisode
            print(f"🖱️ Clic sur l'épisode {i}...")
            page.evaluate(f"""
                () => {{
                    const episodes = document.querySelectorAll('.ep-download');
                    if (episodes[{i - 1}]) {{
                        episodes[{i - 1}].click();
                    }}
                }}
            """)
            
            time.sleep(2)
            
            # Attendre le popup (max 10 secondes)
            max_wait = 10
            waited = 0
            while waited < max_wait and not popup_detected:
                time.sleep(1)
                waited += 1
            
            page.context.remove_listener("page", on_popup)
            
            if popup_detected and popup_page:
                print("✅ Popup ouvert, extraction du lien...")
                lien = recuperer_lien_vidzy(popup_page, f"Episode {i}")
                if lien:
                    all_links.append({
                        "episode": i,
                        "lien": lien
                    })
                    print(f"✅ Épisode {i} : Lien récupéré")
                    # Fermer le popup pour continuer
                    popup_page.close()
                else:
                    print(f"❌ Épisode {i} : Lien non trouvé")
                    all_links.append({
                        "episode": i,
                        "lien": None
                    })
            else:
                print(f"❌ Épisode {i} : Aucun popup détecté")
                all_links.append({
                    "episode": i,
                    "lien": None
                })
            
            # Pause entre chaque épisode
            time.sleep(1)
        
        print(f"\n✅ Terminé : {len([l for l in all_links if l['lien']])}/{episodes_count} liens récupérés")
        return all_links
    
    except Exception as e:
        print(f"❌ Erreur téléchargement tous épisodes : {e}")
        return []

def run_scraper(titre_film, is_serie=False, episode_num=1, all_episodes=False):
    """Fonction principale appelée par app.py
    
    Args:
        titre_film: Titre du film ou de la série
        is_serie: True si c'est une série, False si c'est un film
        episode_num: Numéro de l'épisode (seulement pour les séries si all_episodes=False)
        all_episodes: True pour télécharger tous les épisodes, False pour un seul
    """
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
            
            if is_serie:
                print("📺 Mode SÉRIE détecté")
                if all_episodes:
                    lien_final = download_all_episodes(page)
                else:
                    lien_final = download_episode(page, episode_num)
            else:
                print("🎬 Mode FILM détecté")
                print("🖱️ Clic sur le bouton de téléchargement...")
                if not page.locator("#downloadBtn").is_visible():
                    print("❌ Bouton introuvable"); browser.close(); return None

                popup_detected = False
                popup_page = None
                
                def on_popup(popup):
                    nonlocal popup_detected, popup_page
                    popup_detected = True
                    popup_page = popup
                    print("🎉 Popup détecté!")
                
                page.context.on("page", on_popup)
                
                page.evaluate("document.getElementById('downloadBtn').click()")
                print("✅ Bouton cliqué, analyse du comportement...")
                
                max_wait = 8
                waited = 0
                menu_appeared = False
                
                while waited < max_wait:
                    time.sleep(1)
                    waited += 1
                    
                    if popup_detected:
                        print(f"🚀 Popup détecté après {waited}s")
                        break
                    
                    menu_visible = page.evaluate("""
                        () => {
                            const menu = document.getElementById('downloadOptions');
                            if (!menu) return false;
                            const style = window.getComputedStyle(menu);
                            return style.display !== 'none' && style.visibility !== 'hidden';
                        }
                    """)
                    
                    if menu_visible:
                        menu_appeared = True
                        print(f"📋 Menu options détecté après {waited}s")
                        break
                
                page.context.remove_listener("page", on_popup)
                
                lien_final = None
                
                if popup_detected and popup_page:
                    print("🚀 SCÉNARIO A : Popup direct")
                    lien_final = recuperer_lien_vidzy(popup_page, titre_film)
                
                elif menu_appeared:
                    print("🔄 SCÉNARIO B : Menu Options détecté")
                    try:
                        page.evaluate("""
                            const menu = document.getElementById('downloadOptions');
                            if(menu) { 
                                menu.style.display = 'block'; 
                                menu.style.visibility = 'visible'; 
                                menu.style.opacity = '1';
                            }
                        """)
                        time.sleep(1)
                        
                        print("🎯 Sélection qualité...")
                        
                        quality_info = page.evaluate("""
                            () => {
                                console.log('[v0] Recherche des boutons de qualité...');
                                
                                const selectors = [
                                    '[onclick*="downloadFile"]',
                                    'button[onclick*="downloadFile"]',
                                    'a[onclick*="downloadFile"]',
                                    '.download-option',
                                    '#downloadOptions button',
                                    '#downloadOptions a'
                                ];
                                
                                let allButtons = [];
                                for (const selector of selectors) {
                                    const found = Array.from(document.querySelectorAll(selector));
                                    allButtons = allButtons.concat(found);
                                }
                                
                                allButtons = [...new Set(allButtons)];
                                
                                console.log('[v0] Boutons trouvés:', allButtons.length);
                                
                                if (allButtons.length === 0) {
                                    return { found: false, message: 'Aucun bouton trouvé' };
                                }
                                
                                let btn = allButtons.find(el => {
                                    const onclick = el.getAttribute('onclick') || '';
                                    const text = el.innerText || '';
                                    return onclick.includes("'haute'") || text.toLowerCase().includes('haute');
                                });
                                
                                if (btn) {
                                    console.log('[v0] Bouton HAUTE trouvé');
                                    btn.click();
                                    return { found: true, quality: 'haute' };
                                }
                                
                                btn = allButtons.find(el => {
                                    const onclick = el.getAttribute('onclick') || '';
                                    const text = el.innerText || '';
                                    return onclick.includes("'moyenne'") || text.toLowerCase().includes('moyenne');
                                });
                                
                                if (btn) {
                                    console.log('[v0] Bouton MOYENNE trouvé');
                                    btn.click();
                                    return { found: true, quality: 'moyenne' };
                                }
                                
                                if (allButtons.length > 0) {
                                    console.log('[v0] Clic sur le premier bouton disponible');
                                    allButtons[0].click();
                                    return { found: true, quality: 'premier disponible' };
                                }
                                
                                return { found: false, message: 'Aucun bouton valide' };
                            }
                        """)
                        
                        if quality_info and quality_info.get('found'):
                            print(f"✅ Qualité '{quality_info.get('quality')}' sélectionnée, attente popup...")
                            time.sleep(2)
                            
                            try:
                                with page.expect_popup(timeout=15000) as popup_info:
                                    pass
                                lien_final = recuperer_lien_vidzy(popup_info.value, titre_film)
                            except:
                                print("⚠️ Aucun popup détecté après clic qualité")
                        else:
                            message = quality_info.get('message', 'Erreur inconnue') if quality_info else 'Pas de réponse'
                            print(f"❌ {message}")
                    
                    except Exception as e:
                        print(f"❌ Erreur Scénario B : {e}")
                
                else:
                    print("⚠️ Aucun scénario détecté (ni popup ni menu)")
            
            browser.close()
            return lien_final
        
        except Exception as e:
            print(f"❌ Erreur générale : {e}")
            browser.close()
            return None

# Pour tester en local seulement
if __name__ == "__main__":
    HEADLESS_MODE = False
    choice = input("Film (F) ou Série (S) ? ").upper()
    t = input("Titre : ")
    
    if choice == "S":
        all_ep = input("Tous les épisodes ? (O/N) : ").upper()
        if all_ep == "O":
            print("Résultat :", run_scraper(t, is_serie=True, all_episodes=True))
        else:
            ep = int(input("Numéro d'épisode : "))
            print("Résultat :", run_scraper(t, is_serie=True, episode_num=ep))
    else:
        print("Résultat :", run_scraper(t, is_serie=False))
