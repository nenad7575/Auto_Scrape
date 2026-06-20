import asyncio
import re
import random
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
# from config_loader import ScraperConfig, DEFAULT_MODELI
# from stealth_manager import stealth_manager
# from retry_decorator import retry_with_backoff
import unicodedata
from dataclasses import dataclass

BASE_URL = "https://www.avto.net"
SEARCH_URL = f"{BASE_URL}/Ads/results.asp"

# VIEWPORTS sada dolaze iz stealth_manager-a
VIEWPORTS = stealth_manager.VIEWPORTS

FIELDNAMES = [
    'ID oglasa', 'ID vlasnika', 'Oglasivac', 'Opis', 'Cena', 'Datum obnove',
    'URL ka detaljnom oglasu', 'Marka', 'Model', 'URL glavne slike', 'Sve slike',
    'Godina proizvodnje', 'Kilometraža', 'Vrsta goriva', 'Menjač',
    'Zapremina motora', 'Snaga motora (kW)', 'Snaga motora (KS)', 'Lokacija',
    'Badgevi', 'Tip oglašivača', 'Stara cena / popust', 'Karoserija',
    'Datum skrejpa', 'Datum prodaje', 'Broj pregleda', 'Potrosnja', 'Emisijski razred', 'Boja', 'Enterijer', 'VIN'
]


@dataclass
class BrowserFingerprint:
    """Represents a unique browser fingerprint."""
    user_agent: str
    viewport: Dict[str, int]
    locale: str
    timezone_id: str
    device_scale_factor: float
    has_touch: bool
    is_mobile: bool
    color_scheme: str

@dataclass
class ScraperConfig:
    """Konfiguraciona klasa za Avto.net skrejper."""
    brands: Dict[str, Optional[List[str]]]
    filters: Dict[str, int]
    settings: Dict[str, Any]
    
    @classmethod
    def from_json(cls, path: str) -> 'ScraperConfig':
        """Učitava konfiguraciju iz JSON fajla sa validacijom."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Konfiguracioni fajl nije pronađen: {path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validacija strukture
        brands = data.get('brands')
        filters = data.get('filters', {})
        settings = data.get('settings', {})
        
        # Default vrednosti za filters
 

def load_json(filename: str) -> Dict:
    """
    Učitava JSON fajl. Ako fajl ne postoji, vraća osnovnu strukturu:
    {
        "metadata": {
            "poslednje_azuriranje": None,
            "broj_oglasa": 0
        },
        "oglasi": {}
    }
    """
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Osiguraj da postoji 'oglasi' ključ
                if 'oglasi' not in data:
                    data['oglasi'] = {}
                if 'metadata' not in data:
                    data['metadata'] = {}
                return data
        except Exception as e:
            print(f"Greška pri učitavanju {filename}: {e}")

    # Default struktura
    return {
        "metadata": {
            "poslednje_azuriranje": None,
            "broj_oglasa": 0
        },
        "oglasi": {}
    }


def remove_missing_ads(file_path: str, active_ids: set, today_str: str) -> None:
    """
    Briše oglase koji nisu u active_ids iz JSON fajla.

    Args:
        file_path: Putanja do JSON fajla
        active_ids: Set aktivnih ID-eva oglasa
        today_str: Današnji datum kao string
    """
    data = load_json(file_path)
    existing_ads = data.get('oglasi', {})

    # Pronađi ID-jeve koji nedostaju
    missing_ids = set(existing_ads.keys()) - active_ids

    if missing_ids:
        for ad_id in missing_ids:
            del existing_ads[ad_id]
        data['oglasi'] = existing_ads
        data['metadata']['zadnji_skrejp'] = today_str
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  Obrisano {len(missing_ids)} oglasa iz {file_path}")
    else:
        print(f"  Nema oglasa za brisanje u {file_path}")


def retry_with_backoff(max_retries: int = 3, base_delay: float = 10.0):
    """
    Decorator that retries an async function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds between retries (will be multiplied by 2^attempt)
    
    Example:
        @retry_with_backoff(max_retries=3, base_delay=10)
        async def fetch_data():
            # Your async code here
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # Don't retry on the last attempt
                    if attempt == max_retries - 1:
                        logger.error(f"Function {func.__name__} failed after {max_retries} attempts: {e}")
                        raise
                    
                    # Calculate backoff delay
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Function {func.__name__} failed (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay} seconds..."
                    )
                    await asyncio.sleep(delay)
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
                
        return wrapper
    return decorator


def normalize(text):
    return ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )


def update_json_with_details(file_path: str, scraped_ads: List[Dict], today_str: str):
    data = load_json(file_path)
    existing_ads = data.get('oglasi', {})

    for ad in scraped_ads:
        ad_id = str(ad['ID oglasa'])
        if not ad_id:
            continue

        danasnji_pregledi = ad.pop('_današnji_pregledi', 0)
        zadnja_sprememba = ad.pop('_zadnja_sprememba', None)

        if ad_id in existing_ads:
            old = existing_ads[ad_id]
            if ad.get('Cena'):
                old['Cena'] = ad['Cena']
            stari_broj = old.get('Broj pregleda', 0)
            old['Broj pregleda'] = stari_broj + danasnji_pregledi
            if old.get('Datum obnove') is None and zadnja_sprememba:
                old['Datum obnove'] = zadnja_sprememba
            stara_lok = old.get('Lokacija')
            nova_lok = ad.get('Lokacija')
            if nova_lok and (not stara_lok or stara_lok == '/'):
                old['Lokacija'] = nova_lok
            if ad.get('Karoserija'):
                old['Karoserija'] = ad['Karoserija']
            if ad.get('Boja'):
                old['Boja'] = ad['Boja']
            if ad.get('Enterijer'):
                old['Enterijer'] = ad['Enterijer']
            if ad.get('Potrosnja'):
                old['Potrosnja'] = ad['Potrosnja']
            if ad.get('Emisijski razred'):
                old['Emisijski razred'] = ad['Emisijski razred']
            if ad.get('Sve slike'):
                old['Sve slike'] = ad['Sve slike']
            if ad.get('URL glavne slike'):
                old['URL glavne slike'] = ad['URL glavne slike']
            if ad.get('VIN'):
                old['VIN'] = ad['VIN']
        else:
            new_ad = ad.copy()
            new_ad['Broj pregleda'] = danasnji_pregledi
            if zadnja_sprememba and not new_ad.get('Datum obnove'):
                new_ad['Datum obnove'] = zadnja_sprememba
            existing_ads[ad_id] = new_ad

    data['oglasi'] = existing_ads
    data['metadata']['zadnji_skrejp'] = today_str
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Ažuriran fajl: {file_path}")


async def extract_ad_data_avto(ad_element, brand: str) -> Optional[Dict]:
    try:
        link_element = await ad_element.query_selector('a.stretched-link')
        link = await link_element.get_attribute('href') if link_element else ""
        ad_id = None
        if link:
            id_match = re.search(r'ID=(\d+)', link, re.IGNORECASE)
            if id_match:
                ad_id = id_match.group(1)
            if not link.startswith('http'):
                if link.startswith('/'):
                    link = BASE_URL + link
                else:
                    link = f"{BASE_URL}/Ads/{link}"

        title_element = await ad_element.query_selector('div.GO-Results-Naziv span')
        title = await title_element.text_content() if title_element else ""
        title = normalize(title.strip() if title else None)

        model = None
        if title and title.lower().startswith(brand.lower()):
            ostatak = title[len(brand):].strip()
            if ostatak:
                model = ostatak.split()[0]

        img_element = await ad_element.query_selector('div.GO-Results-Top-Photo img, div.GO-Results-Photo img')
        img_url = await img_element.get_attribute('src') if img_element else None

        cena_info = await extract_price_avto(ad_element)
        cena = cena_info.get('cena')
        stara_cena = cena_info.get('stara_cena')
        stara_cena_popust = f"{stara_cena} -> {cena}" if stara_cena and cena else None

        logo_div = await ad_element.query_selector('div.GO-Results-Logo, div.GO-Results-Top-Logo')
        oglasivac = None
        tip_oglasivaca = None
        id_vlasnika = None
        if logo_div:
            img = await logo_div.query_selector('img')
            if img:
                src = await img.get_attribute('src')
                if src and 'blank.gif' in src:
                    tip_oglasivaca = 'fizičko lice'
                else:
                    tip_oglasivaca = 'agencija'
                oglasivac = await img.get_attribute('alt') or await img.get_attribute('title')
                link_a = await logo_div.query_selector('a')
                if link_a:
                    href = await link_a.get_attribute('href')
                    if href:
                        broker_match = re.search(r'broker=(\d+)', href)
                        if broker_match:
                            id_vlasnika = broker_match.group(1)

        opis = None
        comment_div = await ad_element.query_selector('div.alert.GO-bg-graylight')
        if comment_div:
            opis = await comment_div.text_content()
            opis = opis.strip()

        badgevi = []
        top_badge = await ad_element.query_selector('div.GO-Results-Top-BadgeTop')
        if top_badge:
            badgevi.append((await top_badge.text_content()).strip())
        hd_badge = await ad_element.query_selector('div.GO-Results-Top-BadgeHD')
        if hd_badge:
            badgevi.append((await hd_badge.text_content()).strip())
        video_badge = await ad_element.query_selector('div.GO-Results-Top-BadgeHDVideo')
        if video_badge:
            badgevi.append((await video_badge.text_content()).strip())
        ribbon = await ad_element.query_selector('div.GO-ResultsRibbon')
        if ribbon:
            badgevi.append((await ribbon.text_content()).strip())
        badgevi_str = ', '.join(badgevi) if badgevi else None

        table = await ad_element.query_selector('table.table')
        godina = kilometraza = gorivo = menjalnik = snaga_kw = snaga_ks = kubikaza = None
        if table:
            rows = await table.query_selector_all('tbody tr')
            for row in rows:
                cells = await row.query_selector_all('td')
                if len(cells) < 2:
                    continue
                key = (await cells[0].text_content()).strip().lower()
                value = (await cells[1].text_content()).strip()
                if any(x in key for x in ['1.registracija', 'prva registracija', 'letnik', 'god']):
                    godina = value
                elif any(x in key for x in ['prevoženih', 'kilometrov', 'km']):
                    kilometraza = value
                elif 'gorivo' in key:
                    gorivo = value
                elif any(x in key for x in ['menjalnik', 'tip menjalnika', 'pogon']):
                    menjalnik = value
                elif 'motor' in key:
                    kw_match = re.search(r'(\d+)\s*kW', value)
                    if kw_match:
                        snaga_kw = kw_match.group(1)
                    ks_match = re.search(r'(\d+)\s*KM', value)
                    if ks_match:
                        snaga_ks = ks_match.group(1)
                    ccm_match = re.search(r'(\d+)\s*ccm', value)
                    if ccm_match:
                        kubikaza = ccm_match.group(1)

        datum_skrejpa = datetime.now().strftime("%d.%m.%Y")

        ad_data = {
            'ID oglasa': ad_id,
            'ID vlasnika': id_vlasnika,
            'Oglasivac': oglasivac,
            'Opis': opis,
            'Cena': cena,
            'Datum obnove': None,
            'URL ka detaljnom oglasu': link,
            'Marka': brand.upper(),
            'Model': model,
            'URL glavne slike': img_url,
            'Sve slike': [],
            'Godina proizvodnje': godina,
            'Kilometraža': kilometraza,
            'Vrsta goriva': gorivo,
            'Menjač': menjalnik,
            'Zapremina motora': kubikaza,
            'Snaga motora (kW)': snaga_kw,
            'Snaga motora (KS)': snaga_ks,
            'Lokacija': None,
            'Badgevi': badgevi_str,
            'Tip oglašivača': tip_oglasivaca,
            'Stara cena / popust': stara_cena_popust,
            'Karoserija': None,
            'VIN': None,
            'Datum skrejpa': datum_skrejpa,
            'Datum prodaje': None,
            'Broj pregleda': 0,
            'Potrosnja': None,
            'Emisijski razred': None,
            'Boja': None,
            'Enterijer': None,
        }
        return ad_data
    except Exception as e:
        print(f"    Greška pri ekstrakciji: {e}")
        return None


async def extract_price_avto(ad_element) -> Dict[str, Optional[str]]:
    price_container = await ad_element.query_selector('div.GO-Results-Price, div.GO-Results-Top-Price')
    if not price_container:
        return {'cena': None, 'stara_cena': None}
    stara_cena = None
    cena = None
    stara_elem = await price_container.query_selector('div.GO-Results-Price-TXT-StaraCena')
    akcija_elem = await price_container.query_selector('div.GO-Results-Price-TXT-AkcijaCena')
    if stara_elem and akcija_elem:
        stara_cena = await stara_elem.text_content()
        cena = await akcija_elem.text_content()
    else:
        regular_elem = await price_container.query_selector('div.GO-Results-Top-Price-TXT-Regular')
        akcija_elem = await price_container.query_selector('div.GO-Results-Top-Price-TXT-AkcijaCena')
        if regular_elem and akcija_elem:
            stara_cena = await regular_elem.text_content()
            cena = await akcija_elem.text_content()
        else:
            regular = await price_container.query_selector('div.GO-Results-Price-TXT-Regular')
            if not regular:
                regular = await price_container.query_selector('div.GO-Results-Top-Price-TXT-Regular')
            if regular:
                cena = await regular.text_content()
            else:
                all_text = await price_container.text_content()
                match = re.search(r'([\d\.]+\s*€)', all_text)
                if match:
                    cena = match.group(1)
    if stara_cena:
        stara_cena = stara_cena.strip()
    if cena:
        cena = cena.strip()
    return {'cena': cena, 'stara_cena': stara_cena}


@retry_with_backoff(max_retries=3, base_delay=10)
async def fetch_ad_details(context, ad: Dict) -> Optional[Dict]:
    """Otvara stranicu detalja oglasa i prikuplja dodatne informacije."""
    page = None
    try:
        viewport = stealth_manager.rotate_viewport()
        page = await context.new_page()
        await page.set_viewport_size(viewport)
        await stealth_async(page)

        url = ad['URL ka detaljnom oglasu']
        print(f"    Pristupam: {url}")
        response = await page.goto(url, wait_until='domcontentloaded', timeout=3000)
        status = response.status if response else 0

        if status == 403:
            print(f"    -> 403 Forbidden - verovatno blokada, preskačem.")
            return None
        if status != 200:
            print(f"    -> Oglas nije dostupan (status {status})")
            return None

        await asyncio.sleep(2)

        body_text = await page.text_content('body')
        if 'Oglas ne obstaja' in body_text or 'ne obstaja' in body_text:
            print(f"    -> Oglas {ad.get('ID oglasa')} ne postoji")
            return None

        selectors = ['div.container.bg-white', 'div.GO-Rounded-B', 'div.container.p-0']
        found = False
        for selector in selectors:
            try:
                await page.wait_for_selector(selector, timeout=5000)
                found = True
                break
            except:
                continue
        if not found:
            print(f"    -> Nema poznatog kontejnera")
            return None

        # ========== 1. EKSTRAKCIJA IZ JavaScript VARIJABLI (najpouzdanije) ==========
        html = await page.content()

        # Marka (znamka)
        make_match = re.search(r"var AdBMake='znamka:([^,]+),';", html)
        if make_match:
            marka = make_match.group(1).strip()
            ad['Marka'] = marka.upper()
            # print(f"    -> Marka iz JS: {marka}")

        # Model (model) - podržava višerečne modele (npr. "Grand Scenic")
        model_match = re.search(r"var AdBModel='model:([^,]+),';", html)
        if model_match:
            model = model_match.group(1).strip()
            ad['Model'] = model
            # print(f"    -> Model iz JS: {model}")

        # Karoserija (karoserija) - opciono, brojčani kod
        karoserija_kod_match = re.search(r"var AdBKaroserija='karoserija:(\d+),';", html)
        if karoserija_kod_match:
            ad['_karoserija_kod'] = karoserija_kod_match.group(1)

        # Gorivo (gorivo) - opciono, brojčani kod
        gorivo_kod_match = re.search(r"var AdBGorivo='gorivo:(\d+),';", html)
        if gorivo_kod_match:
            ad['_gorivo_kod'] = gorivo_kod_match.group(1)

        # ========== 2. SVE SLIKE ==========
        image_urls = []
        lightgallery = await page.query_selector('#lightgallery')
        if lightgallery:
            img_ps = await lightgallery.query_selector_all('p[data-src]')
            for p in img_ps:
                src = await p.get_attribute('data-src')
                if src:
                    image_urls.append(src)
        if not image_urls:
            img_elements = await page.query_selector_all('img.GO-OglasPhotoSharp')
            for img in img_elements:
                src = await img.get_attribute('src')
                if src:
                    image_urls.append(src)
        ad['Sve slike'] = image_urls
        # print(f"    -> Prikupljeno slika: {len(image_urls)}")

        # ========== 3. PODACI IZ TABELE (osnovni podaci) ==========
        rows = await page.query_selector_all('table.table tbody tr')

        for row in rows:
            th = await row.query_selector('th')
            td = await row.query_selector('td')
            if not th or not td:
                continue

            key = (await th.text_content()).strip().lower()
            value = (await td.text_content()).strip()

            if 'oblika' in key:
                ad['Karoserija'] = value
                # print(f"    -> Karoserija: {value}")
            elif 'barva' in key:
                ad['Boja'] = value
                # print(f"    -> Boja: {value}")
            elif 'notranjost' in key:
                ad['Enterijer'] = value
                # print(f"    -> Enterijer: {value}")
            elif 'kraj ogleda' in key:
                if value and value != '':
                    ad['Lokacija'] = value
                    # print(f"    -> Lokacija: {value}")
            elif 'vin' in key or 'številka šasije' in key:
                ad['VIN'] = value
                # print(f"    -> VIN: {value}")
            # Ako tabela ima i model (kao fallback ako JS varijabla nije pronađena)
            elif 'model' in key and not ad.get('Model'):
                ad['Model'] = value
                # print(f"    -> Model iz tabele: {value}")

        # Ako lokacija nije pronađena, postavi na '/'
        if not ad.get('Lokacija'):
            ad['Lokacija'] = '/'

        # ========== 4. POTROŠNJA I EMISIJA (WLTP tabela) ==========
        wlpt_tables = await page.query_selector_all('table.table-sm')
        for table in wlpt_tables:
            thead = await table.query_selector('thead.thead-light')
            if thead:
                header_text = await thead.text_content()
                if 'NEDC' in header_text:
                    rows_w = await table.query_selector_all('tbody tr')
                    for r in rows_w:
                        th = await r.query_selector('th')
                        td = await r.query_selector('td')
                        if th and td:
                            key = (await th.text_content()).strip().lower()
                            val = (await td.text_content()).strip()
                            if 'kombinirana vožnja' in key and val and val != '/':
                                ad['Potrosnja'] = val
                                # print(f"    -> Potrošnja: {val}")
                            elif 'emisijski razred' in key:
                                ad['Emisijski razred'] = val
                                # print(f"    -> Emisijski razred: {val}")
                    break

        # ========== 5. BROJ PREGLEDA I DATUM IZMENE ==========
        stats_div = await page.query_selector('div.container.p-0.pb-2.GO-bg-graylight')
        if stats_div:
            text = await stats_div.text_content()

            # Broj pregleda
            match = re.search(r'Ogledov oglasa / danes:\s*(\d+)', text)
            if match:
                ad['_današnji_pregledi'] = int(match.group(1))
                # print(f"    -> Današnji pregledi: {ad['_današnji_pregledi']}")
            else:
                ad['_današnji_pregledi'] = 0

            # Datum zadnje spremembe
            match = re.search(r'Zadnja sprememba:\s*(\d+\.\d+\.\d+)', text)
            if match:
                zadnja = match.group(1)
                parts = zadnja.split('.')
                if len(parts) == 3:
                    dan = parts[0].zfill(2)
                    mesec = parts[1].zfill(2)
                    godina = parts[2]
                    ad['_zadnja_sprememba'] = f"{dan}.{mesec}.{godina}"
                    # print(f"    -> Zadnja sprememba: {ad['_zadnja_sprememba']}")
        else:
            ad['_današnji_pregledi'] = 0

        # ========== 6. CENA SA STRANICE DETALJA ==========
        price_div = await page.query_selector('div.card-body.p-0 p.h2.font-weight-bold')
        if price_div:
            cena_text = await price_div.text_content()
            match = re.search(r'([\d\.]+)\s*€', cena_text)
            if match:
                nova_cena = match.group(1).replace('.', '')
                ad['Cena'] = nova_cena
                # print(f"    -> Cena sa detalja: {nova_cena} €")

        print(f"    -> Uspešno prikupljeni detalji za oglas {ad.get('ID oglasa')}")
        return ad

    except Exception as e:
        print(f"    Greška za oglas {ad.get('ID oglasa')}: {e}")
        return None
    finally:
        if page:
            await page.close()


@retry_with_backoff(max_retries=3, base_delay=10)
async def scrape_avto_net(
        config: Optional[ScraperConfig] = None,
        config_path: str = "scraper/scraper_config.json",
        output_file: str = "data/podaci.json",


) -> List[Dict]:
    """
    Skrejpovanje oglasa sa Avto.net sa konfiguracionim fajlom.
    """
    print('Skrejpovanje oglasa sa Avto.net (lista + detalji) - AŽURIRANJE')

    # Učitaj konfiguraciju
    if config is None:
        try:
            config = ScraperConfig.from_json(config_path)
            print(f"Konfiguracija učitana iz: {config_path}")
        except FileNotFoundError:
            print(f"Konfiguracioni fajl {config_path} nije pronađen, koristim default vrednosti.")
            config = ScraperConfig(
                brands=DEFAULT_MODELI,
                filters={'year_from': 2015, 'year_to': 2024, 'price_min': 1, 'price_max': 6000},
                settings={'delay_between_requests': 10, 'headless': True, 'max_pages': 1500}
            )
    else:
        print("Koristim prosleđeni ScraperConfig (preskačem učitavanje iz fajla).")

    # Izvuči parametre iz konfiguracije
    brands_config = config.get_brands_to_scrape()
    year_from = config.filters.get('year_from', 2015)
    year_to = config.filters.get('year_to', 2024)
    price_min = config.filters.get('price_min', 1)
    price_max = config.filters.get('price_max', 6000)
    headless = config.settings.get('headless', True)
    max_pages = config.settings.get('max_pages', 1500)
    delay_between_requests = config.settings.get('delay_between_requests', 10)

    print(f"Filtri: Godina {year_from}-{year_to}, Cena {price_min}-{price_max} EUR")
    print(f"Marke za skrejping: {list(brands_config.keys())}")

    async with async_playwright() as p:
        user_data_dir = r"C:\Users\DEX\AppData\Local\Google\Chrome\User Data\Default"

        # Koristi stealth_manager za launch args i context options
        launch_args = stealth_manager.get_launch_args()
        context_options = stealth_manager.get_context_options()

        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            args=launch_args,
            **context_options
        )

        today_str = datetime.now().strftime("%d.%m.%Y")
        all_ads = []

        for brand, models in brands_config.items():
            print(f"\n=== Obrada brenda: {brand} ===")

            if models and len(models) > 0:
                print(f"  Modeli: {models}")
                for model in models:
                    brand_ads = await scrape_brand_with_model(
                        context, brand, model, year_from, year_to,
                        price_min, price_max, max_pages, today_str,
                        delay_between_requests, output_file
                    )
                    all_ads.extend(brand_ads)
            else:
                brand_ads = await scrape_brand_with_model(
                    context, brand, None, year_from, year_to,
                    price_min, price_max, max_pages, today_str,
                    delay_between_requests, output_file
                )
                all_ads.extend(brand_ads)

        await context.close()

    if all_ads:
        print(f"\nAžuriranje glavnog fajla {output_file} sa {len(all_ads)} oglasa...")
        update_json_with_details(output_file, all_ads, today_str)
        overall_data = load_json(output_file)
        overall_existing_ids = set(overall_data['oglasi'].keys())
        overall_scraped_ids = {str(ad['ID oglasa']) for ad in all_ads if ad.get('ID oglasa')}
        overall_missing = overall_existing_ids - overall_scraped_ids
        if overall_missing:
            remove_missing_ads(output_file, overall_scraped_ids, today_str)
            print(f"U glavnom fajlu obrisano {len(overall_missing)} oglasa koji nisu viđeni na listi.")

    return all_ads


async def scrape_brand_with_model(
        context,
        brand: str,
        model: Optional[str],
        year_from: int,
        year_to: int,
        price_min: int,
        price_max: int,
        max_pages: int,
        today_str: str,
        delay_between_requests: float,
        output_file: str  # <-- NOVI parametar
) -> List[Dict]:
    """
    Skrejpovanje oglasa za specifičnu marku i model.
    Umesto posebnih fajlova po brendovima, koristi glavni fajl output_file.
    """
    page_num = 1
    brand_ads = []

    model_param = f"&model={model}" if model else "&model="
    model_id_param = "&modelID="

    print(f"  Skrejpujem: {brand} {model if model else '(svi modeli)'}")

    # 1. Prikupljanje oglasa sa lista
    while page_num <= max_pages:
        page = None
        try:
            params = (
                f"?znamka={brand}"
                f"{model_param}"
                f"{model_id_param}"
                f"&cenaMin={price_min}"
                f"&cenaMax={price_max}"
                f"&letnikMin={year_from}"
                f"&letnikMax={year_to}"
                "&tip=katerikoli%20tip&znamka2=&model2=&tip2=katerikoli%20tip"
                "&znamka3=&model3=&tip3=katerikoli%20tip&bencin=0&starost2=999&oblika=0"
                "&ccmMin=0&ccmMax=99999&mocMin=&mocMax=&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999"
                "&motortakt=&motorvalji=&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100"
                "&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0"
                "&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0"
                "&BkOkvirType=0&Bk4=0"
                "&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000"
                "&EQ7=1110100120&EQ8=1010000000&EQ9=1000000020&EQ10=1000000000&EQ11=1000000000&KAT=1010000000"
                "&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0"
                "&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC"
            )
            current_url = SEARCH_URL + params + f"&stran={page_num}"
            current_viewport = stealth_manager.rotate_viewport()

            page = await context.new_page()
            await page.set_viewport_size(current_viewport)
            await stealth_async(page)

            print(
                f"    >>> Stranica {page_num} <<< (viewport: {current_viewport['width']}x{current_viewport['height']})")
            await page.goto(current_url, wait_until='domcontentloaded', timeout=30000)

            if page_num == 1:
                try:
                    accept_cookies = await page.query_selector('button:has-text("Dovoli piškotke")')
                    if accept_cookies:
                        await accept_cookies.click()
                        await asyncio.sleep(1)
                        print("    Kolačići prihvaćeni.")
                except:
                    pass

            if await page.query_selector('iframe[src*="challenges.cloudflare.com"]'):
                print("    ⚠️ Cloudflare challenge detected. Čekam 15 sekundi...")
                await asyncio.sleep(5)
                await page.reload()
                await page.wait_for_selector('div.GO-Results-Row', timeout=30000)

            try:
                await page.wait_for_selector('div.GO-Results-Row', timeout=15000)
                # print("    Oglasi su se učitali.")
            except:
                print(f"    Nema oglasa na stranici {page_num}. Kraj.")
                break

            ads = await page.query_selector_all('div.GO-Results-Row')
            # print(f"    Pronađeno {len(ads)} oglasa na stranici {page_num}")
            if not ads:
                break

            for ad in ads:
                try:
                    ad_data = await extract_ad_data_avto(ad, brand)
                    if ad_data:
                        brand_ads.append(ad_data)
                except Exception as e:
                    print(f"      Greška pri obradi oglasa: {e}")
                    continue

            next_link = await page.query_selector('a.page-link:has-text("Naprej")')
            if next_link:
                parent_li = await next_link.evaluate_handle('el => el.closest("li")')
                is_disabled = False
                if parent_li:
                    is_disabled = await parent_li.evaluate('el => el.classList.contains("disabled")')
                if is_disabled:
                    print("    Dugme 'Naprej' je onemogućeno – KRAJ.")
                    break
                href = await next_link.get_attribute('href')
                if href:
                    page_num += 1
                else:
                    break
            else:
                break

            await asyncio.sleep(random.uniform(3, 5))

        except Exception as e:
            print(f"    GREŠKA na stranici {page_num}: {e}")
            break
        finally:
            if page:
                await page.close()

    # 2. Prikupljanje detalja koristeći GLAVNI fajl
    if brand_ads:
        print(f"\n  Prikupljanje detalja za {len(brand_ads)} oglasa...")

        # Učitaj podatke iz GLAVNOG fajla
        main_data = load_json(output_file)
        existing_ads = main_data.get('oglasi', {})

        # Podeli oglase: preskoči one koji već imaju Datum obnove
        ads_to_skip = []
        ads_to_fetch = []

        for ad in brand_ads:
            ad_id = str(ad['ID oglasa'])
            existing_ad = existing_ads.get(ad_id, {})
            if existing_ad.get('Datum obnove'):
                ads_to_skip.append(ad)
            else:
                ads_to_fetch.append(ad)

        print(f"  Od toga, {len(ads_to_skip)} oglasa već ima Datum obnove (preskačemo detalje).")
        print(f"  Za {len(ads_to_fetch)} oglasa ćemo učitati detalje.")

        updated_ads = ads_to_skip.copy()

        if ads_to_fetch:
            successful_count = 0
            for idx, ad in enumerate(ads_to_fetch):
                result = await fetch_ad_details(context, ad)
                if result is not None:
                    updated_ads.append(result)
                    successful_count += 1
                if idx < len(ads_to_fetch) - 1:
                    # print(f"    Pauza {delay_between_requests} sekundi pre sledećeg oglasa...")
                    await asyncio.sleep(delay_between_requests)
            print(f"  Uspešno učitano detalja: {successful_count} od {len(ads_to_fetch)}")

        # VRATI listu ažuriranih oglasa (bez upisivanja u fajl)
        return updated_ads

    return brand_ads


if __name__ == "__main__":
    # GitHub Actions / repository layout
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(root)
    asyncio.run(scrape_avto_net())
