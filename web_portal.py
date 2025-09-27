# web_portal.py — Compact UI, wide Notes, reference defaults, 0-based normalization
# + Node metadata persistence (JSON file with env fallback) + polling endpoints.
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Tuple
from pymodbus.client import ModbusTcpClient
from modbus_portal_cli import perform_row
from pathlib import Path
import json
import os

APP_DIR = Path(__file__).resolve().parent
CONF_PATH = APP_DIR / "node_config.json"

def _load_node_config() -> Dict[str, str]:
    # 1) file
    if CONF_PATH.exists():
        try:
            with CONF_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
                name = str(data.get("name", "")).strip()
                role = str(data.get("role", "Master")).strip()
                if role not in ("Master", "Slave"):
                    role = "Master"
                return {"name": name or "UPS Node A", "role": role}
        except Exception:
            pass
    # 2) env
    name = os.getenv("NODE_NAME", "UPS Node A").strip()
    role = os.getenv("NODE_ROLE", "Master").strip()
    role = role if role in ("Master", "Slave") else "Master"
    return {"name": name, "role": role}

def _save_node_config(name: str, role: str) -> bool:
    try:
        with CONF_PATH.open("w", encoding="utf-8") as f:
            json.dump({"name": name, "role": role}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

app = FastAPI(title="Ultra-simple Modbus TCP Portal (Form Mode)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Node metadata (persisted)
cfg = _load_node_config()
app.state.node_name = cfg["name"]
app.state.node_role = cfg["role"]

INDEX_HTML = r"""
<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>Team 1 High Specification Smart UPS - UL/Braeden</title>
<style>
:root{color-scheme:light dark}
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:20px;line-height:1.35}
header{margin-bottom:12px}
h2{margin:0 0 4px 0;padding:6px 10px;background:#e8e6ff;border-radius:10px;display:inline-block}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.card{border:1px solid #ddd;border-radius:12px;padding:10px;margin:10px 0}
.section{margin-top:10px}
label{display:inline-flex;gap:6px;align-items:center}
input,select,button{font-size:14px;padding:3px 6px}
input[type="number"]{width:6em}

/* TABLE — compact */
table{border-collapse:collapse;border-spacing:0;width:auto;max-width:100%;margin-top:6px;table-layout:auto}
th,td{border:1px solid #eee;padding:2px 4px;font-size:13px;vertical-align:top;white-space:nowrap}
th{background:#fafafa;text-align:left}
td input{width:100%}

/* Column sizing */
.gridnum{width:5.5em}
.ipcell{width:9em}
.unitcell{width:4em}
.valuecell{width:10em}
.notescell{min-width:64em}
.notescell input{width:100%}

.ok{color:#0a7a2f;font-weight:600}
.err{color:#b00020;font-weight:600}
.muted{color:#666;font-size:12px}
.tabbar{display:flex;gap:8px;margin:6px 0}
.tabbar button{padding:6px 10px;border-radius:8px;border:1px solid #ccc;background:#f5f5f5;cursor:pointer}
.tabbar button.active{background:#e8f0ff;border-color:#7aa2ff}
.hidden{display:none}
</style></head><body>
<header>
  <h2>Team 1 High Specification Smart UPS - UL/Braeden</h2>
  <div class="muted">Configure rows for each table, then click <b>Read All</b> or <b>Write All</b>.<br/>You may enter classic Modbus reference numbers (Coils 1-…, Discrete 10001-…, Input 30001-…, Holding 40001-…). The portal automatically normalizes to <b>0-based</b> before sending to the device.</div>
</header>

<div class="card">
  <div class="row">
    <label>Node Name <input id="node_name" placeholder="e.g. UPS Node A"/></label>
    <label>Role
      <select id="node_role">
        <option>Master</option>
        <option>Slave</option>
      </select>
    </label>
    <span class="muted">(polled at <code>/node</code> &amp; <code>/node/name</code>)</span>
  </div>
  <div class="row">
    <label>Default Device/IP <input id="ip" placeholder="192.168.1.10"/></label>
    <label>Default Unit ID <input id="unit_id" type="number" min="0" max="247" value="1"/></label>
    <label>Timeout (s) <input id="timeout" type="number" step="0.1" min="0.1" value="3.0"/></label>
    <label><input id="dry" type="checkbox" checked/> Dry-run</label>
    <button id="save-meta">Save Node Meta</button>
    <span id="save-status" class="muted"></span>
  </div>
  <div class="muted">Each row can override IP/Unit. Leave blank to use defaults above.</div>
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
      <button id="coils-build">Build Table</button>
    </div>
    <table id="coils-table"></table>
    <div class="muted">For writes, put values in the <b>Value</b> column. For multi write, provide 0/1 values like <code>1,0,1</code>.</div>
  </div>

  <div id="tab-discrete" class="section hidden">
    <div class="row">
      <label>Rows <input class="gridnum" id="discrete-rows" type="number" min="1" value="8"/></label>
      <label>Base address <input class="gridnum" id="discrete-base" type="number" min="0" value="10001"/></label>
      <button id="discrete-build">Build Table</button>
    </div>
    <table id="discrete-table"></table>
    <div class="muted">Discrete inputs are read-only (bits).</div>
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
      <button id="holding-build">Build Table</button>
    </div>
    <table id="holding-table"></table>
    <div class="muted">For 32-bit types, two registers are consumed per row.</div>
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

<div id="results" class="card" style="display:none"></div>

<script>
(function(){
  // Tabs
  const tabBtns=document.querySelectorAll('.tabbar button');
  const tabs={coils:document.getElementById('tab-coils'),discrete:document.getElementById('tab-discrete'),holding:document.getElementById('tab-holding'),input:document.getElementById('tab-input')};
  tabBtns.forEach(b=>b.addEventListener('click',()=>{tabBtns.forEach(x=>x.classList.remove('active'));b.classList.add('active');const k=b.dataset.tab;Object.keys(tabs).forEach(t=>tabs[t].classList.toggle('hidden',t!==k));}));
  const escCsv=s=>'"'+String(s??'').replace(/"/g,'""')+'"'; const escHtml=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  // Build grid
  function buildTable(table,base,rows,includeValue,includeDatatypeNotes=false){
    table.innerHTML='';
    const thead=document.createElement('thead');
    let head='<tr><th>#</th><th class="ipcell">IP (override)</th><th class="unitcell">Unit</th><th>Address</th>';
    if(includeDatatypeNotes) head+='<th class="valuecell">Value (int/float or comma list)</th>';
    else if(includeValue) head+='<th class="valuecell">Value</th>';
    head+='<th class="notescell">Notes</th></tr>';
    thead.innerHTML=head; table.appendChild(thead);
    const tbody=document.createElement('tbody');
    for(let i=0;i<rows;i++){
      const tr=document.createElement('tr');
      tr.innerHTML=`<td>${i+1}</td>
        <td><input class="ipcell"></td>
        <td><input type="number" min="0" max="247" class="unitcell"></td>
        <td><input type="number" min="0" value="${base+i}" class="gridnum"></td>
        ${includeValue?'<td class="valuecell"><input></td>':''}
        ${includeDatatypeNotes?(!includeValue?'<td class="valuecell"><input></td>':''):''}
        <td class="notescell"><input placeholder="free text notes..."></td>`;
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
  }

  // Build buttons
  document.getElementById('coils-build').onclick=()=>{const inc=document.getElementById('coils-mode').value!=='read_coils';buildTable(document.getElementById('coils-table'),Number(document.getElementById('coils-base').value),Number(document.getElementById('coils-rows').value),inc,false);};
  document.getElementById('discrete-build').onclick=()=>{buildTable(document.getElementById('discrete-table'),Number(document.getElementById('discrete-base').value),Number(document.getElementById('discrete-rows').value),false,false);};
  document.getElementById('holding-build').onclick=()=>{const inc=document.getElementById('holding-mode').value!=='read_holding';buildTable(document.getElementById('holding-table'),Number(document.getElementById('holding-base').value),Number(document.getElementById('holding-rows').value),inc,true);};
  document.getElementById('input-build').onclick=()=>{buildTable(document.getElementById('input-table'),Number(document.getElementById('input-base').value),Number(document.getElementById('input-rows').value),false,true);};
  document.getElementById('coils-build').click();document.getElementById('discrete-build').click();document.getElementById('holding-build').click();document.getElementById('input-build').click();

  // Helpers
  function rowsFromTable(tableEl){
    const rows=[]; const trs=tableEl.querySelectorAll('tbody tr');
    trs.forEach(tr=>{
      const tds=tr.querySelectorAll('td');
      const ip=tds[1].querySelector('input')?.value??''; const unit=tds[2].querySelector('input')?.value??''; const addr=tds[3].querySelector('input')?.value??'';
      let idx=4, value=''; if(tds[idx]&&tds[idx].querySelector('input')){value=tds[idx].querySelector('input').value; idx++;}
      const notes=(tds[idx]&&tds[idx].querySelector('input'))?tds[idx].querySelector('input').value:'';
      rows.push({ip:ip.trim(),unit_id:unit===''?'':Number(unit),address:addr===''?'':Number(addr),value:value??'',notes});
    });
    return rows;
  }
  function refToZeroBased(kind,addr){
    if(addr===''||isNaN(addr)) return addr; const a=Number(addr);
    if(kind==='coils')return a>=1?a-1:a; if(kind==='discrete')return a>=10001?a-10001:a; if(kind==='input')return a>=30001?a-30001:a; if(kind==='holding')return a>=40001?a-40001:a; return a;
  }

  // Node meta load/save (persisted on server)
  async function loadNodeMeta(){
    try{
      const r=await fetch('/node'); if(!r.ok) return;
      const j=await r.json();
      const nn=document.getElementById('node_name'); const rl=document.getElementById('node_role');
      if(j.name!==undefined) nn.value=j.name;
      if(j.role!==undefined) rl.value=j.role;
    }catch(_){}
  }
  async function saveNodeMeta(){
    const nn=document.getElementById('node_name').value.trim();
    const rl=document.getElementById('node_role').value;
    const s=document.getElementById('save-status');
    try{
      const r=await fetch('/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nn,role:rl})});
      if(!r.ok){s.textContent='Save failed';return;}
      s.textContent='Saved'; setTimeout(()=>s.textContent='',1500);
    }catch(_){s.textContent='Save failed';}
  }
  document.getElementById('save-meta').onclick=saveNodeMeta;
  loadNodeMeta();

  // Build ops
  function buildOps(which){
    const def_ip=document.getElementById('ip').value.trim(); const def_unit=Number(document.getElementById('unit_id').value);
    const timeout=Number(document.getElementById('timeout').value); const dry=document.getElementById('dry').checked;
    const node_name=document.getElementById('node_name').value.trim(); const node_role=document.getElementById('node_role').value;
    const ops=[];
    const coilsMode=document.getElementById('coils-mode').value;
    rowsFromTable(document.getElementById('coils-table')).forEach(r=>{ if(r.address==='')return; const addr0=refToZeroBased('coils',r.address); const isW=(coilsMode!=='read_coils'); if((which==='read'&&isW)||(which==='write'&&!isW))return; const ip=r.ip||def_ip; const unit=(r.unit_id===''?def_unit:r.unit_id);
      ops.push({node_name,node_role,device:"COILS",ip,unit_id:unit,function:coilsMode,address:addr0,count:1,datatype:"bool",rw:isW?"W":"R",scale:1.0,endianness:"",value:isW?(coilsMode==='write_single'?(r.value||'0').trim():(r.value||'').trim()):"",notes:r.notes||""});});
    rowsFromTable(document.getElementById('discrete-table')).forEach(r=>{ if(r.address===''||which==='write')return; const addr0=refToZeroBased('discrete',r.address); const ip=r.ip||def_ip; const unit=(r.unit_id===''?def_unit:r.unit_id);
      ops.push({node_name,node_role,device:"DISCRETE",ip,unit_id:unit,function:"read_discrete",address:addr0,count:1,datatype:"bool",rw:"R",scale:1.0,endianness:"",value:"",notes:r.notes||""});});
    const hMode=document.getElementById('holding-mode').value, hDT=document.getElementById('holding-dt').value, hEnd=document.getElementById('holding-endian').value, hScale=Number(document.getElementById('holding-scale').value);
    const hCount=(hDT==="int32"||hDT==="float32")?2:1; const hW=(hMode!=="read_holding");
    rowsFromTable(document.getElementById('holding-table')).forEach(r=>{ if(r.address==='')return; if((which==='read'&&hW)||(which==='write'&&!hW))return; const addr0=refToZeroBased('holding',r.address); const ip=r.ip||def_ip; const unit=(r.unit_id===''?def_unit:r.unit_id);
      ops.push({node_name,node_role,device:"HOLDING",ip,unit_id:unit,function:hMode,address:addr0,count:hCount,datatype:hDT,rw:hW?"W":"R",scale:hScale,endianness:hEnd,value:hW?(r.value||'').trim():"",notes:r.notes||""});});
    const iDT=document.getElementById('input-dt').value, iEnd=document.getElementById('input-endian').value, iScale=Number(document.getElementById('input-scale').value);
    const iCount=(iDT==="int32"||iDT==="float32")?2:1;
    rowsFromTable(document.getElementById('input-table')).forEach(r=>{ if(r.address===''||which==='write')return; const addr0=refToZeroBased('input',r.address); const ip=r.ip||def_ip; const unit=(r.unit_id===''?def_unit:r.unit_id);
      ops.push({node_name,node_role,device:"INPUT",ip,unit_id:unit,function:"read_input",address:addr0,count:iCount,datatype:iDT,rw:"R",scale:iScale,endianness:iEnd,value:"",notes:r.notes||""});});
    return {ops,timeout,dry,node:{name:node_name,role:node_role}};
  }

  function renderResults(columns,rows){
    const div=document.getElementById('results'); div.style.display='block';
    let html='<h3>Results</h3><div class="muted">Rows: '+rows.length+'</div><div style="max-height:60vh;overflow:auto"><table><thead><tr>'+columns.map(c=>'<th>'+escHtml(c)+'</th>').join('')+'</tr></thead><tbody>';
    for(const r of rows){ html+='<tr>'+columns.map(c=>{const v=r[c];const cls=(c.toLowerCase()==='ok')?(v?'ok':'err'):'';const t=(typeof v==='object')?escHtml(JSON.stringify(v)):escHtml(v);return '<td class="'+cls+'">'+t+'</td>';}).join('')+'</tr>'; }
    html+='</tbody></table></div>'; div.innerHTML=html;
    const esc=escCsv, hdr=columns.map(esc).join(','), body=rows.map(row=>columns.map(c=>esc(typeof row[c]==='object'?JSON.stringify(row[c]):(row[c]??''))).join(',')).join('\n');
    const blob=new Blob([hdr+'\n'+body],{type:'text/csv'}), url=URL.createObjectURL(blob); const a=document.getElementById('download'); a.href=url; a.style.display='inline-block';
  }

  async function postOps(which){
    const payload=buildOps(which); const status=document.getElementById('status'); status.textContent=(which==='read'?'Reading ':'Writing ')+payload.ops.length+' operations...';
    try{
      const resp=await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),credentials:'same-origin'});
      if(!resp.ok){const t=await resp.text().catch(()=> ''); throw new Error('HTTP '+resp.status+' '+(t||''));}
      const data=await resp.json(); renderResults(data.columns||[],data.rows||[]); status.textContent='Done.';
    }catch(err){status.textContent='Error: '+(err?.message||err);}
  }
  document.getElementById('read-btn').onclick=()=>postOps('read');
  document.getElementById('write-btn').onclick=()=>postOps('write');
})();
</script></body></html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

# --- Node metadata endpoints (persisted) ---
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

# --- Run mapping ---
@app.post("/run")
async def run_mapping(request: Request):
    payload = await request.json()
    rows: List[Dict[str, Any]] = payload.get("rows") or []
    timeout = float(payload.get("timeout", 3.0))
    dry = bool(payload.get("dry", False))
    node = payload.get("node") or {}

    # If UI included node updates, persist them
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
