/* Power BI Agentic dashboard — client logic (one agent at a time) */
(() => {
  const $ = id => document.getElementById(id);
  const esc = t => (''+(t==null?'':t)).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

  // Each agent is self-contained: its own file, folder path, Run button and result.
  const AGENTS = [
    {
      agent: 'bpa', icon: '✓', title: 'Best Practice Analyzer',
      desc: 'Scans your model against the Tabular Editor best-practice rule set — naming, DAX, '
          + 'relationships, formatting and performance. Produces a pass/fail report listing the exact '
          + 'offending objects and how to fix each one. BPA always runs the complete rule set.',
      uses: 'a <b>.pbix</b> or <b>.pbip</b> (PBIP/TMDL) model'
    },
    {
      agent: 'unused', icon: '🧹', title: 'Unused Artifacts',
      desc: 'Finds measures, columns, calculated columns/tables, hierarchies and relationships that are '
          + 'not placed on any report visual and not referenced by any other object — your safe-to-delete '
          + 'cleanup list, grouped by type.',
      uses: 'a <b>.pbix</b> or <b>.pbip</b> (PBIP/TMDL) model'
    },
    {
      agent: 'lineage', icon: '🔗', title: 'Data Lineage',
      desc: 'Traces end-to-end dependencies — source → table → column → measure → visual → page — in both '
          + 'directions: upstream (what feeds a field) and downstream (what breaks if you change it). '
          + 'Includes a column-level source map, calculation groups, field parameters and RLS.',
      uses: 'a <b>.pbix</b> or <b>.pbip</b> (PBIP/TMDL) model'
    },
  ];

  // per-agent chosen file (File object), keyed by agent id
  const chosen = {};

  function render() {
    $('agents').innerHTML = AGENTS.map(a => `
      <div class="agent-card" data-agent="${a.agent}">
        <div class="agent-top">
          <span class="agent-ic ${a.agent}">${a.icon}</span>
          <div class="agent-main">
            <h3>${esc(a.title)}</h3>
            <p class="agent-desc">${a.desc}</p>
          </div>
        </div>
        <div class="agent-uses">Works with ${a.uses}.</div>
        <div class="agent-run">
          <label class="browse">
            <input type="file" class="file" accept=".pbix,.pbip,.zip" hidden>
            <span>📂 Browse…</span>
          </label>
          <span class="chosen" title="chosen model">No file chosen</span>
          <button class="btn primary run" type="button">▶ Run</button>
        </div>
        <div class="agent-result"></div>
      </div>`).join('');

    document.querySelectorAll('.agent-card').forEach(card => {
      const agent = card.dataset.agent;
      const fileInput = card.querySelector('.file');
      const chosenLbl = card.querySelector('.chosen');
      fileInput.addEventListener('change', () => {
        chosen[agent] = fileInput.files[0] || null;
        chosenLbl.textContent = chosen[agent] ? chosen[agent].name : 'No file chosen';
        chosenLbl.classList.toggle('has', !!chosen[agent]);
      });
      card.querySelector('.run').addEventListener('click', () => runAgent(agent, false, card));
    });
  }

  const srcLabel = s => s === 'tmdl' ? 'offline · PBIP/TMDL'
    : s === 'launched' ? 'launched Desktop' : s === 'live' ? 'live' : 'done';
  const launchBtn = r => r.canLaunch
    ? `<div style="margin-top:10px"><button class="btn primary launchbtn">▶ Launch Power BI Desktop &amp; run</button>
         <span style="color:var(--muted);font-size:12px;margin-left:8px">opens the .pbix, reads it, then closes</span></div>`
    : '';

  async function runAgent(agent, launch, card) {
    const file = chosen[agent];
    if (!file) {
      flashResult(card, `<div class="result"><span class="pill err">No model</span>
        Browse to a .pbix or .pbip (zip a PBIP project for a fully offline run), then press Run.</div>`);
      return;
    }
    const btn = card.querySelector('.run');
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> ${launch ? 'Launching…' : 'Running…'}`;
    flashResult(card, `<div class="result"><span class="spinner"></span> ${
      launch ? 'Opening the .pbix in Power BI Desktop, waiting for the model to load…' : 'Running agent…'}</div>`);

    const fd = new FormData();
    fd.append('steps', JSON.stringify([{ agent }]));
    fd.append('ruleSet', 'all');
    fd.append('tmdlPath', '');
    fd.append('launch', launch ? '1' : '0');
    fd.append('files', file, file.name);

    try {
      const res = await fetch('/execute', { method: 'POST', body: fd });
      const data = await res.json();
      const r = (data.results || [])[0];
      card.querySelector('.agent-result').innerHTML = '';
      if (r) renderResult(card, r);
      else flashResult(card, '<div class="result">Nothing ran.</div>');
    } catch (e) {
      flashResult(card, `<div class="result"><span class="pill err">Error</span> ${esc(e.message)}</div>`);
    } finally {
      btn.disabled = false; btn.innerHTML = '▶ Run';
    }
  }

  function flashResult(card, html) { card.querySelector('.agent-result').innerHTML = html; }

  function renderResult(card, r) {
    const box = document.createElement('div');
    box.className = 'result';
    if (r.agent === 'bpa' && r.status === 'ok') {
      const c = r.counts || {};
      box.innerHTML = `<h3>${esc(r.title)} <span class="pill ok">done · ${esc(srcLabel(r.source))}</span></h3>
        <div class="kv">
          <span><b>Model:</b> ${esc(r.model)}</span>
          <span><b>Rules:</b> ${r.total}</span>
          <span><b>Passed:</b> ${r.passed}</span>
          <span><b>Failed:</b> ${r.failed}</span>
        </div>
        <div class="kv" style="opacity:.75">
          <span>${c.tables} tables</span><span>${c.columns} columns</span>
          <span>${c.measures} measures</span><span>${c.relationships} relationships</span>
        </div>
        <a class="btn primary" href="${r.viewUrl}" target="_blank">Open report ↗</a>`;
    } else if (r.agent === 'bpa') {
      box.innerHTML = `<h3>${esc(r.title)} <span class="pill bridge">action needed</span></h3>
        <div style="margin-bottom:10px">${esc(r.message)}</div>${launchBtn(r)}`;
    } else if (r.agent === 'unused' && r.status === 'ok') {
      const bt = r.byType || {};
      const chips = Object.keys(bt).map(k => `<span class="pill" style="background:var(--fail-bg);color:var(--fail)">${esc(k)}: ${bt[k].unused}/${bt[k].total}</span>`).join(' ');
      box.innerHTML = `<h3>${esc(r.title)} <span class="pill ok">done · ${esc(srcLabel(r.source))}</span></h3>
        <div class="kv">
          <span><b>Model:</b> ${esc(r.model)}</span>
          <span><b>Scanned:</b> ${r.scanned}</span>
          <span><b>Unused:</b> ${r.unused}</span>
          ${r.pbixParsed ? '' : '<span class="pill bridge">no report layer — visual usage not checked</span>'}
        </div>
        <div class="kv" style="margin-bottom:10px">${chips}</div>
        <a class="btn primary" href="${r.viewUrl}" target="_blank">Open report ↗</a>`;
    } else if (r.agent === 'lineage' && r.status === 'ok') {
      box.innerHTML = `<h3>${esc(r.title)} <span class="pill ok">done · ${esc(srcLabel(r.source))}</span></h3>
        <div class="kv">
          <span><b>Model:</b> ${esc(r.model)}</span>
          <span><b>Nodes:</b> ${r.nodes}</span>
          <span><b>Edges:</b> ${r.edges}</span>
          <span><b>Visuals:</b> ${r.visuals}</span>
          <span><b>Pages:</b> ${r.pages}</span>
          <span><b>Orphans:</b> ${r.orphans}</span>
          ${r.pbixParsed ? '' : '<span class="pill bridge">no report layer — model-only lineage</span>'}
        </div>
        <a class="btn primary" href="${r.viewUrl}" target="_blank">Open lineage explorer ↗</a>`;
    } else {
      const needs = r.status === 'needs-model';
      box.innerHTML = `<h3>${esc(r.title)} <span class="pill ${needs ? 'bridge' : 'err'}">${needs ? 'action needed' : 'skipped'}</span></h3>
        <div>${esc(r.message)}</div>${launchBtn(r)}`;
    }
    card.querySelector('.agent-result').appendChild(box);
    box.querySelectorAll('.launchbtn').forEach(b => b.onclick = () => runAgent(r.agent, true, card));
  }

  render();
})();
