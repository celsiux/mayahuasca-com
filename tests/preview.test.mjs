import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPair, exportJWK, SignJWT } from 'jose';
import worker from '../src/worker.js';
import { readFileSync } from 'node:fs';

let privateKey;
const realFetch = globalThis.fetch;
const issuer = 'https://test-team.cloudflareaccess.com';
const audience = 'synthetic-preview-audience';
const members = ['staff-one@example.invalid', 'staff-two@example.invalid'];
let reads;
const env = {
  MAYA_PREVIEW_ACCESS_ISSUER: issuer,
  MAYA_PREVIEW_ACCESS_AUD: audience,
  MAYA_PREVIEW_ALLOWED_EMAILS: JSON.stringify(members),
  SITE_BUCKET: { async get(key) {
    reads.push(key);
    return { body: key.startsWith('preview/') ? 'PRIVATE_DOCUMENT' : 'PUBLIC_SITE',
      httpEtag: 'etag', writeHttpMetadata(headers) { headers.set('Content-Type','text/plain'); } };
  } }
};
before(async () => {
  const pair = await generateKeyPair('RS256');
  privateKey = pair.privateKey;
  const jwk = await exportJWK(pair.publicKey); jwk.kid = 'fixture-key';
  globalThis.fetch = async url => {
    assert.equal(String(url), issuer + '/cdn-cgi/access/certs');
    return Response.json({ keys: [jwk] });
  };
});
after(() => { globalThis.fetch = realFetch; });
async function token(overrides = {}, omit = []) {
  const now = Math.floor(Date.now()/1000);
  const claims = { email: members[0], iss: issuer, aud: [audience], sub: 'synthetic-subject',
    iat: now-1, exp: now+600, ...overrides };
  for (const key of omit) delete claims[key];
  return new SignJWT(claims).setProtectedHeader({alg:'RS256',kid:'fixture-key'}).sign(privateKey);
}
async function fetchDoc(path='/preview/', assertion, options={}) {
  reads=[];
  const req=new Request((options.host || 'https://mayahuasca.com')+path, {
    method: options.method || 'GET', headers: assertion ? {'Cf-Access-Jwt-Assertion':assertion} : options.headers
  });
  return worker.fetch(req, options.env || env);
}
for (const path of ['/preview','/preview/','/preview/index.html',
  '/preview/maya-tiktok-rendimiento-20261126.html', '/preview/maya-tiktok-comentarios-20261126.html',
  '/preview/assets/file.css','/%70review/index.html','/preview%2findex.html','//preview/index.html']) {
  test(`signed out cannot read ${path}`, async () => {
    const r=await fetchDoc(path);
    assert.equal(r.status,403); assert.equal(reads.length,0);
    assert.equal(r.headers.get('Cache-Control'),'private, no-store, max-age=0');
    assert.doesNotMatch(await r.text(),/PRIVATE_DOCUMENT/);
  });
}
for (const email of members) {
  test(`allowed policy member can read: ${email}`, async () => {
    const r=await fetchDoc('/preview/',await token({email}));
    assert.equal(r.status,200); assert.equal(await r.text(),'PRIVATE_DOCUMENT');
    assert.deepEqual(reads,['preview/index.html']);
    assert.match(r.headers.get('Content-Security-Policy'),/default-src 'none'/);
  });
}
for (const [name,overrides,omit] of [
  ['other user',{email:'outsider@example.invalid'},[]],
  ['another application',{aud:['other-app']},[]],
  ['another issuer',{iss:'https://other.cloudflareaccess.com'},[]],
  ['expired',{exp:1},[]], ['future nbf',{nbf:Math.floor(Date.now()/1000)+600},[]],
  ['missing expiration',{},['exp']], ['service without email',{},['email']],
  ['missing subject',{},['sub']]
]) {
  test(`reject ${name}`,async()=>{
    const r=await fetchDoc('/preview/',await token(overrides,omit));
    assert.equal(r.status,403); assert.equal(reads.length,0);
  });
}
test('forged and unsigned assertions do not authorize',async()=>{
  for (const assertion of ['not-a-token','eyJhbGciOiJub25lIn0.eyJlbWFpbCI6InN0YWZmIn0.', 'a'.repeat(17000)]) {
    const r=await fetchDoc('/preview/',assertion); assert.equal(r.status,403);assert.equal(reads.length,0);
  }
});
test('identity header alone never authorizes',async()=>{
  assert.equal((await fetchDoc('/preview/',null,{headers:{'Cf-Access-Authenticated-User-Email':members[0]}})).status,403);
});
test('missing configuration fails closed without a bucket read',async()=>{
  const r=await fetchDoc('/preview/',await token(),{env:{...env,MAYA_PREVIEW_ACCESS_AUD:''}});
  assert.equal(r.status,503);assert.equal(reads.length,0);
});
test('expanded audience configuration is refused',async()=>{
  assert.equal((await fetchDoc('/preview/',await token(),{env:{...env,MAYA_PREVIEW_ALLOWED_EMAILS:JSON.stringify([...members,'new@example.invalid'])}})).status,503);
});
for (const host of ['https://www.mayahuasca.com','https://new.mayahuasca.com',
 'https://mayahuasca-site.example.workers.dev','https://old-mayahuasca-site.example.workers.dev',
 'https://example.pages.dev','http://mayahuasca.com','https://mayahuasca.com:444']) {
  test(`alternate origin blocked even with staff token: ${host}`,async()=>{
    const r=await fetchDoc('/preview/',await token(),{host});assert.equal(r.status,403);assert.equal(reads.length,0);
  });
}
for (const path of ['/preview/../preview/%2e%2e%2fsecret','/preview/%2f..%2fsecret',
 '/preview/%252e%252e/secret','/preview/%5csecret','/preview/%','/%70review/index.html',
 '/preview%2findex.html','//preview/index.html','/preview/private.csv']) {
  test(`traversal/alias/unknown file does not read bucket: ${path}`,async()=>{
    const r=await fetchDoc(path,await token());assert.ok([400,404].includes(r.status));assert.equal(reads.length,0);
  });
}
test('canonical redirect is only returned after authorization',async()=>{
  const r=await fetchDoc('/preview',await token());assert.equal(r.status,308);assert.equal(r.headers.get('Location'),'/preview/');
});
test('authenticated HEAD returns no body and never a shared cache response',async()=>{
  const r=await fetchDoc('/preview/',await token(),{method:'HEAD'});assert.equal(r.status,200);assert.equal(await r.text(),'');
  assert.equal(r.headers.get('Cache-Control'),'private, no-store, max-age=0');
});
test('public site and public HEAD retain existing behavior',async()=>{
  for (const path of ['/','/experiencia-3-dias-peru/','/llms.txt','/robots.txt','/sitemap.xml','/images/picture.png']) {
    const r=await fetchDoc(path);assert.equal(r.status,200);assert.equal(await r.text(),'PUBLIC_SITE');
    assert.match(r.headers.get('Cache-Control'),/^public, max-age=/);
  }
  const r=await fetchDoc('/',null,{method:'HEAD'});assert.equal(await r.text(),'');
});
test('write methods rejected on private and public paths',async()=>{
  for (const path of ['/preview/','/']) assert.equal((await fetchDoc(path,await token(),{method:'POST'})).status,405);
});
test('both alternate URL classes explicitly disabled in production config',()=>{
  const config=JSON.parse(readFileSync(new URL('../wrangler.jsonc',import.meta.url)));
  assert.equal(config.workers_dev,false);assert.equal(config.preview_urls,false);
  assert.equal(config.name,'mayahuasca-site');assert.equal(config.r2_buckets[0].bucket_name,'maya-site');
});

for (const path of ['/preview/maya-youtube-relanzamiento.html', '/preview/maya-publicidad-ayrshare.html', '/preview/maya-tiktok-historico.html', '/preview/videos.html', '/preview/video-explorer.js', '/preview/videos.json']) {
  test(`registered library resource requires staff auth: ${path}`, async () => {
    assert.equal((await fetchDoc(path)).status, 403); assert.equal(reads.length, 0);
    assert.equal((await fetchDoc(path, await token({ email: 'outsider@example.invalid' }))).status, 403); assert.equal(reads.length, 0);
    const r = await fetchDoc(path, await token());
    assert.equal(r.status, 200); assert.deepEqual(reads, [path.slice(1)]);
    assert.equal(r.headers.get('Cache-Control'), 'private, no-store, max-age=0');
    assert.match(r.headers.get('Content-Type'), path.endsWith('.json') ? /application\/json/ : path.endsWith('.js') ? /application\/javascript/ : /text\/html/);
    for (const host of ['https://www.mayahuasca.com', 'https://new.mayahuasca.com', 'https://old.example.workers.dev']) {
      assert.equal((await fetchDoc(path, await token(), { host })).status, 403); assert.equal(reads.length, 0);
    }
    assert.equal((await fetchDoc(path, await token(), { method: 'PUT' })).status, 405); assert.equal(reads.length, 0);
  });
}
test('only the explorer receives exact script/data CSP sources', async () => {
  const explorer = await fetchDoc('/preview/videos.html', await token());
  assert.equal(explorer.headers.get('Content-Security-Policy'), "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'; script-src https://mayahuasca.com/preview/video-explorer.js; connect-src https://mayahuasca.com/preview/videos.json");
  for (const path of ['/preview/', '/preview/maya-tiktok-historico.html', '/preview/videos.json']) {
    const r = await fetchDoc(path, await token()); assert.doesNotMatch(r.headers.get('Content-Security-Policy'), /script-src|connect-src/);
  }
});
test('encoded assets and unregistered datasets never read storage', async () => {
  for (const path of ['/preview/%76ideos.json', '/preview/videos.csv', '/preview/data/private.json', '/preview/video-explorer.js/x', '/preview/%76ideo-explorer.js']) {
    assert.ok([400, 404].includes((await fetchDoc(path, await token())).status)); assert.equal(reads.length, 0);
  }
});
