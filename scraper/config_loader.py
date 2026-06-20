import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Iterable


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
        default_filters = {
            'year_from': 2015,
            'year_to': 2024,
            'price_min': 1,
            'price_max': 6000
        }
        filters = {**default_filters, **filters}
        
        # Default vrednosti za settings
        default_settings = {
            'delay_between_requests': 10,
            'headless': True,
            'max_pages': 1500,
            'max_retries': 3,
            'retry_base_delay': 10
        }
        settings = {**default_settings, **settings}
        
        return cls(brands=brands, filters=filters, settings=settings)
    
    def get_brands_to_scrape(self) -> Dict[str, Optional[List[str]]]:
        """
        Vraća rečnik marka za skrejping.
        
        Logika:
        - Ako brands == None -> parsira SVE marke (vrati sve default marke)
        - Ako marka ima [] ili None -> parsira SVE modele te marke
        - Ako marka ima ['208', '308'] -> parsira SAMO te modele
        """
        if self.brands is None:
            # Sve default marke, svi modeli
            return {
                "Peugeot": None,
                "Renault": None,
                "Citroen": None,
                "Ford": None,
                "Volkswagen": None,
                "Opel": None,
                "Mercedes-Benz": None,
                "Fiat": None,
                "Audi": None
            }
        
        return self.brands
    
    def get_models_for_brand(self, brand: str) -> Optional[List[str]]:
        """
        Vraća listu modela za datu marku.
        - None -> svi modeli
        - [] -> svi modeli
        - ['208', '308'] -> samo navedeni modeli
        """
        brands = self.get_brands_to_scrape()
        models = brands.get(brand)
        
        # Prazna lista i None znače "svi modeli"
        if models == [] or models is None:
            return None
        
        return models
    
    def should_scrape_all_brands(self) -> bool:
        """Proverava da li treba parsirati sve marke."""
        return self.brands is None
    
    def should_scrape_all_models(self, brand: str) -> bool:
        """Proverava da li treba parsirati sve modele za datu marku."""
        models = self.get_models_for_brand(brand)
        return models is None


# Globalni defaultni MODELI za fallback
DEFAULT_MODELI = {
    "Peugeot": None,
    "Renault": None,
    "Citroen": None,
    "Ford": None,
    "Volkswagen": None,
    "Opel": None,
    "Mercedes-Benz": None,
    "Fiat": None,
    "Audi": None
}


# ==============================
# Main pipeline defaults
# ==============================
DEFAULT_MAIN_BRANDS: tuple[str, ...] = (
    "Citroen",
    "Ford",
    "Volkswagen",
    "Opel",
    "Peugeot",
    "Mercedes-Benz",
    "Renault",
    "Fiat",
    "Audi"
)

DEFAULT_MAIN_FILTERS: Dict[str, int] = {
    "year_from": 2015,
    "year_to": 2025,
    "price_min": 1,
    "price_max": 6000,
}

DEFAULT_MAIN_SETTINGS: Dict[str, Any] = {
    "delay_between_requests": 10,
    "headless": True,
    "max_pages": 1500,
    "max_retries": 3,
    "retry_base_delay": 10,
}


def build_main_scraper_config(
    brands: Optional[Iterable[str]] = None,
    *,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    headless: Optional[bool] = None,
) -> ScraperConfig:
    """
    Kreira ScraperConfig za `main.py` (jedno mesto istine za marke/filtere/settings).
    - brands: lista marki; ako je None koristi DEFAULT_MAIN_BRANDS
    - year/price/headless mogu da override-uju default vrednosti
    """
    selected_brands = tuple(brands) if brands is not None else DEFAULT_MAIN_BRANDS

    filters = dict(DEFAULT_MAIN_FILTERS)
    if year_from is not None:
        filters["year_from"] = year_from
    if year_to is not None:
        filters["year_to"] = year_to
    if price_min is not None:
        filters["price_min"] = price_min
    if price_max is not None:
        filters["price_max"] = price_max

    settings = dict(DEFAULT_MAIN_SETTINGS)
    if headless is not None:
        settings["headless"] = headless

    config = ScraperConfig(brands=DEFAULT_MODELI, filters=filters, settings=settings)
    # None/[] znači "svi modeli" po ScraperConfig.get_models_for_brand logici
    config.brands = {brand: None for brand in selected_brands}
    return config
