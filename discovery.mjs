const agent = 'HospitalityJobAgent/1.0 (local job search)';
const emailPattern = /[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,63}\b/gi;

export async function geocode(address, key) {
  const query = new URLSearchParams({ text: address, apiKey: key, format: 'json', limit: '1' });
  const response = await fetch('https://api.geoapify.com/v1/geocode/search?' + query, {
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error('Geocoding failed (HTTP ' + response.status + ').');
  const { results } = await response.json();
  const match = results?.[0];
  if (!Number.isFinite(match?.lat) || !Number.isFinite(match?.lon)) {
    throw new Error('Address not found. Include the city, postal code, and country.');
  }
  return { lat: match.lat, lon: match.lon, label: match.formatted };
}

function distanceKm(from, to) {
  const radians = Math.PI / 180;
  const a = Math.sin((to.lat - from.lat) * radians / 2) ** 2
    + Math.cos(from.lat * radians) * Math.cos(to.lat * radians)
    * Math.sin((to.lon - from.lon) * radians / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(Math.min(1, a)));
}

function webUrl(value, base) {
  if (!value) return null;
  try {
    const url = new URL(value, base);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

export async function findVenues(center, radiusKm) {
  const around = '(around:' + Math.ceil(radiusKm * 1000) + ',' + center.lat + ',' + center.lon + ')';
  const query = '[out:json][timeout:40];('
    + 'nwr["amenity"~"^(restaurant|cafe|fast_food|ice_cream)$"]' + around + ';'
    + 'nwr["shop"~"^(kiosk|bakery|deli)$"]' + around + ';);out center;';
  const response = await fetch(process.env.OVERPASS_URL || 'https://overpass.kumi.systems/api/interpreter', {
    method: 'POST',
    body: new URLSearchParams({ data: query }),
    headers: { 'User-Agent': agent },
    signal: AbortSignal.timeout(60000),
  });
  if (!response.ok) throw new Error('Venue search failed (HTTP ' + response.status + '). Try again later or configure another Overpass endpoint.');
  const data = await response.json();
  if (!Array.isArray(data.elements) || data.remark) {
    throw new Error('Overpass returned an incomplete result. Try a smaller radius or another endpoint.');
  }
  const venues = [];
  for (const element of data.elements) {
    if (!['node', 'way', 'relation'].includes(element.type) || !Number.isSafeInteger(element.id)) continue;
    const tags = element.tags || {};
    const name = (tags.name || tags.brand || tags.operator || '').trim();
    const point = element.center || element;
    if (!name || tags.access === 'private' || !Number.isFinite(point.lat) || !Number.isFinite(point.lon)) continue;
    const km = distanceKm(center, point);
    if (km > radiusKm) continue;
    const map = 'https://www.openstreetmap.org/' + element.type + '/' + element.id;
    const website = webUrl(tags['contact:website'] || tags.website)?.href ?? null;
    const address = [
      [tags['addr:street'], tags['addr:housenumber']].filter(Boolean).join(' '),
      [tags['addr:postcode'], tags['addr:city']].filter(Boolean).join(' '),
    ].filter(Boolean).join(', ');
    const category = tags.amenity || tags.shop;
    venues.push({
      id: element.type + '-' + element.id, name, category, address, km, website, map,
      mappedEmails: [tags['contact:email'], tags.email].filter(Boolean).join(' '),
      mapsSearch: 'https://www.google.com/maps/search/?' + new URLSearchParams({
        api: '1', query: [name, address, point.lat + ',' + point.lon].filter(Boolean).join(' '),
      }),
    });
  }
  return venues.sort((a, b) => a.km - b.km).filter((venue, index, sorted) => {
    return !sorted.slice(0, index).some(other => other.name.toLowerCase() === venue.name.toLowerCase()
      && (Math.abs(other.km - venue.km) < 0.1)
      && other.address && venue.address && other.address === venue.address);
  });
}

function decodeHtml(value) {
  return value.replace(/&(?:#(\d+)|#x([0-9a-f]+)|(commat|period|amp));/gi, (entity, decimal, hex, named) => {
    if (named) return { commat: '@', period: '.', amp: '&' }[named.toLowerCase()];
    const code = decimal ? Number(decimal) : parseInt(hex, 16);
    return code < 128 ? String.fromCharCode(code) : entity;
  });
}

function extractEmails(value) {
  return (decodeHtml(value).match(emailPattern) || []).filter(email =>
    !/^(?:no-?reply|do-?not-?reply|privacy|abuse|support)@/i.test(email)
    && !/@(?:example\.(?:com|org|net)|sentry\.io)$/i.test(email)
    && !/\.(?:png|jpg|jpeg|gif|webp|svg)$/i.test(email));
}

async function getPage(url) {
  try {
    const response = await fetch(url, {
      headers: { 'User-Agent': agent },
      redirect: 'follow',
      signal: AbortSignal.timeout(4500),
    });
    const type = response.headers.get('content-type') || '';
    if (!response.ok || !type.includes('text/html') || !response.body) {
      await response.body?.cancel();
      return null;
    }
    const reader = response.body.getReader();
    const chunks = [];
    let bytes = 0;
    try {
      while (bytes < 600000) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(Buffer.from(value));
        bytes += value.length;
      }
    } finally {
      await reader.cancel();
    }
    return { url: response.url || String(url), html: Buffer.concat(chunks).toString('utf8') };
  } catch {
    return null;
  }
}

function emailPriority(email) {
  if (/^(careers?|jobs?|hr|recruitment|rekruttering|ansogning|bewerbung)@/i.test(email)) return 0;
  if (/^(info|kontakt|contact|hello|hej|office)@/i.test(email)) return 1;
  return 2;
}

export async function findContact(venue) {
  const candidates = new Map();
  function add(emails, source) {
    for (const email of emails) candidates.set(email.toLowerCase(), { email, source });
  }
  add(extractEmails(venue.mappedEmails), venue.map);
  const home = venue.website && await getPage(venue.website);
  if (home) {
    const links = Array.from(home.html.matchAll(/href\s*=\s*["']([^"']+)["']/gi), match =>
      webUrl(decodeHtml(match[1]), home.url));
    const relevant = links.filter(url => url?.origin === new URL(home.url).origin
      && /contact|kontakt|career|karriere|job|impressum/i.test(url.pathname));
    const pages = [home];
    for (const url of [...new Set(relevant.map(link => link.href))].filter(link => link !== home.url).slice(0, 4)) {
      const page = await getPage(url);
      if (page) pages.push(page);
    }
    for (const page of pages) {
      const html = page.html.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, '');
      const mailto = Array.from(html.matchAll(/href\s*=\s*["']mailto:([^?"']+)/gi), match => match[1]);
      add(extractEmails([html.replace(/<[^>]+>/g, ' '), ...mailto].join(' ')), page.url);
    }
  }
  const contacts = [...candidates.values()].sort((a, b) => emailPriority(a.email) - emailPriority(b.email));
  return { email: contacts[0]?.email ?? null, emailSource: contacts[0]?.source ?? null, contacts };
}
