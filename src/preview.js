import { createRemoteJWKSet, jwtVerify } from 'jose';

const keys = new Map();
const FILES = new Set([
  'preview/index.html',
  'preview/maya-tiktok-rendimiento-20261126.html',
  'preview/maya-tiktok-comentarios-20261126.html'
]);
const HEADERS = {
  'Cache-Control': 'private, no-store, max-age=0',
  'X-Robots-Tag': 'noindex, nofollow, noarchive',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'"
};

export function isPreview(key) {
  return key === 'preview' || key.startsWith('preview/');
}

function denied(status) {
  return new Response(status === 503 ? 'Unavailable' : 'Access denied', {
    status, headers: { ...HEADERS, 'Content-Type': 'text/plain; charset=utf-8' }
  });
}

// Configuration comes privately from the existing Maya staff policy.
export async function authorized(request, env, keyResolver) {
  const issuer = env.MAYA_PREVIEW_ACCESS_ISSUER;
  const audience = env.MAYA_PREVIEW_ACCESS_AUD;
  let members;
  try { members = JSON.parse(env.MAYA_PREVIEW_ALLOWED_EMAILS); } catch { return 503; }
  if (!/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(issuer || '') || !audience ||
      !Array.isArray(members) || members.length !== 2 || new Set(members).size !== 2 ||
      members.some(x => typeof x !== 'string' || !/^[^@\s*]+@[^@\s*]+\.[^@\s*]+$/.test(x))) return 503;
  const assertion = request.headers.get('Cf-Access-Jwt-Assertion');
  if (!assertion || assertion.length > 16384) return 403;
  try {
    if (!keyResolver && !keys.has(issuer)) keys.set(issuer, createRemoteJWKSet(
      new URL(`${issuer}/cdn-cgi/access/certs`), { timeoutDuration: 5000 }
    ));
    const { payload } = await jwtVerify(assertion, keyResolver || keys.get(issuer), {
      issuer, audience, algorithms: ['RS256'], requiredClaims: ['exp', 'iat', 'sub', 'email']
    });
    if (typeof payload.email !== 'string' || !members.includes(payload.email)) return 403;
    return 200;
  } catch { return 403; }
}

export async function preview(request, env, key, keyResolver) {
  const url = new URL(request.url);
  if (url.protocol !== 'https:' || url.hostname !== 'mayahuasca.com' || url.port) return denied(403);
  const auth = await authorized(request, env, keyResolver);
  if (auth !== 200) return denied(auth);
  if (key === 'preview') {
    if (url.pathname !== '/preview') return denied(400);
    return new Response(null, { status: 308, headers: { ...HEADERS, Location: '/preview/' } });
  }
  if (!FILES.has(key) || (url.pathname !== `/${key}` && !(key === 'preview/index.html' && url.pathname === '/preview/'))) {
    return denied(404);
  }
  const object = await env.SITE_BUCKET.get(key);
  if (!object) return denied(404);
  return new Response(request.method === 'HEAD' ? null : object.body, {
    headers: { ...HEADERS, 'Content-Type': 'text/html; charset=utf-8' }
  });
}
