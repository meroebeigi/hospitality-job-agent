import assert from 'node:assert/strict';
import { test } from 'node:test';
import { findContact, findVenues, geocode } from './discovery.mjs';
import { application, emailDraft } from './drafts.mjs';

test('geocodes an address and filters out distant mapped venues', async t => {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    if (String(url).includes('geoapify')) {
      assert.equal(new URL(url).searchParams.get('text'), 'Test street, Copenhagen');
      return Response.json({ results: [{ lat: 55, lon: 12, formatted: 'Copenhagen' }] });
    }
    assert.match(options.body.get('data'), /around:2000,55,12/);
    return Response.json({ elements: [
      { type: 'node', id: 1, lat: 55.01, lon: 12, tags: { amenity: 'cafe', name: 'Near Café' } },
      { type: 'way', id: 2, center: { lat: 55.03, lon: 12 }, tags: { shop: 'kiosk', name: 'Far Kiosk' } },
    ] });
  });
  const center = await geocode('Test street, Copenhagen', 'fixture');
  const venues = await findVenues(center, 2);
  assert.deepEqual(venues.map(venue => venue.name), ['Near Café']);
});

test('uses a recruitment email and records its page', async t => {
  t.mock.method(globalThis, 'fetch', async url => new Response(
    String(url).endsWith('/jobs') ? '<a href="mailto:jobs@fixture.test">Apply</a>' : '<a href="/jobs">Jobs</a>',
    { headers: { 'Content-Type': 'text/html' } },
  ));
  const contact = await findContact({
    website: 'https://fixture.test/', mappedEmails: 'info@fixture.test', map: 'https://www.openstreetmap.org/node/42',
  });
  assert.equal(contact.email, 'jobs@fixture.test');
  assert.equal(contact.emailSource, 'https://fixture.test/jobs');
  assert.equal((await findContact({ mappedEmails: '' })).email, null);
});

test('writes an unsent application with CV evidence and the original attachment', () => {
  const resume = Buffer.from('Restaurant server with table service experience.');
  const draft = application({ name: 'Sample Café', category: 'cafe' }, 'Applicant', resume.toString());
  assert.match(draft.subject, /waiter or front-of-house assistant/);
  assert.match(draft.body, /Restaurant server with table service experience/);
  const eml = emailDraft('jobs@fixture.test', draft, resume, 'CV.txt');
  assert.match(eml, /^X-Unsent: 1\r\nTo: jobs@fixture\.test\r\n/);
  assert.ok(eml.includes(resume.toString('base64')));
  assert.ok(eml.includes("filename*=UTF-8''CV.txt"));
});
