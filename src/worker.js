const MIME = {
  css: 'text/css; charset=utf-8',
  html: 'text/html; charset=utf-8',
  ico: 'image/x-icon',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  js: 'text/javascript; charset=utf-8',
  json: 'application/json; charset=utf-8',
  md: 'text/markdown; charset=utf-8',
  png: 'image/png',
  svg: 'image/svg+xml',
  txt: 'text/plain; charset=utf-8',
  webp: 'image/webp',
  xml: 'application/xml; charset=utf-8'
};

function objectKey(pathname) {
  let path;
  try {
    path = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  if (path.includes('\\') || path.split('/').includes('..')) return null;
  path = path.replace(/^\/+/, '');
  if (!path || path.endsWith('/')) path += 'index.html';
  return path;
}

export default {
  async fetch(request, env) {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD' } });
    }

    const key = objectKey(new URL(request.url).pathname);
    if (!key) return new Response('Bad request', { status: 400 });

    const object = await env.SITE_BUCKET.get(key);
    if (!object) return new Response('Not found', { status: 404 });

    const ext = key.split('.').pop().toLowerCase();
    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set('Content-Type', MIME[ext] || headers.get('Content-Type') || 'application/octet-stream');
    headers.set('Cache-Control', /\.(html|md|txt|xml)$/.test(key) ? 'public, max-age=300' : 'public, max-age=86400');
    headers.set('ETag', object.httpEtag);
    return new Response(request.method === 'HEAD' ? null : object.body, { headers });
  }
};
