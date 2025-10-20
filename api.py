"""
eCourts Scraper – REST API (Fixed for real eCourts v6)
Exposes search + cause-list + hierarchy helpers for a front-end.
"""

from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile
import io as _io
import re
import time

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from scraper import eCourtsScraper
import hierarchy_fetcher as hf

app = Flask(__name__)
CORS(app)

scraper = eCourtsScraper()

# ====================================================================
# Helper
# ====================================================================
def _captcha_error():
    """Return standardized invalid-captcha error response."""
    return jsonify({
        "success": False,
        "code": "INVALID_CAPTCHA",
        "message": "Invalid captcha"
    }), 400

# ====================================================================
# Health
# ====================================================================
@app.route("/api/health")
def health():
    token = scraper._get_app_token()
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "has_token": bool(token)
    })

# ====================================================================
# Hierarchy
# ====================================================================
@app.route("/api/states")
def api_states():
    """Get list of all states."""
    try:
        states = hf.states()
        return jsonify({"success": True, "data": states})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/districts")
def api_districts():
    """Get districts for a state. Query: ?state_code=16"""
    state = request.args.get("state_code")
    if not state:
        return jsonify({"success": False, "message": "state_code required"}), 400

    try:
        districts = hf.districts(state)
        return jsonify({"success": True, "data": districts})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/complexes")
def api_complexes():
    """Get court complexes. Query: ?state_code=16&dist_code=13"""
    state = request.args.get("state_code")
    dist = request.args.get("dist_code")

    if not state or not dist:
        return jsonify({"success": False, "message": "state_code and dist_code required"}), 400

    try:
        complexes = hf.complexes(state, dist)
        return jsonify({"success": True, "data": complexes})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/courts")
def api_courts():
    """Get courts in a complex. Query: ?state_code=16&dist_code=13&complex_code=1360016"""
    state = request.args.get("state_code")
    dist = request.args.get("dist_code")
    comp = request.args.get("complex_code")

    if not state or not dist or not comp:
        return jsonify({
            "success": False,
            "message": "state_code, dist_code, and complex_code required"
        }), 400

    try:
        courts = hf.courts(state, dist, comp)
        return jsonify({"success": True, "data": courts})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ====================================================================
# Searches
# ====================================================================
@app.route("/api/search/cnr", methods=["POST"])
def search_cnr():
    """
    Search by CNR number.
    Body: {
        "cnr": "MHAU01999992015",
        "captcha_code": "abc12" (optional if already solved)
    }
    """
    data = request.get_json(silent=True) or {}

    if "cnr" not in data:
        return jsonify({"success": False, "message": "CNR required"}), 400

    captcha = data.get("captcha_code")
    res = scraper.search_by_cnr(data["cnr"], captcha)

    if not res["success"] and "captcha" in (res.get("message", "").lower()):
        return _captcha_error()

    return jsonify(res), 200 if res["success"] else 404

@app.route("/api/search/case", methods=["POST"])
def search_case():
    """
    Search by case details.
    Body: {
        "state_code": "16",
        "dist_code": "13",
        "court_complex_code": "1360016",
        "est_code": "null" (optional),
        "case_type": "5^3",
        "case_number": "1",
        "year": "2020",
        "captcha_code": "abc12" (optional)
    }
    """
    data = request.get_json(silent=True) or {}
    required = ["state_code", "dist_code", "court_complex_code", "case_type", "case_number", "year"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"success": False, "message": f"Missing required fields: {', '.join(missing)}"}), 400

    res = scraper.search_by_case_details(
        state_code=data["state_code"],
        dist_code=data["dist_code"],
        court_complex_code=data["court_complex_code"],
        est_code=data.get("est_code", "null"),
        case_type=data["case_type"],
        case_number=data["case_number"],
        year=data["year"],
        captcha_code=data.get("captcha_code"),
    )

    if not res["success"] and "captcha" in (res.get("message", "").lower()):
        return _captcha_error()

    return jsonify(res), 200 if res["success"] else 404

# ====================================================================
# Cause List (JSON)
# ====================================================================
@app.route("/api/causelist", methods=["GET", "POST"])
def api_causelist():
    """
    Get cause list for a specific court and date.
    Query params (GET) or Body (POST):
    {
        "state_code": "16",
        "dist_code": "13",
        "court_complex_code": "1360016",
        "court_code": "346^11",
        "date": "17-10-2025" (optional, defaults to today),
        "case_type": "civ" (optional, defaults to civ),
        "court_name_txt": "Court Name" (optional),
        "captcha_code": "abc12" (optional)
    }
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args.to_dict()

    required = ["state_code", "dist_code", "court_complex_code", "court_code"]
    missing = [k for k in required if k not in data]

    if missing:
        return jsonify({
            "success": False,
            "message": f"Missing required fields: {', '.join(missing)}"
        }), 400

    date = data.get("date") or datetime.now().strftime("%d-%m-%Y")

    res = scraper.get_cause_list(
        state_code=data["state_code"],
        dist_code=data["dist_code"],
        court_complex_code=data["court_complex_code"],
        court_code=data["court_code"],
        date=date,
        captcha_code=data.get("captcha_code"),
        case_type=data.get("case_type", "civ"),
        court_name_txt=data.get("court_name_txt", "")
    )

    if res.get("captcha_error") or (not res.get("success") and "captcha" in (res.get("message", "").lower())):
        return _captcha_error()

    return jsonify(res)

@app.route("/api/causelist/today", methods=["POST"])
def api_today():
    """Convenience endpoint for today's cause list."""
    data = request.get_json(silent=True) or {}
    data["date"] = datetime.now().strftime("%d-%m-%Y")
    request.get_json = lambda silent=True: data
    return api_causelist()

@app.route("/api/causelist/tomorrow", methods=["POST"])
def api_tomorrow():
    """Convenience endpoint for tomorrow's cause list."""
    data = request.get_json(silent=True) or {}
    data["date"] = (datetime.now() + timedelta(days=1)).strftime("%d-%m-%Y")
    request.get_json = lambda silent=True: data
    return api_causelist()

# ====================================================================
# Captcha
# ====================================================================
@app.route("/api/captcha")
def api_captcha():
    try:
        from urllib.parse import urljoin

        def _is_img(r):
            ct = r.headers.get("Content-Type", "").lower()
            head = r.content[:4]
            return ("image" in ct or "octet-stream" in ct or head in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1"))

        sid = int(time.time() * 1000)
        token = scraper._get_app_token(force_refresh=True) or ""
        base = scraper.BASE_URL.rstrip("/")
        headers_json = {"Referer": f"{scraper.BASE_URL}/?p=casestatus/index"}
        headers_img = {"Referer": f"{scraper.BASE_URL}/?p=casestatus/index",
                       "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}

        # 1) Browser-like getCaptcha call with token
        r = scraper.session.get(
            f"{base}/",
            params={"p": "casestatus/getCaptcha", "ajax_req": "true", "app_token": token, "_": sid},
            headers=headers_json,
            timeout=scraper.TIMEOUT,
        )
        if r.ok and _is_img(r):
            resp = send_file(_io.BytesIO(r.content), mimetype=r.headers.get("Content-Type", "image/png"))
            resp.headers["Cache-Control"] = "no-store"
            return resp

        # Extract <img src="..."> and fetch it with proper Accept
        try:
            j = r.json()
        except Exception:
            j = None
        html = " ".join([v for v in (j or {}).values() if isinstance(v, str)]) if isinstance(j, dict) else (r.text or "")
        m = re.search(r'<img[^>]+src=["\']([^"\']*(?:securimage|captcha)[^"\']*)["\']', html, re.I)
        if m:
            img_url = urljoin(scraper.BASE_URL + "/", m.group(1))
            ir = scraper.session.get(img_url, headers=headers_img, timeout=scraper.TIMEOUT)
            if ir.ok and _is_img(ir):
                resp = send_file(_io.BytesIO(ir.content), mimetype=ir.headers.get("Content-Type", "image/png"))
                resp.headers["Cache-Control"] = "no-store"
                return resp

        # 2) Hard fallback: securimage with sid
        for url in (
            f"{base}/securimage/securimage_show.php?sid={sid}&app_token={token}",
            f"{base}/securimage/securimage_show.php?sid={sid}",
        ):
            ir = scraper.session.get(url, headers=headers_img, timeout=scraper.TIMEOUT)
            if ir.ok and _is_img(ir):
                resp = send_file(_io.BytesIO(ir.content), mimetype=ir.headers.get("Content-Type", "image/png"))
                resp.headers["Cache-Control"] = "no-store"
                return resp

        return jsonify({"success": False, "message": "Captcha fetch failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ====================================================================
# Cause List PDF Download
# ====================================================================
@app.route("/api/causelist/pdf", methods=["POST"])
def api_causepdf():
    """
    Download cause list as PDF.
    Body: Same as /api/causelist
    """
    data = request.get_json(silent=True) or {}
    required = ["state_code", "dist_code", "court_complex_code", "court_code"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"success": False, "message": f"Missing required fields: {', '.join(missing)}"}), 400

    date = data.get("date") or datetime.now().strftime("%d-%m-%Y")

    cl = scraper.get_cause_list(
        state_code=data["state_code"],
        dist_code=data["dist_code"],
        court_complex_code=data["court_complex_code"],
        court_code=data["court_code"],
        date=date,
        captcha_code=data.get("captcha_code"),
        case_type=data.get("case_type", "civ"),
        court_name_txt=data.get("court_name_txt", "")
    )
    if not cl.get("success"):
        if "captcha" in (cl.get("message", "").lower()):
            return _captcha_error()
        return jsonify({"success": False, "message": cl.get("message", "Could not fetch cause list")}), 400

    pdf_path = scraper.download_cause_list_pdf(
        state_code=data["state_code"],
        dist_code=data["dist_code"],
        court_complex_code=data["court_complex_code"],
        court_code=data["court_code"],
        date=date,
        html=cl.get("html"),
        case_type=data.get("case_type", "civ"),
        court_name_txt=data.get("court_name_txt", "")
    )
    if not pdf_path:
        return jsonify({"success": False, "message": "PDF generation failed"}), 500

    return send_file(pdf_path, mimetype="application/pdf", as_attachment=True, download_name=f"causelist_{date}.pdf")

# ====================================================================
# Cause List ALL PDFs (ZIP)
# ====================================================================
@app.route("/api/causelist/pdf/all", methods=["POST"])
def api_causepdf_all():
    """
    Download all cause lists for a complex as ZIP.
    Body: {
        "state_code": "16",
        "dist_code": "13",
        "court_complex_code": "1360016",
        "date": "17-10-2025",
        "case_type": "civ" (optional),
        "captcha_code": "abc12"
    }
    """
    d = request.get_json(silent=True) or {}
    for k in ["state_code", "dist_code", "court_complex_code", "date", "captcha_code"]:
        if k not in d:
            return jsonify({"success": False, "message": f"Missing {k}"}), 400

    courts = hf.courts(d["state_code"], d["dist_code"], d["court_complex_code"])
    if not courts:
        return jsonify({"success": False, "message": "No courts found"}), 404

    mem = _io.BytesIO()
    z = ZipFile(mem, "w")
    ok = 0

    for c in courts:
        cl = scraper.get_cause_list(
            state_code=d["state_code"],
            dist_code=d["dist_code"],
            court_complex_code=d["court_complex_code"],
            court_code=c["code"],
            date=d["date"],
            captcha_code=d["captcha_code"],
            case_type=d.get("case_type", "civ"),
            court_name_txt=c["name"],
        )
        if not cl.get("success"):
            continue
        
        pdf_path = scraper.download_cause_list_pdf(
            state_code=d["state_code"],
            dist_code=d["dist_code"],
            court_complex_code=d["court_complex_code"],
            court_code=c["code"],
            date=d["date"],
            html=cl.get("html"),
            case_type=d.get("case_type", "civ"),
            court_name_txt=c["name"],
        )
        if pdf_path:
            z.write(pdf_path, arcname=Path(pdf_path).name)
            ok += 1

    z.close()
    mem.seek(0)
    if ok == 0:
        return jsonify({"success": False, "message": "No PDFs generated"}), 500
    
    return send_file(mem, mimetype="application/zip", as_attachment=True, download_name=f"causelist_all_{d['date']}.zip")

# ====================================================================
# Stats
# ====================================================================
@app.route("/api/stats", methods=["POST"])
def api_stats():
    """
    Get statistics for a cause list.
    Body: Same as /api/causelist
    """
    data = request.get_json(silent=True) or {}

    required = ["state_code", "dist_code", "court_complex_code", "court_code"]
    missing = [k for k in required if k not in data]

    if missing:
        return jsonify({
            "success": False,
            "message": f"Missing required fields: {', '.join(missing)}"
        }), 400

    date = data.get("date") or datetime.now().strftime("%d-%m-%Y")

    cl = scraper.get_cause_list(
        state_code=data["state_code"],
        dist_code=data["dist_code"],
        court_complex_code=data["court_complex_code"],
        court_code=data["court_code"],
        date=date,
        captcha_code=data.get("captcha_code"),
        case_type=data.get("case_type", "civ"),
        court_name_txt=data.get("court_name_txt", "")
    )

    if not cl["success"]:
        return jsonify({"success": False, "message": "Could not fetch cause list"}), 404

    # Generate basic statistics
    cases = cl["data"]["cases"]
    stats = {
        "total_cases": len(cases),
        "date": date,
        "court_code": data["court_code"],
        "case_types": {},
        "purposes": {}
    }

    # Count by type and purpose
    for case in cases:
        case_type = case.get("case_type", "Unknown")
        purpose = case.get("purpose", "Unknown")

        stats["case_types"][case_type] = stats["case_types"].get(case_type, 0) + 1
        stats["purposes"][purpose] = stats["purposes"].get(purpose, 0) + 1

    return jsonify({"success": True, "data": stats})

# ====================================================================
# Banner & Run
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("eCourts Scraper API (v6 Compatible)")
    print("=" * 70)
    print("Server: http://localhost:5000")
    print("\n Hierarchy End-points:")
    print(" GET /api/states")
    print(" GET /api/districts?state_code=16")
    print(" GET /api/complexes?state_code=16&dist_code=13")
    print(" GET /api/courts?state_code=16&dist_code=13&complex_code=1360016")
    print("\n Search End-points:")
    print(" POST /api/search/cnr")
    print(" Body: {\"cnr\": \"MHAU01999992015\", \"captcha_code\": \"abc12\"}")
    print(" POST /api/search/case")
    print(" Body: {\"state_code\": \"16\", \"dist_code\": \"13\", ...}")
    print("\n Cause List End-points:")
    print(" POST /api/causelist")
    print(" POST /api/causelist/today")
    print(" POST /api/causelist/tomorrow")
    print(" POST /api/causelist/pdf")
    print(" POST /api/causelist/pdf/all")
    print("\n Utility End-points:")
    print(" GET /api/captcha")
    print(" POST /api/stats")
    print(" GET /api/health")
    print("=" * 70 + "\n")

    app.run(debug=True, port=5000)