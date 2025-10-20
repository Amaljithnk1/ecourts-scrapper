"""
eCourts Scraper Fixed for actual eCourts v6 API
Based on real Network tab analysis
"""

from __future__ import annotations
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

class eCourtsScraper:
    BASE_URL = "https://services.ecourts.gov.in/ecourtindia_v6"
    TIMEOUT = 15

    def __init__(self, use_ocr: bool = False) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                " AppleWebKit/537.36 (KHTML, like Gecko)"
                " Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        })
        self.app_token: Optional[str] = None
        self.use_ocr: bool = use_ocr

    # ----------------------------------------------------------------
    # Token Management
    # ----------------------------------------------------------------
    def _get_app_token(self, force_refresh: bool = False) -> str:
        """Get or refresh the app_token from the cause list page."""
        if self.app_token and not force_refresh:
            return self.app_token

        try:
            # Get initial page for cookies
            url = f"{self.BASE_URL}/"
            r = self.session.get(url, timeout=self.TIMEOUT)
            r.raise_for_status()
            
            # Get cause list page which sets initial token
            url = f"{self.BASE_URL}/?p=cause_list/"
            r = self.session.get(url, timeout=self.TIMEOUT)
            r.raise_for_status()
            
            # Get fillDistrict data
            # Get initial fillDistrict data
            url = f"{self.BASE_URL}/?p=casestatus/fillDistrict"
            r = self.session.post(url, data={
                "state_code": "4",  # Start with Kerala
                "ajax_req": "true"
            }, timeout=self.TIMEOUT)
            r.raise_for_status()
            
            # Get fillDistrict with district
            r = self.session.post(url, data={
                "state_code": "4",
                "dist_code": "3",
                "ajax_req": "true",
            }, timeout=self.TIMEOUT)
            r.raise_for_status()
            
            # Extract token from response
            try:
                token = r.json().get("app_token")
                if token:
                    self.app_token = token
                    return token
            except Exception:
                pass

            # Method 1: Token in URL
            if "app_token=" in r.url:
                match = re.search(r'app_token=([a-f0-9]+)', r.url)
                if match:
                    self.app_token = match.group(1)
                    logger.info(f"✓ Got app_token from URL: {self.app_token[:20]}...")
                    return self.app_token

            # Method 2: Token in HTML
            soup = BeautifulSoup(r.text, "lxml")
            
            all_links = soup.find_all("a", href=re.compile(r"app_token="))
            if all_links:
                first_link = all_links[0]["href"]
                match = re.search(r'app_token=([a-f0-9]+)', first_link)
                if match:
                    self.app_token = match.group(1)
                    logger.info(f"✓ Got app_token from href: {self.app_token[:20]}...")
                    return self.app_token
            
            token_input = soup.find("input", {"name": "app_token"})
            if token_input and token_input.get("value"):
                self.app_token = token_input["value"]
                logger.info(f"✓ Got app_token from input: {self.app_token[:20]}...")
                return self.app_token

            match = re.search(r'app_token=([a-f0-9]{64,})', r.text)
            if match:
                self.app_token = match.group(1)
                logger.info(f"✓ Got app_token from page text: {self.app_token[:20]}...")
                return self.app_token

            logger.warning("Could not extract app_token")
            return ""

        except Exception as exc:
            logger.error(f"Error getting app_token: {exc}")
            return ""

    # ----------------------------------------------------------------
    # Captcha Helpers
    # ----------------------------------------------------------------
    def _captcha_img_url_from_response(self, r) -> Optional[str]:
        """Extract captcha image URL from response (JSON or HTML)."""
        try:
            j = r.json()
        except Exception:
            j = None

        html_chunk = ""
        if isinstance(j, dict):
            for v in j.values():
                if isinstance(v, str):
                    html_chunk += " " + v
        else:
            html_chunk = r.text or ""

        # Look for img tag with captcha/securimage
        m = re.search(r'<img[^>]+src=["\']([^"\']*(?:securimage|captcha)[^"\']*)["\']', html_chunk, re.I)
        if m:
            return urljoin(self.BASE_URL + "/", m.group(1))

        # Look in JSON values
        if isinstance(j, dict):
            for v in j.values():
                if isinstance(v, str) and ("securimage" in v or "captcha" in v):
                    return urljoin(self.BASE_URL + "/", v)

        return None

    def _captcha_invalid(self, payload) -> bool:
        """Check if response indicates invalid captcha."""
        txt = ""
        if isinstance(payload, dict):
            for k in ("errormsg", "error", "message", "msg", "status", "case_data"):
                v = payload.get(k)
                if isinstance(v, str):
                    txt += " " + v
        elif isinstance(payload, list):
            txt = " ".join(map(str, payload))
        else:
            txt = str(payload or "")
        
        txt = txt.lower()
        patterns = (
            "invalid captcha",
            "wrong captcha",
            "captcha mismatch",
            "captcha code is incorrect",
            "captcha does not match",
            "please enter valid captcha",
            "please enter captcha",
            "invalid verification code",
            "verification code incorrect",
            "captcha not matched",
        )
        return ("captcha" in txt) and any(p in txt for p in patterns)

    def _get_captcha_code(self, captcha_url: str, auto_solve: bool = True) -> str:
        """Fetch captcha image → OCR-first (ask to confirm) → manual. Prompts even if image fetch fails."""
        try:
            import time, webbrowser
            ts = int(time.time() * 1000)
            token = self._get_app_token() or ""
            full_url = urljoin(self.BASE_URL, captcha_url)

            def _is_img(resp) -> bool:
                ct = resp.headers.get("Content-Type", "").lower()
                if "image" in ct or "octet-stream" in ct:
                    return True
                return resp.content[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1")

            # Try getCaptcha (with referer + token)
            r = self.session.get(
                full_url,
                params={"ajax_req": "true", "app_token": token, "_": ts},
                headers={"Referer": f"{self.BASE_URL}/?p=casestatus/index"},
                timeout=self.TIMEOUT,
            )
            r.raise_for_status()

            img_bytes = None
            if _is_img(r):
                img_bytes = r.content
            else:
                img_url = self._captcha_img_url_from_response(r)
                if img_url:
                    ir = self.session.get(
                        img_url,
                        headers={"Referer": f"{self.BASE_URL}/?p=casestatus/index"},
                        timeout=self.TIMEOUT,
                    )
                    if ir.ok and _is_img(ir):
                        img_bytes = ir.content

            # Fallbacks to securimage
            if img_bytes is None:
                base = self.BASE_URL.rstrip("/")
                for url in (
                    f"{base}/securimage/securimage_show.php?sid={ts}&app_token={token}",
                    f"{base}/securimage/securimage_show.php?sid={ts}",
                    f"{base}/securimage/securimage_show.php?app_token={token}",
                    f"{base}/securimage/securimage_show.php",
                ):
                    try:
                        ir = self.session.get(
                            url,
                            headers={"Referer": f"{self.BASE_URL}/?p=casestatus/index"},
                            timeout=self.TIMEOUT,
                        )
                        if ir.ok and _is_img(ir):
                            img_bytes = ir.content
                            break
                    except Exception:
                        pass

            # If still no image: prompt manually anyway
            if img_bytes is None:
                logger.warning("Captcha image not fetched; prompting for manual entry without image.")
                try:
                    webbrowser.open(f"{self.BASE_URL}/?p=casestatus/index")
                except Exception:
                    pass
                return input("Enter captcha code (from browser page): ").strip()

            # Save the image
            captcha_path = Path("output/captcha.png")
            captcha_path.parent.mkdir(exist_ok=True)
            captcha_path.write_bytes(img_bytes)
            logger.info(f"Captcha saved to: {captcha_path}")

            # OCR-first, ask to confirm or correct
            if auto_solve and self.use_ocr:
                guess = self._solve_captcha_ocr(captcha_path)
                if guess:
                    print(f"OCR guess: {guess}")
                    try:
                        webbrowser.open(captcha_path.resolve().as_uri())
                    except Exception:
                        pass
                    corrected = input("Press Enter to accept, or type the correct code: ").strip()
                    return (corrected or guess).strip()

            # Manual entry
            print("\n" + "="*60)
            print("CAPTCHA REQUIRED")
            print(f"Captcha image saved to: {captcha_path}")
            print("="*60)
            try:
                webbrowser.open(captcha_path.resolve().as_uri())
            except Exception:
                pass
            return input("Enter captcha code: ").strip()

        except Exception as exc:
            logger.error(f"Error getting captcha: {exc}")
            return ""

    def _solve_captcha_ocr(self, image_path: Path) -> Optional[str]:
        """Solve captcha using OCR."""
        try:
            import pytesseract
            from PIL import Image, ImageEnhance, ImageFilter
            import cv2
            import numpy as np
        except ImportError:
            logger.warning(
                "OCR libraries not installed. Install with:\n"
                " pip install pytesseract pillow opencv-python\n"
                " Also install tesseract-ocr system package"
            )
            return None

        try:
            img = Image.open(image_path)
            img = img.convert('L')
            
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            
            img_np = np.array(img)
            _, img_np = cv2.threshold(img_np, 127, 255, cv2.THRESH_BINARY)
            
            kernel = np.ones((2, 2), np.uint8)
            img_np = cv2.morphologyEx(img_np, cv2.MORPH_CLOSE, kernel)
            img_np = cv2.morphologyEx(img_np, cv2.MORPH_OPEN, kernel)
            
            img = Image.fromarray(img_np)
            img = img.filter(ImageFilter.MedianFilter(size=3))
            
            debug_path = image_path.parent / "captcha_processed.png"
            img.save(debug_path)
            
            custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
            
            text = pytesseract.image_to_string(img, config=custom_config)
            text = text.strip()
            text = ''.join(c for c in text if c.isalnum())
            
            if 4 <= len(text) <= 8:
                return text
            else:
                logger.warning(f"OCR result has unexpected length: '{text}' ({len(text)} chars)")
                return None
                
        except Exception as exc:
            logger.warning(f"OCR processing failed: {exc}")
            return None

    # ----------------------------------------------------------------
    # CNR Search
    # ----------------------------------------------------------------
    def search_by_cnr(self, cnr: str, captcha_code: Optional[str] = None) -> Dict:
        """Search by CNR number."""
        token = self._get_app_token()
        if not token:
            return {"success": False, "data": None, "message": "Failed to get app_token"}

        if not captcha_code:
            captcha_url = f"{self.BASE_URL}/?p=casestatus/getCaptcha"
            captcha_code = self._get_captcha_code(captcha_url, auto_solve=self.use_ocr)
            if not captcha_code:
                return {"success": False, "data": None, "message": "Captcha required"}

        url = f"{self.BASE_URL}/?p=cnr_status/searchByCNR/"
        data = {
            "cino": cnr,
            "fcaptcha_code": captcha_code,
            "ajax_req": "true",
            "app_token": token
        }

        try:
            r = self.session.post(url, data=data, timeout=self.TIMEOUT)
            r.raise_for_status()
            
            try:
                j = r.json()
            except Exception:
                j = None
            
            if self._captcha_invalid(j or r.text):
                return {"success": False, "data": None, "message": "Invalid captcha"}
            
            try:
                result = r.json()
                return {
                    "success": True,
                    "data": result,
                    "message": "Case found"
                }
            except:
                parsed = self._parse_case_details(r.text)
                return {
                    "success": parsed is not None,
                    "data": parsed,
                    "html": r.text,
                    "message": "Case found" if parsed else "Case not found"
                }

        except Exception as exc:
            logger.error(f"Error searching CNR: {exc}")
            return {"success": False, "data": None, "message": str(exc)}

    # ----------------------------------------------------------------
    # Case Number Search
    # ----------------------------------------------------------------
    def search_by_case_details(
        self,
        state_code: str,
        dist_code: str,
        court_complex_code: str,
        est_code: str,
        case_type: str,
        case_number: str,
        year: str,
        captcha_code: Optional[str] = None
    ) -> Dict:
        """Search by case details (Type, Number, Year)."""
        token = self._get_app_token()
        if not token:
            return {"success": False, "data": None, "message": "Failed to get app_token"}

        if not captcha_code:
            captcha_url = f"{self.BASE_URL}/?p=casestatus/getCaptcha"
            captcha_code = self._get_captcha_code(captcha_url, auto_solve=self.use_ocr)
            if not captcha_code:
                return {"success": False, "data": None, "message": "Captcha required"}

        url = f"{self.BASE_URL}/?p=casestatus/submitCaseNo"
        data = {
            "p": "casestatus/submitCaseNo",
            "state_code": state_code,
            "dist_code": dist_code,
            "court_complex_code": court_complex_code,
            "est_code": est_code,
            "case_type": case_type,
            "case_no": case_number,
            "rgyear": year,
            "case_captcha_code": captcha_code,
            "ajax_req": "true",
            "app_token": token
        }

        try:
            r = self.session.post(url, data=data, timeout=self.TIMEOUT)
            r.raise_for_status()
            
            try:
                j = r.json()
            except Exception:
                j = None
            
            if self._captcha_invalid(j or r.text):
                return {"success": False, "data": None, "message": "Invalid captcha"}
            
            try:
                result = r.json()
                return {
                    "success": True,
                    "data": result,
                    "message": "Case found"
                }
            except:
                parsed = self._parse_case_details(r.text)
                return {
                    "success": parsed is not None,
                    "data": parsed,
                    "html": r.text,
                    "message": "Case found" if parsed else "Case not found"
                }

        except Exception as exc:
            logger.error(f"Error searching case: {exc}")
            return {"success": False, "data": None, "message": str(exc)}

    # ----------------------------------------------------------------
    # Preflight set_data
    # ----------------------------------------------------------------
    def _set_data(self, state_code, dist_code, court_complex_code, est_code, token):
        """Mirror browser preflight flow."""
        try:
            # First set the complex data with establishment codes format
            self.session.post(
                f"{self.BASE_URL}/?p=casestatus/set_data",
                data={
                    "complex_code": f"{court_complex_code}@{est_code}@N",
                    "selected_state_code": state_code,
                    "selected_dist_code": dist_code,
                    "selected_est_code": "null",
                    "ajax_req": "true",
                    "app_token": token,
                },
                timeout=self.TIMEOUT,
            )
            
            # Then fill the cause list data
            self.session.post(
                f"{self.BASE_URL}/?p=cause_list/fillCauseList",
                data={
                    "state_code": state_code,
                    "dist_code": dist_code,
                    "court_complex_code": court_complex_code,
                    "est_code": est_code,
                    "ajax_req": "true",
                    "app_token": token,
                },
                timeout=self.TIMEOUT,
            )
        except Exception:
            pass

    # ----------------------------------------------------------------
    # Cause List
    # ----------------------------------------------------------------
    def get_cause_list(
        self,
        state_code: str,
        dist_code: str,
        court_complex_code: str,
        court_code: str,
        date: Optional[str] = None,
        captcha_code: Optional[str] = None,
        case_type: str = "civ",
        court_name_txt: Optional[str] = None,
    ) -> Dict:
        """Get cause list for a specific court on a specific date."""
        if not date:
            date = datetime.now().strftime("%d-%m-%Y")

        token = self._get_app_token()
        if not token:
            return {"success": False, "data": None, "message": "Failed to get app_token"}

        if not captcha_code:
            captcha_url = f"{self.BASE_URL}/?p=casestatus/getCaptcha"
            captcha_code = self._get_captcha_code(captcha_url, auto_solve=self.use_ocr)
            if not captcha_code:
                return {"success": False, "data": None, "message": "Captcha required"}

        if "^" not in court_code:
            return {"success": False, "data": None, "message": "Invalid court_code (must be est^court)"}

        est = court_code.split("^", 1)[0]

        # Mirror browser flow
        self._set_data(state_code, dist_code, court_complex_code, est, token)

        # map case_type to cicri required by site
        cicri = "cri" if str(case_type).lower() in ("cri", "crim", "criminal") else "civ"

        # sanitize any accidental HTML in court_name_txt
        if court_name_txt:
            court_name_txt = re.sub(r"<[^>]*>", "", court_name_txt).strip()

        url = f"{self.BASE_URL}/?p=cause_list/submitCauseList"
        # Order matters! Match exact order from network trace
        data = {
            "CL_court_no": court_code,
            "causelist_date": date,
            "cause_list_captcha_code": captcha_code,
            "court_name_txt": court_name_txt or "",  # Format: "7-Smt. Sruthy M-Additional Sub judge"
            "state_code": state_code,
            "dist_code": dist_code,
            "court_complex_code": court_complex_code,
            "est_code": "null",  # Must be null for submitCauseList
            "cicri": cicri,
            "selprevdays": "0",
            "ajax_req": "true",
            "app_token": token
        }

        try:
            url = f"{self.BASE_URL}/?p=cause_list/submitCauseList"

            logger.info(f"submitCauseList -> est={est}, cicri={cicri}, court={court_code}, date={date}")

            def post_once(tok):
                # Step 1: Get initial fillDistrict response (mirror network trace exactly)
                r = self.session.post(
                    f"{self.BASE_URL}/?p=casestatus/fillDistrict",
                    data={
                        "state_code": state_code,
                        "ajax_req": "true",
                        "app_token": tok
                    },
                    timeout=self.TIMEOUT
                )
                r.raise_for_status()
                try:
                    tok = r.json().get("app_token", tok)
                except:
                    pass
                
                # Step 2: Get fillDistrict with district code
                r = self.session.post(
                    f"{self.BASE_URL}/?p=casestatus/fillDistrict",
                    data={
                        "state_code": state_code,
                        "dist_code": dist_code,
                        "ajax_req": "true",
                        "app_token": tok
                    },
                    timeout=self.TIMEOUT
                )
                r.raise_for_status()
                try:
                    tok = r.json().get("app_token", tok)
                except:
                    pass
                
                # Step 3: Set complex data
                est_list = "1,2,3,4,5,6,7,26,29,34"
                r = self.session.post(
                    f"{self.BASE_URL}/?p=casestatus/set_data",
                    data={
                        "complex_code": f"{court_complex_code}@{est_list}@N",
                        "selected_state_code": state_code,
                        "selected_dist_code": dist_code,
                        "selected_est_code": "null",
                        "ajax_req": "true",
                        "app_token": tok
                    },
                    timeout=self.TIMEOUT
                )
                r.raise_for_status()
                try:
                    tok = r.json().get("app_token", tok)
                except:
                    pass
                
                # Step 4: Get new captcha
                r = self.session.post(
                    f"{self.BASE_URL}/?p=casestatus/getCaptcha",
                    data={
                        "ajax_req": "true",
                        "app_token": tok
                    },
                    timeout=self.TIMEOUT
                )
                r.raise_for_status()
                try:
                    tok = r.json().get("app_token", tok)
                except:
                    pass
                
                # Step 5: Initialize fillCauseList
                r = self.session.post(
                    f"{self.BASE_URL}/?p=cause_list/fillCauseList",
                    data={
                        "state_code": state_code,
                        "dist_code": dist_code,
                        "court_complex_code": court_complex_code,
                        "est_code": est_list,
                        "ajax_req": "true",
                        "app_token": tok
                    },
                    timeout=self.TIMEOUT
                )
                r.raise_for_status()
                try:
                    tok = r.json().get("app_token", tok)
                except:
                    pass
                
                # Finally submit with latest token
                payload = data.copy()
                payload["app_token"] = tok
                resp = self.session.post(url, data=payload, timeout=self.TIMEOUT)
                resp.raise_for_status()
                try:
                    j = resp.json()
                except Exception:
                    j = None
                return resp, j

            # first attempt
            r, j = post_once(token)

            # captcha check
            if self._captcha_invalid(j or r.text):
                return {"success": False, "data": None, "message": "Invalid captcha", "captcha_error": True}

            # helper to read errormsg
            def parse_errmsg(x):
                if isinstance(x, dict) and x.get("errormsg"):
                    try:
                        return BeautifulSoup(x["errormsg"], "lxml").get_text(" ", strip=True)
                    except Exception:
                        return str(x["errormsg"])
                return None

            errmsg = parse_errmsg(j)

            # token rotate + retry once
            if errmsg and isinstance(j, dict) and j.get("app_token") and j.get("app_token") != token:
                token = j["app_token"]
                self.app_token = token
                r, j = post_once(token)
                if self._captcha_invalid(j or r.text):
                    return {"success": False, "data": None, "message": "Invalid captcha", "captcha_error": True}
                errmsg = parse_errmsg(j)

            # still an error? bubble it up
            if errmsg:
                return {"success": False, "data": None, "message": errmsg}

            # extract HTML
            if isinstance(j, dict) and "case_data" in j:
                html = j["case_data"]
            else:
                html = r.text

            # Save returned HTML for inspection
            try:
                Path("output").mkdir(exist_ok=True)
                Path("output/last_causelist.html").write_text(html or "", encoding="utf-8")
                logger.info(f"Saved raw HTML to output/last_causelist.html (len={len(html or '')})")
            except Exception:
                pass

            cases = self._parse_cause_list(html or "", date)
            return {
                "success": True,
                "data": {"date": date, "total_cases": len(cases), "cases": cases},
                "html": html,
                "message": f"Found {len(cases)} cases",
            }
        except Exception as exc:
            logger.error(f"Error fetching cause list: {exc}")
            return {"success": False, "data": None, "message": str(exc)}

    # ----------------------------------------------------------------
    # PDF Download
    # ----------------------------------------------------------------
    def _wrap_html_for_pdf(self, html: str) -> str:
        """Wrap HTML in proper document structure."""
        return f"""<!doctype html>
<html>
<head><meta charset="utf-8"></head>
<body>{html}</body>
</html>"""

    def download_cause_list_pdf(
        self,
        state_code: str,
        dist_code: str,
        court_complex_code: str,
        court_code: str,
        date: str,
        out_dir: str = "output",
        case_type: str = "civ",
        captcha_code: Optional[str] = None,
        html: Optional[str] = None,
        court_name_txt: Optional[str] = None,
    ) -> Optional[str]:
        """Generate a PDF for the cause list. Returns path to PDF or None."""
        try:
            if html is None:
                if not captcha_code:
                    return None
                token = self._get_app_token()
                if not token:
                    return None
                est = court_code.split("^")[0] if "^" in court_code else "null"

                # map case_type to cicri required by site
                cicri = "cri" if str(case_type).lower() in ("cri", "crim", "criminal") else "civ"

                # sanitize court_name_txt
                if court_name_txt:
                    court_name_txt = re.sub(r"<[^>]*>", "", court_name_txt).strip()

                payload = {
                    "p": "cause_list/submitCauseList",
                    "state_code": state_code,
                    "dist_code": dist_code,
                    "court_complex_code": court_complex_code,
                    "CL_court_no": court_code,
                    "court_name_txt": court_name_txt or "",
                    "causelist_date": date,
                    "cause_list_captcha_code": captcha_code,
                    "est_code": est,
                    "selprevdays": "0",
                    "cicri": cicri,
                    "search": "true",
                    "ajax_req": "true",
                    "app_token": token,
                }
                r = self.session.post(f"{self.BASE_URL}/?p=cause_list/submitCauseList", data=payload, timeout=self.TIMEOUT)
                r.raise_for_status()
                try:
                    j = r.json()
                    if self._captcha_invalid(j):
                        return None
                    html = j.get("case_data", "")
                except Exception:
                    if self._captcha_invalid(r.text):
                        return None
                    html = r.text

            if not html:
                return None

            Path(out_dir).mkdir(parents=True, exist_ok=True)
            pdf_path = Path(out_dir) / f"causelist_{state_code}_{dist_code}_{court_complex_code}_{court_code.replace('^','-')}_{date}.pdf"
            wrapped = self._wrap_html_for_pdf(html)

            try:
                from weasyprint import HTML
                HTML(string=wrapped, base_url=self.BASE_URL).write_pdf(str(pdf_path))
                return str(pdf_path)
            except Exception:
                try:
                    import os, shutil, pdfkit
                    wkhtml = os.getenv("WKHTMLTOPDF_PATH") or shutil.which("wkhtmltopdf")
                    cfg = pdfkit.configuration(wkhtmltopdf=wkhtml) if wkhtml else None
                    if cfg:
                        pdfkit.from_string(wrapped, str(pdf_path), configuration=cfg)
                    else:
                        pdfkit.from_string(wrapped, str(pdf_path))
                    return str(pdf_path)
                except Exception as e:
                    logger.error(f"pdfkit failed: {e}")
                    (pdf_path.with_suffix(".html")).write_text(wrapped, encoding="utf-8")
                    return None
        except Exception as exc:
            logger.error(f"PDF generation failed: {exc}")
            return None

    def get_all_courts_cause_lists(
        self,
        state_code: str,
        dist_code: str,
        complex_code: str,
        date: str,
        captcha_code: Optional[str] = None
    ) -> Dict:
        """Download cause lists for ALL courts in a complex."""
        from hierarchy_fetcher import courts

        logger.info(f"Fetching all courts in complex {complex_code}...")
        court_list = courts(state_code, dist_code, complex_code)

        if not court_list:
            return {
                "success": False,
                "data": None,
                "message": "No courts found in complex"
            }

        results = []
        for court in court_list:
            logger.info(f"Fetching cause list for: {court['name']}")
            
            result = self.get_cause_list(
                state_code=state_code,
                dist_code=dist_code,
                court_complex_code=complex_code,
                court_code=court['code'],
                date=date,
                captcha_code=captcha_code
            )
            
            results.append({
                "court": court['name'],
                "court_code": court['code'],
                "result": result
            })

        successful = sum(1 for r in results if r["result"]["success"])

        return {
            "success": True,
            "data": {
                "complex_code": complex_code,
                "date": date,
                "total_courts": len(results),
                "successful": successful,
                "courts": results
            },
            "message": f"Downloaded {successful}/{len(results)} cause lists"
        }

    # ----------------------------------------------------------------
    # Parsing Helpers
    # ----------------------------------------------------------------
    def _parse_case_details(self, html: str) -> Optional[Dict]:
        """Parse case details from HTML response."""
        soup = BeautifulSoup(html, "lxml")
        case = {
            "case_number": None,
            "case_type": None,
            "filing_date": None,
            "petitioner": None,
            "respondent": None,
            "court_name": None,
            "judge_name": None,
            "next_hearing": None,
            "is_listed_today": False,
            "is_listed_tomorrow": False,
            "serial_number": None,
            "status": None,
        }

        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cols = row.find_all(["td", "th"])
                if len(cols) < 2:
                    continue
                label = cols[0].get_text(strip=True).lower()
                value = cols[1].get_text(strip=True)
                if not value or value == "-":
                    continue
                    
                if "case number" in label or "case no" in label:
                    case["case_number"] = value
                elif "case type" in label:
                    case["case_type"] = value
                elif "filing" in label:
                    case["filing_date"] = value
                elif "petitioner" in label or "plaintiff" in label:
                    case["petitioner"] = value
                elif "respondent" in label or "defendant" in label:
                    case["respondent"] = value
                elif "court" in label and "name" in label:
                    case["court_name"] = value
                elif "judge" in label or "coram" in label:
                    case["judge_name"] = value
                elif "next" in label and ("date" in label or "hearing" in label):
                    case["next_hearing"] = value
                    case["is_listed_today"] = self._is_today(value)
                    case["is_listed_tomorrow"] = self._is_tomorrow(value)
                elif "status" in label:
                    case["status"] = value

        return case if case["case_number"] else None


    def _parse_cause_list(self, html: str, date: str) -> List[Dict]:
        """Parse cause list from HTML response."""
        soup = BeautifulSoup(html, "lxml")
        cases = []

        for table in soup.find_all("table"):
            for idx, row in enumerate(table.find_all("tr")[1:], 1):
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue

                case_col_text = cols[1].get_text(strip=True)
            
                lines = case_col_text.split('Next hearing date:')
                case_number = lines[0].strip()
                case_number = re.sub(r'View\s*', '', case_number).strip()
                
                next_hearing = ""
                if len(lines) > 1:
                    next_hearing = lines[1].strip()
                    next_hearing = re.sub(r'^-\s*', '', next_hearing).strip()
                
                if not case_number:
                    continue
               
                cases.append({
                    "serial_number": cols[0].get_text(strip=True) or str(idx),
                    "case_number": case_number,
                    "parties": cols[2].get_text(strip=True) if len(cols) > 2 else "",
                    "purpose": cols[3].get_text(strip=True) if len(cols) > 3 else "",
                    "court_name": cols[4].get_text(strip=True) if len(cols) > 4 else "",
                    "next_hearing": next_hearing,
                    "date": date,
                })
                
        return cases


    def _is_today(self, ds: str) -> bool:
        parsed = self._parse_date(ds)
        return parsed == datetime.now().date() if parsed else False

    def _is_tomorrow(self, ds: str) -> bool:
        parsed = self._parse_date(ds)
        return parsed == (datetime.now() + timedelta(days=1)).date() if parsed else False

    @staticmethod
    def _parse_date(ds: str):
        if not ds:
            return None
        part = ds.split()[0]
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(part, fmt).date()
            except ValueError:
                continue
        return None


# ================================================================
# Quick Test
# ================================================================
if __name__ == "__main__":
    scraper = eCourtsScraper()

    print("Testing eCourts Scraper...")
    print("=" * 60)

    print("\n1. Getting app_token...")
    token = scraper._get_app_token()
    if token:
        print(f" Token: {token[:30]}...")
    else:
        print(" Failed to get token")

    print("\n" + "=" * 60)
    print("Ready to use!")