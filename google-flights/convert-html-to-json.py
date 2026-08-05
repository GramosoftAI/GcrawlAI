from lxml import html
import json
import re
import logging
logger = logging.getLogger(__name__)

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
    
    # Flight cards are now listed inside li with class pIav2d
    cards = tree.xpath('//li[contains(@class, "pIav2d")]')

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

        airline_elem = card.xpath('.//div[contains(@class,"sSHqwe") and contains(@class,"tPgKwe") and contains(@class,"ogfYpf")]/span')
        airline = airline_elem[0].text_content().strip() if airline_elem else None

        price = text('.//span[contains(@aria-label, "rupees")]/text()') or text('.//span[contains(@aria-label, "₹")]/text()')
        if not price:
            price_elem = card.xpath('.//div[contains(@class,"YMlIz")]//span[contains(text(), "₹")]/text()')
            if price_elem: price = price_elem[0].strip()

        flight = {
            "airline": airline,
            "departure_time": text('.//div[contains(@class,"wtdjmc")]//text()'),
            "arrival_time": text('.//div[contains(@class,"XWcVob")]//text()'),
            "duration": text('.//div[contains(@class,"gvkrdb")]//text()'),
            "stops": text('.//div[contains(@class,"EfT7Ae")]//text()'),
            "price": price,
            "emissions": text('.//*[contains(text(),"CO2e")]//text()'),
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