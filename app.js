'use strict';

// ── Configuration ─────────────────────────────────────────────────────────────

const API = (window.location.port === '5500' || window.location.port === '8080')
  ? 'http://localhost:5001/api'
  : '/api';

const DECADE_RANGES = {
  '':       null,
  pre1980:  [0,    1979],
  '1980s':  [1980, 1989],
  '1990s':  [1990, 1999],
  '2000s':  [2000, 2009],
  '2010s':  [2010, 2019],
  '2020s':  [2020, 2029],
};

const PAGE_SIZE = 20;

// Keyword → color domain key
const DOMAIN = {
  'harmony':                'gold',  'tonality':               'gold',
  'voice leading':          'gold',  'schenkerian analysis':   'gold',
  'modality':               'gold',  'counterpoint':           'gold',
  'cadence':                'gold',  'chromaticism':           'gold',
  'pitch-class set theory': 'gold',  'pitch class sets':       'gold',
  'serialism':              'gold',  'neo-riemannian theory':  'gold',
  'transformational theory':'gold',  'tonal':                  'gold',
  'atonality':              'gold',  'microtonality':          'gold',
  'mode':                   'gold',  'chord':                  'gold',
  'diatonic':               'gold',  'chromatic':              'gold',
  'interval':               'gold',  'pitch':                  'gold',
  'scale':                  'gold',  'melody':                 'gold',
  'modulation':             'gold',  'spectralism':            'gold',
  'twelve-tone':            'gold',  'post-tonal':             'gold',
  'voice exchange':         'gold',  'j. s. bach':             'gold',
  'bach':                   'gold',  'beethoven':              'gold',
  'brahms':                 'gold',  'schubert':               'gold',
  'chopin':                 'gold',  'haydn':                  'gold',
  'mozart':                 'gold',  'schoenberg':             'gold',
  'stravinsky':             'gold',

  'rhythm':              'blue',  'meter':             'blue',
  'tempo':               'blue',  'groove':            'blue',
  'pulse':               'blue',  'syncopation':       'blue',
  'polyrhythm':          'blue',  'hypermeter':        'blue',
  'entrainment':         'blue',  'metric modulation': 'blue',
  'beat':                'blue',  'duration':          'blue',
  'timing':              'blue',  'isochrony':         'blue',

  'form':                    'green',  'sonata form':            'green',
  'structure':               'green',  'phrase':                 'green',
  'music analysis':          'green',  'partimento':             'green',
  'schema':                  'green',  'fugue':                  'green',
  'history of music theory': 'green',  'history of theory':      'green',
  'music theory':            'green',  'pedagogy':               'green',
  'public music theory':     'green',  'canon':                  'green',
  'style':                   'green',  'variation':              'green',

  'timbre':            'red',  'orchestration':  'red',
  'texture':           'red',  'register':       'red',
  'dynamics':          'red',  'noise':          'red',
  'sound':             'red',  'instrumentation':'red',
  'rock':              'red',  'rock music':     'red',
  'jazz':              'red',  'rap':            'red',
  'popular music':     'red',  'film music':     'red',
  'text-music relations':'red',

  'perception':         'purple',  'cognition':          'purple',
  'embodiment':         'purple',  'gesture':            'purple',
  'emotion':            'purple',  'memory':             'purple',
  'expectation':        'purple',  'imagery':            'purple',
  'semiotics':          'purple',  'narrative':          'purple',
  'hermeneutics':       'purple',  'phenomenology':      'purple',
  'improvisation':      'purple',  'music cognition':    'purple',
  'music psychology':   'purple',  'performance':        'purple',
  'performance analysis':'purple', 'aesthetics':         'purple',
  'metaphor':           'purple',  'gender':             'purple',
  'identity':           'purple',  'meaning':            'purple',
  'affect':             'purple',
};

// Dark variants of each domain color — readable on the off-white canvas
const PALETTE = {
  gold:   { base: '#7a4e0c' },
  blue:   { base: '#1a5c8a' },
  green:  { base: '#2a6b35' },
  red:    { base: '#962020' },
  purple: { base: '#5c2b8a' },
  grey:   { base: '#4a5568' },
};

// ── State ─────────────────────────────────────────────────────────────────────

const state = {
  decade:   '',
  type:     '',
  keywords: [],
  stats:    null,
  view:     'cloud',   // 'cloud' | 'trends'
};

// Drawer state — reset each time drawer opens
const ds = {
  mode:         'keyword',  // 'keyword' | 'search'
  allItems:     [],
  filtered:     [],
  tab:          'articles', // 'articles' | 'books'
  page:         0,
  sortBy:       'date-desc',
  searchTerms:  [],
  kwText:       '',
  primaryKwId:  null,         // ID of the keyword whose drawer is open
  filterKwIds:  new Set(),    // active chip intersection filters (multi-select)
};

// ── DOM refs ──────────────────────────────────────────────────────────────────

const statsBanner    = document.getElementById('stats-banner');
const cloudArea      = document.getElementById('cloud-area');
const cloudOverlay   = document.getElementById('cloud-overlay');
const cloudEmpty     = document.getElementById('cloud-empty');
const cloudHint      = document.getElementById('cloud-hint');
const filterStats    = document.getElementById('filter-stats');
const tooltip        = document.getElementById('kw-tooltip');
const drawer         = document.getElementById('drawer');
const drawerOverlay  = document.getElementById('drawer-overlay');
const drawerKeyword  = document.getElementById('drawer-keyword');
const drawerCount    = document.getElementById('drawer-count');
const drawerMeta     = document.getElementById('drawer-meta');
const drawerBody     = document.getElementById('drawer-body');
const resultList     = document.getElementById('result-list');
const pagination     = document.getElementById('pagination');
const pagePrev       = document.getElementById('page-prev');
const pageNext       = document.getElementById('page-next');
const pageInfo       = document.getElementById('page-info');
const drawerTabs     = document.getElementById('drawer-tabs');
const tabArticles    = document.getElementById('tab-articles');
const tabBooks       = document.getElementById('tab-books');
const tabCountArt    = document.getElementById('tab-count-articles');
const tabCountBook   = document.getElementById('tab-count-books');
const drawerSrchWrap = document.getElementById('drawer-search-wrap');
const drawerSrchIn   = document.getElementById('drawer-search-input');
const sortBar        = document.getElementById('sort-bar');
const sortGroup      = document.getElementById('sort-group');
const searchForm     = document.getElementById('search-form');
const searchInput    = document.getElementById('global-search');
const searchClear    = document.getElementById('search-clear');
const modalOverlay   = document.getElementById('modal-overlay');
const modalEl        = document.getElementById('modal');
const modalCover     = document.getElementById('modal-cover');
const modalBadges    = document.getElementById('modal-badges');
const modalTitle     = document.getElementById('modal-title');
const modalAuthors   = document.getElementById('modal-authors');
const modalMeta      = document.getElementById('modal-meta');
const modalAbstract  = document.getElementById('modal-abstract');
const modalKwList    = document.getElementById('modal-kw-list');
const modalLink      = document.getElementById('modal-link');
const modalClose     = document.getElementById('modal-close');

// ── API helpers ───────────────────────────────────────────────────────────────

async function apiFetch(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ── Static-data layer (used when window.STATIC_DATA_URL is set) ───────────────

let _sd = null; // cached static dataset

async function ensureStaticData() {
  if (_sd) return _sd;
  const url = window.STATIC_DATA_URL || 'data/data.json';
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Failed to load static data: ${r.status}`);
  const raw = await r.json();

  // Build O(1) lookup indices
  raw._kwById     = {};
  raw._itemById   = {};
  raw._byKwId     = {}; // kw_id → [item, ...]
  raw._explicitOf = {}; // item.id → Set<kw_id>

  for (const kw of raw.keywords) raw._kwById[kw.id] = kw;
  for (const item of raw.items) {
    raw._itemById[item.id]   = item;
    raw._explicitOf[item.id] = new Set(item.kw_explicit_ids || []);
    for (const kid of item.kw_ids) {
      (raw._byKwId[kid] = raw._byKwId[kid] || []).push(item);
    }
  }

  // Build Map-based indices for byYear and cooccur
  raw._byYear  = new Map();
  raw._cooccur = new Map();
  for (const [kid, pairs] of Object.entries(raw.byYear  || {})) {
    const m = new Map();
    for (const [y, c] of pairs) m.set(y, c);
    raw._byYear.set(Number(kid), m);
  }
  for (const [kid, pairs] of Object.entries(raw.cooccur || {})) {
    raw._cooccur.set(Number(kid), pairs);   // [[peerId, count], ...]
  }

  _sd = raw;
  return _sd;
}

function _sdDecadeFilter(items, decade) {
  if (!decade) return items;
  const range = DECADE_RANGES[decade];
  if (!range) return items;
  const [lo, hi] = range;
  // pre1980 uses [0, 1979] — exclude year=0 (unknown)
  return items.filter(i => i.year > 0 && i.year >= lo && i.year <= hi);
}

// ── Data-load functions (API or static) ──────────────────────────────────────

async function loadKeywords() {
  if (window.STATIC_DATA_URL) {
    const sd = await ensureStaticData();
    let filtered = _sdDecadeFilter(sd.items, state.decade);
    if (state.type) filtered = filtered.filter(i => i.item_type === state.type);
    const counts = new Map();
    for (const item of filtered) {
      for (const kid of item.kw_ids) {
        if (!counts.has(kid)) counts.set(kid, {a: 0, b: 0, c: 0});
        const c = counts.get(kid);
        if      (item.item_type === 'article') c.a++;
        else if (item.item_type === 'book')    c.b++;
        else                                    c.c++;
      }
    }
    return sd.keywords
      .filter(kw => kw.cloud && counts.has(kw.id))
      .map(kw => {
        const c = counts.get(kw.id);
        return { id: kw.id, keyword: kw.keyword, weight: kw.weight,
                 article_count: c.a, book_count: c.b, chapter_count: c.c };
      });
  }
  const d = state.decade;
  const apiDecade = (d && d !== 'pre1980') ? d : '';
  const apiType = state.type ? `&type=${state.type}` : '';
  return apiFetch(apiDecade ? `/keywords?decade=${apiDecade}${apiType}` : `/keywords?${apiType}`);
}

async function loadItems(keyword) {
  if (window.STATIC_DATA_URL) {
    const sd = await ensureStaticData();
    const kw = sd.keywords.find(k => k.keyword.toLowerCase() === keyword.toLowerCase());
    if (!kw) return [];
    let items = (sd._byKwId[kw.id] || []).map(item => ({
      ...item,
      kw_explicit: sd._explicitOf[item.id].has(kw.id) ? 1 : 0,
    }));
    if (state.type) items = items.filter(i => i.item_type === state.type);
    items = _sdDecadeFilter(items, state.decade);
    return items.sort((a, b) => (b.year || 0) - (a.year || 0));
  }
  let path = `/items?keyword=${encodeURIComponent(keyword)}`;
  if (state.type) path += `&type=${state.type}`;
  const items = await apiFetch(path);
  const range = DECADE_RANGES[state.decade];
  if (range) {
    const [lo, hi] = range;
    return items.filter(i => i.year >= lo && i.year <= hi);
  }
  return items;
}

async function loadSearch(q) {
  if (window.STATIC_DATA_URL) {
    const sd = await ensureStaticData();
    const terms = q.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return sd.items
      .filter(item => terms.every(t =>
        (item.title    || '').toLowerCase().includes(t) ||
        (item.authors  || '').toLowerCase().includes(t) ||
        (item.abstract || '').toLowerCase().includes(t)
      ))
      .slice(0, 100);
  }
  return apiFetch(`/search?q=${encodeURIComponent(q)}`);
}

async function loadStats(decade) {
  if (window.STATIC_DATA_URL) {
    const sd = await ensureStaticData();
    const items = _sdDecadeFilter(sd.items, decade);
    const journals = new Set(items.map(i => i.journal).filter(Boolean));
    const years    = items.map(i => i.year).filter(y => y > 0);
    return {
      articles:   items.filter(i => i.item_type === 'article').length,
      books:      items.filter(i => i.item_type === 'book').length,
      chapters:   items.filter(i => i.item_type === 'chapter').length,
      keywords:   sd.keywords.length,
      journals:   journals.size,
      publishers: 0,
      year_min:   years.length ? Math.min(...years) : null,
      year_max:   years.length ? Math.max(...years) : null,
    };
  }
  const p = decade && decade !== 'pre1980' ? `?decade=${decade}` : '';
  return apiFetch(`/stats${p}`);
}

async function loadChapters(bookId) {
  if (window.STATIC_DATA_URL) {
    const sd = await ensureStaticData();
    return sd.items.filter(i => i.parent_id === bookId);
  }
  return apiFetch(`/items/${bookId}/chapters`);
}

async function loadItemKeywords(itemId) {
  if (window.STATIC_DATA_URL) {
    const sd = await ensureStaticData();
    const item = sd._itemById[itemId];
    if (!item) return [];
    return item.kw_ids.map(kid => ({
      keyword: sd._kwById[kid]?.keyword || '',
      source:  sd._explicitOf[item.id].has(kid) ? 'explicit' : 'extracted',
    }));
  }
  return apiFetch(`/items/${itemId}/keywords`);
}

async function loadSources() {
  return apiFetch('/sources');
}

// ── Stats banner ──────────────────────────────────────────────────────────────

function renderStats(s) {
  if (!s) { statsBanner.textContent = ''; return; }

  const n = v => `<span class="stat-num">${v.toLocaleString()}</span>`;
  const sep = `<span class="stat-sep"> · </span>`;

  const parts = [];
  if (s.articles)  parts.push(`${n(s.articles)} articles`);
  if (s.books)     parts.push(`${n(s.books)} books`);
  if (s.chapters)  parts.push(`${n(s.chapters)} chapters`);
  if (!parts.length) parts.push(`${n((s.articles||0) + (s.books||0) + (s.chapters||0))} items`);

  if (s.year_min && s.year_max) {
    const label = state.decade === 'pre1980'
      ? `up to ${s.year_max}`
      : `${s.year_min}–${s.year_max}`;
    parts.push(`covering ${label}`);
  }

  statsBanner.innerHTML = parts.join(sep);
}

async function refreshStats() {
  try {
    const s = await loadStats(state.decade);
    state.stats = s;
    renderStats(s);
  } catch { /* silently ignore */ }
}

// ── Word cloud (d3-cloud) ─────────────────────────────────────────────────────

let cloudSvg = null;

function domainKey(text) { return DOMAIN[text.toLowerCase()] ?? 'grey'; }
function baseColor(text) { return PALETTE[domainKey(text)].base; }

function fontSizeFor(weight, minW, maxW) {
  const W     = cloudArea.clientWidth;
  const maxPx = Math.min(72, Math.max(28, W / 14));
  const minPx = Math.max(12, W / 80);
  const t     = maxW === minW ? 1 : (weight - minW) / (maxW - minW);
  return Math.round(minPx + t * (maxPx - minPx));
}

function layoutCloud(words, W, H) {
  return new Promise(resolve => {
    d3.layout.cloud()
      .size([W, H])
      .words(words)
      .padding(6)
      .rotate(0)
      .font("'Playfair Display', Georgia, serif")
      .fontSize(d => d.size)
      .on('end', resolve)
      .start();
  });
}

async function refreshCloud() {
  cloudOverlay.style.opacity = '1';
  cloudEmpty.hidden = true;
  cloudHint.style.opacity = '0';

  try {
    const kws = await loadKeywords();
    state.keywords = kws;

    if (kws.length === 0) {
      clearCloud();
      cloudEmpty.hidden = false;
      filterStats.textContent = '';
      return;
    }

    const W = cloudArea.clientWidth;
    const H = cloudArea.clientHeight;
    const legendEl = document.getElementById('cloud-legend');
    const legendVisible = window.getComputedStyle(legendEl).display !== 'none';
    const bottomPad = 70; // clear the hint pill on all sizes
    const layoutH = H - bottomPad;
    const weights = kws.map(k => k.weight);
    const minW = Math.min(...weights), maxW = Math.max(...weights);

    // Compute legend mask rect in canvas coords (with padding) for post-filter
    let legendMask = null;
    if (legendVisible) {
      const cloudRect = cloudArea.getBoundingClientRect();
      const legRect   = legendEl.getBoundingClientRect();
      legendMask = {
        x: legRect.left - cloudRect.left - 6,
        y: legRect.top  - cloudRect.top  - 6,
        w: legRect.width  + 12,
        h: legRect.height + 12,
      };
    }

    const placed = await layoutCloud(
      kws.map(kw => ({ text: kw.keyword, size: fontSizeFor(kw.weight, minW, maxW), kw })),
      W, layoutH
    );
    drawCloud(placed, W, H, layoutH, legendMask);

    cloudHint.style.opacity = '1';
    const total = kws.reduce(
      (s, k) => s + k.article_count + k.book_count + k.chapter_count, 0
    );
    filterStats.textContent = (state.decade || state.type)
      ? `${kws.length} keywords · ${total.toLocaleString()} linked items`
      : '';

  } catch (err) {
    console.error('Cloud load error', err);
    cloudEmpty.hidden = false;
    cloudEmpty.querySelector('p').textContent =
      'Could not load keywords. Is the API running?';
  } finally {
    cloudOverlay.style.opacity = '0';
  }
}

function clearCloud() {
  if (cloudSvg) cloudSvg.selectAll('*').remove();
}

// ── Drawer sparkline ──────────────────────────────────────────────────────────

function renderSparkline(kwId) {
  drawerSparkline.innerHTML = '';
  if (!_sd?._byKwId) return;

  const DECADES = [
    ['pre-1980', 0,    1979],
    ["'80s",     1980, 1989],
    ["'90s",     1990, 1999],
    ["'00s",     2000, 2009],
    ["'10s",     2010, 2019],
    ["'20s",     2020, 2029],
  ];

  // Start with all items for the primary keyword, then intersect active chips
  let items = _sd._byKwId[kwId] || [];
  if (ds.filterKwIds.size > 0) {
    for (const fid of ds.filterKwIds) {
      const fSet = new Set((_sd._byKwId[fid] || []).map(i => i.id));
      items = items.filter(i => fSet.has(i.id));
    }
  }
  if (!items.length && ds.filterKwIds.size === 0) return;

  const data = DECADES.map(([label, lo, hi]) => ({
    label,
    total: items.filter(i => i.year > 0 && i.year >= lo && i.year <= hi).length,
  }));

  const maxVal = Math.max(1, ...data.map(d => d.total));
  const color  = baseColor(_sd._kwById[kwId]?.keyword || '');

  const W = drawerSparkline.clientWidth || 340;
  const H = 72, mb = 20, mt = 6, ml = 4, mr = 4;
  const iW = W - ml - mr, iH = H - mt - mb;

  const xSc = d3.scaleBand().domain(data.map(d => d.label)).range([0, iW]).padding(0.22);
  const ySc = d3.scaleLinear().domain([0, maxVal]).range([iH, 0]);

  const svg = d3.select(drawerSparkline).append('svg')
    .attr('width', W).attr('height', H).attr('class', 'sparkline-svg');
  const g = svg.append('g').attr('transform', `translate(${ml},${mt})`);

  // Bars
  g.selectAll('rect').data(data).enter().append('rect')
    .attr('x',      d => xSc(d.label))
    .attr('y',      d => ySc(d.total))
    .attr('width',  xSc.bandwidth())
    .attr('height', d => iH - ySc(d.total))
    .attr('fill',   d => d.total > 0 ? color : '#d8d8d8')
    .attr('rx', 2);

  // Count labels on bars with enough height
  g.selectAll('text.bar-val').data(data).enter().append('text')
    .attr('class', 'bar-val')
    .attr('x', d => xSc(d.label) + xSc.bandwidth() / 2)
    .attr('y', d => ySc(d.total) - 3)
    .attr('text-anchor', 'middle')
    .attr('fill', '#555')
    .attr('font-size', '9px')
    .text(d => d.total > 0 ? d.total : '');

  // Decade labels
  g.selectAll('text.dec-label').data(data).enter().append('text')
    .attr('class', 'dec-label')
    .attr('x', d => xSc(d.label) + xSc.bandwidth() / 2)
    .attr('y', iH + 14)
    .attr('text-anchor', 'middle')
    .attr('fill', '#999')
    .attr('font-size', '9.5px')
    .text(d => d.label);
}

// ── Related keywords chips ────────────────────────────────────────────────────

function renderRelatedChips(kwId) {
  drawerRelated.innerHTML = '';
  drawerRelated.hidden = true;
  if (!_sd?._cooccur) return;
  const peers = _sd._cooccur.get(kwId);
  if (!peers || !peers.length) return;

  const top = peers.slice(0, 10);

  // Compute the item IDs that currently match primary + all selected chips.
  // A candidate chip is only shown if adding it would still yield ≥1 result.
  let baseIds = new Set((_sd._byKwId[kwId] || []).map(i => i.id));
  for (const sid of ds.filterKwIds) {
    const sIds = new Set((_sd._byKwId[sid] || []).map(i => i.id));
    baseIds = new Set([...baseIds].filter(id => sIds.has(id)));
  }

  const visiblePeers = top.filter(([peerId]) => {
    if (ds.filterKwIds.has(peerId)) return true; // always show active chips
    const peerIds = new Set((_sd._byKwId[peerId] || []).map(i => i.id));
    return [...baseIds].some(id => peerIds.has(id));
  });

  if (!visiblePeers.length) return;

  const label = document.createElement('span');
  label.className = 'related-label';
  label.textContent = 'Often paired with:';
  drawerRelated.appendChild(label);

  visiblePeers.forEach(([peerId, count]) => {
    const kw = _sd._kwById[peerId];
    if (!kw) return;
    const isActive = ds.filterKwIds.has(peerId);
    const chip = document.createElement('button');
    chip.className = 'related-chip' + (isActive ? ' active' : '');
    chip.title = isActive
      ? 'Click to remove this filter'
      : `${count} items in common — click to filter`;
    chip.dataset.kwId = String(peerId);
    chip.style.setProperty('--chip-color', baseColor(kw.keyword));
    chip.innerHTML = `<span class="chip-dot"></span>${escapeHtml(kw.keyword)}`;
    chip.addEventListener('click', () => {
      if (ds.filterKwIds.has(peerId)) {
        ds.filterKwIds.delete(peerId);
      } else {
        ds.filterKwIds.add(peerId);
      }
      renderRelatedChips(kwId);
      renderSparkline(kwId);
      ds.page = 0;
      applyDrawerFilter();
    });
    drawerRelated.appendChild(chip);
  });

  drawerRelated.hidden = false;
}

// ── Trends view ───────────────────────────────────────────────────────────────

const TREND_COLORS = [
  '#2563eb','#dc2626','#16a34a','#d97706','#7c3aed',
  '#0891b2','#db2777','#65a30d','#ea580c','#0d9488',
];

const trendsState = {
  active: new Map(),   // kwId → { keyword, color, yearMap }
  colorIdx: 0,
  chart: null,
};

function setView(view) {
  state.view = view;
  const isCloud = view === 'cloud';

  trendsToggleBtn.setAttribute('aria-pressed', String(!isCloud));
  trendsToggleBtn.classList.toggle('active', !isCloud);

  // Show/hide cloud elements
  cloudOverlay.style.display  = isCloud ? '' : 'none';
  cloudHint.hidden            = !isCloud;
  document.getElementById('cloud-legend').hidden = !isCloud;
  if (cloudSvg) cloudSvg.node().style.display = isCloud ? '' : 'none';

  // Show/hide trends panel
  trendsPanel.hidden = isCloud;

  if (!isCloud) {
    initTrendsPanel();
  }
}

async function addToTrends(kwId, keyword) {
  if (trendsState.active.has(kwId)) return;
  let yearMap = new Map();
  try {
    const sd = await ensureStaticData();
    yearMap = sd._byYear.get(kwId) || new Map();
  } catch { /* proceed without trend data */ }
  const color = TREND_COLORS[trendsState.colorIdx % TREND_COLORS.length];
  trendsState.colorIdx++;
  trendsState.active.set(kwId, { kwId, keyword, color, yearMap });
  renderTrendsLegend();
  renderTrendsChart();
}

function removeFromTrends(kwId) {
  trendsState.active.delete(kwId);
  renderTrendsLegend();
  renderTrendsChart();
}

function initTrendsPanel() {
  if (trendsPanel.dataset.initialized) return;
  trendsPanel.dataset.initialized = '1';

  trendsPanel.innerHTML = `
    <div class="trends-header">
      <div class="trends-header-top">
        <h2 class="trends-title">Keyword Trends</h2>
        <p class="trends-sub">Frequency of each keyword across the corpus by year</p>
      </div>
      <div class="trends-selector-wrap">
        <div class="trends-search-field">
          <svg viewBox="0 0 20 20" fill="none" width="14" height="14" aria-hidden="true">
            <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.5"/>
            <path d="M13 13L17 17" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
          <input id="trends-search" type="search" placeholder="Add keyword to compare…"
                 autocomplete="off" spellcheck="false" class="trends-search-input"/>
        </div>
        <div id="trends-suggestions" class="trends-suggestions" hidden></div>
      </div>
      <div id="trends-legend" class="trends-legend"></div>
    </div>
    <div id="trends-chart-area" class="trends-chart-area"></div>
  `;

  // Wire search
  const searchEl = document.getElementById('trends-search');
  const suggEl   = document.getElementById('trends-suggestions');

  searchEl.addEventListener('input', debounce(() => {
    const q = searchEl.value.trim().toLowerCase();
    if (!q || !_sd) { suggEl.hidden = true; return; }
    const matches = _sd.keywords
      .filter(k => k.cloud && k.keyword.toLowerCase().includes(q) && !trendsState.active.has(k.id))
      .slice(0, 8);
    if (!matches.length) { suggEl.hidden = true; return; }
    suggEl.innerHTML = matches.map(k =>
      `<button class="trends-sugg-item" data-id="${k.id}" data-kw="${escapeHtml(k.keyword)}">
         ${escapeHtml(k.keyword)}
       </button>`
    ).join('');
    suggEl.hidden = false;
  }, 150));

  suggEl.addEventListener('click', e => {
    const btn = e.target.closest('.trends-sugg-item');
    if (!btn) return;
    addToTrends(Number(btn.dataset.id), btn.dataset.kw);
    searchEl.value = '';
    suggEl.hidden = true;
    searchEl.focus();
  });

  document.addEventListener('click', e => {
    if (!suggEl.contains(e.target) && e.target !== searchEl) suggEl.hidden = true;
  }, { capture: true });
}

function renderTrendsLegend() {
  const el = document.getElementById('trends-legend');
  if (!el) return;
  if (!trendsState.active.size) {
    el.innerHTML = '<span class="trends-empty-hint">Search above or switch back to Cloud view and click keywords to add them here</span>';
    return;
  }
  el.innerHTML = [...trendsState.active.values()].map(s =>
    `<span class="trends-legend-item" data-id="${s.kwId}">
       <span class="trends-legend-dot" style="background:${s.color}"></span>
       ${escapeHtml(s.keyword)}
       <button class="trends-legend-remove" aria-label="Remove ${escapeHtml(s.keyword)}">✕</button>
     </span>`
  ).join('');
  el.querySelectorAll('.trends-legend-remove').forEach(btn => {
    btn.addEventListener('click', () => removeFromTrends(Number(btn.closest('[data-id]').dataset.id)));
  });
}

function renderTrendsChart() {
  const area = document.getElementById('trends-chart-area');
  if (!area) return;
  area.innerHTML = '';

  const series = [...trendsState.active.values()];

  if (!series.length) {
    area.innerHTML = '<div class="trends-no-data">Add keywords above to see trends</div>';
    return;
  }

  // Collect all years across active keywords
  const allYears = new Set();
  series.forEach(s => { for (const [y] of s.yearMap) { if (y >= 1950) allYears.add(y); } });
  const years = [...allYears].sort((a, b) => a - b);
  if (!years.length) return;
  const [yMin, yMax] = [years[0], years[years.length - 1]];

  const margin = { top: 16, right: 24, bottom: 40, left: 44 };
  const W = area.clientWidth  - margin.left - margin.right;
  const H = area.clientHeight - margin.top  - margin.bottom;
  if (W <= 0 || H <= 0) return;

  const xSc = d3.scaleLinear().domain([yMin, yMax]).range([0, W]);
  const maxCount = d3.max(series, s => d3.max([...s.yearMap.values()])) || 1;
  const ySc = d3.scaleLinear().domain([0, maxCount]).nice().range([H, 0]);

  const svg = d3.select(area).append('svg')
    .attr('width',  W + margin.left + margin.right)
    .attr('height', H + margin.top  + margin.bottom);

  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

  // Grid lines
  g.append('g').attr('class', 'trends-grid')
    .call(d3.axisLeft(ySc).ticks(5).tickSize(-W).tickFormat(''))
    .call(ax => ax.select('.domain').remove());

  // Axes
  g.append('g').attr('class', 'trends-axis')
    .attr('transform', `translate(0,${H})`)
    .call(d3.axisBottom(xSc).ticks(Math.min(10, yMax - yMin)).tickFormat(d3.format('d')));

  g.append('g').attr('class', 'trends-axis')
    .call(d3.axisLeft(ySc).ticks(5));

  // Line generator — fill missing years with 0
  const line = d3.line()
    .x(d => xSc(d[0]))
    .y(d => ySc(d[1]))
    .curve(d3.curveMonotoneX);

  // Draw lines
  series.forEach(s => {
    const pts = [];
    for (let y = yMin; y <= yMax; y++) pts.push([y, s.yearMap.get(y) || 0]);
    g.append('path')
      .datum(pts)
      .attr('fill', 'none')
      .attr('stroke', s.color)
      .attr('stroke-width', 2)
      .attr('d', line);
  });

  // Hover interaction
  const tooltip = d3.select(area).append('div').attr('class', 'trends-tooltip');
  const crosshair = g.append('line')
    .attr('class', 'trends-crosshair')
    .attr('y1', 0).attr('y2', H)
    .style('display', 'none');

  g.append('rect')
    .attr('width', W).attr('height', H)
    .attr('fill', 'none').attr('pointer-events', 'all')
    .on('mousemove', function(event) {
      const [mx] = d3.pointer(event);
      const yr = Math.round(xSc.invert(mx));
      if (yr < yMin || yr > yMax) return;
      crosshair.style('display', null)
        .attr('x1', xSc(yr)).attr('x2', xSc(yr));
      const rows = series
        .map(s => ({ label: s.keyword, val: s.yearMap.get(yr) || 0, color: s.color }))
        .sort((a, b) => b.val - a.val);
      tooltip.style('display', 'block')
        .style('left', `${Math.min(event.offsetX + 14, area.clientWidth - 160)}px`)
        .style('top',  `${event.offsetY - 12}px`)
        .html(`<div class="tt-year">${yr}</div>` +
          rows.map(r => `<div class="tt-row">
            <span class="tt-dot" style="background:${r.color}"></span>
            <span class="tt-label">${escapeHtml(r.label)}</span>
            <span class="tt-val">${r.val}</span>
          </div>`).join(''));
    })
    .on('mouseleave', () => {
      crosshair.style('display', 'none');
      tooltip.style('display', 'none');
    });
}

function drawCloud(words, W, H, layoutH = H, legendMask = null) {
  if (!cloudSvg) {
    cloudSvg = d3.select('#cloud-area')
      .append('svg')
      .style('position', 'absolute')
      .style('inset', '0')
      .attr('aria-hidden', 'true');
  }
  cloudSvg.attr('width', W).attr('height', H);
  cloudSvg.selectAll('*').remove();

  const g = cloudSvg.append('g')
    .attr('transform', `translate(${W / 2},${layoutH / 2})`);

  // Filter out words whose bounding box overlaps the legend zone so the
  // legend corner is clear while the rest of the bottom row remains usable.
  const visible = legendMask ? words.filter(d => {
    const cx = d.x + W / 2;
    const cy = d.y + layoutH / 2;
    const hw = (d.width  ?? d.size * 0.6) / 2;
    const hh = (d.height ?? d.size)       / 2;
    return !(cx + hw > legendMask.x && cx - hw < legendMask.x + legendMask.w &&
             cy + hh > legendMask.y && cy - hh < legendMask.y + legendMask.h);
  }) : words;

  g.selectAll('text')
    .data(visible)
    .enter()
    .append('text')
      .attr('class', 'cloud-word')
      .style('font-family', "'Playfair Display', Georgia, serif")
      .style('font-size',   d => `${d.size}px`)
      .style('font-weight', d => d.size >= 20 ? '600' : '400')
      .style('fill',        d => baseColor(d.text))
      .style('cursor',      'pointer')
      .style('user-select', 'none')
      .style('transition',  'opacity 0.18s ease, fill 0.18s ease')
      .attr('text-anchor',  'middle')
      .attr('transform',    d => `translate(${d.x},${d.y})rotate(${d.rotate ?? 0})`)
      .text(d => d.text)
      .on('mouseenter', function(event, d) {
        if (drawer.classList.contains('open')) return;
        g.selectAll('text.cloud-word').style('opacity', 0.22);
        d3.select(this).style('opacity', 1).style('fill', '#1c1814');
        showTooltip(event, d);
      })
      .on('mousemove', function(event) {
        if (!drawer.classList.contains('open')) positionTooltip(event);
      })
      .on('mouseleave', function() {
        g.selectAll('text.cloud-word')
          .style('opacity', 1)
          .style('fill', d => baseColor(d.text));
        hideTooltip();
      })
      .on('click', function(event, d) {
        event.stopPropagation();
        if (state.view === 'trends') {
          addToTrends(d.kw.id, d.text);
        } else {
          openKeywordDrawer(d);
        }
      });
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

function showTooltip(event, d) {
  const total = d.kw.article_count + d.kw.book_count + d.kw.chapter_count;
  const parts = [
    d.kw.article_count ? `${d.kw.article_count.toLocaleString()} article${d.kw.article_count !== 1 ? 's' : ''}` : '',
    d.kw.book_count    ? `${d.kw.book_count.toLocaleString()} book${d.kw.book_count !== 1 ? 's' : ''}`           : '',
    d.kw.chapter_count ? `${d.kw.chapter_count.toLocaleString()} chapter${d.kw.chapter_count !== 1 ? 's' : ''}` : '',
  ].filter(Boolean).join(' · ');

  tooltip.innerHTML =
    `<span class="tt-keyword" style="color:${baseColor(d.text)}">${escapeHtml(d.text)}</span>` +
    `<span class="tt-total">${total.toLocaleString()} item${total !== 1 ? 's' : ''}</span>` +
    (parts ? `<span class="tt-breakdown">${parts}</span>` : '');

  positionTooltip(event);
  tooltip.removeAttribute('aria-hidden');
  tooltip.classList.add('visible');
}

function positionTooltip(event) {
  const x = Math.min(event.clientX + 16, window.innerWidth  - 220);
  const y = Math.max(event.clientY - 72, 8);
  tooltip.style.left = `${x}px`;
  tooltip.style.top  = `${y}px`;
}

function hideTooltip() {
  tooltip.classList.remove('visible');
  tooltip.setAttribute('aria-hidden', 'true');
}

// ── Sorting ───────────────────────────────────────────────────────────────────

function lastNameOf(item) {
  try {
    const list = typeof item.authors === 'string'
      ? JSON.parse(item.authors) : (item.authors || []);
    if (!list.length) return '￿'; // sort unnamed to end
    const name = list[0];
    // "Last, First" → use part before comma; "First Last" → use last word
    const lastName = name.includes(',')
      ? name.split(/,\s*/)[0]
      : name.trim().split(/\s+/).pop();
    return lastName.toLowerCase();
  } catch { return '￿'; }
}

function sortItems(items, by) {
  const copy = [...items];
  switch (by) {
    case 'date-desc': return copy.sort((a, b) => (b.year || 0) - (a.year || 0));
    case 'date-asc':  return copy.sort((a, b) => (a.year || 0) - (b.year || 0));
    case 'author':    return copy.sort((a, b) => lastNameOf(a) < lastNameOf(b) ? -1 : lastNameOf(a) > lastNameOf(b) ? 1 : 0);
    case 'title':     return copy.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
    default:          return copy; // preserve API order
  }
}

function setSortBtn(by) {
  ds.sortBy = by;
  sortGroup.querySelectorAll('.sort-btn').forEach(btn => {
    const active = btn.dataset.sort === by;
    btn.classList.toggle('active', active);
  });
}

// ── Drawer core ───────────────────────────────────────────────────────────────

function openDrawerShell(heading, metaText) {
  drawerKeyword.textContent = heading;
  drawerMeta.textContent    = metaText || '';
  drawerCount.textContent   = '';
  resultList.innerHTML      =
    '<li class="result-loading" role="listitem"><span class="spinner"></span> Loading…</li>';
  pagination.hidden = true;
  sortBar.hidden    = false;
  drawer.classList.add('open');
  drawer.removeAttribute('aria-hidden');
  drawerOverlay.classList.add('visible');
  drawerOverlay.removeAttribute('aria-hidden');
  drawerBody.scrollTop = 0;
}

function closeDrawer() {
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
  drawerOverlay.classList.remove('visible');
  drawerOverlay.setAttribute('aria-hidden', 'true');
  drawerTabs.hidden     = true;
  drawerSrchWrap.hidden = true;
  sortBar.hidden        = true;
  pagination.hidden     = true;
  ds.filterKwIds.clear();
  ds.primaryKwId = null;
  drawerSparkline.innerHTML = '';
  drawerRelated.innerHTML   = '';
  drawerRelated.hidden      = true;
  if (cloudSvg) {
    cloudSvg.selectAll('text.cloud-word')
      .style('opacity', 1)
      .style('fill', d => baseColor(d.text));
  }
  hideTooltip();
  drawerSrchIn.value = '';
}

// ── Drawer: keyword drill-down ────────────────────────────────────────────────

async function openKeywordDrawer(d) {
  const kwText      = d.text;
  ds.mode         = 'keyword';
  ds.kwText       = kwText;
  ds.searchTerms  = [];
  ds.tab          = 'articles';
  ds.page         = 0;
  ds.primaryKwId = null;
  ds.filterKwIds.clear();
  drawerSrchIn.value = '';
  setSortBtn('date-desc');

  const decadeLabel = state.decade
    ? (state.decade === 'pre1980' ? 'pre-1980' : state.decade)
    : 'All Years';
  openDrawerShell(kwText, `${decadeLabel} · ${state.type || 'All Types'}`);

  if (cloudSvg) {
    cloudSvg.selectAll('text.cloud-word')
      .style('opacity', d2 => d2.text === kwText ? 1 : 0.18)
      .style('fill',    d2 => d2.text === kwText ? '#1c1814' : baseColor(d2.text));
  }

  try {
    const items = await loadItems(kwText);
    ds.allItems = items;
    activateKeywordDrawerUI();

    try {
      const sd = await ensureStaticData();
      const kwObj = d.kw || sd.keywords.find(k => k.keyword.toLowerCase() === kwText.toLowerCase());
      if (kwObj) {
        ds.primaryKwId = kwObj.id;
        renderSparkline(kwObj.id);
        renderRelatedChips(kwObj.id);
      }
    } catch { /* correlation data unavailable */ }
  } catch (err) {
    resultList.innerHTML =
      `<li class="result-error" role="listitem">Failed to load items: ${escapeHtml(err.message)}</li>`;
  }
}

function activateKeywordDrawerUI() {
  drawerSrchWrap.hidden = false;

  const artChap = ds.allItems.filter(i => i.item_type !== 'book');
  const books   = ds.allItems.filter(i => i.item_type === 'book');

  tabCountArt.textContent  = artChap.length;
  tabCountBook.textContent = books.length;

  tabArticles.style.display = artChap.length === 0 ? 'none' : '';
  tabBooks.style.display    = books.length   === 0 ? 'none' : '';

  // Hide the tab bar entirely when only one type is present (no choice to make)
  const bothVisible = artChap.length > 0 && books.length > 0;
  drawerTabs.hidden = !bothVisible;

  // Auto-select the right tab based on what's available
  const defaultTab = books.length > 0 && artChap.length === 0 ? 'books' : 'articles';
  setActiveTab(defaultTab);
}

function setActiveTab(tab) {
  ds.tab  = tab;
  ds.page = 0;

  tabArticles.classList.toggle('active', tab === 'articles');
  tabArticles.setAttribute('aria-selected', String(tab === 'articles'));
  tabBooks.classList.toggle('active', tab === 'books');
  tabBooks.setAttribute('aria-selected', String(tab === 'books'));

  applyDrawerFilter();
}

function applyDrawerFilter() {
  const q = drawerSrchIn.value.trim().toLowerCase();

  // Compute intersection of all items × all selected chip keywords once
  let intersected = ds.allItems;
  if (ds.filterKwIds.size > 0 && _sd) {
    for (const fid of ds.filterKwIds) {
      const peerIds = new Set((_sd._byKwId[fid] || []).map(i => i.id));
      intersected = intersected.filter(i => peerIds.has(i.id));
    }
  }

  // Update tab badge counts to reflect the current intersection
  if (ds.mode === 'keyword') {
    const nArt  = intersected.filter(i => i.item_type !== 'book').length;
    const nBook = intersected.filter(i => i.item_type === 'book').length;
    tabCountArt.textContent  = nArt;
    tabCountBook.textContent = nBook;
  }

  const src = ds.tab === 'books'
    ? intersected.filter(i => i.item_type === 'book')
    : intersected.filter(i => i.item_type !== 'book');

  const filtered = q
    ? src.filter(i =>
        (i.title   || '').toLowerCase().includes(q) ||
        (i.authors || '').toLowerCase().includes(q) ||
        (i.journal || '').toLowerCase().includes(q)
      )
    : src;

  ds.filtered = sortItems(filtered, ds.sortBy);
  ds.page = 0;
  renderPage();
}

function renderPage() {
  const total   = ds.filtered.length;
  const pages   = Math.max(1, Math.ceil(total / PAGE_SIZE));
  ds.page       = Math.max(0, Math.min(ds.page, pages - 1));
  const start   = ds.page * PAGE_SIZE;
  const pageItems = ds.filtered.slice(start, start + PAGE_SIZE);

  drawerCount.textContent = total.toLocaleString() +
    ' item' + (total !== 1 ? 's' : '') +
    (ds.allItems.length !== total ? ` (${ds.allItems.length.toLocaleString()} total)` : '');

  if (total === 0) {
    resultList.innerHTML =
      '<li class="result-empty" role="listitem">No items match this filter.</li>';
    pagination.hidden = true;
    return;
  }

  resultList.innerHTML = pageItems.map(item =>
    ds.mode === 'search'
      ? renderSearchCard(item, ds.searchTerms)
      : ds.tab === 'books' ? renderBookCard(item) : renderArticleCard(item, [])
  ).join('');

  // Wire chapter expand buttons
  resultList.querySelectorAll('.chapter-toggle').forEach(btn => {
    btn.addEventListener('click', () => toggleChapters(btn));
  });

  if (pages > 1) {
    pagination.hidden = false;
    pagePrev.disabled = ds.page === 0;
    pageNext.disabled = ds.page >= pages - 1;
    pageInfo.textContent = `${ds.page + 1} / ${pages}`;
  } else {
    pagination.hidden = true;
  }

  drawerBody.scrollTop = 0;
}

// ── Chapters expand ───────────────────────────────────────────────────────────

async function toggleChapters(btn) {
  const bookId = btn.dataset.bookId;
  const listEl = btn.nextElementSibling;

  if (listEl && listEl.classList.contains('chapter-list')) {
    const hidden = listEl.hidden;
    listEl.hidden = !hidden;
    btn.textContent = hidden ? '▲ Hide chapters' : '▼ Show chapters';
    return;
  }

  btn.textContent = 'Loading…';
  btn.disabled    = true;
  try {
    const chapters = await loadChapters(bookId);
    const ul = document.createElement('ul');
    ul.className = 'chapter-list';
    if (chapters.length === 0) {
      ul.innerHTML = '<li class="chapter-item" style="color:var(--text-dim);font-style:italic">No chapters indexed yet.</li>';
    } else {
      ul.innerHTML = chapters.map(ch => {
        const link = ch.doi
          ? `<a href="https://doi.org/${ch.doi}" target="_blank" rel="noopener">${safeTitleHtml(ch.title)}</a>`
          : safeTitleHtml(ch.title);
        const authors = formatAuthors(ch.authors);
        return `<li class="chapter-item">${link}${authors ? ` <span style="color:var(--text-dim)">— ${escapeHtml(authors)}</span>` : ''}</li>`;
      }).join('');
    }
    btn.after(ul);
    btn.textContent = '▲ Hide chapters';
    btn.disabled    = false;
  } catch {
    btn.textContent = '▼ Show chapters';
    btn.disabled    = false;
  }
}

// ── Drawer: search results ────────────────────────────────────────────────────

async function openSearchDrawer(q) {
  if (!q) return;
  ds.mode        = 'search';
  ds.searchTerms = q.trim().split(/\s+/).filter(Boolean);
  ds.kwText      = '';
  ds.page        = 0;
  drawerSrchIn.value = '';
  drawerTabs.hidden  = true;
  setSortBtn('date-desc');

  openDrawerShell(`"${q}"`, 'Full-Text Search');
  drawerSrchWrap.hidden = true;

  if (cloudSvg) {
    cloudSvg.selectAll('text.cloud-word')
      .style('opacity', 1).style('fill', d => baseColor(d.text));
  }

  try {
    let items = await loadSearch(q);
    if (state.type) items = items.filter(i => i.item_type === state.type);
    const range = DECADE_RANGES[state.decade];
    if (range) {
      const [lo, hi] = range;
      items = items.filter(i => i.year >= lo && i.year <= hi);
    }

    ds.allItems = items;
    ds.filtered = items;

    if (items.length === 0) {
      renderNoSearchResults(q);
      return;
    }

    drawerCount.textContent = `${items.length.toLocaleString()} result${items.length !== 1 ? 's' : ''}`;
    renderPage();

  } catch (err) {
    resultList.innerHTML =
      `<li class="result-error" role="listitem">Search failed: ${escapeHtml(err.message)}</li>`;
  }
}

function renderNoSearchResults(q) {
  const terms     = q.toLowerCase().split(/\s+/);
  const suggested = state.keywords
    .filter(kw => terms.some(t => kw.keyword.toLowerCase().includes(t)))
    .slice(0, 10);

  drawerCount.textContent = '0 results';
  pagination.hidden       = true;

  if (suggested.length === 0) {
    resultList.innerHTML =
      '<li class="result-empty" role="listitem">No results found for this query.</li>';
    return;
  }

  const chips = suggested.map(kw =>
    `<button class="suggest-chip" data-kw="${escapeHtml(kw.keyword)}">${escapeHtml(kw.keyword)}</button>`
  ).join('');

  resultList.innerHTML = `
    <li class="search-suggest" role="listitem">
      <p>No results found. Try exploring a related keyword:</p>
      <div class="suggest-chips">${chips}</div>
    </li>`;

  resultList.querySelectorAll('.suggest-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const kwText = chip.dataset.kw;
      const kwObj  = state.keywords.find(k => k.keyword === kwText);
      if (kwObj) openKeywordDrawer({ text: kwObj.keyword, kw: kwObj });
    });
  });
}

// ── Result card renderers ─────────────────────────────────────────────────────

function coverImgReplace(img) {
  const ph = document.createElement('div');
  ph.className = 'result-cover-placeholder';
  ph.setAttribute('aria-hidden', 'true');
  ph.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="3" y="2" width="14" height="20" rx="1"/><path d="M7 6h6M7 10h6M7 14h4"/></svg>';
  img.replaceWith(ph);
}

function coverImgError(img) {
  img.onerror = null;
  coverImgReplace(img);
}

function coverImgLoad(img) {
  // Open Library returns a 1×1 GIF for missing covers (HTTP 200)
  if (img.naturalWidth <= 1 || img.naturalHeight <= 1) {
    coverImgReplace(img);
  }
}

function isReview(item) {
  if (item.is_review) return true;
  const t = (item.title || '').trimStart();
  return /^(book\s+)?review[\s:]/i.test(t) || /^review of /i.test(t);
}

function itemHref(item) {
  if (item.doi) return `https://doi.org/${item.doi}`;
  if (item.url) return item.url;
  return null;
}

function renderArticleCard(item, highlightTerms = []) {
  const authors   = formatAuthors(item.authors);
  const rawTitle  = item.title || '';
  const titleHtml = highlightTerms.length
    ? highlightText(safeTitleHtml(rawTitle), highlightTerms)
    : safeTitleHtml(rawTitle);
  const href      = itemHref(item);
  const linked    = href
    ? `<a class="result-title-link" href="${escapeHtml(href)}" target="_blank" rel="noopener">${titleHtml}</a>`
    : titleHtml;
  const abstract  = item.abstract
    ? `<p class="result-abstract">${
        highlightTerms.length
          ? highlightText(escapeHtml(truncate(cleanAbstract(item.abstract), 220)), highlightTerms)
          : escapeHtml(truncate(cleanAbstract(item.abstract), 220))
      }</p>`
    : '';
  const journal   = item.journal
    ? `<span class="result-journal">${escapeHtml(item.journal)}</span>` : '';
  const volIss    = [item.volume && `Vol. ${item.volume}`, item.issue && `No. ${item.issue}`]
    .filter(Boolean).join(', ');

  const sourceBadge = item.kw_explicit != null
    ? `<span class="kw-source-badge ${item.kw_explicit ? 'kw-source-explicit' : 'kw-source-extracted'}">${item.kw_explicit ? 'explicit' : 'extracted'}</span>`
    : '';

  const reviewBadge = isReview(item)
    ? `<span class="result-type-badge result-type-review">review</span>`
    : '';

  return `
    <li class="result-card" role="listitem" data-id="${item.id}">
      <div class="result-content">
        <div class="result-top-row">
          <span class="result-type-badge result-type-article">article</span>
          ${reviewBadge}
          ${item.year > 0 ? `<span class="result-year">${item.year}</span>` : ''}
          ${journal}
          ${volIss ? `<span class="result-voliss">${escapeHtml(volIss)}</span>` : ''}
          ${sourceBadge}
        </div>
        <h3 class="result-title">${linked}</h3>
        ${authors ? `<p class="result-authors">${escapeHtml(authors)}</p>` : ''}
        ${abstract}
      </div>
    </li>`;
}

function renderBookCard(item) {
  const authors   = formatAuthors(item.authors);
  const titleHtml = safeTitleHtml(item.title || '');
  const href      = itemHref(item);
  const titleLink = href
    ? `<a class="result-title-link" href="${escapeHtml(href)}" target="_blank" rel="noopener">${titleHtml}</a>`
    : titleHtml;

  const cover = item.cover_url
    ? `<img class="result-cover" src="${item.cover_url}" alt="Cover of ${escapeHtml(item.title || '')}" loading="lazy" onload="coverImgLoad(this)" onerror="coverImgError(this)"/>`
    : `<div class="result-cover-placeholder" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="3" y="2" width="14" height="20" rx="1"/><path d="M7 6h6M7 10h6M7 14h4"/></svg></div>`;

  const chapBtn = item.chapters_available
    ? `<button class="chapter-toggle" data-book-id="${item.id}">▼ Show chapters (${item.chapters_available})</button>`
    : '';

  return `
    <li class="result-card" role="listitem" data-id="${item.id}">
      ${cover}
      <div class="result-content">
        <div class="result-top-row">
          <span class="result-type-badge result-type-book">book</span>
          ${item.year > 0 ? `<span class="result-year">${item.year}</span>` : ''}
          ${item.publisher ? `<span class="result-journal">${escapeHtml(item.publisher)}</span>` : ''}
        </div>
        <h3 class="result-title">${titleLink}</h3>
        ${authors ? `<p class="result-authors">${escapeHtml(authors)}</p>` : ''}
        ${chapBtn}
      </div>
    </li>`;
}

function renderSearchCard(item, highlightTerms) {
  return item.item_type === 'book'
    ? renderBookCard(item)
    : renderArticleCard(item, highlightTerms);
}

// ── Modal ─────────────────────────────────────────────────────────────────────

async function openModal(item) {
  // Header badges
  const badges = [`<span class="result-type-badge result-type-${item.item_type}">${item.item_type}</span>`];
  if (isReview(item)) badges.push(`<span class="result-type-badge result-type-review">review</span>`);
  modalBadges.innerHTML = badges.join('');

  if (item.cover_url && item.item_type === 'book') {
    modalCover.src = item.cover_url;
    modalCover.alt = `Cover of ${item.title || ''}`;
    modalCover.hidden = false;
    modalCover.onerror = () => { modalCover.hidden = true; };
    modalCover.onload = () => { if (modalCover.naturalWidth <= 1 || modalCover.naturalHeight <= 1) modalCover.hidden = true; };
  } else {
    modalCover.hidden = true;
    modalCover.src = '';
  }

  modalTitle.innerHTML   = safeTitleHtml(item.title || 'Untitled');
  modalAuthors.textContent = formatAuthors(item.authors) || '';

  // Meta grid
  const metaParts = [];
  if (item.year > 0)  metaParts.push(`<span class="modal-meta-item"><span class="modal-meta-label">Year</span>${item.year}</span>`);
  if (item.journal)   metaParts.push(`<span class="modal-meta-item"><span class="modal-meta-label">Journal</span>${escapeHtml(item.journal)}</span>`);
  if (item.volume)    metaParts.push(`<span class="modal-meta-item"><span class="modal-meta-label">Vol.</span>${escapeHtml(item.volume)}</span>`);
  if (item.issue)     metaParts.push(`<span class="modal-meta-item"><span class="modal-meta-label">No.</span>${escapeHtml(item.issue)}</span>`);
  if (item.publisher) metaParts.push(`<span class="modal-meta-item"><span class="modal-meta-label">Publisher</span>${escapeHtml(item.publisher)}</span>`);
  modalMeta.innerHTML = metaParts.join('');

  // Abstract
  const abst = item.abstract ? cleanAbstract(item.abstract) : '';
  if (abst) {
    modalAbstract.innerHTML = escapeHtml(abst);
    document.getElementById('modal-abstract-section').hidden = false;
  } else {
    modalAbstract.innerHTML = `<span class="modal-abstract-empty">No abstract available.</span>`;
    document.getElementById('modal-abstract-section').hidden = false;
  }

  // Link
  const href = itemHref(item);
  if (href) {
    modalLink.href    = href;
    modalLink.hidden  = false;
    modalLink.textContent = item.doi ? 'Open via DOI →' : 'Open full text →';
  } else {
    modalLink.hidden = true;
  }

  // Keywords (show placeholder, load async)
  modalKwList.innerHTML = '<span class="modal-kw-loading">Loading…</span>';

  // Show modal
  modalOverlay.classList.add('open');
  modalOverlay.removeAttribute('aria-hidden');
  document.body.style.overflow = 'hidden';

  // Scroll modal body to top
  document.getElementById('modal-body').scrollTop = 0;

  // Fetch keywords async
  try {
    const kws = await loadItemKeywords(item.id);
    if (!modalOverlay.classList.contains('open')) return; // closed already
    if (kws.length === 0) {
      modalKwList.innerHTML = '<span class="modal-kw-loading">No keywords indexed.</span>';
    } else {
      modalKwList.innerHTML = kws.map(kw =>
        `<button class="modal-kw-chip" data-kw="${escapeHtml(kw.keyword)}">${escapeHtml(kw.keyword)}</button>`
      ).join('');
      modalKwList.querySelectorAll('.modal-kw-chip').forEach(chip => {
        chip.addEventListener('click', () => {
          closeModal();
          const kwText = chip.dataset.kw;
          const kwObj  = state.keywords.find(k => k.keyword === kwText);
          if (kwObj) {
            setTimeout(() => openKeywordDrawer({ text: kwObj.keyword, kw: kwObj }), 180);
          }
        });
      });
    }
  } catch {
    modalKwList.innerHTML = '<span class="modal-kw-loading">Could not load keywords.</span>';
  }
}

function closeModal() {
  modalOverlay.classList.remove('open');
  modalOverlay.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

// ── Info panel ────────────────────────────────────────────────────────────────

const infoOverlay = document.getElementById('info-overlay');
const infoClose   = document.getElementById('info-close');
const infoLoading = document.getElementById('info-loading');
const infoContent     = document.getElementById('info-content');
const drawerSparkline = document.getElementById('drawer-sparkline');
const drawerRelated   = document.getElementById('drawer-related');
const trendsPanel     = document.getElementById('trends-panel');
const trendsToggleBtn = document.getElementById('trends-toggle');

async function openInfo() {
  infoOverlay.classList.add('open');
  infoOverlay.removeAttribute('aria-hidden');
  document.body.style.overflow = 'hidden';

  // Reset to loading state each time
  infoLoading.hidden  = false;
  infoContent.hidden  = true;
  infoContent.innerHTML = '';

  try {
    const r = await fetch('data/info.json');
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    const data = await r.json();
    infoContent.innerHTML = renderInfoContent(data.stats, { journals: data.journals, publishers: data.publishers });
    infoLoading.hidden    = true;
    infoContent.hidden    = false;
  } catch (err) {
    infoLoading.innerHTML = `<span style="color:var(--red-dim)">Could not load data: ${escapeHtml(err.message)}</span>`;
  }
}

function closeInfo() {
  infoOverlay.classList.remove('open');
  infoOverlay.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

function renderInfoContent(stats, sources) {
  const n = v => `<span class="info-stat-num">${Number(v).toLocaleString()}</span>`;

  const statCards = [
    { val: stats.articles,  label: 'Articles' },
    { val: stats.books,     label: 'Books' },
    { val: stats.chapters,  label: 'Chapters' },
    { val: stats.journals,  label: 'Journals' },
    { val: stats.keywords,  label: 'Keywords' },
  ]
    .filter(s => s.val > 0)
    .map(s => `
      <div class="info-stat-card">
        ${n(s.val)}
        <span class="info-stat-label">${s.label}</span>
      </div>`)
    .join('');

  const yearRange = stats.year_min && stats.year_max
    ? `<div class="info-stat-card">
         <span class="info-stat-num">${stats.year_min}–${stats.year_max}</span>
         <span class="info-stat-label">Years Covered</span>
       </div>`
    : '';

  const maxJ = sources.journals[0]?.count || 1;
  const journalRows = sources.journals.map(j => `
    <div class="source-row">
      <div class="source-name-row">
        <span class="source-name" title="${escapeHtml(j.name)}">${escapeHtml(j.name)}</span>
        <span class="source-count">${Number(j.count).toLocaleString()}</span>
      </div>
      <div class="source-bar-wrap">
        <div class="source-bar" style="width:${Math.round(j.count / maxJ * 100)}%"></div>
      </div>
    </div>`).join('');

  const publisherSection = sources.publishers.length ? (() => {
    const maxP = sources.publishers[0].count;
    const rows = sources.publishers.map(p => `
      <div class="source-row">
        <div class="source-name-row">
          <span class="source-name" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</span>
          <span class="source-count">${Number(p.count).toLocaleString()}</span>
        </div>
        <div class="source-bar-wrap">
          <div class="source-bar" style="width:${Math.round(p.count / maxP * 100)}%"></div>
        </div>
      </div>`).join('');
    return `<h3 class="info-section-heading" style="margin-top:1.5rem">Publishers</h3>
            <div class="source-list">${rows}</div>`;
  })() : '';

  return `
    <h2 class="info-heading" id="info-heading">About This Database</h2>
    <p class="info-description">
      The Music Theory Scholarship Database is a searchable index of peer-reviewed articles,
      books, and book chapters from the leading journals and presses in music theory. Each entry
      is tagged with keywords—drawn from author-supplied terms or extracted from abstracts—which
      power the word cloud and enable exploration by concept. Use the cloud to browse by topic,
      or the search bar to query titles, authors, and abstracts directly.
    </p>
    <div class="info-stats-grid">${statCards}${yearRange}</div>
    <h3 class="info-section-heading">Journals &amp; Series</h3>
    <div class="source-list">${journalRows}</div>
    ${publisherSection}

    <h3 class="info-section-heading" style="margin-top:2rem">Methodology</h3>
    <div class="info-method-blocks">

      <div class="info-method-block">
        <div class="info-method-title">Data Collection</div>
        <p class="info-method-body">
          Article metadata is retrieved from the
          <a class="info-link" href="https://www.crossref.org/" target="_blank" rel="noopener">CrossRef API</a>
          using each journal's ISSN, which provides titles, authors, DOIs, years, volumes, and—where
          available—abstracts. Book records come from two sources: Cambridge University Press titles
          are harvested directly from the
          <a class="info-link" href="https://www.cambridge.org/core/browse-subjects/music" target="_blank" rel="noopener">Cambridge Core</a>
          music catalogue; books from Oxford University Press, MIT Press, Routledge, W.&nbsp;W.&nbsp;Norton,
          Princeton, Yale, Chicago, Michigan, California, Cornell, Rochester, and Duke University Presses
          are retrieved via the
          <a class="info-link" href="https://developers.google.com/books" target="_blank" rel="noopener">Google Books API</a>
          using subject-filtered searches, with cover images supplemented from
          <a class="info-link" href="https://openlibrary.org/developers" target="_blank" rel="noopener">Open Library</a>.
          Coverage depends on what publishers have registered with CrossRef and Google Books;
          some journals (notably <em>Perspectives of New Music</em>) have incomplete abstract
          and post-2020 coverage in CrossRef's records.
        </p>
      </div>

      <div class="info-method-block">
        <div class="info-method-title">Cleaning &amp; Normalization</div>
        <p class="info-method-body">
          Raw records are deduplicated by DOI and normalized: author names are parsed from
          varying formats into consistent lists, HTML entities in titles and abstracts are
          decoded, and near-duplicate journal names are merged. A custom normalization
          pipeline then standardises keyword casing, expands common abbreviations
          (e.g. "pc set" → "pitch-class set theory"), merges near-duplicate terms
          using fuzzy string matching, and removes analytically uninformative stand-alone words.
        </p>
      </div>

      <div class="info-method-block">
        <div class="info-method-title">Keyword Extraction <span class="info-ai-badge">AI-assisted</span></div>
        <p class="info-method-body">
          Keywords come from two sources. <strong>Explicit keywords</strong> are author- or
          publisher-supplied terms included in the original CrossRef metadata.
          <strong>Extracted keywords</strong> are generated automatically using
          <a class="info-link" href="https://github.com/MaartenGr/KeyBERT" target="_blank" rel="noopener">KeyBERT</a>,
          a transformer-based keyword extraction library. KeyBERT embeds the text and a
          domain-specific candidate vocabulary into the same vector space and selects the
          candidates most semantically similar to each abstract. For entries that lack
          abstracts, the same model runs on the article title at reduced confidence.
          Extracted keywords are weighted lower than explicit ones throughout the pipeline.
        </p>
      </div>

      <div class="info-method-block">
        <div class="info-method-title">Keyword Weighting</div>
        <p class="info-method-body">
          Each keyword receives a weight between 0 and 1 that reflects how frequently and
          prominently it appears across the corpus. Associations from journal articles count
          more than those from books or chapters. Weights are normalized so that the most
          common keyword in the corpus scores 1.0; the word cloud sizes each term
          proportionally. Keywords below a minimum weight threshold are excluded from the
          cloud to reduce noise.
        </p>
      </div>

    </div>
  `;
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function formatAuthors(rawAuthors) {
  try {
    const list = typeof rawAuthors === 'string'
      ? JSON.parse(rawAuthors) : (rawAuthors || []);
    if (!list.length) return '';
    if (list.length <= 3) return list.join(', ');
    return `${list.slice(0, 3).join(', ')} et al.`;
  } catch { return ''; }
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n).trimEnd() + '…' : s;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function safeTitleHtml(s) {
  return escapeHtml(s).replace(/&lt;(\/?(?:i|em|b|sup|sub))&gt;/gi, '<$1>');
}

function cleanAbstract(s) {
  return s.replace(/^(abstract|summary)[:\s]*/i, '').trimStart();
}

function highlightText(safeHtml, terms) {
  if (!terms.length) return safeHtml;
  const escaped = terms
    .map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .filter(Boolean);
  if (!escaped.length) return safeHtml;
  return safeHtml.replace(
    new RegExp(`(${escaped.join('|')})`, 'gi'),
    '<mark>$1</mark>'
  );
}

// ── Debounce ──────────────────────────────────────────────────────────────────

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// ── Event wiring ──────────────────────────────────────────────────────────────

pagePrev.addEventListener('click', () => { ds.page--; renderPage(); });
pageNext.addEventListener('click', () => { ds.page++; renderPage(); });

drawerTabs.addEventListener('click', e => {
  const btn = e.target.closest('.drawer-tab');
  if (!btn) return;
  setActiveTab(btn.dataset.tab);
});

sortGroup.addEventListener('click', e => {
  const btn = e.target.closest('.sort-btn');
  if (!btn) return;
  setSortBtn(btn.dataset.sort);
  // Re-sort and re-render
  if (ds.mode === 'keyword') {
    applyDrawerFilter();
  } else {
    ds.filtered = sortItems(ds.allItems, ds.sortBy);
    ds.page = 0;
    renderPage();
  }
});

drawerSrchIn.addEventListener('input', debounce(applyDrawerFilter, 200));

document.getElementById('decade-group').addEventListener('click', e => {
  const btn = e.target.closest('.filter-btn');
  if (!btn) return;
  document.querySelectorAll('#decade-group .filter-btn').forEach(b => {
    b.classList.toggle('active', b === btn);
    b.setAttribute('aria-pressed', String(b === btn));
  });
  state.decade = btn.dataset.decade;
  if (drawer.classList.contains('open')) closeDrawer();
  refreshCloud();
  refreshStats();
});

document.getElementById('type-group').addEventListener('click', e => {
  const btn = e.target.closest('.filter-btn');
  if (!btn) return;
  document.querySelectorAll('#type-group .filter-btn').forEach(b => {
    b.classList.toggle('active', b === btn);
    b.setAttribute('aria-pressed', String(b === btn));
  });
  state.type = btn.dataset.type;
  if (drawer.classList.contains('open')) closeDrawer();
  refreshCloud();
  refreshStats();
});

const debouncedSearch = debounce(q => openSearchDrawer(q), 300);

searchInput.addEventListener('input', () => {
  searchClear.hidden = !searchInput.value;
  const q = searchInput.value.trim();
  if (q.length >= 2) {
    debouncedSearch(q);
  } else if (!q && drawer.classList.contains('open') && ds.mode === 'search') {
    closeDrawer();
  }
});

searchClear.addEventListener('click', () => {
  searchInput.value = '';
  searchClear.hidden = true;
  searchInput.focus();
  if (drawer.classList.contains('open') && ds.mode === 'search') closeDrawer();
});

searchForm.addEventListener('submit', e => {
  e.preventDefault();
  const q = searchInput.value.trim();
  if (q) openSearchDrawer(q);
});

document.getElementById('drawer-close').addEventListener('click', closeDrawer);
document.getElementById('drawer-handle').addEventListener('click', closeDrawer);
drawerOverlay.addEventListener('click', closeDrawer);

resultList.addEventListener('click', e => {
  if (e.target.closest('a')) return;
  if (e.target.closest('button')) return;
  const card = e.target.closest('.result-card[data-id]');
  if (!card) return;
  const id = parseInt(card.dataset.id, 10);
  const item = ds.filtered.find(i => i.id === id) || ds.allItems.find(i => i.id === id);
  if (item) openModal(item);
});

modalClose.addEventListener('click', closeModal);
modalOverlay.addEventListener('click', e => {
  if (e.target === modalOverlay) closeModal();
});

trendsToggleBtn.addEventListener('click', () => {
  setView(state.view === 'cloud' ? 'trends' : 'cloud');
});

document.getElementById('info-btn').addEventListener('click', openInfo);
infoClose.addEventListener('click', closeInfo);
infoOverlay.addEventListener('click', e => { if (e.target === infoOverlay) closeInfo(); });

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (infoOverlay.classList.contains('open'))  { closeInfo();   return; }
    if (modalOverlay.classList.contains('open')) { closeModal();  return; }
    if (drawer.classList.contains('open'))        closeDrawer();
  }
});

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.view === 'trends') renderTrendsChart();
    else refreshCloud();
  }, 250);
});

// ── Boot ──────────────────────────────────────────────────────────────────────

refreshStats();
refreshCloud();
