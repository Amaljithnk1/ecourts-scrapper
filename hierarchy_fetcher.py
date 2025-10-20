"""
hierarchy_fetcher.py
Fetch State → District → Court-Complex → Court lists
from the e-Courts portal.
"""

from __future__ import annotations
import re
import json
import bs4
import requests

try:
    from json import JSONDecodeError
except Exception:
    JSONDecodeError = ValueError

BASE = "https://services.ecourts.gov.in/ecourtindia_v6"
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, /; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
})
S.headers["Referer"] = f"{BASE}/?p=cause_list/"

# Global to store app_token
APP_TOKEN = None

def _safe_json(resp) -> dict | list:
    """Return resp.json() or {} if the body isn't valid JSON."""
    try:
        return resp.json()
    except (JSONDecodeError, ValueError):
        return {}

def get_app_token(force_refresh: bool = False) -> str:
    """
    Fetch app_token from the cause list page.
    """
    global APP_TOKEN

    if APP_TOKEN and not force_refresh:
        return APP_TOKEN

    try:
        resp = S.get(f"{BASE}/?p=cause_list/", timeout=10, allow_redirects=True)

        if "app_token=" not in resp.url:
            cap = S.get(f"{BASE}/?p=casestatus/getCaptcha",
                     timeout=10, allow_redirects=True)
            if "app_token=" in cap.url:
                m = re.search(r"app_token=([a-f0-9]+)", cap.url)
                if m:
                    APP_TOKEN = m.group(1)
                    print(f"✓ Got app_token from captcha redirect: {APP_TOKEN[:20]}...")
                    return APP_TOKEN
        
        if "app_token=" in resp.url:
            m = re.search(r"app_token=([a-f0-9]+)", resp.url)
            if m:
                APP_TOKEN = m.group(1)
                print(f"✓ Got app_token from URL: {APP_TOKEN[:20]}...")
                return APP_TOKEN
        
        soup = bs4.BeautifulSoup(resp.text, "lxml")

        token_input = (
            soup.find("input", {"id": "app_token"}) or
            soup.find("input", {"name": "app_token"}) or
            soup.find("input", id=re.compile(r"token", re.I))
        )

        if token_input and token_input.get("value"):
            APP_TOKEN = token_input["value"]
            print(f"✓ Got app_token: {APP_TOKEN[:20]}...")
            return APP_TOKEN

        scripts = soup.find_all("script")
        for script in scripts:
            if script.string and "app_token" in script.string:
                match = re.search(r'app_token["\s:=]+(["\'])([a-f0-9]{64,})\1', script.string)
                if match:
                    APP_TOKEN = match.group(2)
                    print(f"✓ Got app_token from JS: {APP_TOKEN[:20]}...")
                    return APP_TOKEN

        m = re.search(r"app_token=([a-f0-9]{20,})", resp.text, re.I)
        if m:
            APP_TOKEN = m.group(1)
            print(f"✓ Got app_token from page text: {APP_TOKEN[:20]}...")
            return APP_TOKEN

        print("⚠ Could not find app_token - requests may fail")
        return ""
    except Exception as e:
        print(f"✗ Error getting app_token: {e}")
        return ""

def states() -> list[dict]:
    """
    Returns: [{ "code":"16", "name":"Karnataka" }, … ]
    """
    get_app_token()

    try:
        resp = S.get(f"{BASE}/?p=cause_list/", timeout=10)
        soup = bs4.BeautifulSoup(resp.text, "lxml")

        state_select = (
            soup.find("select", {"id": "sess_state_code"}) or
            soup.find("select", {"name": "state_code"}) or
            soup.find("select", id=re.compile(r"state", re.I))
        )

        if not state_select:
            print("✗ Could not find state dropdown")
            return []

        opts = state_select.find_all("option", value=True)

        data = [
            {"code": o["value"].strip(), "name": o.text.strip()}
            for o in opts 
            if o["value"].strip() and o["value"].strip() not in ("0", "")
        ]

        return data
    except Exception as e:
        print(f"✗ Error fetching states: {e}")
        return []

def districts(state_code: str) -> list[dict]:
    """
    Returns: [{ "code":"13", "name":"HASSAN" }, … ]
    """
    global APP_TOKEN

    if not APP_TOKEN:
        get_app_token()

    def _call(tok):
        return S.post(
            f"{BASE}/?p=casestatus/fillDistrict",
            data={
                "state_code": state_code,
                "ajax_req": "true",
                "app_token": tok
            },
            timeout=15
        )

    try:
        r = _call(APP_TOKEN or get_app_token())
        data = _safe_json(r)

        if isinstance(data, dict) and "app_token" in data and "errormsg" in data:
            APP_TOKEN = data["app_token"]
            r = _call(APP_TOKEN)
            data = _safe_json(r)

        if isinstance(data, dict) and "dist_list" in data:
            html_options = data["dist_list"]
        elif "<option" in r.text:
            html_options = r.text
        else:
            return []

        soup = bs4.BeautifulSoup(html_options, "lxml")
        return [
            {"code": o["value"].strip(), "name": o.text.strip()}
            for o in soup.find_all("option", value=True)
            if o["value"].strip() and o["value"].strip() not in ("0", "")
        ]
    except Exception as e:
        print(f"✗ Error fetching districts: {e}")
        return []

def complexes(state_code: str, dist_code: str) -> list[dict]:
    """
    Returns: [{ "code":"1360016", "name":"Court Complex-Arasikere" }, … ]
    """
    global APP_TOKEN

    def _call(tok):
        return S.post(
            f"{BASE}/?p=casestatus/fillcomplex",
            data={
                "state_code": state_code,
                "dist_code": dist_code,
                "ajax_req": "true",
                "app_token": tok
            },
            timeout=15
        )

    try:
        token = get_app_token()
        r = _call(token)
        data = _safe_json(r)

        if isinstance(data, dict) and "app_token" in data and "errormsg" in data:
            token = data["app_token"]
            APP_TOKEN = token
            r = _call(token)
            data = _safe_json(r)

        html_options = None
        if isinstance(data, dict):
            html_options = data.get("complex_list") or data.get("court_complex_list")

        if html_options is None and "<option" in r.text:
            html_options = r.text

        if html_options is None:
            return []

        soup = bs4.BeautifulSoup(html_options, "lxml")
        return [
            {"code": o["value"].split("@", 1)[0].strip(), "name": o.text.strip()}
            for o in soup.find_all("option", value=True)
            if o["value"].strip() and o["value"].strip() not in ("0", "")
        ]
    except Exception as e:
        print(f"✗ Error fetching complexes: {e}")
        return []

def courts(state_code: str, dist_code: str, complex_code: str) -> list[dict]:
    """
    Returns: [{ "code":"est^court", "name":"court_no-COURT NAME" }, … ]
    """
    global APP_TOKEN

    token = get_app_token()

    def _parse(html):
        soup = bs4.BeautifulSoup(html, "lxml")
        out = []
        for o in soup.find_all("option", value=True):
            val = (o.get("value") or "").strip()
            if not val or val.lower() in ("0", "null", "undefined"):
                continue
            if "^" in val:
                name = o.text.strip()
                name = re.sub(r'<[^>]*>', '', name)
                name = re.sub(r',\s*"[^"]*":\s*[^,}]*', '', name)
                name = re.sub(r'\{\s*".*?\}\s*$', '', name)
                name = re.sub(r'\s+', ' ', name)
                name = name.strip()
                
                if name:
                    out.append({"code": val, "name": name})
        return out

    def _cause(tok):
        return S.post(
            f"{BASE}/?p=cause_list/fillCauseList",
            data={
                "state_code": state_code,
                "dist_code": dist_code,
                "court_complex_code": complex_code,
                "est_code": "undefined",
                "search_act": "undefined",
                "ajax_req": "true",
                "app_token": tok,
            },
            timeout=15,
        )

    try:
        r = _cause(token)
        d = _safe_json(r)
        if isinstance(d, dict) and "app_token" in d and "errormsg" in d:
            token = d["app_token"]
            APP_TOKEN = token
            r = _cause(token)
            d = _safe_json(r)

        html = None
        if isinstance(d, dict):
            html = d.get("court_list") or d.get("est_list")
        if html is None and "<option" in r.text:
            html = r.text

        return _parse(html or "")
    except Exception as e:
        print(f"✗ Error fetching courts: {e}")
        return []
    
# ====================================================================
# Test
# ====================================================================
if __name__ == "__main__":
    print("Testing hierarchy_fetcher...\n")

    print("1. Fetching states...")
    st_list = states()
    if st_list:
        print(f" Found {len(st_list)} states")
        print(f"First 3: {st_list[:3]}\n")
        st = st_list[0]
    else:
        print(" Failed\n")
        exit()

    print(f"2. Fetching districts for {st['name']}...")
    ds = districts(st["code"])
    if ds:
        print(f" Found {len(ds)} districts")
        print(f"First 3: {ds[:3]}\n")
    else:
        print(" Failed\n")
        exit()

    # Try districts until we find one with complexes
    cp = []
    for d in ds[:3]:  # Try first 3 districts
        print(f"3. Fetching complexes for {d['name']}...")
        cp = complexes(st["code"], d["code"])
        if cp:
            print(f" Found {len(cp)} complexes")
            print(f"First 3: {cp[:3]}\n")
            break
        print(f"No complexes found in {d['name']}\n")
    
    if not cp:
        print(" No complexes found in first 3 districts")
        exit()

    print(f"4. Fetching courts for {cp[0]['name']}...")
    ct = courts(st["code"], ds[0]["code"], cp[0]["code"])
    if ct:
        print(f" Found {len(ct)} courts")
        print(f"First 3: {ct[:3]}\n")
    else:
        print(" Failed\n")

    print("="*60)
    print(" All hierarchy levels working!")