import base64
import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import agent
import discovery


class HospitalityAgentTests(unittest.TestCase):
    def test_address_and_venue_radius(self):
        with patch("discovery.request_json") as request:
            request.side_effect = [
                {"results": [{"lat": 55, "lon": 12, "formatted": "Test address"}]},
                {"elements": [
                    {"type": "node", "id": 1, "lat": 55.01, "lon": 12, "tags": {"name": "Near", "amenity": "cafe"}},
                    {"type": "way", "id": 2, "center": {"lat": 55.03, "lon": 12}, "tags": {"name": "Far", "shop": "kiosk"}},
                ]},
            ]
            center = discovery.geocode("Test address", "fixture")
            venues = discovery.find_venues(center, 2)
        address_request, map_request = request.call_args_list
        self.assertEqual(parse_qs(urlsplit(address_request.args[0]).query)["text"], ["Test address"])
        self.assertIn("around:2000,55,12", parse_qs(map_request.kwargs["data"].decode())["data"][0])
        self.assertEqual([venue["name"] for venue in venues], ["Near"])

    def test_recruitment_email_and_source(self):
        home = "https://fixture.test/"
        jobs = home + "jobs"
        venue = {"website": home, "mappedEmails": "info@fixture.test", "map": "https://www.openstreetmap.org/node/42"}
        with patch("discovery.get_page", side_effect=[
            (home, discovery.ContactPage('<a href="/jobs">Jobs</a><script>fake@fixture.test</script>')),
            (jobs, discovery.ContactPage('<a href="mailto:jobs%40fixture.test">Apply</a>')),
        ]):
            contact = discovery.find_contact(venue)
        self.assertEqual(contact["email"], "jobs@fixture.test")
        self.assertEqual(contact["emailSource"], jobs)
        self.assertEqual(len(contact["contacts"]), 2)

    def test_search_writes_report_and_attached_cv(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as work:
            root = Path(work)
            cv = root / "CV.txt"
            cv.write_text("Restaurant server with table service experience.", encoding="utf-8")
            venue = {
                "id": "node-1", "name": "Test Café", "category": "cafe", "website": None,
                "map": "https://www.openstreetmap.org/node/1", "mappedEmails": "",
            }
            with patch("agent.find_venues", return_value=[venue]) as search, redirect_stdout(io.StringIO()):
                status = agent.main([
                    "search", "--coordinates", "55,12", "--area-km2", "10", "--name", "Applicant",
                    "--resume", str(cv), "--out", str(root / "output"),
                ])
            self.assertEqual(status, 0)
            self.assertAlmostEqual(search.call_args.args[1], math.sqrt(10 / math.pi))
            report_path, = (root / "output").glob("*/leads.json")
            lead, = json.loads(report_path.read_text(encoding="utf-8"))["venues"]
            self.assertIsNone(lead["email"])
            message = BytesParser(policy=policy.default).parsebytes((report_path.parent / lead["draft"]).read_bytes())
            self.assertEqual(message["X-Unsent"], "1")
            self.assertIsNone(message["To"])
            self.assertIn("Restaurant server", message.get_body().get_content())
            attachment, = message.iter_attachments()
            self.assertEqual(attachment.get_payload(decode=True), cv.read_bytes())

    def test_gmail_uses_only_draft_endpoint(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as work:
            path = Path(work) / "reviewed.eml"
            path.write_bytes(agent.email_draft("jobs@fixture.test", "Application", "Hello.", b"CV", "CV.pdf"))
            with patch.dict(os.environ, {"GMAIL_ACCESS_TOKEN": "fixture"}), \
                 patch("agent.request_json", return_value={"id": "draft-id"}) as request, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(agent.main(["gmail-draft", str(path)]), 0)
            self.assertEqual(request.call_args.args[0], "https://gmail.googleapis.com/gmail/v1/users/me/drafts")
            sent = base64.urlsafe_b64decode(json.loads(request.call_args.kwargs["data"])["message"]["raw"])
            message = BytesParser(policy=policy.default).parsebytes(sent)
            self.assertIsNone(message["X-Unsent"])
            self.assertEqual(message["To"], "jobs@fixture.test")


if __name__ == "__main__":
    unittest.main()
