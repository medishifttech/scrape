from http.server import BaseHTTPRequestHandler
import httpx
from bs4 import BeautifulSoup
import json

KARNATAKA_URL = "https://kpme.karnataka.gov.in/AllapplicationList.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}


def extract_aspnet_tokens(html: str) -> dict:
    """Extract hidden ASP.NET form fields needed for POST"""
    soup = BeautifulSoup(html, "lxml")
    tokens = {}
    for field in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]:
        tag = soup.find("input", {"name": field})
        if tag:
            tokens[field] = tag.get("value", "")
    return tokens


def parse_results(html: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 6:
                continue
            try:
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
            except Exception:
                continue
    return results


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        certificate_no = body.get("certificate_no", "").strip()

        if not certificate_no:
            self._respond(400, {"success": False, "error": "certificate_no is required"})
            return

        try:
            with httpx.Client(
                timeout=30,
                follow_redirects=True,
                headers=HEADERS
            ) as client:

                # Step 1 — GET page to grab ASP.NET hidden tokens
                get_resp = client.get(KARNATAKA_URL)
                tokens = extract_aspnet_tokens(get_resp.text)

                if not tokens.get("__VIEWSTATE"):
                    self._respond(200, {
                        "success": False,
                        "error": "Could not extract ViewState — site may have changed"
                    })
                    return

                # Step 2 — POST the search form
                form_data = {
                    **tokens,
                    "ctl00$ContentPlaceHolder1$txt_app_cert": certificate_no,
                    "ctl00$ContentPlaceHolder1$btn_app_cert": "Search",
                }

                post_resp = client.post(
                    KARNATAKA_URL,
                    data=form_data,
                    headers={
                        **HEADERS,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": KARNATAKA_URL,
                    }
                )

            results = parse_results(post_resp.text)
            self._respond(200, {"success": True, "count": len(results), "data": results})

        except Exception as e:
            self._respond(200, {"success": False, "error": str(e)})

    def _respond(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)