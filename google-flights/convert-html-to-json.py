from lxml import html
import json
import re
import logging
from api.core.database import get_pooled_connection

logger = logging.getLogger(__name__)

def get_google_flights_xpaths():
    xpaths = {
        'cards_xpath': '//li[contains(@class, "pIav2d")]',
        'airline_xpath': './/div[contains(@class,"sSHqwe") and contains(@class,"tPgKwe") and contains(@class,"ogfYpf")]/span',
        'price_xpath_1': './/span[contains(@aria-label, "rupees")]/text()',
        'price_xpath_2': './/span[contains(@aria-label, "₹")]/text()',
        'price_xpath_fallback': './/div[contains(@class,"YMlIz")]//span[contains(text(), "₹")]/text()',
        'departure_time_xpath': './/div[contains(@class,"wtdjmc")]//text()',
        'arrival_time_xpath': './/div[contains(@class,"XWcVob")]//text()',
        'duration_xpath': './/div[contains(@class,"gvkrdb")]//text()',
        'stops_xpath': './/div[contains(@class,"EfT7Ae")]//text()',
        'emissions_xpath': './/*[contains(text(),"CO2e")]//text()'
    }
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT field_name, xpath_value FROM scraper_xpaths WHERE scraper_name = 'google-flights'")
                rows = cursor.fetchall()
                if rows:
                    for row in rows:
                        field_name = row[0]
                        xpath_value = row[1]
                        xpaths[field_name] = xpath_value
    except Exception as e:
        logger.error(f"Error fetching google-flights xpaths: {e}")
    return xpaths

def extract_google_flights(html_content: str):
    """
    Extract Google Flights data from flight cards having class='pIav2d'

    Args:
        html_content (str): HTML source

    Returns:
        list[dict]
    """
    # logger.info(html_content,"============********************===============")

    tree = html.fromstring(html_content)
    flights = []
    
    xpaths = get_google_flights_xpaths()
    
    # Flight cards are now listed inside li with class pIav2d
    cards = tree.xpath(xpaths['cards_xpath'])

    for card in cards:

        def text(xpath):
            value = card.xpath(xpath)
            if not value: return None
            # Take only the first match to avoid duplicates
            if isinstance(value[0], str):
                res = value[0]
            else:
                res = ''.join(value[0].itertext())
            res = re.sub(r'\s+', ' ', res).strip()
            return res if res else None

        airline_elem = card.xpath(xpaths['airline_xpath'])
        airline = airline_elem[0].text_content().strip() if airline_elem else None

        price = text(xpaths['price_xpath_1']) or text(xpaths['price_xpath_2'])
        if not price:
            price_elem = card.xpath(xpaths['price_xpath_fallback'])
            if price_elem: price = price_elem[0].strip()

        flight = {
            "airline": airline,
            "departure_time": text(xpaths['departure_time_xpath']),
            "arrival_time": text(xpaths['arrival_time_xpath']),
            "duration": text(xpaths['duration_xpath']),
            "stops": text(xpaths['stops_xpath']),
            "price": price,
            "emissions": text(xpaths['emissions_xpath']),
            "booking_site": None
        }

        flights.append(flight)

    return flights


# Example
if __name__ == "__main__":

    with open("page.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    data = extract_google_flights(html_content)

    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(data, indent=4, ensure_ascii=False))