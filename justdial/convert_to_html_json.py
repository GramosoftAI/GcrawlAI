import logging
from lxml import html
from urllib.parse import urljoin
from api.core.database import get_pooled_connection

logger = logging.getLogger(__name__)

def get_justdial_xpaths():
    xpaths = {
        'main_xpath': '//main',
        'card_xpath': './/div[contains(@class,"resultbox_textbox")]',
        'name_xpath': './/h2//span[contains(@class,"resultbox_title_anchor")]',
        'href_xpath': './/h2/a/@href',
        'rating_xpath': './/li[contains(@class,"resultbox_totalrate")]/text()',
        'rating_count_xpath': './/li[contains(@class,"resultbox_countrate")]',
        'address_xpath': './/div[contains(@class,"locatcity")]',
        'status_xpath': './/ul[contains(@class,"resultbox_address")][2]//span',
        'phone_xpath': './/span[contains(@class,"callcontent")]',
        'whatsapp_xpath': './/*[contains(text(),"WhatsApp")]',
        'responds_in_xpath': './/button//*[contains(text(),"Responds")]',
        'enquiries_xpath': './/div[contains(@class,"btnresponse")]',
        'verified_xpath': './/img[contains(@src,"verified")]'
    }
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT field_name, xpath_value FROM scraper_xpaths WHERE scraper_name = 'justdial'")
                rows = cursor.fetchall()
                if rows:
                    for row in rows:
                        xpaths[row[0]] = row[1]
    except Exception as e:
        logger.error(f"Failed to fetch Justdial XPaths from DB, using defaults: {e}")
    return xpaths

def extract_business_listings(
    html_content,
    base_url="https://www.justdial.com"
):
    """
    Extract business listings from Justdial search page HTML.

    Args:
        html_content (str): HTML source
        base_url (str): Base URL for relative links

    Returns:
        list[dict]
    """
    if not html_content:
        return []

    try:
        tree = html.fromstring(html_content)
        xpaths = get_justdial_xpaths()

        # Find the main tag
        main = tree.xpath(xpaths['main_xpath'])
        if not main:
            return []

        main = main[0]

        # Every business card
        cards = main.xpath(xpaths['card_xpath'])

        results = []

        for card in cards:

            def first(xpath):
                value = card.xpath(xpath)
                if not value:
                    return None

                if isinstance(value[0], str):
                    return value[0].strip()

                return value[0].text_content().strip()

            # Name
            name = first(xpaths['name_xpath'])

            # Profile URL
            href = first(xpaths['href_xpath'])
            if href:
                href = urljoin(base_url, href)

            # Rating
            rating = first(xpaths['rating_xpath'])

            # Rating Count
            rating_count = first(xpaths['rating_count_xpath'])

            # Address
            address = first(xpaths['address_xpath'])

            # Business Status
            status = first(xpaths['status_xpath'])

            # Phone
            phone = first(xpaths['phone_xpath'])
            if phone == "Show Number":
                phone = "Not Available"

            # WhatsApp Available
            whatsapp = bool(card.xpath(xpaths['whatsapp_xpath']))

            # Respond Time
            responds_in = first(xpaths['responds_in_xpath'])

            # Recent Enquiries
            enquiries = first(xpaths['enquiries_xpath'])

            # Verified
            verified = bool(
                card.xpath(xpaths['verified_xpath'])
            )

            results.append({
                "name": name,
                "url": href,
                "rating": rating,
                "rating_count": rating_count,
                "address": address,
                "status": status,
                "phone": phone,
                "whatsapp": whatsapp,
                "verified": verified,
                "responds_in": responds_in,
                "recent_enquiries": enquiries
            })

        return results
    except Exception as e:
        logger.error(f"Error extracting Justdial business listings: {e}")
        return []