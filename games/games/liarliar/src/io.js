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

export async function writeData(uri, data, { contentType = 'application/json', method = 'POST' } = {}) {
  const body = Buffer.isBuffer(data) ? data : Buffer.from(String(data));
  const parsed = parseUri(uri);
  if (parsed.scheme === 'http:' || parsed.scheme === 'https:') {
    const response = await fetch(uri, {
      method,
      headers: { 'content-type': contentType },
      body,
    });
    if (!response.ok) throw new Error(`${method} ${uri} failed: ${response.status}`);
    return;
  }
  await mkdir(dirname(parsed.path), { recursive: true });
  await writeFile(parsed.path, body);
}

export async function writeJson(uri, value, method = 'POST') {
  await writeData(uri, JSON.stringify(value, null, 2), { contentType: 'application/json', method });
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
