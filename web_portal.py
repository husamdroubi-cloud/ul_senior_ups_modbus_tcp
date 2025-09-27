# web_portal.py — 3-line title + right-aligned logo, light-blue (i) icons, tooltips, Help modal, Ping, auto-build
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Tuple
from pathlib import Path
from pymodbus.client import ModbusTcpClient
from modbus_portal_cli import perform_row, parse_host_port
import json, os

APP_DIR = Path(__file__).resolve().parent
CONF_PATH = APP_DIR / "node_config.json"

# ---- Set your logo URL here (or via env var LOGO_URL) ----
LOGO_URL = os.getenv(
    "LOGO_URL",
    # Update this to a valid image in your repo if you like:
    "https://raw.githubusercontent.com/husamdroubi-cloud/ul_senior_ups_modbus_tcp/main/assets/braeden_logo.png"
)

def _load_node_config() -> Dict[str, str]:
    if CONF_PATH.exists():
        try:
            with CONF_PATH.open("r", encoding="utf-8") as f:
                d = json.load(f)
                name = str(d.get("name", "")).strip() or "UPS Node A"
                role = str(d.get("role", "Master")).strip()
                role = role if role in ("Master", "Slave") else "Master"
                return {"name": name, "role": role}
        except Exception:
            pass
    name = os.getenv("NODE_NAME", "UPS Node A").strip()
    role = os.getenv("NODE_ROLE", "Master").strip()
    role = role if role in ("Master", "Slave") else "Master"
    return {"name": name, "role": role}

def _save_node_config(name: str, role: str) -> bool:
    if os.getenv("CONFIG_MODE") == "env":
        return True
    try:
        with CONF_PATH.open("w", encoding="utf-8") as f:
            json.dump({"name": name, "role": role}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

app = FastAPI(title="Ultra-simple Modbus TCP Portal (Form Mode)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_cfg = _load_node_config()
app.state.node_name = _cfg["name"]
app.state.node_role = _cfg["role"]

INDEX_HTML = rf"""
<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Team 1 High Specification Smart UPS - UL/Braeden</title>
<style>
:root{{color-scheme:light dark}}
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:20px;line-height:1.35}}
header{{margin-bottom:12px;display:flex;align-items:flex-start;justify-content:space-between;gap:12px}}
.brand-left{{display:flex;flex-direction:column;gap:4px;min-width:0}}
.brand-line{{display:inline-block;padding:6px 10px;background:#e8e6ff;border-radius:10px;max-width:100%}}
.brand1{{font-size:18px;font-weight:700}}
.brand2{{font-size:16px;font-weight:600}}
.brand3{{font-size:14px;font-weight:600}}
.brand-right img{{max-height:54px;object-fit:contain}}
.row{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.card{{border:1px solid #ddd;border-radius:12px;padding:10px;margin:10px 0}}
.section{{margin-top:10px}}
label{{display:inline-flex;gap:6px;align-items:center}}
input,select,button{{font-size:14px;padding:3px 6px}}
button.icon{{padding:2px 8px}}
input[type="number"]{{width:6em}}
table{{border-collapse:collapse;border-spacing:0;width:auto;max-width:100%;margin-top:6px;table-layout:auto}}
th,td{{border:1px solid #eee;padding:2px 4px;font-size:13px;vertical-align:top;white-space:nowrap}}
th{{background:#fafafa;text-align:left}}
td input{{width:100%}}
.gridnum{{width:5.5em}}
.ipcell{{width:12em}}
.unitcell{{width:4em}}
.valuecell{{width:10em}}
.notescell{{min-width:64em}}
.notescell input{{width:100%}}
.ok{{color:#0a7a2f;font-weight:600}}
.err{{color:#b00020;font-weight:600}}
.muted{{color:#666;font-size:12px}}
.tabbar{{display:flex;gap:8px;margin:6px 0}}
.tabbar button{{padding:6px 10px;border-radius:8px;border:1px solid #ccc;background:#f5f5f5;cursor:pointer}}
.tabbar button.active{{background:#e8f0ff;border-color:#7aa2ff}}
.hidden{{display:none}}
.badge{{font-size:12px;padding:2px 6px;border:1px solid #ddd;border-radius:999px}}

/* Info (ⓘ) tooltip — light blue filled */
.hint{{position:relative;display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;border:1px solid #7aa2ff;color:#0b3b8c;background:#dbeafe;font-size:12px;cursor:help}}
.hint::before{{content:"ⓘ";line-height:1}}
.hint:hover,.hint.active{{background:#c7dcff;border-color:#5d91ff}}
.hint .tip{{position:absolute;z-index:999;left:50%;transform:translateX(-50%);bottom:125%;min-width:260px;max-width:420px;background:#111;color:#fff;padding:8px 10px;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.2);opacity:0;pointer-events:none;transition:opacity .15s;white-space:pre-wrap}}
.hint .tip a{{color:#9ecbff}}
.hint .tip:after{{content:"";position:absolute;top:100%;left:50%;transform:translateX(-50%);border:7px solid transparent;border-top-color:#111}}
.hint:hover .tip,.hint.active .tip{{opacity:1;pointer-events:auto}}

/* Help modal */
#help-btn{{margin-left:8px}}
#help-modal{{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;align-items:center;justify-content:center;padding:24px;z-index:9999}}
#help-modal.show{{display:flex}}
#help-card{{background:#fff;color:#111;max-width:900px;width:100%;border-radius:12px;box-shadow:0 10px 40px rgba(0,0,0,.4);padding:16px}}
#help-card h3{{margin:0 0 8px 0}}
#help-card .actions{{display:flex;gap:8px;justify-content:flex-end;margin-top:10px}}
#help-card .grid{{display:grid;grid-template-columns:1fr;gap:8px}}
@media (min-width:800px){{#help-card .grid{{grid-template-columns:1fr 1fr}}}}
#help-card .callout{{border-left:4px solid #7aa2ff;background:#eef5ff;padding:8px;border-radius:8px}}

/* Print the help card nicely */
@media print{{
  body *{{visibility:hidden}}
  #help-card, #help-card *{{visibility:visible}}
  #help-card{{position:absolute;inset:auto;left:0;top:0;width:100%;box-shadow:none}}
}}
</style></head><body>

<header>
  <div class="brand-left">
    <div class="brand-line brand1">Team 1 High Specification Smart UPS Senior Project</div>
    <div class="brand-line brand2">ModBus/TCP Polling and Simulation Portal</div>
    <div class="brand-line brand3">University of Louisiana &amp; Braeden Engineering Internship Program</div>
    <div class="muted" style="margin-top:6px">Configure rows for each table, then click <b>Read All</b> or <b>Write All</b>. You may enter classic Modbus reference numbers (Coils 1–, Discrete 10001–, Input 30001–, Holding 40001–). The portal normalizes to <b>0-based</b> before sending.</div>
  </div>
  <div class="brand-right">
    <img src="{LOGO_URL}" alt="Braeden logo" onerror="this.style.display='none'"/>
    <div style="text-align:right;margin-top:6px">
      <button id="help-btn" class="icon" title="Quick setup help">❓ Help</button>
    </div>
  </div>
</header>

<div class="card">
  <div class="row">
    <label>Node Name <input id="node_name" placeholder="e.g. UPS Node A"/></label>
    <span class="hint" tabindex="0"><span class="tip">Human-friendly name for this node. Shown at /node and /node/name.
Examples: “UPS Node A”, “Gateway-01”.</span></span>

    <label>Role
      <select id="node_role"><option>Master</option><option>Slave</option></select>
    </label>
    <span class="hint" tabindex="0"><span class="tip">Master initiates reads/writes. Slave typically exposes values.
You can change at any time; it’s metadata for now.</span></span>
    <span class="muted">(polled at <code>/node</code> &amp; <code>/node/name</code>)</span>
  </div>

  <div class="row">
    <label>Default Device/IP <input id="ip" placeholder="192.168.1.10 or host:port"/></label>
    <span class="hint" tabindex="0"><span class="tip">TCP target for all rows unless a row provides an override.
Use host or host:port (e.g. 192.168.1.21:1502).</span></span>

    <label>Default <span class="badge">Port</span> <input id="port" type="number" min="1" max="65535" value="502" title="For LAN sims use 1502"/></label>
    <span class="hint" tabindex="0"><span class="tip">Modbus/TCP port. Common: 502. Simulators often use 1502.</span></span>

    <label>Default Unit ID <input id="unit_id" type="number" min="0" max="247" value="1"/></label>
    <span class="hint" tabindex="0"><span class="tip">Modbus Unit Identifier (slave ID). For TCP-only devices usually 1.
Through TCP→RTU gateways it’s the RS-485 device ID (1–247).</span></span>

    <label>Timeout (s) <input id="timeout" type="number" step="0.1" min="0.1" value="3.0"/></label>
    <span class="hint" tabindex="0"><span class="tip">Network timeout for each request. Increase on slow links.</span></span>

    <label><input id="dry" type="checkbox" checked/> Dry-run</label>
    <span class="hint" tabindex="0"><span class="tip">If ON, writes are simulated locally (no change on device). Reads still go to the device.</span></span>

    <button id="save-meta">Save Node Meta</button><span id="save-status" class="muted"></span>
    <button id="ping-btn" class="icon" title="Try connecting to Default Device/IP at Default Port">Ping Device</button>
    <span id="ping-status" class="muted"></span>
  </div>

  <div class="row">
    <label><input id="auto" type="checkbox"/> Auto-Read</label>
    <label>every <input id="autoint" type="number" step="0.1" min="0.2" value="2.0" class="gridnum"/> s</label>
    <span class="hint" tabindex="0"><span class="tip">When enabled, the portal triggers “Read All” periodically using the interval above.</span></span>
    <span class="muted">Each row can override IP/Unit. You may also specify <code>host:port</code> in a row’s IP override. The global Port applies if no per-row port is given.</span>
  </div>
</div>

<div class="card">
  <div class="tabbar">
    <button data-tab="coils" class="active">Coils</button>
    <button data-tab="discrete">Discrete Inputs</button>
    <button data-tab="holding">Holding Registers</button>
    <button data-tab="input">Input Registers</button>
  </div>

  <div id="tab-coils" class="section">
    <div class="row">
      <label>Rows <input class="gridnum" id="coils-rows" type="number" min="1" value="8"/></label>
      <label>Base address <input class="gridnum" id="coils-base" type="number" min="0" value="1"/></label>
      <label>Mode
        <select id="coils-mode">
          <option value="read_coils">Read Coils</option>
          <option value="write_single">Write Single Coil (0/1)</option>
          <option value="write_multi">Write Multiple Coils (comma/semicolon list)</option>
        </select>
      </label>
      <span class="hint" tabindex="0"><span class="tip">Classic coil addresses start at 1.
For multi-write put values like “1,0,1”.</span></span>
      <button id="coils-build">Build Table</button>
    </div>
    <table id="coils-table"></table>
  </div>

  <div id="tab-discrete" class="section hidden">
    <div class="row">
      <label>Rows <input class="gridnum" id="discrete-rows" type="number" min="1" value="8"/></label>
      <label>Base address <input class="gridnum" id="discrete-base" type="number" min="0" value="10001"/></label>
      <span class="hint" tabindex="0"><span class="tip">Discrete inputs are read-only bits. Classic references start at 10001.</span></span>
      <button id="discrete-build">Build Table</button>
    </div>
    <table id="discrete-table"></table>
  </div>

  <div id="tab-holding" class="section hidden">
    <div class="row">
      <label>Rows <input class="gridnum" id="holding-rows" type="number" min="1" value="4"/></label>
      <label>Base address <input class="gridnum" id="holding-base" type="number" min="0" value="40001"/></label>
      <label>Mode
        <select id="holding-mode">
          <option value="read_holding">Read Holding</option>
          <option value="write_single">Write Single Reg</option>
          <option value="write_multi">Write Multiple Regs</option>
        </select>
      </label>
      <label>Datatype
        <select id="holding-dt"><option>int16</option><option>uint16</option><option>int32</option><option>float32</option></select>
      </label>
      <label>Endianness
        <select id="holding-endian"><option>ABCD</option><option>BADC</option><option>CDAB</option><option>DCBA</option></select>
      </label>
      <label>Scale <input id="holding-scale" class="gridnum" type="number" step="0.01" value="1.0"/></label>
      <span class="hint" tabindex="0"><span class="tip">Use int32/float32 for two-register values. Endianness controls word/byte order.
Scale lets you store raw units (e.g., *10) but display engineering units.</span></span>
      <button id="holding-build">Build Table</button>
    </div>
    <table id="holding-table"></table>
  </div>

  <div id="tab-input" class="section hidden">
    <div class="row">
      <label>Rows <input class="gridnum" id="input-rows" type="number" min="1" value="4"/></label>
      <label>Base address <input class="gridnum" id="input-base" type="number" min="0" value="30001"/></label>
      <label>Datatype
        <select id="input-dt"><option>int16</option><option>uint16</option><option>int32</option><option>float32</option></select>
      </label>
      <label>Endianness
        <select id="input-endian"><option>ABCD</option><option>BADC</option><option>CDAB</option><option>DCBA</option></select>
      </label>
      <label>Scale <input id="input-scale" class="gridnum" type="number" step="0.01" value="1.0"/></label>
      <span class="hint" tabindex="0"><span class="tip">Input registers are read-only words. Choose datatype/endianness to match the device map.</span></span>
      <button id="input-build">Build Table</button>
    </div>
    <table id="input-table"></table>
  </div>

  <div class="section">
    <div class="row">
      <button id="read-btn">Read All</button>
      <button id="write-btn">Write All</button>
      <a id="download" href="#" download="results.csv" style="display:none">Download results.csv</a>
    </div>
    <div id="status" class="muted"></div>
  </div>
</div>

<!-- HELP MODAL -->
<div id="help-modal" aria-hidden="true">
  <div id="help-card" role="dialog" aria-modal="true" aria-labelledby="help-title">
    <h3 id="help-title">Quick Setup: 2 Nodes (Master / Slave)</h3>
    <div class="grid">
      <div class="callout">
        <b>Node A (Master)</b>
        <ul>
          <li>Role: Master, Node Name: “UPS Node A”</li>
          <li>Default Device/IP: <i>Node B</i> IP (e.g., 192.168.1.21), Port: 1502 (sim) or 502</li>
          <li>Default Unit ID: 1</li>
          <li>Coils/Holding: choose modes, enter addresses/values</li>
          <li>Uncheck Dry-run to perform actual writes</li>
        </ul>
      </div>
      <div class="callout">
        <b>Node B (Slave)</b>
        <ul>
          <li>Role: Slave, Node Name: “UPS Node B”</li>
          <li>Run a Modbus server/simulator on B (listen on 1502/502)</li>
          <li>Use the same map (addresses, datatypes) you expect the master to read</li>
          <li>Optionally enable Auto-Read on B for monitoring</li>
        </ul>
      </div>
      <div class="callout">
        <b>Gateway (TCP → RTU) case</b>
        <ul>
          <li>Default Device/IP: gateway IP; Port: gateway’s Modbus/TCP port</li>
          <li>Set per-row <b>Unit</b> = RS-485 slave ID (1–247)</li>
          <li>Leave IP override blank unless a row targets a different device/port</li>
        </ul>
      </div>
      <div class="callout">
        <b>Tips</b>
        <ul>
          <li>Use <b>Ping Device</b> to verify TCP reachability</li>
          <li>Classic references (40001, 30001, …) are normalized to 0-based automatically</li>
          <li>Endianness: ABCD (no swap), CDAB (word swap), BADC/DCBA (byte swaps)</li>
        </ul>
      </div>
    </div>
    <div class="actions">
      <button id="help-print">🖨️ Print</button>
      <button id="help-close">Close</button>
    </div>
  </div>
</div>

<div id="results" class="card" style="display:none"></div>

<script>
(function(){
  // Tabs
  const tabBtns=document.querySelectorAll('.tabbar button');
  const tabs={coils:document.getElementById('tab-coils'),discrete:document.getElementById('tab-discrete'),holding:document.getElementById('tab-holding'),input:document.getElementById('tab-input')};
  tabBtns.forEach(b=>b.addEventListener('click',()=>{tabBtns.forEach(x=>x.classList.remove('active'));b.classList.add('active');const k=b.dataset.tab;Object.keys(tabs).forEach(t=>tabs[t].classList.toggle('hidden',t!==k));}));

  // Hints: click-to-toggle (mobile friendly)
  document.body.addEventListener('click',e=>{
    const isHint=e.target.classList.contains('hint')?e.target:(e.target.closest('.hint'));
    document.querySelectorAll('.hint.active').forEach(h=>{if(h!==isHint)h.classList.remove('active');});
    if(isHint){isHint.classList.toggle('active');}
  });

  // Help modal
  const helpModal=document.getElementById('help-modal');
  document.getElementById('help-btn').onclick=()=>{helpModal.classList.add('show');helpModal.setAttribute('aria-hidden','false');};
  document.getElementById('help-close').onclick=()=>{helpModal.classList.remove('show');helpModal.setAttribute('aria-hidden','true');};
  helpModal.addEventListener('click',e=>{if(e.target===helpModal){helpModal.classList.remove('show');helpModal.setAttribute('aria-hidden','true');}});
  document.getElementById('help-print').onclick=()=>{window.print();};

  const escCsv=s=>'"'+String(s??'').replace(/"/g,'""')+'"';
  const escHtml=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  // Table builders
  function buildTable(table,base,rows,includeValue,includeDatatypeNotes=false){
    table.innerHTML='';
    const thead=document.createElement('thead');
    let head='<tr><th>#</th><th class="ipcell">IP (override) <span class="hint"><span class="tip">Optional: host or host:port per row. If blank, uses Default Device/IP (+ Port).</span></span></th><th class="unitcell">Unit <span class="hint"><span class="tip">Modbus Unit ID. Leave blank to use Default Unit ID.</span></span></th><th>Address</th>';
    if(includeDatatypeNotes) head+='<th class="valuecell">Value (int/float or comma list)</th>';
    else if(includeValue) head+='<th class="valuecell">Value</th>';
    head+='<th class="notescell">Notes</th></tr>';
    thead.innerHTML=head; table.appendChild(thead);
    const tbody=document.createElement('tbody');
    for(let i=0;i<rows;i++){
      const tr=document.createElement('tr');
      tr.innerHTML=`<td>${i+1}</td>
        <td><input class="ipcell" placeholder="e.g. 192.168.1.21 or 192.168.1.21:1502"></td>
        <td><input type="number" min="0" max="247" class="unitcell"></td>
        <td><input type="number" min="0" value="${base+i}" class="gridnum"></td>
        ${includeValue?'<td class="valuecell"><input></td>':''}
        ${includeDatatypeNotes?(!includeValue?'<td class="valuecell"><input></td>':''):''}
        <td class="notescell"><input placeholder="free text notes..."></td>`;
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
  }

  const coilsBuild=()=>{const inc=document.getElementById('coils-mode').value!=='read_coils';buildTable(document.getElementById('coils-table'),Number(document.getElementById('coils-base').value),Number(document.getElementById('coils-rows').value),inc,false);};
  const discreteBuild=()=>{buildTable(document.getElementById('discrete-table'),Number(document.getElementById('discrete-base').value),Number(document.getElementById('discrete-rows').value),false,false);};
  const holdingBuild=()=>{const inc=document.getElementById('holding-mode').value!=='read_holding';buildTable(document.getElementById('holding-table'),Number(document.getElementById('holding-base').value),Number(document.getElementById('holding-rows').value),inc,true);};
  const inputBuild=()=>{buildTable(document.getElementById('input-table'),Number(document.getElementById('input-base').value),Number(document.getElementById('input-rows').value),false,true);};

  document.getElementById('coils-build').onclick=coilsBuild;
  document.getElementById('discrete-build').onclick=discreteBuild;
  document.getElementById('holding-build').onclick=holdingBuild;
  document.getElementById('input-build').onclick=inputBuild;

  // Auto-build on load
  coilsBuild(); discreteBuild(); holdingBuild(); inputBuild();

  // Auto-rebuild when controls change
  function rebuildOnChange(ids, buildFn){
    ids.forEach(id=>{const el=document.getElementById(id); if(el){ el.addEventListener('change', buildFn); }});
  }
  rebuildOnChange(['coils-rows','coils-base','coils-mode'], coilsBuild);
  rebuildOnChange(['discrete-rows','discrete-base'], discreteBuild);
  rebuildOnChange(['holding-rows','holding-base','holding-mode','holding-dt','holding-endian','holding-scale'], holdingBuild);
  rebuildOnChange(['input-rows','input-base','input-dt','input-endian','input-scale'], inputBuild);

  function rowsFromTable(tableEl){
    const rows=[]; tableEl.querySelectorAll('tbody tr').forEach(tr=>{
      const tds=tr.querySelectorAll('td');
      const ip=tds[1].querySelector('input')?.value??''; const unit=tds[2].querySelector('input')?.value??''; const addr=tds[3].querySelector('input')?.value??'';
      let idx=4, value=''; if(tds[idx]&&tds[idx].querySelector('input')){value=tds[idx].querySelector('input').value; idx++;}
      const notes=(tds[idx]&&tds[idx].querySelector('input'))?tds[idx].querySelector('input').value:'';
      rows.push({ip:ip.trim(),unit_id:unit===''?'':Number(unit),address:addr===''?'':Number(addr),value:value??'',notes});
    }); return rows;
  }

  function refToZeroBased(kind,addr){
    if(addr===''||isNaN(addr)) return addr; const a=Number(addr);
    if(kind==='coils')return a>=1?a-1:a;
    if(kind==='discrete')return a>=10001?a-10001:a;
    if(kind==='input')return a>=30001?a-30001:a;
    if(kind==='holding')return a>=40001?a-40001:a;
    return a;
  }

  // Node meta + settings
  const node_name=document.getElementById('node_name'), node_role=document.getElementById('node_role'), save_status=document.getElementById('save-status');
  const ip_default=document.getElementById('ip'), port=document.getElementById('port'), unit_id=document.getElementById('unit_id'), timeout=document.getElementById('timeout'), dry=document.getElementById('dry');
  const auto=document.getElementById('auto'), autoint=document.getElementById('autoint');
  const ping_btn=document.getElementById('ping-btn'), ping_status=document.getElementById('ping-status');

  const LS_NAME='ups_node_name', LS_ROLE='ups_node_role', LS_AUTO='ups_auto_on', LS_AUTOS='ups_auto_secs', LS_PORT='ups_default_port';

  async function loadNodeMeta(){
    try{{const r=await fetch('/node'); if(r.ok){{const j=await r.json(); node_name.value=j.name??''; node_role.value=j.role??'Master';}}}}catch(_){}
    const rn=localStorage.getItem(LS_NAME), rr=localStorage.getItem(LS_ROLE);
    if(rn) node_name.value=rn; if(rr==='Master'||rr==='Slave') node_role.value=rr;
    const savedPort=localStorage.getItem(LS_PORT); if(savedPort && !isNaN(savedPort)) port.value=Number(savedPort);
    const on=localStorage.getItem(LS_AUTO)==='1'; auto.checked=on; const secs=parseFloat(localStorage.getItem(LS_AUTOS)||'2'); if(!isNaN(secs)) autoint.value=secs.toString();
  }
  loadNodeMeta();

  document.getElementById('save-meta').onclick=async ()=>{
    const nn=node_name.value.trim(), rl=node_role.value; save_status.textContent='Saving...';
    localStorage.setItem(LS_NAME, nn); localStorage.setItem(LS_ROLE, rl);
    try{{const r=await fetch('/config',{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name:nn,role:rl}})}); save_status.textContent=r.ok?'Saved':'Save failed';}}
    catch(_){save_status.textContent='Save failed';} setTimeout(()=>save_status.textContent='',1500);
  };

  function saveDefaultPort(){ const p=parseInt(port.value,10); if(!isNaN(p)) localStorage.setItem(LS_PORT,String(p)); }
  port.addEventListener('change',saveDefaultPort);

  // Auto-Read
  let autoTimer=null;
  function startAuto(){ stopAuto(); const secs=Math.max(0.2,parseFloat(autoint.value)||2); autoTimer=setInterval(()=>read_btn.click(), secs*1000); localStorage.setItem(LS_AUTO,'1'); localStorage.setItem(LS_AUTOS,String(secs)); }
  function stopAuto(){ if(autoTimer){clearInterval(autoTimer); autoTimer=null;} localStorage.setItem(LS_AUTO,'0'); }
  auto.addEventListener('change',()=>{ if(auto.checked) startAuto(); else stopAuto(); });
  autoint.addEventListener('change',()=>{ if(auto.checked) startAuto(); });

  // Ping Device
  async function pingDevice(){
    const ip=(ip_default.value||'').trim();
    const p=parseInt(port.value,10)||502;
    const tmo=Math.max(0.2,parseFloat(timeout.value)||3.0);
    ping_status.textContent=' Pinging...';
    try{
      const r=await fetch('/ping',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip,port:p,timeout:tmo})});
      const j=await r.json();
      if(j.ok) ping_status.innerHTML=` <span class="ok">OK</span> (${j.host}:${j.port})`;
      else ping_status.innerHTML=` <span class="err">FAIL</span> (${j.host}:${j.port}) ${j.error||''}`;
    }catch(e){ ping_status.innerHTML=` <span class="err">FAIL</span> ${e}`; }
    setTimeout(()=>ping_status.textContent='',4000);
  }
  ping_btn.onclick=pingDevice;

  // Build ops payload for /run
  function normalizeHostPort(raw, defPort){ if(!raw) return ''; return raw.includes(':')?raw:String(raw)+':'+String(defPort); }

  function buildOps(which){
    const def_ip=(ip_default.value||'').trim();
    const def_port=parseInt(port.value,10)||502;
    const def_unit=Number(unit_id.value);
    const tmo=Number(timeout.value);
    const isDry=dry.checked;
    const nodeName=node_name.value.trim(), nodeRole=node_role.value;
    const ops=[];

    const coilsMode=document.getElementById('coils-mode').value;
    rowsFromTable(document.getElementById('coils-table')).forEach(r=>{
      if(r.address==='')return;
      const addr0=refToZeroBased('coils',r.address);
      const isW=(coilsMode!=='read_coils'); if((which==='read'&&isW)||(which==='write'&&!isW))return;
      const raw=r.ip||def_ip; const ip=normalizeHostPort(raw, def_port); const unit=(r.unit_id===''?def_unit:r.unit_id);
      ops.push({node_name:nodeName,node_role:nodeRole,device:"COILS",ip,unit_id:unit,function:coilsMode,address:addr0,count:1,datatype:"bool",rw:isW?"W":"R",scale:1.0,endianness:"",value:isW?(coilsMode==='write_single'?(r.value||'0').trim():(r.value||'').trim()):"",notes:r.notes||""});
    });

    rowsFromTable(document.getElementById('discrete-table')).forEach(r=>{
      if(r.address===''||which==='write')return;
      const addr0=refToZeroBased('discrete',r.address);
      const raw=r.ip||def_ip; const ip=normalizeHostPort(raw, def_port); const unit=(r.unit_id===''?def_unit:r.unit_id);
      ops.push({node_name:nodeName,node_role:nodeRole,device:"DISCRETE",ip,unit_id:unit,function:"read_discrete",address:addr0,count:1,datatype:"bool",rw:"R",scale:1.0,endianness:"",value:"",notes:r.notes||""});
    });

    const hMode=document.getElementById('holding-mode').value, hDT=document.getElementById('holding-dt').value, hEnd=document.getElementById('holding-endian').value, hScale=Number(document.getElementById('holding-scale').value);
    const hCount=(hDT==="int32"||hDT==="float32")?2:1; const hW=(hMode!=="read_holding");
    rowsFromTable(document.getElementById('holding-table')).forEach(r=>{
      if(r.address==='')return;
      if((which==='read'&&hW)||(which==='write'&&!hW))return;
      const addr0=refToZeroBased('holding',r.address);
      const raw=r.ip||def_ip; const ip=normalizeHostPort(raw, def_port); const unit=(r.unit_id===''?def_unit:r.unit_id);
      ops.push({node_name:nodeName,node_role:nodeRole,device:"HOLDING",ip,unit_id:unit,function:hMode,address:addr0,count:hCount,datatype:hDT,rw:hW?"W":"R",scale:hScale,endianness:hEnd,value:hW?(r.value||'').trim():"",notes:r.notes||""});
    });

    const iDT=document.getElementById('input-dt').value, iEnd=document.getElementById('input-endian').value, iScale=Number(document.getElementById('input-scale').value);
    const iCount=(iDT==="int32"||iDT==="float32")?2:1;
    rowsFromTable(document.getElementById('input-table')).forEach(r=>{
      if(r.address===''||which==='write')return;
      const addr0=refToZeroBased('input',r.address);
      const raw=r.ip||def_ip; const ip=normalizeHostPort(raw, def_port); const unit=(r.unit_id===''?def_unit:r.unit_id);
      ops.push({node_name:nodeName,node_role:nodeRole,device:"INPUT",ip,unit_id:unit,function:"read_input",address:addr0,count:iCount,datatype:iDT,rw:"R",scale:iScale,endianness:iEnd,value:"",notes:r.notes||""});
    });

    return {{ops:ops, timeout:tmo, dry:isDry, node:{{name:nodeName, role:nodeRole}}}};
  }

  function renderResults(columns,rows){
    const div=document.getElementById('results'); div.style.display='block';
    let html='<h3>Results</h3><div class="muted">Rows: '+rows.length+'</div><div style="max-height:60vh;overflow:auto"><table><thead><tr>'+columns.map(c=>'<th>'+escHtml(c)+'</th>').join('')+'</tr></thead><tbody>';
    for(const r of rows){ html+='<tr>'+columns.map(c=>{const v=r[c];const cls=(c.toLowerCase()==='ok')?(v?'ok':'err'):'';const t=(typeof v==='object')?escHtml(JSON.stringify(v)):escHtml(v);return '<td class="'+cls+'">'+t+'</td>';}).join('')+'</tr>'; }
    html+='</tbody></table></div>'; div.innerHTML=html;
    const hdr=columns.map(escCsv).join(','), body=rows.map(row=>columns.map(c=>escCsv(typeof row[c]==='object'?JSON.stringify(row[c]):(row[c]??''))).join(',')).join('\n');
    const blob=new Blob([hdr+'\n'+body],{{type:'text/csv'}}), url=URL.createObjectURL(blob); const a=document.getElementById('download'); a.href=url; a.style.display='inline-block';
  }

  async function postOps(which){
    const payload=buildOps(which); const status=document.getElementById('status'); status.textContent=(which==='read'?'Reading ':'Writing ')+payload.ops.length+' operations...';
    try{{const resp=await fetch('/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload),credentials:'same-origin'}}); if(!resp.ok){{const t=await resp.text().catch(()=> ''); throw new Error('HTTP '+resp.status+' '+(t||''));}} const data=await resp.json(); renderResults(data.columns||[],data.rows||[]); status.textContent='Done.';}}
    catch(err){{status.textContent='Error: '+(err?.message||err);}}
  }
  const read_btn=document.getElementById('read-btn'); const write_btn=document.getElementById('write-btn');
  read_btn.onclick=()=>postOps('read');
  write_btn.onclick=()=>postOps('write');
})();
</script></body></html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/node")
async def get_node():
    return {"name": app.state.node_name, "role": app.state.node_role}

@app.get("/node/name", response_class=PlainTextResponse)
async def get_node_name():
    return app.state.node_name

@app.post("/config")
async def set_node_config(req: Request):
    data = await req.json()
    name = (data.get("name") or "").strip() or app.state.node_name
    role = (data.get("role") or app.state.node_role).strip()
    if role not in ("Master", "Slave"):
        raise HTTPException(status_code=400, detail="role must be 'Master' or 'Slave'")
    app.state.node_name = name
    app.state.node_role = role
    _save_node_config(app.state.node_name, app.state.node_role)
    return {"ok": True, "name": app.state.node_name, "role": app.state.node_role}

@app.post("/ping")
async def ping_device(req: Request):
    data = await req.json()
    ip = str(data.get("ip", "")).strip()
    default_port = int(data.get("port", 502))
    timeout = float(data.get("timeout", 1.5))
    host, port = parse_host_port(ip or "127.0.0.1", default_port=default_port)

    ok = False
    err = ""
    client = ModbusTcpClient(host=host, port=port, timeout=timeout)
    try:
        ok = client.connect()
        if not ok:
            err = "connect failed"
    except Exception as e:
        ok = False
        err = f"{type(e).__name__}: {e}"
    finally:
        try:
            client.close()
        except Exception:
            pass
    return {"ok": ok, "host": host, "port": port, "timeout": timeout, "error": err}

@app.post("/run")
async def run_mapping(request: Request):
    payload = await request.json()
    rows: List[Dict[str, Any]] = payload.get("rows") or []
    timeout = float(payload.get("timeout", 3.0))
    dry = bool(payload.get("dry", False))
    node = payload.get("node") or {}
    maybe_name = (node.get("name") or "").strip()
    maybe_role = (node.get("role") or "").strip()
    changed = False
    if maybe_name:
        app.state.node_name = maybe_name
        changed = True
    if maybe_role in ("Master", "Slave"):
        app.state.node_role = maybe_role
        changed = True
    if changed:
        _save_node_config(app.state.node_name, app.state.node_role)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="No rows provided")

    clients: Dict[Tuple[str, float], ModbusTcpClient] = {}
    results: List[Dict[str, Any]] = []
    try:
        for r in rows:
            norm = {
                "node_name": r.get("node_name", app.state.node_name),
                "node_role": r.get("node_role", app.state.node_role),
                "device": r.get("device", ""), "ip": r.get("ip", ""), "unit_id": r.get("unit_id", 1),
                "function": r.get("function", ""), "address": r.get("address", 0), "count": r.get("count", 1),
                "datatype": r.get("datatype", "int16"), "rw": r.get("rw", "R"), "scale": r.get("scale", 1.0),
                "endianness": r.get("endianness", "ABCD"), "value": r.get("value", ""), "notes": r.get("notes", "")
            }
            res = perform_row(norm, clients, timeout=timeout, dry=dry)
            results.append({**norm, **res})
    finally:
        for c in list(clients.values()):
            try: c.close()
            except Exception: pass

    columns = sorted({k for r in results for k in r.keys()})
    return {"columns": columns, "rows": results}
