"""Address lookup, venue discovery, and public business contacts."""

import json
import math
import os
import re
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import unquote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


USER_AGENT = "HospitalityJobAgent/2.0 (local job search)"
EMAIL = re.compile(r"[\w.!#$%&'*+/=?^_~-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,63}\b", re.I | re.ASCII)


def request_json(url, *, service, data=None, headers=None, timeout=15):
    request = Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (OSError, ValueError) as error:
        detail = getattr(error, "code", None)
        raise RuntimeError(f"{service} request failed" + (f" (HTTP {detail})." if detail else ".")) from error


def geocode(address, key):
    query = urlencode({"text": address, "apiKey": key, "format": "json", "limit": 1})
    data = request_json(f"https://api.geoapify.com/v1/geocode/search?{query}", service="Geocoding")
    results = data.get("results") or []
    if not results or not valid_point(results[0].get("lat"), results[0].get("lon")):
        raise ValueError("Address not found. Include city, postal code, and country.")
    return {key: results[0].get(key) for key in ("lat", "lon")} | {"label": results[0].get("formatted")}


def valid_point(lat, lon):
    return (
        isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        and -90 <= lat <= 90 and -180 <= lon <= 180
    )


def distance_km(center, lat, lon):
    lat1, lat2 = math.radians(center["lat"]), math.radians(lat)
    dlon = math.radians(lon - center["lon"])
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1, a)))


def web_url(value, base=""):
    if not value:
        return None
    try:
        url = urljoin(base, value.strip())
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and parts.hostname and not (parts.username or parts.password):
            return url
    except ValueError:
        pass
    return None


def find_venues(center, radius):
    around = f'(around:{math.ceil(radius * 1000)},{center["lat"]},{center["lon"]})'
    query = (
        '[out:json][timeout:40];('
        f'nwr["amenity"~"^(restaurant|cafe|fast_food|ice_cream)$"]{around};'
        f'nwr["shop"~"^(kiosk|bakery|deli)$"]{around};);out center;'
    )
    url = os.environ.get("OVERPASS_URL") or "https://overpass-api.de/api/interpreter"
    data = request_json(
        url, service="Overpass venue search", data=urlencode({"data": query}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=60,
    )
    if data.get("remark") or not isinstance(data.get("elements"), list):
        raise RuntimeError("Overpass returned an incomplete result. Try a smaller radius or another endpoint.")
    venues = []
    for element in data["elements"]:
        tags = element.get("tags", {})
        kind, identity = element.get("type"), element.get("id")
        name = (tags.get("name") or tags.get("brand") or tags.get("operator") or "").strip()
        point = element.get("center", element)
        lat, lon = point.get("lat"), point.get("lon")
        if kind not in ("node", "way", "relation") or type(identity) is not int:
            continue
        if not name or tags.get("access") == "private" or not valid_point(lat, lon):
            continue
        km = distance_km(center, lat, lon)
        if km > radius:
            continue
        address = ", ".join(filter(None, (
            " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])),
            " ".join(filter(None, [tags.get("addr:postcode"), tags.get("addr:city")])),
        )))
        map_query = urlencode({"api": 1, "query": f"{name} {address} {lat},{lon}"})
        venues.append({
            "id": f"{kind}-{identity}", "name": name, "category": tags.get("amenity") or tags.get("shop"),
            "address": address, "km": km, "website": web_url(tags.get("contact:website") or tags.get("website")),
            "map": f"https://www.openstreetmap.org/{kind}/{identity}",
            "mapsSearch": f"https://www.google.com/maps/search/?{map_query}",
            "mappedEmails": " ".join(filter(None, [tags.get("contact:email"), tags.get("email")])),
        })
    unique = []
    locations = {}
    for venue in sorted(venues, key=lambda venue: venue["km"]):
        key = (venue["name"].casefold(), venue["address"].casefold())
        previous = locations.get(key)
        if venue["address"] and previous is not None and venue["km"] - previous < 0.1:
            continue
        locations[key] = venue["km"]
        unique.append(venue)
    return unique


class ContactPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.text = []
        self.hidden = None
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attributes):
        if tag in ("script", "style"):
            self.hidden = tag
        if tag != "a" or self.hidden:
            return
        url = dict(attributes).get("href") or ""
        if url.lower().startswith("mailto:"):
            self.text.append(unquote(url[7:].split("?", 1)[0]))
        else:
            self.links.append(url)

    def handle_endtag(self, tag):
        if tag == self.hidden:
            self.hidden = None

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def get_page(url):
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=4.5) as response:
            if response.headers.get_content_type() != "text/html":
                return None
            charset = response.headers.get_content_charset() or "utf-8"
            return response.geturl(), ContactPage(response.read(600_000).decode(charset, errors="replace"))
    except (OSError, URLError, ValueError, LookupError):
        return None


def email_priority(email):
    local = email.lower().split("@", 1)[0]
    if local in {"career", "careers", "job", "jobs", "hr", "recruitment", "rekruttering", "bewerbung", "ansogning"}:
        return 0
    if local in {"info", "kontakt", "contact", "hello", "hej", "office"}:
        return 1
    return 2


def find_contact(venue):
    contacts = {}

    def add(text, source):
        for email in EMAIL.findall(text):
            local, domain = email.lower().split("@", 1)
            if local in {"noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "support", "abuse"}:
                continue
            if domain in {"example.com", "example.net", "example.org", "sentry.io"}:
                continue
            if domain.rsplit(".", 1)[-1] in {"png", "jpg", "jpeg", "gif", "webp", "svg"}:
                continue
            contacts[email.lower()] = {"email": email, "source": source}

    add(venue["mappedEmails"], venue["map"])
    home = get_page(venue["website"]) if venue["website"] else None
    if home:
        home_url, page = home
        origin = urlsplit(home_url)[:2]
        add(" ".join(page.text), home_url)
        relevant = {}
        for href in page.links:
            url = web_url(href, home_url)
            if url and url != home_url and urlsplit(url)[:2] == origin and re.search(
                r"contact|kontakt|career|karriere|job|impressum", urlsplit(url).path, re.I
            ):
                relevant[url] = None
        for url in list(relevant)[:4]:
            result = get_page(url)
            if result:
                source, page = result
                add(" ".join(page.text), source)
    ranked = sorted(contacts.values(), key=lambda item: email_priority(item["email"]))
    best = ranked[0] if ranked else {}
    return {"email": best.get("email"), "emailSource": best.get("source"), "contacts": ranked}
