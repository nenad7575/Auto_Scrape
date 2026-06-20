import csv
import os
import json
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
import asyncio
import httpx
from bs4 import BeautifulSoup

"""
# ==================== HTTP FUNKCIJE ====================
async def fetch_page(url: str, headers: Optional[Dict] = None, delay: float = 0) -> Optional[str]:
    # Asinhroni HTTP GET sa poštovanjem delay-a.
    if delay:
        await asyncio.sleep(delay)
    if headers is None:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"Greška pri fetch-u {url}: {e}")
            return None

"""

# ==================== HTTP FUNKCIJE ====================
async def fetch_page(url: str, headers: Optional[Dict] = None, delay: float = 0) -> Optional[str]:
    """Asinhroni HTTP GET sa poštovanjem delay-a."""
    if delay:
        await asyncio.sleep(delay)
    if headers is None:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"Greška pri fetch-u {url}: {e}")
            return None





# ==================== POMOĆNE FUNKCIJE ====================
def parse_date(date_str: str, input_format: str = "%Y-%m-%d %H:%M:%S", output_format: str = "%d.%m.%Y") -> Optional[str]:
    """Konvertuje datum u željeni format. Vraća None ako ne može da parsira."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, input_format)
        return dt.strftime(output_format)
    except ValueError:
        return None


def extract_json_ld(soup: BeautifulSoup) -> List[Dict]:
    """Vraća sve JSON-LD skripte kao listu Python objekata."""
    scripts = soup.find_all('script', type='application/ld+json')
    result = []
    for script in scripts:
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                result.extend(data)
            else:
                result.append(data)
        except json.JSONDecodeError:
            continue
    return result


# ==================== JSON FUNKCIJE ====================
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


def save_json(data: Dict, filename: str) -> None:
    """Snima podatke u JSON fajl."""

    # Kreiraj direktorijum ako ne postoji
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    # Ažuriraj metapodatke
    data['metadata']['poslednje_azuriranje'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data['metadata']['broj_oglasa'] = len(data['oglasi'])

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_json_with_ads(ads_data: List[Dict], filename: str) -> None:
    """
    Ažurira JSON fajl novim oglasima.
    - Ako oglas već postoji, ažurira Cenu, Datum obnove i Datum skrejpa.
    - Ako ne postoji, dodaje ga.
    """
    data = load_json(filename)

    for ad in ads_data:
        ad_id = str(ad['ID oglasa'])
        if ad_id in data['oglasi']:
            # Ažuriraj postojeći
            data['oglasi'][ad_id]['Cena'] = ad.get('Cena', data['oglasi'][ad_id].get('Cena'))
            data['oglasi'][ad_id]['Datum skrejpa'] = ad.get('Datum skrejpa', data['oglasi'][ad_id].get('Datum skrejpa'))
            if ad.get('Datum obnove'):
                data['oglasi'][ad_id]['Datum obnove'] = ad['Datum obnove']
        else:
            # Dodaj novi
            data['oglasi'][ad_id] = ad

    save_json(data, filename)


def update_json_with_sold(json_path: str, prodati_oglasi: List[Dict], today_str: str) -> None:
    """
    Ažurira JSON fajl sa prodatim oglasima.

    - Ako oglas postoji i Datum prodaje je prazan -> ažurira datum
    - Ako oglas postoji i Datum prodaje nije prazan -> preskače
    - Ako oglas ne postoji -> dodaje ceo oglas sa Datum prodaje = today_str
    """
    data = load_json(json_path)

    novi_oglasi = 0
    azurirani_oglasi = 0
    preskoceni_oglasi = 0

    for ad in prodati_oglasi:
        ad_id = str(ad['ID oglasa'])

        if ad_id in data['oglasi']:
            # Oglas već postoji
            postojeci_datum = data['oglasi'][ad_id].get('Datum prodaje')
            if postojeci_datum in (None, '', 'null'):
                # Datum prodaje je prazan – ažuriraj
                data['oglasi'][ad_id]['Datum prodaje'] = today_str
                azurirani_oglasi += 1
            else:
                # Već ima datum prodaje – preskoči
                preskoceni_oglasi += 1
        else:
            # Nov oglas – dodaj ceo
            ad['Datum prodaje'] = today_str
            data['oglasi'][ad_id] = ad
            novi_oglasi += 1

    if novi_oglasi > 0 or azurirani_oglasi > 0:
        save_json(data, json_path)
        print(f"  JSON ažuriran {json_path}: {novi_oglasi} novih, {azurirani_oglasi} ažuriranih, {preskoceni_oglasi} već prodatih.")
    else:
        print(f"  Nema promena u JSON-u {json_path} | ({preskoceni_oglasi} već prodatih).")


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


# ==================== CSV FUNKCIJE (opciono, za izvoz) ====================
def json_to_csv(json_path: str, csv_path: str, fieldnames: List[str]) -> None:
    """
    Konvertuje JSON fajl u CSV (opciono, ako želiš izvoz).
    """
    data = load_json(json_path)
    ads = list(data['oglasi'].values())

    if not ads:
        return

    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        for ad in ads:
            # Zameni None sa praznim stringom
            row = {k: ('' if v is None else v) for k, v in ad.items() if k in fieldnames}
            writer.writerow(row)
    print(f"CSV fajl sačuvan: {csv_path}")
