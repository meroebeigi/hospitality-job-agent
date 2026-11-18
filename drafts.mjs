import { randomUUID } from 'node:crypto';

const hospitality = /\b(waiter|waitress|server|hospitality|barista|café|cafe|restaurant|cashier|customer service|food service|kitchen|catering|guest service|tjen(er|ing)|kundeservice|køkken)\b/i;

export function application(venue, name, resumeText, role) {
  const title = role || (['restaurant', 'cafe'].includes(venue.category)
    ? 'waiter or front-of-house assistant' : 'food service assistant');
  const evidence = [...new Set(resumeText.split(/\r?\n/).map(line => line.trim()))]
    .filter(line => line.length >= 12 && line.length <= 180 && hospitality.test(line)
      && !/[\w.+-]+@[\w.-]+\.[a-z]{2,}/i.test(line)).slice(0, 2);
  const subject = 'Application for ' + title + ' — ' + venue.name;
  const intro = 'I’m writing to ask about ' + title + ' opportunities at ' + venue.name + '.';
  const background = evidence.length ? '\n\nRelevant details from my CV:\n' + evidence.map(line =>
    '• ' + line.replace(/^[-*•]\s*/, '')).join('\n') : '';
  const body = 'Dear ' + venue.name + ' team,\n\n' + intro + background
    + '\n\nMy CV is attached. If you have any current or upcoming openings, I’d be happy to discuss how I could help your team.\n\n'
    + 'Thank you for your time.\n\nKind regards,\n' + name;
  return { subject, body, evidence };
}

function base64Lines(value) {
  return Buffer.from(value).toString('base64').match(/.{1,76}/g)?.join('\r\n') || '';
}

export function emailDraft(to, application, attachment, filename) {
  const boundary = 'draft-' + randomUUID();
  const subject = Array.from(application.subject.matchAll(/.{1,12}/gu), part =>
    '=?UTF-8?B?' + Buffer.from(part[0]).toString('base64') + '?=').join('\r\n ');
  const encodedFilename = encodeURIComponent(filename).replace(/['()*]/g, character =>
    '%' + character.charCodeAt(0).toString(16));
  return [
    'X-Unsent: 1', 'To: ' + (to || ''), 'Subject: ' + subject, 'MIME-Version: 1.0',
    'Content-Type: multipart/mixed; boundary="' + boundary + '"', '',
    '--' + boundary, 'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: base64', '', base64Lines(application.body),
    '--' + boundary, 'Content-Type: application/octet-stream',
    "Content-Disposition: attachment; filename*=UTF-8''" + encodedFilename,
    'Content-Transfer-Encoding: base64', '', base64Lines(attachment), '--' + boundary + '--', '',
  ].join('\r\n');
}
