import asyncio
import os
import re
import json
from datetime import datetime
from typing import Dict, List, Optional
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from common import update_json_with_sold  # Pretpostavka: postoji modul common sa ovom funkcijom

# ==================== KONSTANTE ====================
BASE_URL = "https://www.polovniautomobili.com"
PRODATO_URL = f"{BASE_URL}/auto-oglasi/prodato"
POLOVNI_FOLDER = "."
REQUEST_DELAY = 2  # sekundi između stranica

# Višerečni brendovi – za fallback kada JSON-LD nema marku
MULTI_WORD_BRANDS = [
    "Alfa Romeo",
    "Aston Martin",
    "Citroen",
    "Land Rover",
    "Mercedes Benz",
    "Mercedes-Benz",
    "Range Rover",
    "Rolls Royce",
    "Rolls-Royce",
]




# ==================== POMOĆNE FUNKCIJE ====================
def extract_json_ld(soup: BeautifulSoup) -> Dict[str, Dict]:
    """
    Pronalazi sve JSON-LD skripte tipa 'Car' i vraća rečnik gde je ključ ID oglasa,
    a vrednost JSON-LD objekat.
    """
    car_map = {}
    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Car':
                        url = item.get('url')
                        if url:
                            match = re.search(r'/(\d+)/', url)
                            if match:
                                car_map[match.group(1)] = item
            elif isinstance(data, dict) and data.get('@type') == 'Car':
                url = data.get('url')
                if url:
                    match = re.search(r'/(\d+)/', url)
                    if match:
                        car_map[match.group(1)] = data
        except Exception:
            continue
    return car_map


def extract_ad_data_new(article: BeautifulSoup) -> Optional[Dict]:
    """
    Ekstrahuje podatke iz jednog oglasa (nova struktura sa data-testid).
    """
    try:
        # --- ID oglasa ---
        ad_id = None
        # Pokušaj iz <data id="...">
        data_tag = article.find('data')
        if data_tag and data_tag.get('id'):
            ad_id = data_tag['id']
        else:
            # Ili iz href-a
            link_tag = article.find('a', {'data-testid': 'adCardDetailPageTitle'})
            if link_tag and link_tag.get('href'):
                match = re.search(r'/(\d+)/', link_tag['href'])
                if match:
                    ad_id = match.group(1)

        if not ad_id:
            return None

        # --- Naslov (Marka + Model) ---
        title_elem = article.find('h2', class_=re.compile(r'DesktopTitle'))
        title = title_elem.text.strip() if title_elem else None

        # --- Cena ---
        price_span = article.find('span', {'data-testid': 'globalAdCardPriceTestId'})
        cena = None
        if price_span:
            cena_text = price_span.get_text(strip=True)
            # ukloni " + registracija" ako postoji
            cena = re.sub(r'\s*\+.*$', '', cena_text).strip()

        # --- Opis (karakteristike) ---
        desc_div = article.find('div', {'data-testid': 'adDescription'})
        opis_items = desc_div.find_all('div', class_=re.compile(r'AdDescItem')) if desc_div else []
        opis = ' | '.join([item.get_text(' ', strip=True) for item in opis_items]) if opis_items else None

        # --- Lokacija ---
        city_div = article.find('div', {'data-testid': 'adCardCity'})
        lokacija = city_div.get_text(strip=True) if city_div else None
        if lokacija:
            lokacija = re.sub(r'^.*?map-marker\s*', '', lokacija)  # ukloni ikonicu

        # --- Slika ---
        img = article.find('img', {'data-testid': 'main-image'})
        img_url = img.get('src') or img.get('srcset', '').split()[0] if img else None

        # --- Oglasivač ---
        adv_p = article.find('p', class_=re.compile(r'AdvertiserText'))
        oglasivac = adv_p.get_text(strip=True) if adv_p else None

        # --- Karakteristike iz opisa (parsiranje) ---
        # Očekujemo redom: "Godina. Karoserija", "Gorivo | cm3", "km", "kW (KS)", "Menjač", "vrata, sedišta"
        godina_proizvodnje = None
        karoserija = None
        gorivo = None
        kubikaza = None
        kilometraza = None
        snaga_kw = None
        snaga_ks = None
        menjac = None

        if len(opis_items) >= 1:
            first = opis_items[0].get_text(strip=True)
            # npr. "2010. Hečbek"
            match = re.match(r'(\d{4})\.\s*(.*)', first)
            if match:
                godina_proizvodnje = match.group(1)
                karoserija = match.group(2)
        if len(opis_items) >= 2:
            second = opis_items[1].get_text(strip=True)
            # npr. "Benzin | 1490 cm3"
            if '|' in second:
                parts = second.split('|')
                gorivo = parts[0].strip()
                kub_match = re.search(r'(\d+)\s*cm', parts[1])
                kubikaza = kub_match.group(1) if kub_match else None
            else:
                gorivo = second
        if len(opis_items) >= 3:
            kilometraza = opis_items[2].get_text(strip=True)  # "180.010 km"
        if len(opis_items) >= 4:
            snaga_text = opis_items[3].get_text(strip=True)  # "84kW (114 KS)"
            kw_match = re.search(r'(\d+)\s*kW', snaga_text)
            ks_match = re.search(r'\((\d+)\s*KS\)', snaga_text)
            snaga_kw = kw_match.group(1) if kw_match else None
            snaga_ks = ks_match.group(1) if ks_match else None
        if len(opis_items) >= 5:
            menjac = opis_items[4].get_text(strip=True)  # "Manuelni 6 brzina"

        # --- Badgevi (stickeri) ---
        badge_div = article.find('div', class_=re.compile(r'Stickers'))
        badgevi = None
        if badge_div:
            badges = badge_div.find_all('div', class_=re.compile(r'Sticker'))
            badgevi = ', '.join([b.get_text(strip=True) for b in badges]) if badges else None

        # --- Stara cena / popust (nema u novoj strukturi, ostaviti prazno) ---
        stara_cena = None

        # --- Tip oglašivača (ako piše OGLAŠIVAČ -> agencija) ---
        tip_oglasivaca = 'agencija' if oglasivac and 'OGLAŠIVAČ' in oglasivac else 'fizičko lice'

        # --- Marka i model iz naslova ---
        marka = None
        model = None
        if title:
            # Pokušaj sa višerečnim brendovima
            matched_brand = None
            for mb in MULTI_WORD_BRANDS:
                if title.lower().startswith(mb.lower()):
                    matched_brand = mb
                    break
            if matched_brand:
                marka = matched_brand
                model = title[len(matched_brand):].strip()
            else:
                parts = title.split()
                if parts:
                    marka = parts[0]
                    model = ' '.join(parts[1:]).strip()

        # --- Ostali podaci (koji nedostaju) ---
        datum_skrejpa = datetime.now().strftime("%d.%m.%Y")
        datum_obnove = None  # nema u novoj strukturi

        # --- Sastavi rečnik ---
        ad_data = {
            'ID oglasa': ad_id,
            'ID vlasnika': None,          # nema u novoj strukturi
            'Oglasivac': oglasivac,
            'Opis': opis,
            'Cena': cena,
            'Datum obnove': datum_obnove,
            'URL ka detaljnom oglasu': None,  # možemo dodati ako treba
            'Marka': marka,
            'Model': model,
            'URL glavne slike': img_url,
            'Sve slike': [],               # nema lista slika u ovom prikazu
            'Godina proizvodnje': godina_proizvodnje,
            'Kilometraža': kilometraza,
            'Vrsta goriva': gorivo,
            'Menjač': menjac,
            'Zapremina motora': kubikaza,
            'Snaga motora (kW)': snaga_kw,
            'Snaga motora (KS)': snaga_ks,
            'Lokacija': lokacija,
            'Badgevi': badgevi,
            'Tip oglašivača': tip_oglasivaca,
            'Stara cena / popust': stara_cena,
            'Karoserija': karoserija,
            'Datum skrejpa': datum_skrejpa,
            'Datum prodaje': None,
        }
        return ad_data

    except Exception as e:
        print(f"    Greška pri ekstrakciji: {e}")
        return None


# ==================== ASINHRONA FUNKCIJA ZA SKREJPOVANJE ====================
async def scrape_prodato_async():
    all_ads = []
    items_per_page = 25
    base_url = "https://www.polovniautomobili.com/auto-oglasi/prodato"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # ---- 1. Učitaj prvu stranicu ----
        first_url = f"{base_url}?sort=basic"
        print(f"Učitavam prvu stranicu: {first_url}")

        # Pokušaj sa domcontentloaded
        await page.goto(first_url, wait_until="domcontentloaded", timeout=30000)

        # Opciono: sačekaj networkidle samo 5 sekundi
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except:
            pass

        # Prihvati kolačiće
        try:
            accept_btn = page.locator(
                "button:has-text('Prihvati sve'), button:has-text('Slažem se'), button:has-text('U redu')"
            ).first
            if await accept_btn.is_visible(timeout=3000):
                await accept_btn.click()
                await asyncio.sleep(1)
        except:
            pass

        # Sačekaj paginaciju
        try:
            await page.wait_for_selector("div.styles__FullPaginationWrapper-sc-e55e181b-0", timeout=15000)
        except:
            print("Nije pronađena paginacija, možda nema oglasa.")
            await browser.close()
            return []

        html = await page.content()
        soup = BeautifulSoup(html, 'lxml')

        # ---- Izvuci ukupan broj oglasa ----
        total_ads = 0
        total_small = soup.find('small', class_=re.compile(r'Show'))
        if total_small:
            text = total_small.get_text()
            match = re.search(r'ukupno\s+(\d+)', text)
            if match:
                total_ads = int(match.group(1))
                print(f"Pronađeno ukupno oglasa: {total_ads}")

        if total_ads == 0:
            print("Nije pronađen ukupan broj oglasa, pretpostavljam 25.")
            total_ads = 25

        total_pages = (total_ads + items_per_page - 1) // items_per_page
        print(f"Ukupno stranica: {total_pages}")

        # ---- 2. Petlja po stranicama (od 2 do total_pages) ----
        for page_num in range(1, total_pages + 1):
            print(f"--- SRBIJA --- Stranica {page_num} ---")

            url = f"{base_url}?sort=basic&page={page_num}"

            # Pokušaj sa ponavljanjem
            success = False
            for attempt in range(3):
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    # Opciono: kratko čekanje na networkidle
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except:
                        pass
                    success = True
                    break
                except Exception as e:
                    print(f"  Pokušaj {attempt + 1}/3 za stranicu {page_num} nije uspeo: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)

            if not success:
                print(f"  Neuspešno učitavanje stranice {page_num}, preskačem.")
                continue

            # Sačekaj oglase
            try:
                await page.wait_for_selector("article[data-testid='emptyAd']", timeout=15000)
            except:
                print(f"  Nema oglasa na stranici {page_num}, verovatno kraj.")
                break

            await asyncio.sleep(1)

            html = await page.content()
            soup = BeautifulSoup(html, 'lxml')
            articles = soup.find_all('article', {'data-testid': 'emptyAd'})

            if not articles:
                print("  Nema oglasa, kraj.")
                break

            print(f"  Pronađeno {len(articles)} oglasa.")

            for article in articles:
                ad = extract_ad_data_new(article)
                if ad:
                    all_ads.append(ad)

            if page_num < total_pages:
                await asyncio.sleep(REQUEST_DELAY)

        await browser.close()
        print(f"Ukupno prikupljeno oglasa: {len(all_ads)}")
        return all_ads


# ==================== GLAVNA ASINHRONA FUNKCIJA ====================
async def main_async():
    print("Pokrećem skrejper za prodate oglase (asinhrono)...")
    all_ads = await scrape_prodato_async()

    if not all_ads:
        print("Nijedan oglas nije pronađen. Prekidam.")
        return

    print(f"\nUkupno prikupljeno oglasa: {len(all_ads)}")
    today_str = datetime.now().strftime("%d.%m.%Y")

    # ===== 1. AŽURIRAJ GLAVNI JSON (svi oglasi) =====
    main_polovni = os.path.join(POLOVNI_FOLDER, "polovni_oglasi.json")
    if os.path.exists(main_polovni):
        update_json_with_sold(main_polovni, all_ads, today_str)

    # ===== 2. AŽURIRAJ POJEDINAČNE FAJLOVE PO MARKAMA =====
    ads_by_brand = {}
    for ad in all_ads:
        marka = ad.get('Marka')
        if not marka:
            continue
        ads_by_brand.setdefault(marka, []).append(ad)

    if os.path.exists(POLOVNI_FOLDER):
        for marka, oglasi in ads_by_brand.items():
            filename_marka = marka.replace(' ', '_')
            json_path = os.path.join(POLOVNI_FOLDER, f"{filename_marka}.json")
            if os.path.exists(json_path):
                update_json_with_sold(json_path, oglasi, today_str)
                print(f"Ažuriran fajl za marku: {marka} ({len(oglasi)} oglasa)")

    print("Završeno.")


if __name__ == "__main__":
    asyncio.run(main_async())