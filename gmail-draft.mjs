import { readFile } from 'node:fs/promises';

async function main() {
  const file = process.argv[2];
  const token = process.env.GMAIL_ACCESS_TOKEN;
  if (!file || !token || process.argv.length !== 3) {
    throw new Error('Set GMAIL_ACCESS_TOKEN and provide exactly one reviewed .eml file.');
  }
  const raw = await readFile(file, 'utf8');
  const headers = raw.split(/\r?\n\r?\n/, 1)[0];
  if (!/^X-Unsent: 1\r?$/mi.test(headers) || !/^To: [^\s@]+@[^\s@]+\.[^\s@]+\r?$/mi.test(headers)) {
    throw new Error('Choose a draft with a single reviewed recipient in its To header.');
  }
  const message = Buffer.from(raw.replace(/^X-Unsent: 1\r?\n/i, '')).toString('base64url');
  const response = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/drafts', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: { raw: message } }),
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) throw new Error('Gmail rejected the draft (HTTP ' + response.status + '). Check the token and gmail.compose scope.');
  const draft = await response.json();
  console.log('Created an unsent Gmail draft:', draft.id);
}

main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
