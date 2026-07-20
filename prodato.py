import asyncio
import os
import re
import json
from datetime import datetime
from typing import Dict, List, Optional
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup


# ==================== LOKALNE JSON FUNKCIJE (bez common.py) ====================
def load_json_data(filename: str) -> Dict:
    """Učitava JSON fajl. Ako ne postoji ili je neispravan, vraća praznu osnovnu strukturu."""
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'oglasi' not in data:
                    data['oglasi'] = {}
                if 'metadata' not in data:
                    data['metadata'] = {}
                return data
        except Exception as e:
            print(f"Greška pri učitavanju {filename}: {e}")
    return {
        "metadata": {"poslednje_azuriranje": None, "broj_oglasa": 0},
        "oglasi": {}
    }


def save_json_data(data: Dict, filename: str) -> None:
    """Snima podatke u JSON fajl i ažurira metapodatke."""
    dirname = os.path.dirname(filename)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    data['metadata']['poslednje_azuriranje'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data['metadata']['broj_oglasa'] = len(data['oglasi'])
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_json_with_sold(json_path: str, prodati_oglasi: List[Dict], today_str: str) -> None:
    """
    Ažurira JSON fajl sa prodatim oglasima.
    - Ako oglas postoji i Datum prodaje je prazan -> ažurira datum.
    - Ako oglas postoji i Datum prodaje nije prazan -> preskače.
    - Ako oglas ne postoji -> dodaje ceo oglas sa Datum prodaje = today_str.
    """
    data = load_json_data(json_path)

    novi_oglasi = 0
    azurirani_oglasi = 0
    preskoceni_oglasi = 0

    for ad in prodati_oglasi:
        ad_id = str(ad['ID oglasa'])

        if ad_id in data['oglasi']:
            postojeci_datum = data['oglasi'][ad_id].get('Datum prodaje')
            if postojeci_datum in (None, '', 'null'):
                data['oglasi'][ad_id]['Datum prodaje'] = today_str
                azurirani_oglasi += 1
            else:
                preskoceni_oglasi += 1
        else:
            ad['Datum prodaje'] = today_str
            data['oglasi'][ad_id] = ad
            novi_oglasi += 1

    if novi_oglasi > 0 or azurirani_oglasi > 0:
        save_json_data(data, json_path)
        print(f"  JSON ažuriran {json_path}: {novi_oglasi} novih, {azurirani_oglasi} ažuriranih, {preskoceni_oglasi} već prodatih.")
    else:
        print(f"  Nema promena u JSON-u {json_path} | ({preskoceni_oglasi} već prodatih).")

# ==================== KONSTANTE ====================
BASE_URL = "https://www.polovniautomobili.com"
PRODATO_URL = f"{BASE_URL}/auto-oglasi/prodato"
POLOVNI_FOLDER = "."
REQUEST_DELAY = 2
DEBUG_FOLDER = "debug"
CF_CHALLENGE_MAX_WAIT = 25
CF_CHALLENGE_POLL_INTERVAL = 2

# --- Podešavanja za posetu detaljnim stranicama ---
DETAIL_PAGE_CONCURRENCY = 3
DETAIL_REQUEST_DELAY = 1.5

# Direktorijum za čuvanje screenshotova detaljnih stranica
SCREENSHOT_DIR = os.path.join(".", "data", "slike", "SRB")

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

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['sr-RS', 'sr', 'en-US', 'en'] });
window.chrome = { runtime: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);
"""


# ==================== POMOĆNE FUNKCIJE ====================
def extract_json_ld(soup: BeautifulSoup) -> Dict[str, Dict]:
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
    try:
        ad_id = None
        detail_url = None
        data_tag = article.find('data')
        if data_tag and data_tag.get('id'):
            ad_id = data_tag['id']

        link_tag = article.find('a', {'data-testid': 'adCardDetailPageTitle'})
        if link_tag and link_tag.get('href'):
            href = link_tag['href']
            detail_url = href if href.startswith('http') else f"{BASE_URL}{href}"
            if not ad_id:
                match = re.search(r'/(\d+)/', href)
                if match:
                    ad_id = match.group(1)

        if not ad_id:
            return None

        title_elem = article.find('h2', class_=re.compile(r'DesktopTitle'))
        title = title_elem.text.strip() if title_elem else None

        price_span = article.find('span', {'data-testid': 'globalAdCardPriceTestId'})
        cena = None
        if price_span:
            cena_text = price_span.get_text(strip=True)
            cena = re.sub(r'\s*\+.*$', '', cena_text).strip()
        else:
            price_request_span = article.find('span', {'data-testid': 'adCardPriceRequest'})
            if price_request_span:
                cena = price_request_span.get_text(strip=True)

        desc_div = article.find('div', {'data-testid': 'adDescription'})
        opis_items = desc_div.find_all('div', class_=re.compile(r'AdDescItem')) if desc_div else []
        opis = ' | '.join([item.get_text(' ', strip=True) for item in opis_items]) if opis_items else None

        city_div = article.find('div', {'data-testid': 'adCardCity'})
        lokacija = city_div.get_text(strip=True) if city_div else None
        if lokacija:
            lokacija = re.sub(r'^.*?map-marker\s*', '', lokacija)

        img = article.find('img', {'data-testid': 'main-image'})
        img_url = img.get('src') or img.get('srcset', '').split()[0] if img else None

        adv_p = article.find('p', class_=re.compile(r'AdvertiserText'))
        oglasivac = adv_p.get_text(strip=True) if adv_p else None

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
            match = re.match(r'(\d{4})\.\s*(.*)', first)
            if match:
                godina_proizvodnje = match.group(1)
                karoserija = match.group(2)
        if len(opis_items) >= 2:
            second = opis_items[1].get_text(strip=True)
            if '|' in second:
                parts = second.split('|')
                gorivo = parts[0].strip()
                kub_match = re.search(r'(\d+)\s*cm', parts[1])
                kubikaza = kub_match.group(1) if kub_match else None
            else:
                gorivo = second
        if len(opis_items) >= 3:
            kilometraza = opis_items[2].get_text(strip=True)
        if len(opis_items) >= 4:
            snaga_text = opis_items[3].get_text(strip=True)
            kw_match = re.search(r'(\d+)\s*kW', snaga_text)
            ks_match = re.search(r'\((\d+)\s*KS\)', snaga_text)
            snaga_kw = kw_match.group(1) if kw_match else None
            snaga_ks = ks_match.group(1) if ks_match else None
        if len(opis_items) >= 5:
            menjac = opis_items[4].get_text(strip=True)

        badge_div = article.find('div', class_=re.compile(r'Stickers'))
        badgevi = None
        if badge_div:
            badges = badge_div.find_all('div', class_=re.compile(r'Sticker'))
            badgevi = ', '.join([b.get_text(strip=True) for b in badges]) if badges else None

        stara_cena = None
        tip_oglasivaca = 'agencija' if oglasivac and 'OGLAŠIVAČ' in oglasivac else 'fizičko lice'

        marka = None
        model = None
        if title:
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

        datum_skrejpa = datetime.now().strftime("%d.%m.%Y")
        datum_obnove = None

        ad_data = {
            'ID oglasa': ad_id,
            'ID vlasnika': None,
            'Oglasivac': oglasivac,
            'Opis': opis,
            'Cena': cena,
            'Datum obnove': datum_obnove,
            'URL ka detaljnom oglasu': detail_url,
            'Marka': marka,
            'Model': model,
            'URL glavne slike': img_url,
            'Sve slike': [],
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
            'Datum prodaje': datum_skrejpa,
        }
        return ad_data

    except Exception as e:
        print(f"    Greška pri ekstrakciji: {e}")
        return None


async def accept_cookies_if_present(page):
    try:
        accept_btn = page.locator(
            "button:has-text('Prihvati sve'), button:has-text('Slažem se'), button:has-text('U redu')"
        ).first
        if await accept_btn.is_visible(timeout=2000):
            await accept_btn.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass


def is_cloudflare_challenge(html: str) -> bool:
    if not html:
        return False
    markers = [
        "Just a moment",
        "cf-chl",
        "Performing security verification",
        "challenges.cloudflare.com",
        "cf_chl_opt",
    ]
    return any(m in html for m in markers)


async def wait_out_cloudflare_challenge(page, page_num: int) -> bool:
    waited = 0
    while waited < CF_CHALLENGE_MAX_WAIT:
        html = await page.content()
        if not is_cloudflare_challenge(html):
            return True
        print(f"  [Cloudflare] Challenge detektovan na strani {page_num}, čekam... ({waited}s)")
        await asyncio.sleep(CF_CHALLENGE_POLL_INTERVAL)
        waited += CF_CHALLENGE_POLL_INTERVAL
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

    html = await page.content()
    return not is_cloudflare_challenge(html)


async def save_debug_snapshot(page, page_num: int, reason: str):
    try:
        os.makedirs(DEBUG_FOLDER, exist_ok=True)
        safe_reason = re.sub(r'[^A-Za-z0-9_\-\.]', '_', reason)
        html = await page.content()
        html_path = os.path.join(DEBUG_FOLDER, f"page_{page_num}_{safe_reason}.html")
        png_path = os.path.join(DEBUG_FOLDER, f"page_{page_num}_{safe_reason}.png")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        await page.screenshot(path=png_path, full_page=True)
        print(f"  [DEBUG] Sačuvano: {html_path} i {png_path}")
    except Exception as e:
        print(f"  [DEBUG] Nisam uspeo da sačuvam debug snapshot: {e}")


async def goto_and_survive_cloudflare(page, url: str, page_num: int) -> bool:
    await page.goto(url, wait_until="domcontentloaded", timeout=5000)
    try:
        await page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass

    html = await page.content()
    if is_cloudflare_challenge(html):
        ok = await wait_out_cloudflare_challenge(page, page_num)
        if not ok:
            print(f"  [Cloudflare] Challenge NIJE prošao na strani {page_num} ni posle {CF_CHALLENGE_MAX_WAIT}s.")
            await save_debug_snapshot(page, page_num, "cf_challenge_stuck")
            return False
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

    return True


# ==================== PARSIRANJE DETALJNE STRANICE OGLASA ====================
DETAIL_FIELD_MAP = {
    'Stanje': 'Stanje',
    'Marka': 'Marka',
    'Model': 'Model',
    'Fiksna cena': 'Fiksna cena',
    'Zamena': 'Zamena',
    'Emisiona klasa motora': 'Emisiona klasa motora',
    'Pogon': 'Pogon',
    'Menjač': 'Menjač',
    'Broj vrata': 'Broj vrata',
    'Broj sedišta': 'Broj sedišta',
    'Strana volana': 'Strana volana',
    'Klima': 'Klima',
    'Boja': 'Boja',
    'Materijal enterijera': 'Materijal enterijera',
    'Boja enterijera': 'Boja enterijera',
    'Registrovan do': 'Registrovan do',
    'Poreklo vozila': 'Poreklo vozila',
    'Oštećenje': 'Oštećenje',
}


def _extract_raw_info_card_items(soup: BeautifulSoup) -> Dict[str, str]:
    for mobile_div in soup.find_all('div', attrs={'display': 'mobile'}):
        mobile_div.decompose()

    raw = {}
    items = soup.find_all('div', class_=re.compile(r'InfoCardListItem'))
    for item in items:
        key_span = item.find('span', class_=re.compile(r'ItemKey'))
        val_span = item.find('span', class_=re.compile(r'ItemValue'))
        if not key_span or not val_span:
            continue
        key = key_span.get_text(strip=True).rstrip(':').strip()
        value = val_span.get_text(strip=True)
        if key and key not in raw:
            raw[key] = value
    return raw


def parse_ad_detail_page(html: str) -> Dict:
    soup = BeautifulSoup(html, 'lxml')
    raw = _extract_raw_info_card_items(soup)

    result = {}
    for raw_key, out_key in DETAIL_FIELD_MAP.items():
        if raw_key in raw:
            result[out_key] = raw[raw_key]

    if 'Godište' in raw:
        result['Godina proizvodnje'] = raw['Godište'].rstrip('.').strip()

    if 'Kilometraža' in raw:
        km_match = re.search(r'([\d.]+)', raw['Kilometraža'])
        result['Kilometraža'] = f"{km_match.group(1)} km" if km_match else raw['Kilometraža']

    if 'Karoserija' in raw:
        result['Karoserija'] = raw['Karoserija']

    if 'Gorivo' in raw:
        result['Vrsta goriva'] = raw['Gorivo']

    if 'Kubikaža' in raw:
        kub_match = re.search(r'(\d+)', raw['Kubikaža'])
        result['Zapremina motora'] = kub_match.group(1) if kub_match else raw['Kubikaža']

    if 'Snaga motora' in raw:
        snaga_match = re.search(r'(\d+)\s*/\s*(\d+)', raw['Snaga motora'])
        if snaga_match:
            result['Snaga motora (kW)'] = snaga_match.group(1)
            result['Snaga motora (KS)'] = snaga_match.group(2)

    if 'Broj oglasa' in raw:
        result['Broj oglasa (potvrda sa stranice)'] = raw['Broj oglasa']

    if 'Datum objave' in raw:
        result['Datum objave'] = raw['Datum objave']

    return result


async def fetch_ad_detail_data(context, url: str, label: str, ad_id: Optional[str] = None) -> Optional[Dict]:
    """
    Otvara detaljnu stranicu jednog oglasa u novom tabu, parsira podatke
    i (opciono) snima screenshot cele stranice.
    """
    page = await context.new_page()
    try:
        ok = await goto_and_survive_cloudflare(page, url, page_num=label)
        if not ok:
            print(f"  [{label}] Cloudflare nije prošao za detaljnu stranicu: {url}")
            return None

        try:
            await page.wait_for_selector(
                "span[class*='ItemKey'], span[data-testid='panelInfoTitle']",
                timeout=6000,
            )
        except Exception:
            pass

        html = await page.content()
        detail = parse_ad_detail_page(html)
        if not detail:
            print(f"  [{label}] Nisu pronađeni InfoCard podaci na: {url}")
            await save_debug_snapshot(page, 0, f"detail_empty_{label}")

        # Snimanje screenshot-a detaljne stranice
        if ad_id and detail is not None:
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            screenshot_filename = f"ad_{ad_id}.png"
            screenshot_path = os.path.join(SCREENSHOT_DIR, screenshot_filename)
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
                # Putanja u JSON zapisu sa forward slash-ovima (univerzalno)
                detail['Slika detaljne stranice'] = f"data/slike/SRB/{screenshot_filename}"
            except Exception as e:
                print(f"  [{label}] Greška pri čuvanju screenshot-a: {e}")

        return detail
    except Exception as e:
        print(f"  [{label}] Greška pri obradi detaljne stranice {url}: {e}")
        return None
    finally:
        await page.close()


async def fetch_all_ad_details(context, ads: List[Dict]) -> None:
    total = len(ads)
    print(f"\nPosećujem {total} detaljnih stranica oglasa radi tačnih podataka "
          f"(marka/model/godište/km/gorivo/menjač/...)...")

    semaphore = asyncio.Semaphore(DETAIL_PAGE_CONCURRENCY)
    completed = 0
    lock = asyncio.Lock()

    async def worker(idx: int, ad: Dict):
        nonlocal completed
        url = ad.get('URL ka detaljnom oglasu')
        if not url:
            async with lock:
                completed += 1
            return

        ad_id = ad.get('ID oglasa')
        async with semaphore:
            detail = await fetch_ad_detail_data(context, url, label=f"{idx + 1}/{total}", ad_id=ad_id)
            if detail:
                ad.update(detail)
            await asyncio.sleep(DETAIL_REQUEST_DELAY)

        async with lock:
            completed += 1
            status = "OK" if detail else "NEUSPEŠNO"
            print(f"  [{completed}/{total}] {status}: "
                  f"{ad.get('Marka')} {ad.get('Model')} ({ad.get('Godina proizvodnje')}) - ID {ad.get('ID oglasa')}")

    await asyncio.gather(*(worker(i, ad) for i, ad in enumerate(ads)))


async def scrape_prodato_async():
    all_ads = []
    items_per_page = 25
    base_url = "https://www.polovniautomobili.com/auto-oglasi/prodato"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="sr-RS",
            timezone_id="Europe/Belgrade",
        )
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        page = await context.new_page()

        first_url = f"{base_url}?sort=basic"
        print(f"Učitavam prvu stranicu: {first_url}")

        ok = await goto_and_survive_cloudflare(page, first_url, page_num=1)
        if not ok:
            print("Cloudflare challenge blokirao prvu stranicu. Prekidam.")
            await browser.close()
            return []

        await accept_cookies_if_present(page)

        try:
            await page.wait_for_selector("div.styles__FullPaginationWrapper-sc-e55e181b-0", timeout=5000)
        except Exception:
            print("Nije pronađena paginacija, možda nema oglasa.")
            await save_debug_snapshot(page, 1, "no_pagination")
            await browser.close()
            return []

        html = await page.content()
        soup = BeautifulSoup(html, 'lxml')

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

        for page_num in range(1, total_pages + 1):
            print(f"--- SRBIJA --- Stranica {page_num} ---")
            url = f"{base_url}?sort=basic&page={page_num}"

            success = False
            for attempt in range(3):
                try:
                    ok = await goto_and_survive_cloudflare(page, url, page_num)
                    if ok:
                        success = True
                        break
                    else:
                        print(f"  Pokušaj {attempt + 1}/3: Cloudflare challenge nije prošao na strani {page_num}.")
                except Exception as e:
                    print(f"  Pokušaj {attempt + 1}/3 za stranicu {page_num} nije uspeo: {e}")

                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)

            if not success:
                print(f"  Neuspešno učitavanje stranice {page_num} (Cloudflare/mreža), preskačem na sledeću.")
                continue

            await accept_cookies_if_present(page)

            try:
                await page.wait_for_selector("article[class*='DesktopView']", timeout=5000)
            except Exception:
                print(f"  Selector za oglase nije pronađen na stranici {page_num}, proveravam ipak sadržaj.")

            await asyncio.sleep(1)

            html = await page.content()
            soup = BeautifulSoup(html, 'lxml')
            articles = soup.find_all('article', class_=re.compile(r'DesktopView'))

            if not articles:
                print(f"  Nema oglasa na stranici {page_num}, nastavljam na sledeću stranicu.")
                await save_debug_snapshot(page, page_num, "empty")
                if page_num < total_pages:
                    await asyncio.sleep(REQUEST_DELAY)
                continue

            print(f"  Pronađeno {len(articles)} elemenata oglasa.")

            expected_count = items_per_page if page_num < total_pages else None
            if expected_count is not None and len(articles) != expected_count:
                print(f"  [UPOZORENJE] Očekivano {expected_count} oglasa na strani {page_num}, "
                      f"pronađeno {len(articles)}. Snimam celu stranicu i spisak svih <article> tagova.")
                await save_debug_snapshot(page, page_num, "count_mismatch")
                all_article_tags = soup.find_all('article')
                print(f"    Ukupno <article> tagova na strani (bilo kog testid-a): {len(all_article_tags)}")
                try:
                    os.makedirs(DEBUG_FOLDER, exist_ok=True)
                    diff_path = os.path.join(DEBUG_FOLDER, f"page_{page_num}_all_articles_testids.txt")
                    with open(diff_path, "w", encoding="utf-8") as f:
                        for i, art in enumerate(all_article_tags):
                            f.write(f"[{i + 1}] data-testid={art.get('data-testid')!r} class={art.get('class')!r}\n")
                    print(f"    Sačuvan spisak svih <article> testid-ova: {diff_path}")

                    for i, art in enumerate(all_article_tags):
                        if art.get('data-testid') != 'emptyAd':
                            odd_path = os.path.join(
                                DEBUG_FOLDER, f"page_{page_num}_odd_article_{i + 1}.html"
                            )
                            with open(odd_path, "w", encoding="utf-8") as f:
                                f.write(str(art))
                            print(f"    Sačuvan HTML 'sumnjivog' article-a: {odd_path}")
                except Exception as e:
                    print(f"    Greška pri čuvanju debug spiska: {e}")

            extracted_count = 0
            for idx, article in enumerate(articles):
                ad = extract_ad_data_new(article)
                if ad:
                    all_ads.append(ad)
                    extracted_count += 1
                else:
                    print(f"  [UPOZORENJE] Element #{idx + 1} na strani {page_num} nije ekstrahovan "
                          f"(verovatno promo/banner blok bez ID-ja oglasa, ne pravi oglas).")
                    try:
                        os.makedirs(DEBUG_FOLDER, exist_ok=True)
                        snippet_path = os.path.join(
                            DEBUG_FOLDER, f"page_{page_num}_unparsed_element_{idx + 1}.html"
                        )
                        with open(snippet_path, "w", encoding="utf-8") as f:
                            f.write(str(article))
                        print(f"    Sačuvan HTML tog bloka radi provere: {snippet_path}")
                    except Exception as e:
                        print(f"    Nisam uspeo da sačuvam HTML bloka: {e}")

            print(f"  Uspešno ekstrahovano {extracted_count}/{len(articles)} oglasa sa stranice {page_num}.")

            if page_num < total_pages:
                await asyncio.sleep(REQUEST_DELAY)

        print(f"Prikupljeno {len(all_ads)} oglasa sa liste. Sada slede posete detaljnim stranicama...")

        main_polovni_path = os.path.join(POLOVNI_FOLDER, "polovni_oglasi.json")
        existing_ids = set(load_json_data(main_polovni_path).get('oglasi', {}).keys())
        if existing_ids:
            print(f"  Pronađeno {len(existing_ids)} već poznatih ID-jeva u {main_polovni_path}.")

        new_ads = [ad for ad in all_ads if str(ad.get('ID oglasa')) not in existing_ids]
        already_known = len(all_ads) - len(new_ads)
        print(f"  Novih oglasa (posećujem detalje): {len(new_ads)}   |   "
              f"Već poznatih (preskačem posetu): {already_known}")

        await fetch_all_ad_details(context, new_ads)

        await browser.close()
        print(f"Ukupno prikupljeno oglasa: {len(all_ads)}")
        return all_ads


async def main_async():
    print("Pokrećem skrejper za prodate oglase (asinhrono)...")
    all_ads = await scrape_prodato_async()

    if not all_ads:
        print("Nijedan oglas nije pronađen. Prekidam.")
        return

    print(f"\nUkupno prikupljeno oglasa: {len(all_ads)}")
    today_str = datetime.now().strftime("%d.%m.%Y")

    main_polovni = os.path.join(POLOVNI_FOLDER, "polovni_oglasi.json")
    if os.path.exists(main_polovni):
        update_json_with_sold(main_polovni, all_ads, today_str)

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