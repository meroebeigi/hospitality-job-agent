"""Find hospitality venues and prepare unsent applications."""

import argparse
import base64
import json
import math
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from discovery import EMAIL, find_contact, find_venues, geocode, request_json, valid_point


HOSPITALITY = re.compile(
    r"\b(waiter|waitress|server|hospitality|barista|café|cafe|restaurant|cashier|customer service"
    r"|food service|kitchen|catering|guest service|tjener|kundeservice|køkken)\b", re.I,
)


def load_settings():
    path = Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key in {"GEOAPIFY_API_KEY", "OVERPASS_URL", "GMAIL_ACCESS_TOKEN"}:
            os.environ.setdefault(key, value.strip().strip("'\""))


def resume_text(path, text_path, attachment):
    if text_path:
        return text_path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".txt", ".md"}:
        return attachment.decode("utf-8-sig")
    if path.suffix.lower() == ".pdf":
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(path.resolve()), "-"], capture_output=True, check=True, timeout=15,
            )
            return result.stdout.decode("utf-8-sig")
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("Install pdftotext or pass a plain-text copy with --resume-text.") from error
    raise ValueError("Provide a plain-text copy of this CV with --resume-text.")


def application(venue, name, cv, role=None):
    role = role or (
        "waiter or front-of-house assistant" if venue["category"] in {"restaurant", "cafe"}
        else "food service assistant"
    )
    business = " ".join(venue["name"].split())
    evidence = [
        line for line in dict.fromkeys(line.strip() for line in cv.splitlines())
        if 12 <= len(line) <= 180 and HOSPITALITY.search(line) and not EMAIL.search(line)
    ][:2]
    paragraphs = [
        f"Dear {business} team,",
        f"I’m writing to ask about {role} opportunities at {business}.",
    ]
    if evidence:
        paragraphs.append("Relevant details from my CV:\n"
                          + "\n".join("• " + line.lstrip("-*• ") for line in evidence))
    paragraphs += [
        "My CV is attached. If you have any current or upcoming openings, "
        "I’d be happy to discuss how I could help your team.",
        "Thank you for your time.",
        f"Kind regards,\n{name}",
    ]
    return f"Application for {role} — {business}", "\n\n".join(paragraphs)


def email_draft(recipient, subject, body, attachment, filename):
    message = EmailMessage(policy=policy.SMTP)
    message["X-Unsent"] = "1"
    if recipient:
        message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    maintype, subtype = (mimetypes.guess_type(filename)[0] or "application/octet-stream").split("/")
    message.add_attachment(attachment, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes()


def search(args):
    radius = args.radius_km if args.radius_km is not None else 10
    if args.area_km2 is not None:
        if not math.isfinite(args.area_km2) or args.area_km2 <= 0:
            raise ValueError("The search area must be positive and finite.")
        radius = math.sqrt(args.area_km2 / math.pi)
    if not math.isfinite(radius) or radius <= 0 or not math.isfinite(radius * 1000):
        raise ValueError("The search radius must be positive and finite.")
    for label, value in (("name", args.name), ("role", args.role)):
        if value is not None and (not value.strip() or "\n" in value or "\r" in value):
            raise ValueError(f"Enter a {label} on one line.")
    attachment = args.resume.read_bytes()
    cv = resume_text(args.resume, args.resume_text, attachment)
    if not attachment or not cv.strip():
        raise ValueError("Provide a nonempty CV with readable text.")
    if args.coordinates:
        try:
            lat, lon = map(float, args.coordinates.split(","))
        except ValueError as error:
            raise ValueError('Use --coordinates "latitude,longitude" in decimal degrees.') from error
        if not valid_point(lat, lon):
            raise ValueError("Coordinates are outside the valid latitude or longitude range.")
        center = {"lat": lat, "lon": lon}
    else:
        key = os.environ.get("GEOAPIFY_API_KEY")
        if not key:
            raise ValueError("Set GEOAPIFY_API_KEY in .env for address searches.")
        center = geocode(args.address, key)
    print(f'Search center: {center.get("label") or (center["lat"], center["lon"])} | Radius: {radius:.3f} km')
    venues = find_venues(center, radius)
    print(f"Found {len(venues)} mapped venues. Checking public contacts.", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="search-", dir=args.out))
    attribution = "© OpenStreetMap contributors — https://www.openstreetmap.org/copyright"
    report = {"center": center, "radiusKm": radius, "attribution": attribution, "venues": []}
    for venue in venues:
        contact = find_contact(venue)
        subject, body = application(venue, args.name.strip(), cv, args.role.strip() if args.role else None)
        filename = venue["id"] + ".eml"
        (folder / filename).write_bytes(email_draft(contact["email"], subject, body, attachment, args.resume.name))
        details = {key: value for key, value in venue.items() if key != "mappedEmails"}
        report["venues"].append(details | contact | {"draft": filename, "subject": subject, "body": body})
        print(f'{venue["name"]} — {contact["email"] or "email needs review"}', flush=True)
    (folder / "leads.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved draft emails and leads.json to {folder}\n{attribution}")
    return folder


def gmail_draft(args):
    token = os.environ.get("GMAIL_ACCESS_TOKEN")
    if not token:
        raise ValueError("Set GMAIL_ACCESS_TOKEN before uploading a reviewed draft.")
    message = BytesParser(policy=policy.SMTP).parsebytes(args.file.read_bytes())
    recipients = message.get_all("To", [])
    if (
        message.get("X-Unsent") != "1" or len(recipients) != 1 or len(recipients[0].addresses) != 1
        or not EMAIL.fullmatch(recipients[0].addresses[0].addr_spec) or message.get("Cc") or message.get("Bcc")
    ):
        raise ValueError("Choose an unsent draft with a single reviewed recipient.")
    del message["X-Unsent"]
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    draft = request_json(
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts", service="Gmail draft",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps({"message": {"raw": raw}}).encode(), timeout=30,
    )
    print(f'Created an unsent Gmail draft: {draft["id"]}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True, dest="command")
    search_parser = commands.add_parser("search", help="Find venues and write local email drafts")
    location = search_parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--address")
    location.add_argument("--coordinates", help="Latitude,longitude in decimal degrees")
    distance = search_parser.add_mutually_exclusive_group()
    distance.add_argument("--radius-km", type=float, help="Straight-line search radius (default: 10 km)")
    distance.add_argument("--area-km2", type=float, help="Circular search area in square kilometres")
    search_parser.add_argument("--name", required=True)
    search_parser.add_argument("--resume", type=Path, required=True, help="Original CV to attach")
    search_parser.add_argument("--resume-text", type=Path, help="Plain-text copy of your CV")
    search_parser.add_argument("--role", help="Override the default role for every venue")
    search_parser.add_argument("--out", type=Path, default=Path("output"))
    search_parser.set_defaults(run=search)
    gmail_parser = commands.add_parser("gmail-draft", help="Create one unsent Gmail draft from a reviewed EML file")
    gmail_parser.add_argument("file", type=Path)
    gmail_parser.set_defaults(run=gmail_draft)
    args = parser.parse_args(argv)
    try:
        load_settings()
        args.run(args)
    except (OSError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
