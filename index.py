from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
import httpx
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

KARNATAKA_URL = "https://kpme.karnataka.gov.in/AllapplicationList.aspx"


@app.get("/")
async def health():
    return {"success": True, "status": "running"}


@app.post("/karnataka/search")
async def karnataka_search(request: Request):
    try:
        body = await request.json()
        certificate_no = body.get("certificate_no", "").strip()
        if not certificate_no:
            return {"success": False, "error": "certificate_no is required"}

        with httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS) as client:
            # Step 1 — GET to extract ViewState tokens
            get_resp = client.get(KARNATAKA_URL)
            soup = BeautifulSoup(get_resp.text, "lxml")
            tokens = {}
            for field in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]:
                tag = soup.find("input", {"name": field})
                if tag:
                    tokens[field] = tag.get("value", "")

            if not tokens.get("__VIEWSTATE"):
                return {"success": False, "error": "Could not extract ViewState"}

            # Step 2 — POST the search form
            post_resp = client.post(
                KARNATAKA_URL,
                data={
                    **tokens,
                    "ctl00$ContentPlaceHolder1$txt_app_cert": certificate_no,
                    "ctl00$ContentPlaceHolder1$btn_app_cert": "Search",
                },
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded", "Referer": KARNATAKA_URL}
            )

        results = []
        for table in BeautifulSoup(post_resp.text, "lxml").find_all("table"):
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 6:
                    continue
                name = cols[2].get_text(strip=True)
                if not name or name.lower() in ("×", "search"):
                    continue
                results.append({
                    "system_of_medicine":   cols[0].get_text(strip=True),
                    "category":             cols[1].get_text(strip=True),
                    "establishment_name":   name,
                    "address":              cols[3].get_text(strip=True),
                    "certificate_validity": cols[4].get_text(strip=True),
                    "certificate_no":       cols[5].get_text(strip=True),
                })

        return {"success": True, "count": len(results), "data": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/kerala/details")
async def kerala_details(request: Request):
    try:
        body = await request.json()
        url = body.get("url", "").strip()
        if not url:
            return {"success": False, "error": "url is required"}

        with httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS) as client:
            r = client.get(url)

        if r.status_code != 200:
            return {"success": False, "error": f"Site returned {r.status_code}"}

        soup = BeautifulSoup(r.text, "lxml")
        lines = [l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]
        result = {}
        for i, line in enumerate(lines):
            try:
                if "Name of the Clinical Establishment" in line:
                    result["name_of_clinical_establishment"] = lines[i + 1]
                elif line == "District":
                    result["district"] = lines[i + 1]
                elif line == "Ownership":
                    result["ownership"] = lines[i + 1]
                elif line == "Address":
                    result["address"] = lines[i + 1]
                elif "Permanent Registration No" in line:
                    result["permanent_registration_no"] = lines[i + 1]
                elif line == "Valid From":
                    result["valid_from"] = lines[i + 1]
                elif line == "Valid To":
                    result["valid_to"] = lines[i + 1]
                elif "Application Status" in line:
                    result["application_status"] = lines[i + 1]
            except Exception:
                continue

        return {"success": True, "data": result}

    except Exception as e:
        return {"success": False, "error": str(e)}
