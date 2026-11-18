import { mkdtemp, readFile, mkdir, writeFile } from 'node:fs/promises';
import { basename, extname, join } from 'node:path';
import { parseArgs, promisify } from 'node:util';
import { execFile } from 'node:child_process';
import { findContact, findVenues, geocode } from './discovery.mjs';
import { application, emailDraft } from './drafts.mjs';

const usage = 'npm run search -- --address "Street, City, Country" --radius-km 10 --name "Your Name" --resume private/cv.pdf\n'
  + 'Options: --area-km2 10, --coordinates "lat,lon", --resume-text private/cv.txt, --role "waiter", --out output';

async function readResumeText(resume, textPath, bytes) {
  if (textPath) return readFile(textPath, 'utf8');
  if (/^\.(txt|md)$/i.test(extname(resume))) return bytes.toString('utf8');
  if (/\.pdf$/i.test(resume)) {
    try {
      const { stdout } = await promisify(execFile)('pdftotext', ['-layout', resume, '-'], { timeout: 15000 });
      return stdout;
    } catch {
      throw new Error('Could not extract PDF text. Install pdftotext or pass a plain-text copy with --resume-text.');
    }
  }
  throw new Error('For this resume format, provide a plain-text copy with --resume-text.');
}

async function main() {
  const stringOptions = ['address', 'coordinates', 'name', 'resume', 'resume-text', 'role', 'radius-km', 'area-km2', 'out'];
  const { values } = parseArgs({ options: {
    ...Object.fromEntries(stringOptions.map(key => [key, { type: 'string' }])),
    help: { type: 'boolean' },
  } });
  if (values.help) return console.log(usage);
  if (!values.name?.trim() || !values.resume || Boolean(values.address) === Boolean(values.coordinates)) {
    throw new Error('Supply a name, a resume, and either an address or coordinates.\n' + usage);
  }
  if (values['radius-km'] !== undefined && values['area-km2'] !== undefined) {
    throw new Error('Choose either --radius-km or --area-km2.');
  }
  const radius = values['area-km2'] === undefined ? Number(values['radius-km'] ?? 10)
    : Math.sqrt(Number(values['area-km2']) / Math.PI);
  if (!Number.isFinite(radius) || radius <= 0) throw new Error('The search distance or area must be positive.');
  if (values.role !== undefined && (!values.role.trim() || /[\r\n]/.test(values.role))) {
    throw new Error('Enter a role on one line.');
  }
  const resume = await readFile(values.resume);
  const cv = await readResumeText(values.resume, values['resume-text'], resume);
  if (!cv.trim() || !resume.length) throw new Error('Provide a nonempty resume and readable resume text.');
  let center;
  if (values.coordinates) {
    const parts = values.coordinates.split(',').map(value => value.trim());
    const [lat, lon] = parts.map(Number);
    if (parts.length !== 2 || parts.some(part => !part) || !(Math.abs(lat) <= 90 && Math.abs(lon) <= 180)) {
      throw new Error('Use --coordinates "latitude,longitude" with valid decimal degrees.');
    }
    center = { lat, lon };
  } else {
    if (!process.env.GEOAPIFY_API_KEY) throw new Error('Set GEOAPIFY_API_KEY in .env for address search.');
    center = await geocode(values.address, process.env.GEOAPIFY_API_KEY);
  }
  console.log('Search center:', center.label || center.lat + ', ' + center.lon, '| Radius:', radius.toFixed(3), 'km');
  const venues = await findVenues(center, radius);
  console.log('Found', venues.length, 'mapped venues. Checking public contacts.');
  const root = values.out || 'output';
  await mkdir(root, { recursive: true });
  const folder = await mkdtemp(join(root, 'search-'));
  const report = { center, radiusKm: radius, attribution: '© OpenStreetMap contributors — https://www.openstreetmap.org/copyright', venues: [] };
  for (const venue of venues) {
    const contact = await findContact(venue);
    const draft = application(venue, values.name.trim(), cv, values.role?.trim());
    const file = venue.id + '.eml';
    await writeFile(join(folder, file), emailDraft(contact.email, draft, resume, basename(values.resume)));
    const { mappedEmails, ...details } = venue;
    report.venues.push({ ...details, ...contact, draft: file, subject: draft.subject, body: draft.body });
    console.log(venue.name, '—', contact.email || 'email needs review');
  }
  await writeFile(join(folder, 'leads.json'), JSON.stringify(report, null, 2) + '\n');
  console.log('Saved draft emails and leads.json to', folder);
  console.log(report.attribution);
}

main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
