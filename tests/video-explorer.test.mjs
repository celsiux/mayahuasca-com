import { test } from 'node:test';
import assert from 'node:assert/strict';
import { selectVideos, validateData } from '../src/video-explorer.js';
const row = (n, extra = {}) => ({id: String(7000000000000000000n + BigInt(n)), caption: `Video ${n} #arte`, published: '2023-01-01T00:00:00Z',
  url: `https://www.tiktok.com/@mayahuasca.gracias/video/${7000000000000000000n + BigInt(n)}`, tags: ['#arte'], candidate: null,
  duration: 60, views: n, likes: 1, comments: 0, shares: 0, saves: null, followers: null, averageWatch: null, completion: null, totalWatch: null, reach: null, ...extra});
const rows = Array.from({length: 55}, (_, i) => row(i + 1));
test('bounded pagination covers each result once and clamps page changes', () => {
  const ids = [1, 2, 3].flatMap(page => selectVideos(rows, {page}).rows.map(r => r.id));
  assert.equal(ids.length,55); assert.equal(new Set(ids).size,55);
  assert.equal(selectVideos(rows, {page:99}).page,3); assert.equal(selectVideos(rows, {page:-1}).page,1);
});
test('accent-insensitive search combines year, literal caption hashtag and candidate filter', () => {
  const data = [row(1,{caption:'Educación consciente #arte', candidate:2}), row(2,{caption:'Educacion',published:'2024-01-01T00:00:00Z'})];
  assert.equal(selectVideos(data,{search:' EDUCACION ',year:'2023',tag:'#arte',candidates:true}).total,1);
  assert.equal(selectVideos(data,{search:'nada'}).total,0);
  assert.equal(selectVideos(data,{tag:'#inventado'}).total,0);
});
for (const [sort,field] of [['views','views'],['shares','shares'],['saves','saves'],['watch','averageWatch'],['completion','completion']]) {
  test(`sort ${sort} preserves literal zero and puts missing last`, () => {
    const result=selectVideos([row(1,{[field]:null}),row(2,{[field]:0}),row(3,{[field]:sort==='completion'?.2:12})],{sort});
    assert.deepEqual(result.rows.map(r=>r.id),[row(3).id,row(2).id,row(1).id]);
  });
}
test('engagement uses likes+comments+shares divided by views; missing/zero denominator stays missing',()=>{
  const result=selectVideos([row(1,{views:0}),row(2,{views:100,likes:10,comments:2,shares:8}),row(3,{views:10,likes:null}),row(4,{views:100,likes:1})],{sort:'engagement'});
  assert.deepEqual(result.rows.slice(0,2).map(r=>r.id),[row(2).id,row(4).id]);
});
test('date sort uses actual publication dates in both directions',()=>{
  const data=[row(1),row(2,{published:'2026-01-01T00:00:00Z'})];
  assert.equal(selectVideos(data,{sort:'oldest'}).rows[0].id,row(1).id);assert.equal(selectVideos(data,{sort:'newest'}).rows[0].id,row(2).id);
});
test('empty result has a usable first page',()=>{assert.deepEqual(selectVideos([],{page:7}),{rows:[],page:1,pages:1,total:0});});
test('data validation accepts untrusted caption as text and nulls, rejects arbitrary native URLs and malformed metrics',()=>{
  assert.equal(validateData({schema:1,videos:[row(1,{caption:'<img src=x onerror=alert(1)>'})]}).length,1);
  for(const extra of [{url:'javascript:alert(1)'},{url:row(1).url+'?token=secret'},{url:'https://evil.test/video/7000000000000000001'},{completion:80},{views:-1},{duration:NaN},{tags:['<x>']},{published:'2023-99-99T00:00:00Z'},{published:'2023-02-31T00:00:00Z'}]) {
    assert.throws(()=>validateData({schema:1,videos:[row(1,extra)]}));
  }
  assert.throws(()=>validateData({schema:1,videos:[row(1),row(1)]}));
  assert.throws(()=>validateData({schema:1,videos:Array(5001).fill(row(1))}));
});
