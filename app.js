'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const TZ = 'Europe/London';
const okD = iso => iso && !isNaN(new Date(iso));
const fmtAbs = iso => okD(iso) ? new Intl.DateTimeFormat('en-GB', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }).format(new Date(iso)) : '–';
const fmtDate = iso => okD(iso) ? new Intl.DateTimeFormat('en-GB', { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso)) : '–';
function ago(iso) {
  if (!okD(iso)) return '–';
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 60) return Math.round(s) + 's ago';
  if (s < 3600) return Math.round(s / 60) + 'm ago';
  if (s < 86400) return Math.round(s / 3600) + 'h ago';
  if (s < 86400 * 45) return Math.round(s / 86400) + 'd ago';
  return fmtDate(iso);
}
const I = {
  live: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></svg>',
  repo: '<svg viewBox="0 0 24 24"><path d="M8 7 3 12l5 5M16 7l5 5-5 5M14 4l-4 16"/></svg>',
};

function card(p) {
  if (p.error) return `<article class="card down"><div class="ch"><h3>${esc(p.name)}</h3></div><p class="desc">Status check failed this cycle.</p></article>`;
  const site = p.site, act = p.active, building = act && act.on;
  const cls = building ? 'building' : site && !site.ok ? 'down' : site ? 'ok' : '';
  const b = [];
  if (site) b.push(site.ok ? `<span class="badge ok" title="${site.ms} ms">HTTP ${site.code}</span>` : `<span class="badge bad">${site.code ? 'HTTP ' + site.code : 'Unreachable'}</span>`);
  else b.push('<span class="badge">No public URL</span>');
  if (building) b.push('<span class="badge warn live">Building</span>');
  else if (act) b.push('<span class="badge">Idle</span>');
  b.push(`<span class="badge">${p.private ? 'Private' : 'Public'}</span>`);
  if (p.ahead > 0) b.push(`<span class="badge warn">${p.ahead} unpushed</span>`);

  const kv = [];
  if (p.commit) {
    kv.push(`<dt>Commit</dt><dd>${esc(fmtAbs(p.commit.time))} <small>· ${ago(p.commit.time)}</small></dd>`);
    kv.push(`<dt>Latest</dt><dd><small>${esc(p.commit.hash)}</small> ${esc(p.commit.message)}</dd>`);
  }
  if (act && (act.changed || act.last_edit)) {
    const bits = [];
    if (act.changed) bits.push(`${act.changed} uncommitted`);
    if (act.last_edit) bits.push(`last edit ${ago(act.last_edit)}`);
    kv.push(`<dt>Local</dt><dd>${esc(bits.join(' · '))}${act.files && act.files.length ? `<div class="files">${act.files.map(esc).join(', ')}</div>` : ''}</dd>`);
  }
  if (site) kv.push(`<dt>Ping</dt><dd>${site.ms} ms</dd>`);

  let steps = '';
  if (p.steps && p.steps.length) {
    const nd = p.steps.filter(s => s.state === 'done').length;
    steps = `<div class="phase"><b>${esc(p.current === 'Complete' ? 'Complete' : '▸ ' + p.current)}</b><span>${nd}/${p.steps.length}</span></div>
      <div class="bar"><i style="width:${p.pct}%"></i></div>
      <ul class="steps">${p.steps.map(s => {
        const pr = s.progress, pct = pr && pr.total ? Math.min(100, 100 * pr.done / pr.total) : 0;
        return `<li class="${s.state}"><span class="ico" aria-label="${s.state}"></span><div>${esc(s.name)}${s.note ? `<small>${esc(s.note)}</small>` : ''}${pr ? `<small>${esc(pr.label)}${pr.extra ? ' · ' + esc(pr.extra) : ''}</small><div class="bar"><i style="width:${pct}%"></i></div>` : ''}</div></li>`;
      }).join('')}</ul>`;
  } else if (p.phase) {
    steps = `<div class="phase"><b>${esc(p.phase)}</b></div>`;
  }
  const acts = [];
  if (p.live) acts.push(`<a class="btn" href="${esc(p.live)}" target="_blank" rel="noopener">${I.live}Open live</a>`);
  acts.push(`<a class="btn ghost" href="${esc(p.repo_url)}" target="_blank" rel="noopener">${I.repo}Repo</a>`);
  return `<article class="card ${cls}" id="p-${esc(p.id)}">
    <div><div class="ch"><h3>${esc(p.name)}</h3></div><p class="desc">${esc(p.description)}</p></div>
    <div class="badges">${b.join('')}</div>
    ${steps}
    <dl class="kv">${kv.join('')}</dl>
    <div class="acts ${acts.length === 1 ? 'one' : ''}">${acts.join('')}</div>
  </article>`;
}

function render(d) {
  const ps = d.projects || [];
  const sites = ps.filter(p => p.site), up = sites.filter(p => p.site.ok).length;
  const act = ps.filter(p => p.active && p.active.on).length;
  const all = ps.flatMap(p => p.steps || []), done = all.filter(s => s.state === 'done').length;
  $('#sUp').textContent = `${up}/${sites.length}`; $('#sUp').classList.toggle('bad', up < sites.length);
  $('#sAct').textContent = act;
  $('#sSteps').textContent = `${done}/${all.length}`;
  $('#sBar').style.width = all.length ? (100 * done / all.length) + '%' : '0';
  $('#projects').innerHTML = ps.map(card).join('') || '<div class="empty">No projects configured</div>';
  const rs = d.repos || [];
  $('#repoCount').textContent = rs.length ? `(${rs.length})` : '';
  $('#repos').innerHTML = rs.map(r => {
    const hot = Date.now() - new Date(r.pushed) < 86400e3;
    return `<div class="repo${hot ? ' hot' : ''}"><b>${esc(r.name)}</b><span class="badge ${r.visibility === 'public' ? 'pub' : 'priv'}">${esc(r.visibility)}</span><time datetime="${esc(r.pushed)}" title="${esc(fmtAbs(r.pushed))}">${esc(ago(r.pushed))}</time></div>`;
  }).join('');
  const age = (Date.now() - new Date(d.updated)) / 1000;
  const stale = age > 180;
  $('#sub').textContent = `${ps.length} projects · data ${ago(d.updated)}`;
  $('#sub').classList.toggle('bad', stale);
  const s = $('#stale'); s.hidden = !stale;
  if (stale) s.textContent = `Data is ${ago(d.updated).replace(' ago', '')} old: the generator loop may have stopped.`;
}

let last = null;
async function load() {
  const btn = $('#refresh'); btn.classList.add('busy');
  try {
    const r = await fetch('status.json?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status);
    const j = await r.json();
    if (!Array.isArray(j.projects)) throw new Error('old schema');
    last = j;
    render(last);
  } catch (e) {
    if (last) render(last);
    $('#sub').textContent = 'Offline · retrying'; $('#sub').classList.add('bad');
    if (!last) $('#projects').innerHTML = '<div class="empty">No telemetry yet</div>';
  } finally { setTimeout(() => btn.classList.remove('busy'), 400); }
}
$('#refresh').addEventListener('click', load);
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
load(); setInterval(load, 15000);
if ('serviceWorker' in navigator && location.protocol === 'https:') navigator.serviceWorker.register('sw.js').catch(() => {});
