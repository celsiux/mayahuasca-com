import { readdir } from 'node:fs/promises';
import { join, relative } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = new URL('../dist/', import.meta.url).pathname;
const mime = {
  css: 'text/css', html: 'text/html', jpg: 'image/jpeg',
  json: 'application/json', md: 'text/markdown', png: 'image/png',
  txt: 'text/plain', webp: 'image/webp', xml: 'application/xml'
};

async function* files(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* files(path);
    else if (entry.isFile()) yield path;
  }
}

let count = 0;
for await (const path of files(root)) {
  const key = relative(root, path).replaceAll('\\', '/');
  const type = mime[key.split('.').pop()] || 'application/octet-stream';
  const result = spawnSync('npx', ['wrangler', 'r2', 'object', 'put', `maya-site/${key}`, '--remote', '--file', path, '--content-type', type], { stdio: 'inherit' });
  if (result.status !== 0) process.exit(result.status || 1);
  count++;
}
console.log(`Uploaded ${count} files to R2 bucket maya-site.`);
