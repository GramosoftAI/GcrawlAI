import sys
import os
import datetime
import requests
import psycopg2
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# Ensure the root GcrawlAI path is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Load .env
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path, override=True)

# Try importing PRIORITY_ISPS from web_crawler, fallback if unavailable
try:
    from web_crawler.common.proxy_manager import PRIORITY_ISPS
except Exception:
    PRIORITY_ISPS = ["jio", "airtel", "reliance", "vodafone", "idea", "bsnl", "comcast", "spectrum", "at&t"]

def fetch_nodemaven_isp(country, api_key):
    headers = {
        "Authorization": f"x-api-key {api_key}",
        "Content-Type": "application/json"
    }
    url = "https://api.nodemaven.com/api/v2/base/locations/isps/"
    params = {
        "country__code": country.lower(),
        "limit": 100,
        "offset": 0
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json()
            all_isps = data.get("isps", [])
            if not all_isps:
                return country.upper(), None
            
            high_isps = [isp for isp in all_isps if isp.get("effective_availability") == "high"]
            medium_isps = [isp for isp in all_isps if isp.get("effective_availability") == "medium"]
            low_isps = [isp for isp in all_isps if isp.get("effective_availability") == "low"]

            selected = None
            # 1. High availability with priority ISP keywords
            for prio in PRIORITY_ISPS:
                for isp in high_isps:
                    code = isp.get("code", "")
                    name = isp.get("name", "")
                    if prio in code.lower() or prio in name.lower():
                        selected = code
                        break
                if selected: break
            
            # 2. Fall back to any high availability ISP
            if not selected and high_isps:
                selected = high_isps[0].get("code")
                
            # 3. Medium availability with priority ISP keywords
            if not selected:
                for prio in PRIORITY_ISPS:
                    for isp in medium_isps:
                        code = isp.get("code", "")
                        name = isp.get("name", "")
                        if prio in code.lower() or prio in name.lower():
                            selected = code
                            break
                    if selected: break
                    
            # 4. Fall back to any medium availability ISP
            if not selected and medium_isps:
                selected = medium_isps[0].get("code")
                
            # 5. Low availability with priority ISP keywords
            if not selected:
                for prio in PRIORITY_ISPS:
                    for isp in low_isps:
                        code = isp.get("code", "")
                        name = isp.get("name", "")
                        if prio in code.lower() or prio in name.lower():
                            selected = code
                            break
                    if selected: break
                    
            # 6. Fall back to any low availability ISP
            if not selected and low_isps:
                selected = low_isps[0].get("code")
                
            return country.upper(), selected
    except Exception as e:
        print(f"Error fetching Nodemaven for {country}: {e}")
    return country.upper(), None

def run_population(conn, evomi_key, nodemaven_key):
    cur = conn.cursor()
    
    # 1. Create tables
    print("Creating tables if they do not exist...")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS nodemaven_isps (
        country_code VARCHAR(10) PRIMARY KEY,
        isp_code VARCHAR(100) NOT NULL,
        updated_at TIMESTAMP NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS evomi_isps (
        country_code VARCHAR(10) PRIMARY KEY,
        isp_code VARCHAR(100) NOT NULL,
        updated_at TIMESTAMP NOT NULL
    );
    """)
    conn.commit()
    print("✓ PostgreSQL tables nodemaven_isps and evomi_isps created/verified.")
    
    # 2. Fetch Evomi settings to get all supported country codes
    headers = {"x-apikey": evomi_key}
    print("Fetching Evomi supported countries...")
    try:
        resp = requests.get("https://api.evomi.com/public/settings", headers=headers, timeout=15.0)
        if resp.status_code != 200:
            print(f"Failed to get Evomi settings from API. Status: {resp.status_code}")
            cur.close()
            return
    except Exception as e:
        print(f"Failed to connect to Evomi API: {e}")
        cur.close()
        return
        
    settings_data = resp.json()
    isp_dict = settings_data.get("data", {}).get("rp", {}).get("isp", {})
    
    countries = set()
    for k, v in isp_dict.items():
        for c in v.get("countries", []):
            countries.add(c.upper())
            
    print(f"✓ Found {len(countries)} supported countries.")
    
    # 3. Populate Evomi database table
    print("Processing and storing Evomi ISPs to database...")
    for c in countries:
        filtered_isps = {
            k: v for k, v in isp_dict.items()
            if c in [country.upper() for country in v.get("countries", [])]
        }
        if not filtered_isps:
            continue
            
        selected = None
        for prio in PRIORITY_ISPS:
            for key, val in filtered_isps.items():
                if prio in key.lower() or prio in val.get("label", "").lower():
                    selected = key
                    break
            if selected:
                break
                
        if not selected:
            selected = list(filtered_isps.keys())[0]
            
        cur.execute("""
        INSERT INTO evomi_isps (country_code, isp_code, updated_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (country_code) DO UPDATE
        SET isp_code = EXCLUDED.isp_code, updated_at = EXCLUDED.updated_at
        """, (c, selected, datetime.datetime.now()))
        
    conn.commit()
    print("✓ Evomi ISPs populated successfully.")
    
    # 4. Populate Nodemaven database table
    if not nodemaven_key:
        print("NODEMAVEN_ISP_APIKEY is not set in .env. Skipping Nodemaven population.")
        cur.close()
        return
        
    print("Processing and storing Nodemaven ISPs to database in parallel (max 20 workers)...")
    success_count = 0
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_nodemaven_isp, c, nodemaven_key): c for c in countries}
        for future in as_completed(futures):
            c, isp = future.result()
            if isp:
                cur.execute("""
                INSERT INTO nodemaven_isps (country_code, isp_code, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (country_code) DO UPDATE
                SET isp_code = EXCLUDED.isp_code, updated_at = EXCLUDED.updated_at
                """, (c, isp, datetime.datetime.now()))
                success_count += 1
                
    conn.commit()
    cur.close()
    print(f"✓ Nodemaven ISPs populated successfully. Total Nodemaven ISPs stored: {success_count}")
    print("★ Setup and Database population completed successfully!")

def main():
    evomi_key = os.getenv("EVOMI_PREMIUM_ISP_APIKEY")
    if not evomi_key:
        print("EVOMI_PREMIUM_ISP_APIKEY is not set in .env.")
        sys.exit(1)
        
    nodemaven_key = os.getenv("NODEMAVEN_ISP_APIKEY")
    
    print("Database Connection Establishing...")
    try:
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DATABASE", "Dev_tamil"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "Ramkumar1+")
        )
        print("Connected directly to PostgreSQL database.")
    except Exception as e:
        print(f"Failed to connect directly to database: {e}")
        sys.exit(1)

    try:
        with conn:
            run_population(conn, evomi_key, nodemaven_key)
    except Exception as e:
        print(f"Error during population: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
