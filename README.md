# Hospitality Job Agent

Find restaurants, cafés, takeaway shops, food kiosks, bakeries, and delis near an address. The agent checks public contact details and prepares an application addressed to each venue. The original CV is attached to each draft.

## Run a search

Install Python 3.10 or newer. The agent uses only Python’s standard library. In the repository directory, copy `.env.example` to `.env` and set `GEOAPIFY_API_KEY` using a key from [Geoapify](https://myprojects.geoapify.com/). Create a `private/` directory for your CV. On Windows, you can use `py` in place of `python` if the Python launcher is installed.

```powershell
python agent.py search --address "Rådhuspladsen 1, 1550 Copenhagen, Denmark" --radius-km 10 --name "Your Name" --resume private/CV.pdf --resume-text private/CV.txt
```

- **Distance.** `--radius-km 10` searches up to 10 km in a straight line from the center. For a circular area of 10 km², use `--area-km2 10` instead. The equivalent radius is about 1.78 km.
- **Address.** Include the city, postal code, and country. Check the resolved center printed at startup. With `--coordinates "55.6758,12.5690"` in place of `--address`, no geocoding key is needed.
- **CV.** Put a plain-text copy of the CV in `--resume-text` when attaching a PDF or Word document. A PDF with selectable text can also be read directly if `pdftotext` is on your PATH. A `.txt` or `.md` CV can be used directly.
- **Role.** Restaurants and cafés default to waiter or front-of-house assistant. Other venues default to food service assistant. Use `--role "waiter"` to override this for every venue.

## Review applications

The search creates a new directory under `output/`. Open `leads.json` for the venue list, straight-line distances, contact sources, Google Maps lookup links, and email text. The `.eml` files hold the application and original CV attachment. Open them with a compatible mail client or copy the text into your mail client and attach the CV.

The agent prefers recruitment addresses, then general business inboxes. Review the source and recipient before using a draft, especially for chains. A draft with no public address has a blank recipient. Drafts are in English and quote up to two relevant lines from the CV when available. Applications ask about openings speculatively.

### Optional Gmail drafts

For a Gmail mailbox draft, use a Gmail API OAuth access token with the `https://www.googleapis.com/auth/gmail.compose` scope. Set `GMAIL_ACCESS_TOKEN` in your local `.env` and upload one reviewed draft at a time.

```powershell
python agent.py gmail-draft output/search-EXAMPLE/node-12345.eml
```

The command only creates drafts. Each successful call creates a new Gmail draft. See [Gmail's draft API guide](https://developers.google.com/workspace/gmail/api/guides/drafts) for API details.

## Coverage and data

- Venue coverage depends on OpenStreetMap listings and tags. Kiosks may need a manual check to confirm they sell food. The search does not verify vacancies or guarantee a complete list of businesses.
- Emails come from venue websites and OpenStreetMap contact tags. The Google Maps link is for manual lookup.
- Geoapify receives the address for geocoding. Overpass receives the search coordinates. Resume text is processed locally. Gmail receives the draft and CV only when you run the optional Gmail command.
- Keep real CVs in `private/`, credentials in `.env`, and draft output in `output/`. These paths are ignored by Git.

Venue data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) via [Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API). Address geocoding by [Geoapify](https://apidocs.geoapify.com/docs/geocoding/forward-geocoding/).

Run `python -m unittest -v` to check discovery, contact prioritization, and draft generation with local fixtures.
