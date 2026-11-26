const PAGE_SIZE = 24;
const number = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 3 });
const canonical = /^https:\/\/www\.tiktok\.com\/@mayahuasca\.gracias\/video\/[1-9]\d{18}$/;
const fold = value => value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase('es');
const present = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const metric = value => present(value) ? number.format(value) : '—';
const ratio = (numerator, denominator) => present(numerator) && present(denominator) && denominator > 0 ? numerator / denominator * 100 : null;
const engagement = row => [row.likes, row.comments, row.shares].every(present) ? ratio(row.likes + row.comments + row.shares, row.views) : null;
const rate = value => present(value) ? `${percent.format(value)} %` : '—';

export function selectVideos(rows, options) {
  const search = fold(options.search || '').trim();
  const filtered = rows.filter(row => (!search || fold(row.caption).includes(search)) &&
    (!options.year || row.published.startsWith(options.year + '-')) &&
    (!options.tag || row.tags.includes(options.tag)) && (!options.candidates || row.candidate !== null));
  const score = row => ({ views: row.views, shares: row.shares, saves: row.saves, engagement: engagement(row),
    oldest: Date.parse(row.published), newest: Date.parse(row.published), watch: row.averageWatch, completion: row.completion })[options.sort || 'views'];
  filtered.sort((a, b) => {
    const av = score(a), bv = score(b);
    if (!present(av)) return present(bv) ? 1 : a.id.localeCompare(b.id);
    if (!present(bv)) return -1;
    return (options.sort === 'oldest' ? av - bv : bv - av) || a.id.localeCompare(b.id);
  });
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.min(pages, Math.max(1, Number.isInteger(options.page) ? options.page : 1));
  return { rows: filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), total, page, pages };
}

export function validateData(data) {
  const fields = ['id', 'caption', 'published', 'url', 'duration', 'views', 'likes', 'comments', 'shares', 'saves', 'followers', 'tags', 'candidate', 'averageWatch', 'completion', 'totalWatch', 'reach'];
  if (!data || data.schema !== 1 || !Array.isArray(data.videos) || data.videos.length > 5000) throw Error('Invalid data');
  const ids = new Set();
  for (const row of data.videos) {
    if (Object.keys(row).some(key => !fields.includes(key)) || fields.some(key => !(key in row)) ||
      typeof row.id !== 'string' || !/^[1-9]\d{18}$/.test(row.id) || ids.has(row.id) ||
      typeof row.url !== 'string' || !canonical.test(row.url) || !row.url.endsWith('/' + row.id) ||
      typeof row.caption !== 'string' || row.caption.length > 4000 ||
      typeof row.published !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(row.published) || !Number.isFinite(Date.parse(row.published)) || new Date(row.published).toISOString().replace('.000Z', 'Z') !== row.published ||
      !Array.isArray(row.tags) || row.tags.length > 40 || row.tags.some(tag => typeof tag !== 'string' || !/^#[\p{L}\p{N}_]{1,60}$/u.test(tag)) ||
      (row.candidate !== null && (!Number.isInteger(row.candidate) || row.candidate < 1 || row.candidate > 30)) ||
      ['duration', 'views', 'likes', 'comments', 'shares', 'saves', 'followers', 'averageWatch', 'completion', 'totalWatch', 'reach'].some(key => row[key] !== null && !present(row[key])) ||
      (row.completion !== null && row.completion > 1)) throw Error('Invalid row');
    ids.add(row.id);
  }
  return data.videos;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function stat(label, value) {
  const wrap = element('div');
  wrap.append(element('dt', label), element('dd', value));
  return wrap;
}
function card(row) {
  const article = element('article', undefined, 'video-card');
  const date = element('time', new Date(row.published).toLocaleDateString('es-PE', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }));
  date.dateTime = row.published;
  const top = element('div', undefined, 'video-top');
  top.append(date, element('span', `${metric(row.duration)} s · duración`));
  article.append(top);
  if (row.candidate !== null) article.append(element('p', `Para clipping · ${row.candidate} de 30`, 'candidate-badge'));
  article.append(element('h2', row.caption.length > 180 ? row.caption.slice(0, 180) + '…' : row.caption || 'Sin descripción'));
  const primary = element('dl', undefined, 'video-primary');
  primary.append(stat('Vistas', metric(row.views)), stat('Compartidos', metric(row.shares)), stat('Guardados', metric(row.saves)));
  article.append(primary);
  const detail = element('details');
  detail.append(element('summary', 'Ver más métricas'));
  const extra = element('dl', undefined, 'video-detail');
  extra.append(stat('Me gusta', metric(row.likes)), stat('Comentarios', metric(row.comments)), stat('Interacciones / vistas', rate(engagement(row))),
    stat('Compartidos / vistas', rate(ratio(row.shares, row.views))), stat('Guardados / vistas', rate(ratio(row.saves, row.views))),
    stat('Seguidores atribuidos', metric(row.followers)), stat('Tiempo medio visto', present(row.averageWatch) ? `${metric(row.averageWatch)} s` : '—'),
    stat('Video completo visto', rate(row.completion === null ? null : row.completion * 100)),
    stat('Tiempo total visto', present(row.totalWatch) ? `${metric(row.totalWatch)} s` : '—'), stat('Alcance', metric(row.reach)));
  detail.append(extra);
  if (row.caption.length > 180) detail.append(element('p', row.caption, 'full-caption'));
  article.append(detail);
  const link = element('a', 'Abrir en TikTok ↗', 'video-link');
  link.href = row.url;
  link.rel = 'noreferrer';
  link.setAttribute('aria-label', `Abrir en TikTok: ${row.caption || 'video sin descripción'} · ${row.published.slice(0, 10)}`);
  article.append(link);
  return article;
}

export async function start() {
  const form = /** @type {HTMLFormElement} */ (document.querySelector('#video-filters'));
  const get = id => /** @type {HTMLInputElement | HTMLSelectElement} */ (document.getElementById(id));
  const grid = document.querySelector('#video-results');
  const status = document.querySelector('#video-status');
  const previous = /** @type {HTMLButtonElement} */ (document.querySelector('#previous-page'));
  const next = /** @type {HTMLButtonElement} */ (document.querySelector('#next-page'));
  const pager = document.querySelector('#page-number');
  let rows;
  let page = 1;
  function render(focus = false) {
    const result = selectVideos(rows, { search: get('video-search').value, year: get('video-year').value, tag: get('video-tag').value,
      sort: get('video-sort').value, candidates: /** @type {HTMLInputElement} */ (get('video-candidates')).checked, page });
    page = result.page;
    grid.replaceChildren(...result.rows.map(card));
    if (!result.total) grid.append(element('p', 'No hay videos con estos filtros. Prueba otra búsqueda o restablece los filtros.', 'empty-results'));
    status.textContent = `${number.format(result.total)} videos · ${result.total ? (page - 1) * PAGE_SIZE + 1 : 0}–${Math.min(page * PAGE_SIZE, result.total)} visibles`;
    pager.textContent = `Página ${page} de ${result.pages}`;
    previous.disabled = page === 1;
    next.disabled = page === result.pages;
    if (focus) /** @type {HTMLElement} */ (status).focus();
  }
  function refresh() { page = 1; render(); }
  form.addEventListener('submit', event => { event.preventDefault(); refresh(); });
  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);
  form.addEventListener('reset', () => { setTimeout(refresh, 0); });
  previous.addEventListener('click', () => { page--; render(true); });
  next.addEventListener('click', () => { page++; render(true); });
  async function load() {
    try {
      status.textContent = 'Cargando videos…';
      const response = await fetch('/preview/videos.json', { credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw Error('Unavailable');
      const body = await response.text();
      if (body.length > 6000000) throw Error('Oversized');
      rows = validateData(JSON.parse(body));
      for (const [id, values] of [['video-year', [...new Set(rows.map(row => row.published.slice(0, 4)))].sort().reverse()],
        ['video-tag', [...rows.flatMap(row => row.tags).reduce((counts, tag) => counts.set(tag, (counts.get(tag) || 0) + 1), new Map())].sort((a, b) => b[1] - a[1]).slice(0, 80).map(([tag]) => tag).sort((a, b) => a.localeCompare(b, 'es'))]]) {
        for (const value of values) { const option = element('option', value); option.setAttribute('value', value); get(id).append(option); }
      }
      /** @type {HTMLFieldSetElement} */ (document.querySelector('#filter-fields')).disabled = false;
      document.querySelector('#retry-load').setAttribute('hidden', '');
      render();
    } catch {
      status.textContent = 'No se pudieron cargar los videos. Si tu sesión venció, vuelve a la biblioteca e inicia sesión.';
      document.querySelector('#retry-load').removeAttribute('hidden');
    }
  }
  document.querySelector('#retry-load').addEventListener('click', load);
  await load();
}
if (typeof document !== 'undefined') start();
