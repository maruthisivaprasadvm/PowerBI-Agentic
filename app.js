/* Power BI Agentic — online. Runs the Python parsers in-browser via Pyodide.
   Nothing is uploaded: files are read in the page and parsed in WebAssembly. */
(() => {
  const $ = id => document.getElementById(id);
  const esc = t => (''+(t==null?'':t)).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

  const AGENTS = [
    { agent:'lineage', icon:'🔗', cls:'lineage', title:'Data Lineage',
      desc:'Full lineage, source → visual.' },
    { agent:'unused', icon:'🧹', cls:'unused', title:'Unused Artifacts',
      desc:'Unused fields safe to delete.' },
    { agent:'bpa', icon:'✓', cls:'bpa', title:'Best Practice Analyzer',
      desc:'Model checked against best-practice rules.' },
  ];

  let chosen = [];          // [{path, file}]

  /* ---------- theme ---------- */
  (function theme(){
    const r=document.documentElement, b=$('themeToggle');
    const paint=()=>{const d=r.getAttribute('data-theme')==='dark';
      b.querySelector('.ico').textContent=d?'☀️':'🌙'; b.querySelector('.lbl').textContent=d?'Light':'Dark';};
    paint();
    b.onclick=()=>{const n=r.getAttribute('data-theme')==='dark'?'light':'dark';
      r.setAttribute('data-theme',n); try{localStorage.setItem('pbai-theme',n);}catch(e){} paint();};
  })();

  /* ---------- agent cards ---------- */
  $('agents').innerHTML = AGENTS.map(a=>`
    <div class="agent-card" data-agent="${a.agent}">
      <div class="agent-top"><span class="agent-ic ${a.cls}">${a.icon}</span><h3>${esc(a.title)}</h3></div>
      <p class="agent-desc">${a.desc}</p>
      <button class="btn primary run" type="button">▶ Run</button>
      <div class="agent-result"></div>
    </div>`).join('');
  document.querySelectorAll('.agent-card .run').forEach(btn=>{
    btn.onclick=()=>runAgent(btn.closest('.agent-card').dataset.agent);
  });

  /* ---------- file selection ---------- */
  function setChosen(files, label){
    chosen = files;
    // a new model means a fresh start — show only current data, drop any prior results
    document.querySelectorAll('.agent-result').forEach(el=>el.innerHTML='');
    clearStatus();
    const box=$('chosen');
    if(!files.length){ box.hidden=true; return; }
    box.hidden=false;
    const names = files.slice(0,6).map(f=>f.path).join('  ·  ');
    // The agents need the data model (model.tmdl, inside the *.SemanticModel folder).
    // Warn early if the selection has no model — e.g. only the .Report folder was picked.
    const hasModel = files.some(f=>/\.tmdl$/i.test(f.path));
    const warn = hasModel ? '' :
      `<div class="warn">⚠ <b>No data model found in this folder.</b> Pick the
       <b>Power BI Project folder</b> that contains the <b>*.SemanticModel</b> folder
       (the one with <code>model.tmdl</code>). Selecting only the <b>.Report</b> folder won't work.</div>`;
    box.innerHTML = `<b>Selected:</b> ${esc(label)} <span class="pill ok">${files.length} file${files.length!==1?'s':''}</span>
      <div class="files">${esc(names)}${files.length>6?'  … (+'+(files.length-6)+' more)':''}</div>${warn}`;
  }
  const fromInput = list => [...list].map(f=>({path:(f.webkitRelativePath||f.name), file:f}));

  $('pickFolder').onclick=()=>$('folder').click();
  $('folder').onchange=()=>{ const f=fromInput($('folder').files);
    if(f.length) setChosen(f, 'PBIP folder ('+(f[0].path.split('/')[0]||'folder')+')'); };

  const dz=$('drop');
  ['dragenter','dragover'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();dz.classList.add('drag');}));
  ['dragleave','drop'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();dz.classList.remove('drag');}));
  dz.addEventListener('drop',ev=>{
    const files=[...(ev.dataTransfer.files||[])];
    if(files.length){ setChosen(files.map(f=>({path:f.name,file:f})), files.length===1?files[0].name:files.length+' files'); }
  });

  /* ---------- status ---------- */
  function status(html, spin){
    const s=$('status'); s.hidden=false;
    s.innerHTML=(spin?'<span class="spin"></span>':'')+html;
  }
  function clearStatus(){ $('status').hidden=true; }

  /* ---------- Pyodide (lazy, once) ---------- */
  let pyReady=null;
  function ensurePyodide(){
    if(pyReady) return pyReady;
    pyReady=(async()=>{
      status('Loading the Python runtime (first run only, ~10&nbsp;MB)…', true);
      const py=await loadPyodide();
      status('Loading the analysis agents…', true);
      // Parsers/templates/rules are inlined in py-bundle.js (window.PBIP_FILES) and written
      // straight into Pyodide's filesystem — the app never fetches .py files, so corporate
      // proxies that block .py downloads (e.g. Zscaler → HTTP 403) can't break it.
      const files=window.PBIP_FILES;
      if(!files || !Object.keys(files).length){
        throw new Error('Could not load the analysis code (py-bundle.js missing or empty). '
          +'If you are self-hosting, run “python build_web.py” to regenerate it.');
      }
      const enc=new TextEncoder();
      for(const rel of Object.keys(files)){
        const dest='/app/'+rel, dir=dest.slice(0,dest.lastIndexOf('/'));
        py.FS.mkdirTree(dir); py.FS.writeFile(dest, enc.encode(files[rel]));
      }
      py.runPython("import sys\n[sys.path.insert(0,p) for p in ('/app','/app/scripts') if p not in sys.path]");
      return py;
    })();
    return pyReady;
  }

  /* ---------- run ---------- */
  async function runAgent(agent){
    if(!chosen.length){ status('<span class="pill err">No model</span> Choose your PBIP folder or a .zip first.',false); return; }
    document.querySelectorAll('.run').forEach(b=>b.disabled=true);
    try{
      const py=await ensurePyodide();
      status('Reading your project files (in-page, nothing uploaded)…', true);
      // reset the work dir, then write the selected files into Pyodide's in-memory FS
      py.runPython("import shutil,os\nshutil.rmtree('/app/work',ignore_errors=True)\nos.makedirs('/app/work',exist_ok=True)");
      for(const f of chosen){
        const buf=new Uint8Array(await f.file.arrayBuffer());
        const safe=f.path.replace(/\\/g,'/').replace(/^\/+/,'');
        const dest='/app/work/'+safe, dir=dest.slice(0,dest.lastIndexOf('/'));
        py.FS.mkdirTree(dir); py.FS.writeFile(dest, buf);
      }
      status('Running the <b>'+esc(agent)+'</b> agent…', true);
      const pyagent=py.pyimport('pyagent');
      const proxy=pyagent.run(agent,'/app/work');
      const res=proxy.toJs({dict_converter:Object.fromEntries}); proxy.destroy();
      if(res.status==='ok'){ openReport(res.html, res.filename); clearStatus();
        showResult(agent, res); }
      else { status('<span class="pill err">Couldn’t run</span> '+esc(res.message||'Unknown error'), false); }
    }catch(e){
      status('<span class="pill err">Error</span> '+esc(e.message||e), false);
    }finally{
      document.querySelectorAll('.run').forEach(b=>b.disabled=false);
    }
  }

  function showResult(agent, res){
    const card=document.querySelector(`.agent-card[data-agent="${agent}"] .agent-result`);
    if(!card) return;
    const s=res.stats||{};
    let line='';
    if(agent==='lineage') line=`${s.nodes||0} nodes · ${s.edges||0} edges · ${s.visuals||0} visuals`;
    else if(agent==='unused') line=`${s.totalScanned||0} scanned · ${s.totalUnused||0} unused`;
    else if(agent==='bpa') line=`${s.total||0} rules · ${s.passed||0} passed · ${s.failed||0} failed`;
    card.innerHTML=`<div class="rez"><span class="pill ok">done</span> ${esc(line)}
      · <a class="rep" href="#">Open report ↗</a></div>`;
    card.querySelector('.rep').onclick=(ev)=>{ev.preventDefault();openReport(res.html,res.filename);};
  }

  // keep the latest report blob per filename so links reopen without rebuilding
  const blobs={};
  function openReport(html, filename){
    if(blobs[filename]) URL.revokeObjectURL(blobs[filename]);
    const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));
    blobs[filename]=url;
    const w=window.open(url,'_blank');
    if(!w){ // popup blocked — offer a download link in the status
      status(`Report ready — <a href="${url}" download="${esc(filename)}">download ${esc(filename)}</a> (pop-up was blocked).`, false);
    }
  }
})();
