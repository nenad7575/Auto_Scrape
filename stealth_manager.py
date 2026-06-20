import random
from typing import Dict, Any, List
from dataclasses import dataclass


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
    reduced_motion: str


class StealthManager:
    """Manages browser fingerprints and stealth rotation for anti-bot protection."""
    
    # Rotating User Agents - Chrome on Windows
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ]
    
    # Common desktop viewports
    VIEWPORTS = [
        {'width': 1920, 'height': 1080},
        {'width': 1366, 'height': 768},
        {'width': 1536, 'height': 864},
        {'width': 1440, 'height': 900},
        {'width': 1280, 'height': 720},
        {'width': 1600, 'height': 900},
        {'width': 1680, 'height': 1050},
    ]
    
    # European locales
    LOCALES = [
        'sl-SI',  # Slovenian (default for Avto.net)
        'en-US',
        'en-GB',
        'de-DE',
        'it-IT',
        'hr-HR',
        'sr-RS',
    ]
    
    TIMEZONES = [
        'Europe/Ljubljana',  # Default for Avto.net
        'Europe/Berlin',
        'Europe/Vienna',
        'Europe/Rome',
        'Europe/Zagreb',
        'Europe/Belgrade',
    ]
    
    def __init__(self):
        self.used_fingerprints: set = set()
        self.fingerprints: List[BrowserFingerprint] = []
        self._generate_fingerprints()
    
    def _generate_fingerprints(self):
        """Generate all possible fingerprint combinations."""
        for ua in self.USER_AGENTS:
            for vp in self.VIEWPORTS:
                for locale in self.LOCALES:
                    for tz in self.TIMEZONES:
                        fp = BrowserFingerprint(
                            user_agent=ua,
                            viewport=vp,
                            locale=locale,
                            timezone_id=tz,
                            device_scale_factor=random.choice([1, 1.25, 1.5]),
                            has_touch=False,
                            is_mobile=False,
                            color_scheme=random.choice(['light', 'dark']),
                            reduced_motion='no-preference'
                        )
                        self.fingerprints.append(fp)
    
    def get_random_fingerprint(self) -> BrowserFingerprint:
        """Get a random unique fingerprint."""
        available = [fp for fp in self.fingerprints 
                     if fp.user_agent not in self.used_fingerprints]
        
        if not available:
            # Reset if all used
            self.used_fingerprints.clear()
            available = self.fingerprints
        
        fp = random.choice(available)
        self.used_fingerprints.add(fp.user_agent)
        return fp
    
    def get_context_options(self) -> Dict[str, Any]:
        """Get Playwright context options for a new fingerprint."""
        fp = self.get_random_fingerprint()
        
        return {
            'viewport': fp.viewport,
            'user_agent': fp.user_agent,
            'locale': fp.locale,
            'timezone_id': fp.timezone_id,
            'device_scale_factor': fp.device_scale_factor,
            'has_touch': fp.has_touch,
            'is_mobile': fp.is_mobile,
            'color_scheme': fp.color_scheme,
            'reduced_motion': fp.reduced_motion,
            'permissions': ['geolocation'],
        }
    
    def rotate_viewport(self) -> Dict[str, int]:
        """Get a random viewport for page rotation."""
        return random.choice(self.VIEWPORTS)
    
    def get_launch_args(self) -> List[str]:
        """Get Chrome launch arguments for stealth."""
        return [
            '--disable-blink-features=AutomationControlled',
            '--disable-features=IsolateOrigins,site-per-process',
            '--disable-web-security',
            '--disable-features=BlockInsecurePrivateNetworkRequests',
            '--no-sandbox',
            '--disable-infobars',
            '--disable-dev-shm-usage',
            '--disable-browser-side-navigation',
            '--disable-gpu',
            '--disable-features=VizDisplayCompositor',
            '--enable-features=NetworkService,NetworkServiceInProcess'
        ]


# Singleton instance
stealth_manager = StealthManager()
