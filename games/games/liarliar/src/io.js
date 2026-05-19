import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

export async function readData(uri) {
  const parsed = parseUri(uri);
  if (parsed.scheme === 'http:' || parsed.scheme === 'https:') {
    const response = await fetch(uri);
    if (!response.ok) throw new Error(`GET ${uri} failed: ${response.status}`);
    return Buffer.from(await response.arrayBuffer());
  }
  return readFile(parsed.path);
}

export async function readJson(uri) {
  return JSON.parse((await readData(uri)).toString('utf8'));
}

export async function postData(uri, data, contentType = 'application/json') {
  const body = Buffer.isBuffer(data) ? data : Buffer.from(String(data));
  const parsed = parseUri(uri);
  if (parsed.scheme === 'http:' || parsed.scheme === 'https:') {
    const response = await fetch(uri, {
      method: 'POST',
      headers: { 'content-type': contentType },
      body,
    });
    if (!response.ok) throw new Error(`POST ${uri} failed: ${response.status}`);
    return;
  }
  await mkdir(dirname(parsed.path), { recursive: true });
  await writeFile(parsed.path, body);
}

export async function postJson(uri, value) {
  await postData(uri, JSON.stringify(value, null, 2), 'application/json');
}

function parseUri(uri) {
  if (!uri) throw new Error('Missing URI');
  if (uri.startsWith('file://')) {
    return { scheme: 'file:', path: fileURLToPath(uri) };
  }
  if (uri.startsWith('http://') || uri.startsWith('https://')) {
    return { scheme: new URL(uri).protocol, path: uri };
  }
  return { scheme: '', path: uri };
}
