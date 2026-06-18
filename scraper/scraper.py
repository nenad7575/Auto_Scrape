import json
import asyncio
import subprocess
from avto_scraper import scrape_avto_net
from prodato import main_async as prodato_main_async

CONFIG_PATH = "scraper_config.json"


# ── ScraperConfig ────────────────────────────────────────────────────────────
# Minimalna klasa koja drži konfiguraciju i pruža metode koje avto_scraper.py
# očekuje. Jedini izvor podataka je scraper_config.json — nema hardkodovanih
# defaulta ovde.

class ScraperConfig:
    def __init__(self, data: dict):
        self.brands   = data.get("brands")    # None → sve marke
        self.filters  = data.get("filters",  {})
        self.settings = data.get("settings", {})
        self.output   = data.get("output",   {})

    def get_brands_to_scrape(self) -> dict:
        """None → prazan dict (avto_scraper parsira sve); inače vraća brands."""
        return self.brands if self.brands is not None else {}

    def get_models_for_brand(self, brand: str):
        """[] ili None → svi modeli (vraća None); lista → samo ti modeli."""
        models = (self.brands or {}).get(brand)
        return None if (models is None or models == []) else models

    def should_scrape_all_brands(self) -> bool:
        return self.brands is None

    def should_scrape_all_models(self, brand: str) -> bool:
        return self.get_models_for_brand(brand) is None


def load_config(path: str) -> ScraperConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    config = ScraperConfig(data)
    print(f"[config] Učitan '{path}'")
    print(f"[config] Marke  : {list(config.get_brands_to_scrape().keys())}")
    print(f"[config] Filteri: {config.filters}")
    return config


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    config = load_config(CONFIG_PATH)
    output_file = config.output.get("avto_file", "avto_net_oglasi.json")

    await asyncio.gather(
        scrape_avto_net(config=config, output_file=output_file),
        prodato_main_async(),
        return_exceptions=True
    )


if __name__ == "__main__":
    asyncio.run(main())

    print("Pokrecem Prepis.py\n")
    subprocess.run(["python", ".\\avto\\Prepis.py"])

    print("\nPokrecem Ana.py")
    with open("ana.py", "r", encoding="utf-8") as f:
        exec(f.read())

    print("\nPokrecem TopPonuda.py")
    with open("TopPonuda.py", "r", encoding="utf-8") as f:
        exec(f.read())

    print("\nPokrecem Analiza oglasa sa Interpolacijom")
    with open("Analiza Oglasa sa Interpolacijom.py", "r", encoding="utf-8") as f:
        exec(f.read())

    print("\n ===============================\n",
          "Pokrecem Analiza ponude.py\n",
          "==================================")
    with open("Analiza ponude.py", "r", encoding="utf-8") as f:
        exec(f.read())

    print("\nPokrecem Excel analizu")
    with open("Excel analiza.py", "r", encoding="utf-8") as f:
        exec(f.read())
