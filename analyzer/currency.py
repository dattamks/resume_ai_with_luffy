"""
Country-to-currency mapping and USD conversion for salary display.

Exchange rates are approximate annual estimates — they don't need to
be real-time because salaries in job postings are already estimates.
Rates are used only for display purposes (not billing).

To update rates, edit ``_USD_RATES`` or set the ``SALARY_USD_RATES``
environment variable as a JSON dict, e.g.:
    SALARY_USD_RATES={"INR": 83.5, "EUR": 0.92}
"""

import json
import os

# ── Country → ISO 4217 currency code ────────────────────────────────────
_COUNTRY_CURRENCY: dict[str, str] = {
    'india': 'INR',
    'united states': 'USD',
    'usa': 'USD',
    'us': 'USD',
    'united kingdom': 'USD',  # override below
    'uk': 'GBP',
    'canada': 'CAD',
    'australia': 'AUD',
    'germany': 'EUR',
    'france': 'EUR',
    'netherlands': 'EUR',
    'spain': 'EUR',
    'italy': 'EUR',
    'ireland': 'EUR',
    'austria': 'EUR',
    'belgium': 'EUR',
    'portugal': 'EUR',
    'finland': 'EUR',
    'singapore': 'SGD',
    'japan': 'JPY',
    'south korea': 'KRW',
    'china': 'CNY',
    'brazil': 'BRL',
    'mexico': 'MXN',
    'united arab emirates': 'AED',
    'uae': 'AED',
    'saudi arabia': 'SAR',
    'israel': 'ILS',
    'sweden': 'SEK',
    'norway': 'NOK',
    'denmark': 'DKK',
    'switzerland': 'CHF',
    'poland': 'PLN',
    'south africa': 'ZAR',
    'new zealand': 'NZD',
    'indonesia': 'IDR',
    'malaysia': 'MYR',
    'philippines': 'PHP',
    'thailand': 'THB',
    'vietnam': 'VND',
    'taiwan': 'TWD',
    'hong kong': 'HKD',
    'nigeria': 'NGN',
    'kenya': 'KES',
    'egypt': 'EGP',
    'bangladesh': 'BDT',
    'pakistan': 'PKR',
    'sri lanka': 'LKR',
    'argentina': 'ARS',
    'colombia': 'COP',
    'chile': 'CLP',
    'peru': 'PEN',
    'czech republic': 'CZK',
    'czechia': 'CZK',
    'romania': 'RON',
    'hungary': 'HUF',
    'turkey': 'TRY',
    'russia': 'RUB',
    'ukraine': 'UAH',
}
# Fix UK entry
_COUNTRY_CURRENCY['united kingdom'] = 'GBP'

# ── 1 USD = X units of foreign currency ──────────────────────────────────
# Approximate rates as of early 2026.  Override via SALARY_USD_RATES env.
_USD_RATES: dict[str, float] = {
    'USD': 1.0,
    'INR': 83.5,
    'GBP': 0.79,
    'EUR': 0.92,
    'CAD': 1.36,
    'AUD': 1.53,
    'SGD': 1.34,
    'JPY': 150.0,
    'KRW': 1320.0,
    'CNY': 7.25,
    'BRL': 5.0,
    'MXN': 17.2,
    'AED': 3.67,
    'SAR': 3.75,
    'ILS': 3.65,
    'SEK': 10.5,
    'NOK': 10.6,
    'DKK': 6.85,
    'CHF': 0.88,
    'PLN': 4.0,
    'ZAR': 18.5,
    'NZD': 1.64,
    'IDR': 15700.0,
    'MYR': 4.7,
    'PHP': 56.0,
    'THB': 35.5,
    'VND': 24500.0,
    'TWD': 32.0,
    'HKD': 7.82,
    'NGN': 1550.0,
    'KES': 153.0,
    'EGP': 50.0,
    'BDT': 110.0,
    'PKR': 280.0,
    'LKR': 320.0,
    'ARS': 900.0,
    'COP': 4000.0,
    'CLP': 950.0,
    'PEN': 3.75,
    'CZK': 23.0,
    'RON': 4.6,
    'HUF': 365.0,
    'TRY': 32.0,
    'RUB': 92.0,
    'UAH': 41.0,
}

# Allow env override
_env_rates = os.environ.get('SALARY_USD_RATES', '')
if _env_rates:
    try:
        _USD_RATES.update(json.loads(_env_rates))
    except (json.JSONDecodeError, TypeError):
        pass


def get_currency_for_country(country: str) -> str:
    """Return the ISO 4217 currency code for a country name.

    Falls back to ``USD`` for unknown countries and for ``country='all'``.
    """
    if not country or country.lower() == 'all':
        return 'USD'
    return _COUNTRY_CURRENCY.get(country.strip().lower(), 'USD')


def convert_usd(amount_usd: float | int | None, currency: str) -> int | None:
    """Convert a USD amount to the target currency.

    Returns an integer (rounded) or ``None`` if the input is ``None``.
    """
    if amount_usd is None:
        return None
    rate = _USD_RATES.get(currency, 1.0)
    return int(round(amount_usd * rate))
