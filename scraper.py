from playwright.sync_api import sync_playwright
import time
import re
import unicodedata
import urllib.parse
import json
import os

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
        page.evaluate("document.querySelector('#loginButtonContainer').click()")
        time.sleep(2)
        
        page.fill("#login_name", username)
        time.sleep(0.5)
        page.fill("#login_password", password)
        time.sleep(0.5)
        page.keyboard.press("Enter")
        time.sleep(5)
        
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        
        if page.evaluate("() => !document.querySelector('#loginButtonContainer') || document.body.innerText.includes('Déconnexion')"):
            print("✅ Connexion réussie !")
            return True
    
    print("❌ Erreur lors de la connexion")
    return False

def search_film(page, search_query, base_url):
    """Cherche un film via l'URL et comparaison stricte du titre"""
    print(f"🔍 Recherche de : {search_query}...")
    
    encoded_title = urllib.parse.quote(search_query)
    search_url = f"{base_url}index.php?do=search&subaction=search&story={encoded_title}"
    page.goto(search_url, wait_until="domcontentloaded")
    time.sleep(2)
    
    found_url = page.evaluate("""
        (searchQuery) => {
            const container = document.getElementById('dle-content');
            if (!container) return null;
            
            const filmBlocks = Array.from(container.querySelectorAll('div.short.film'));
            console.log('[v0] Films trouvés:', filmBlocks.length);
            
            for (const block of filmBlocks) {
                let titleEl = block.querySelector('a.short-poster-title');
                if (!titleEl) titleEl = block.querySelector('div.short-title');
                if (!titleEl) titleEl = block.querySelector('.short-title a');
                
                if (!titleEl) continue;
                
                const titleText = titleEl.innerText.trim();
                console.log('[v0] Comparaison:', titleText, 'vs', searchQuery);
                
                const normalize = (str) => {
                    return str.toLowerCase()
                        .normalize('NFD')
                        .replace(/[\u0300-\u036f]/g, '')
                        .replace(/[^\\w\\s]/g, ' ')
                        .replace(/\\s+/g, ' ')
                        .trim();
                };
                
                const normalizedTitle = normalize(titleText);
                const normalizedQuery = normalize(searchQuery);
                
                if (normalizedTitle === normalizedQuery) {
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
        print(f"✨ Film trouvé ! Navigation vers : {found_url}")
        return found_url
    else:
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
        serveur = None
        
        if "vidzy" in current_url.lower():
            serveur = "vidzy"
            print(f"🎯 Serveur détecté via URL : {serveur}")
            
            try:
                page.wait_for_selector(".container.file-details a.main-button", timeout=20000)
                lien = page.evaluate("""
                    () => {
                        const a = document.querySelector(".container.file-details a.main-button");
                        console.log('[v0] Bouton vidzy trouvé:', !!a);
                        return a ? a.href : null;
                    }
                """)
            except Exception as e:
                print(f"⚠️ Élément vidzy non trouvé : {e}")
        
        elif "fsvid" in current_url.lower():
            serveur = "fsvid"
            print(f"🎯 Serveur détecté via URL : {serveur}")
            
            try:
                page.wait_for_selector("#customDownloadSpan", timeout=20000)
                lien = page.evaluate("""
                    () => {
                        const span = document.querySelector('#customDownloadSpan');
                        console.log('[v0] Span fsvid trouvé:', !!span);
                        
                        if (!span) return null;
                        
                        // MÉTHODE 1 : Chercher le <a> directement dans le span
                        const aTag = span.querySelector('a');
                        if (aTag && aTag.href) {
                            console.log('[v0] Lien trouvé via <a> href:', aTag.href);
                            return aTag.href;
                        }
                        
                        // MÉTHODE 2 : Chercher dans l'attribut onclick du span (fallback)
                        const onclick = span.getAttribute('onclick');
                        console.log('[v0] onclick attribute:', onclick);
                        
                        if (onclick) {
                            const match = onclick.match(/'(https?:\/\/[^']+)'/);
                            if (match) {
                                console.log('[v0] Lien extrait via onclick:', match[1]);
                                return match[1];
                            }
                        }
                        
                        return null;
                    }
                """)
            except Exception as e:
                print(f"⚠️ Élément fsvid non trouvé : {e}")
                print("🔄 Tentative de méthode alternative pour fsvid...")
                lien = page.evaluate("""
                    () => {
                        // Chercher tous les <a> qui contiennent fsvid dans le href
                        const links = Array.from(document.querySelectorAll('a[href*="fsvid"]'));
                        console.log('[v0] Liens fsvid trouvés:', links.length);
                        
                        for (const link of links) {
                            if (link.href && link.href.includes('/v/')) {
                                console.log('[v0] Lien trouvé via recherche générale:', link.href);
                                return link.href;
                            }
                        }
                        
                        return null;
                    }
                """)
        
        else:
            print("🔍 Détection via éléments DOM...")
            is_vidzy = page.evaluate("() => !!document.querySelector('a.main-button')")
            is_fsvid = page.evaluate("() => !!document.querySelector('#customDownloadSpan')")
            
            if is_vidzy:
                serveur = "vidzy"
                print(f"🎯 Serveur détecté via DOM : {serveur}")
                page.wait_for_selector(".container.file-details a.main-button", timeout=20000)
                lien = page.evaluate("""
                    () => {
                        const a = document.querySelector(".container.file-details a.main-button");
                        return a ? a.href : null;
                    }
                """)
            
            elif is_fsvid:
                serveur = "fsvid"
                print(f"🎯 Serveur détecté via DOM : {serveur}")
                page.wait_for_selector("#customDownloadSpan", timeout=20000)
                lien = page.evaluate("""
                    () => {
                        const span = document.querySelector('#customDownloadSpan');
                        if (!span) return null;
                        
                        const onclick = span.getAttribute('onclick');
                        if (!onclick) return null;
                        
                        const match = onclick.match(/'(https?:\/\/[^']+)'/);
                        return match ? match[1] : null;
                    }
                """)
            else:
                print("❌ Serveur non reconnu (ni vidzy ni fsvid)")
                print("🔍 Contenu de la page pour diagnostic :")
                page_info = page.evaluate("""
                    () => {
                        return {
                            title: document.title,
                            hasMainButton: !!document.querySelector('a.main-button'),
                            hasCustomDownloadSpan: !!document.querySelector('#customDownloadSpan'),
                            bodySnippet: document.body.innerText.substring(0, 200)
                        };
                    }
                """)
                print(f"   Titre: {page_info['title']}")
                print(f"   Bouton principal: {page_info['hasMainButton']}")
                print(f"   Span download: {page_info['hasCustomDownloadSpan']}")
                print(f"   Extrait: {page_info['bodySnippet'][:100]}...")
                return None  # Retourne None au lieu de return simple
        
        if not lien:
            print(f"❌ Lien {serveur} non trouvé")
            return None  # Retourne None au lieu de return simple
        
        print(f"✅ Lien {serveur} récupéré :")
        print(lien)
        
        db_file = "filmdb.json"
        data = []
        
        if os.path.exists(db_file):
            try:
                with open(db_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                print("⚠️ filmdb.json vide ou corrompu")
        
        data.append({
            "title": titre_film,
            "quality": "moyenne",
            "serveur": serveur,
            "download_url": lien
        })
        
        with open(db_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        print(f"💾 Lien sauvegardé dans filmdb.json ({len(data)} entrée(s))")
        
        return lien
    
    except Exception as e:
        print(f"❌ Erreur récupération : {e}")
        return None  # Retourne None en cas d'erreur

def run_scraper(titre_film):
    """
    Fonction principale pour scraper un film
    Args:
        titre_film (str): Le titre du film à rechercher
    Returns:
        str: L'URL de téléchargement du film, ou None si échec
    """
    base_url = "https://french-stream.one/"
    
    with sync_playwright() as p:
        print("🚀 Démarrage du navigateur...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            print(f"🌐 Navigation vers {base_url}...")
            page.goto(base_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            if not login_user(page, "Jekle19", "otf192009"):
                browser.close()
                return None
            
            film_url = search_film(page, titre_film, base_url)
            
            if not film_url:
                print("🛑 Film non trouvé. Fermeture.")
                browser.close()
                return None
            
            page.goto(film_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
            
            print("🖱️ Clic sur le bouton de téléchargement...")
            page.wait_for_selector("#downloadBtn", timeout=10000)
            
            popup_detected = False
            popup_page = None
            
            # Créer un listener pour le popup (ne bloque pas)
            def on_popup(popup):
                nonlocal popup_detected, popup_page
                popup_detected = True
                popup_page = popup
            
            page.context.on("page", on_popup)
            
            # Cliquer sur le bouton
            page.evaluate("document.getElementById('downloadBtn').click()")
            print("✅ Bouton cliqué, attente de la réaction...")
            
            # Attendre 3 secondes pour voir si un popup s'ouvre
            time.sleep(3)
            
            # Retirer le listener
            page.context.remove_listener("page", on_popup)
            
            lien_final = None  # Variable pour stocker le lien à retourner
            
            # Scénario A : Popup s'est ouvert directement
            if popup_detected and popup_page:
                print("🚀 SCÉNARIO A : Redirection directe vers serveur (nouvel onglet)")
                lien_final = recuperer_lien_vidzy(popup_page, titre_film)
            
            # Scénario B : Le menu downloadOptions apparaît
            else:
                print("🔄 SCÉNARIO B : Menu de qualité détecté")
                
                try:
                    # Attendre que le menu apparaisse
                    page.wait_for_selector("#downloadOptions", state="visible", timeout=5000)
                    print("✅ Menu des options visible")
                    time.sleep(1)
                    
                    # Vérifier si le menu contient des options
                    has_options = page.evaluate("""
                        () => {
                            const menu = document.getElementById('downloadOptions');
                            return menu && menu.innerText.trim().length > 0;
                        }
                    """)
                    
                    if not has_options:
                        print("⚠️ Menu vide, impossible de continuer")
                        browser.close()
                        return None
                    
                    # Chercher et cliquer sur la qualité (haute en priorité, sinon moyenne)
                    print("🎯 Sélection de la qualité...")
                    
                    quality_clicked = page.evaluate("""
                        () => {
                            // PRIORITÉ 1 : Cherche onclick="downloadFile('haute')"
                            let btn = Array.from(document.querySelectorAll('[onclick*="downloadFile"]'))
                                .find(el => el.getAttribute('onclick').includes("'haute'"));
                            
                            if (btn) {
                                console.log('[v0] ✅ Qualité HAUTE trouvée et sélectionnée');
                                btn.click();
                                return 'haute';
                            }
                            
                            // PRIORITÉ 2 : Sinon cherche onclick="downloadFile('moyenne')"
                            btn = Array.from(document.querySelectorAll('[onclick*="downloadFile"]'))
                                .find(el => el.getAttribute('onclick').includes("'moyenne'"));
                            
                            if (btn) {
                                console.log('[v0] ⚠️ Qualité MOYENNE sélectionnée (haute non disponible)');
                                btn.click();
                                return 'moyenne';
                            }
                            
                            return null;
                        }
                    """)
                    
                    if not quality_clicked:
                        print("❌ Aucune qualité trouvée (ni haute ni moyenne)")
                        browser.close()
                        return None
                    
                    print(f"✅ Qualité '{quality_clicked}' sélectionnée, attente du popup...")
                    
                    # Maintenant attendre le popup après le clic sur la qualité
                    try:
                        with page.expect_popup(timeout=10000) as popup_info:
                            pass
                        
                        popup_page = popup_info.value
                        print("🚀 Popup ouvert, récupération du lien...")
                        lien_final = recuperer_lien_vidzy(popup_page, titre_film)
                    
                    except Exception as e:
                        print(f"❌ Popup non détecté après sélection de qualité : {e}")
                
                except Exception as e:
                    print(f"❌ Erreur dans le scénario B : {e}")
            
            browser.close()
            return lien_final  # Retourne le lien récupéré
        
        except Exception as e:
            print(f"❌ Erreur générale : {e}")
            browser.close()
            return None

def main():
    """Fonction pour tester le scraper manuellement"""
    titre = input("🎬 Entrez le titre du film à rechercher : ").strip()
    lien = run_scraper(titre)
    
    if lien:
        print(f"\n✅ SUCCÈS ! Lien récupéré :")
        print(lien)
    else:
        print("\n❌ ÉCHEC : Aucun lien récupéré")

if __name__ == "__main__":
    main()
