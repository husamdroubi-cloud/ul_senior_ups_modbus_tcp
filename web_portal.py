# web_portal.py
# In-page Modbus portal (no file upload). Configure tables for Coils / Discrete / Holding / Input regs,
# choose counts, per-row IP/Unit overrides, enter values/notes, then Read/Write via JSON.
#
# Run:
#   python -m uvicorn web_portal:app --reload --port 8000
#
# Requires: fastapi, uvicorn (already in requirements), and your modbus_portal_cli.py in same folder.

from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Tuple

from pymodbus.client import ModbusTcpClient
from modbus_portal_cli import perform_row  # reuse decoding + row execution

app = FastAPI(title="Ultra-simple Modbus TCP Portal (Form Mode)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Modbus TCP Portal (Form)</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; line-height: 1.35; }
    header { margin-bottom: 16px; }
    .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .card { border: 1px solid #ddd; border-radius: 12px; padding: 16px; margin: 12px 0; }
    .section { margin-top: 18px; }
    label { display: inline-flex; gap: 6px; align-items: center; }
    input, select, button { font-size: 14px; padding: 4px 6px; }
    input[type="number"] { width: 7em; }
    table { border-collapse: collapse; width: 100%; margin-top: 12px; }
    th, td { border: 1px solid #eee; padding: 6px 8px; font-size: 13px; vertical-align: top; }
    th { background: #fafafa; text-align: left; }
    .ok { color: #0a7a2f; font-weight: 600; }
    .err { color: #b00020; font-weight: 600; }
    .muted { color: #888; font-size: 12px; }
    .tabbar { display:flex; gap: 8px; margin: 8px 0; }
    .tabbar button { padding: 6px 10px; border-radius: 8px; border: 1px solid #ccc; background: #f5f5f5; cursor: pointer; }
    .tabbar button.active { background: #e8f0ff; border-color: #7aa2ff; }
    .hidden { display:none; }
    .gridnum { width: 5em; }
    .valuecell { min-width: 8em; }
    .ipcell { min-width: 11em; }
    .unitcell { min-width: 5em; }
    .notescell { min-width: 12em; }
  </style>
</head>
<body>
  <header>
    <h2>Modbus TCP Portal – No Upload (Form Mode)</h2>
    <div class="muted">Configure rows for each table, then click <b>Read All</b> or <b>Write All</b>. Addresses are <b>0-based</b>.</div>
  </header>

  <div class="card">
    <div class="row">
      <label>Default Device/IP <input id="ip" placeholder="192.168.1.10" /></label>
      <label>Default Unit ID <input id="unit_id" type="number" min="0" max="247" value="1" /></label>
      <label>Timeout (s) <input id="timeout" type="number" step="0.1" min="0.1" value="3.0" /></label>
      <label><input id="dry" type="checkbox" checked /> Dry-run</label>
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

    <!-- Coils -->
    <div id="tab-coils" class="section">
      <div class="row">
        <label>Rows <input class="gridnum" id="coils-rows" type="number" min="1" value="8" /></label>
        <label>Base address <input class="gridnum" id="coils-base" type="number" min="0" value="0" /></label>
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

    <!-- Discrete Inputs (read-only) -->
    <div id="tab-discrete" class="section hidden">
      <div class="row">
        <label>Rows <input class="gridnum" id="discrete-rows" type="number" min="1" value="8" /></label>
        <label>Base address <input class="gridnum" id="discrete-base" type="number" min="0" value="0" /></label>
        <button id="discrete-build">Build Table</button>
      </div>
      <table id="discrete-table"></table>
      <div class="muted">Discrete inputs are read-only (bits).</div>
    </div>

    <!-- Holding Registers -->
    <div id="tab-holding" class="section hidden">
      <div class="row">
        <label>Rows <input class="gridnum" id="holding-rows" type="number" min="1" value="4" /></label>
        <label>Base address <input class="gridnum" id="holding-base" type="number" min="0" value="0" /></label>
        <label>Mode
          <select id="holding-mode">
            <option value="read_holding">Read Holding</option>
            <option value="write_single">Write Single Reg</option>
            <option value="write_multi">Write Multiple Regs</option>
          </select>
        </label>
        <label>Datatype
          <select id="holding-dt">
            <option>int16</option>
            <option>uint16</option>
            <option>int32</option>
            <option>float32</option>
          </select>
        </label>
        <label>Endianness
          <select id="holding-endian">
            <option>ABCD</option><option>BADC</option><option>CDAB</option><option>DCBA</option>
          </select>
        </label>
        <label>Scale <input id="holding-scale" class="gridnum" type="number" step="0.01" value="1.0" /></label>
        <button id="holding-build">Build Table</button>
      </div>
      <table id="holding-table"></table>
      <div class="muted">For 32-bit types, two registers are consumed per row.</div>
    </div>

    <!-- Input Registers (read-only) -->
    <div id="tab-input" class="section hidden">
      <div class="row">
        <label>Rows <input class="gridnum" id="input-rows" type="number" min="1" value="4" /></label>
        <label>Base address <input class="gridnum" id="input-base" type="number" min="0" value="0" /></label>
        <label>Datatype
          <select id="input-dt">
            <option>int16</option>
            <option>uint16</option>
            <option>int32</option>
            <option>float32</option>
          </select>
        </label>
        <label>Endianness
          <select id="input-endian">
            <option>ABCD</option><option>BADC</option><option>CDAB</option><option>DCBA</option>
          </select>
        </label>
        <label>Scale <input id="input-scale" class="gridnum" type="number" step="0.01" value="1.0" /></label>
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
  (function () {
    const tabBtns = document.querySelectorAll('.tabbar button');
    const tabs = {
      coils: document.getElementById('tab-coils'),
      discrete: document.getElementById('tab-discrete'),
      holding: document.getElementById('tab-holding'),
      input: document.getElementById('tab-input'),
    };
    tabBtns.forEach(b => b.addEventListener('click', () => {
      tabBtns.forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      const key = b.dataset.tab;
      Object.keys(tabs).forEach(k => tabs[k].classList.toggle('hidden', k!==key));
    }));

    const escCsv = s => '"' + String(s ?? '').replace(/"/g,'""') + '"';
    const escHtml = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

    function buildTable(table, base, rows, includeValue, includeDatatypeNotes=false) {
      table.innerHTML = '';
      const thead = document.createElement('thead');
      let head = '<tr><th>#</th><th class="ipcell">IP (override)</th><th class="unitcell">Unit</th><th>Address</th>';
      if (includeDatatypeNotes) head += '<th class="valuecell">Value (int/float or comma list)</th>';
      else if (includeValue) head += '<th class="valuecell">Value</th>';
      head += '<th class="notescell">Notes</th></tr>';
      thead.innerHTML = head;
      table.appendChild(thead);
      const tbody = document.createElement('tbody');
      for (let i=0;i<rows;i++) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${i+1}</td>
          <td><input placeholder="" class="ipcell"></td>
          <td><input type="number" min="0" max="247" value="" class="unitcell"></td>
          <td><input type="number" min="0" value="${base+i}" class="gridnum"></td>
          ${includeValue ? '<td class="valuecell"><input></td>' : ''}
          ${includeDatatypeNotes ? (!includeValue ? '<td class="valuecell"><input></td>' : '') : ''}
          <td class="notescell"><input placeholder="free text notes..."></td>
        `;
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
    }

    // Build buttons
    document.getElementById('coils-build').onclick = () => {
      const includeVal = document.getElementById('coils-mode').value !== 'read_coils';
      buildTable(document.getElementById('coils-table'),
        Number(document.getElementById('coils-base').value),
        Number(document.getElementById('coils-rows').value),
        includeVal, false);
    };
    document.getElementById('discrete-build').onclick = () => {
      buildTable(document.getElementById('discrete-table'),
        Number(document.getElementById('discrete-base').value),
        Number(document.getElementById('discrete-rows').value),
        false, false);
    };
    document.getElementById('holding-build').onclick = () => {
      const includeVal = document.getElementById('holding-mode').value !== 'read_holding';
      buildTable(document.getElementById('holding-table'),
        Number(document.getElementById('holding-base').value),
        Number(document.getElementById('holding-rows').value),
        includeVal, true);
    };
    document.getElementById('input-build').onclick = () => {
      buildTable(document.getElementById('input-table'),
        Number(document.getElementById('input-base').value),
        Number(document.getElementById('input-rows').value),
        false, true);
    };

    // Build default tables on load
    document.getElementById('coils-build').click();
    document.getElementById('discrete-build').click();
    document.getElementById('holding-build').click();
    document.getElementById('input-build').click();

    function rowsFromTable(tableEl) {
      const rows = [];
      const trs = tableEl.querySelectorAll('tbody tr');
      trs.forEach(tr => {
        const tds = tr.querySelectorAll('td');
        const ip = tds[1].querySelector('input')?.value ?? '';
        const unit = tds[2].querySelector('input')?.value ?? '';
        const addr = tds[3].querySelector('input')?.value ?? '';
        // value is optional / may not exist
        let valueCellIdx = 4;
        let value = '';
        if (tds[valueCellIdx] && tds[valueCellIdx].querySelector('input')) {
          value = tds[valueCellIdx].querySelector('input').value;
          valueCellIdx++;
        }
        const notes = (tds[valueCellIdx] && tds[valueCellIdx].querySelector('input'))
          ? tds[valueCellIdx].querySelector('input').value
          : '';
        rows.push({
          ip: ip.trim(),
          unit_id: unit === '' ? '' : Number(unit),
          address: addr === '' ? '' : Number(addr),
          value: value ?? '',
          notes
        });
      });
      return rows;
    }

    function buildOps(which) { // which: 'read' | 'write'
      const def_ip = document.getElementById('ip').value.trim();
      const def_unit = Number(document.getElementById('unit_id').value);
      const timeout = Number(document.getElementById('timeout').value);
      const dry = document.getElementById('dry').checked;

      const ops = [];

      // Coils
      const coilsMode = document.getElementById('coils-mode').value; // read_coils | write_single | write_multi
      rowsFromTable(document.getElementById('coils-table')).forEach(r => {
        if (r.address === '') return;
        const isWrite = (coilsMode !== 'read_coils');
        if ((which === 'read' && isWrite) || (which === 'write' && !isWrite)) return;
        const ip = r.ip || def_ip;
        const unit = (r.unit_id === '' ? def_unit : r.unit_id);
        const base = {
          device: "COILS",
          ip, unit_id: unit,
          function: coilsMode,
          address: r.address,
          count: 1,
          datatype: "bool",
          rw: coilsMode==='read_coils' ? 'R':'W',
          scale: 1.0,
          endianness: "",
          value: isWrite ? (coilsMode==='write_single' ? (r.value||'0').trim() : (r.value||'').trim()) : "",
          notes: r.notes || ""
        };
        ops.push(base);
      });

      // Discrete Inputs (read only)
      rowsFromTable(document.getElementById('discrete-table')).forEach(r => {
        if (r.address === '' || which === 'write') return;
        const ip = r.ip || def_ip;
        const unit = (r.unit_id === '' ? def_unit : r.unit_id);
        ops.push({
          device: "DISCRETE",
          ip, unit_id: unit,
          function: "read_discrete",
          address: r.address,
          count: 1,
          datatype: "bool", rw: "R", scale: 1.0, endianness: "",
          value: "", notes: r.notes || ""
        });
      });

      // Holding
      const hMode = document.getElementById('holding-mode').value; // read_holding | write_single | write_multi
      const hDT = document.getElementById('holding-dt').value;
      const hEnd = document.getElementById('holding-endian').value;
      const hScale = Number(document.getElementById('holding-scale').value);
      const hCount = (hDT==="int32"||hDT==="float32") ? 2 : 1;
      const hIsWrite = (hMode !== 'read_holding');
      rowsFromTable(document.getElementById('holding-table')).forEach(r => {
        if (r.address === '') return;
        if ((which === 'read' && hIsWrite) || (which === 'write' && !hIsWrite)) return;
        const ip = r.ip || def_ip;
        const unit = (r.unit_id === '' ? def_unit : r.unit_id);
        ops.push({
          device: "HOLDING",
          ip, unit_id: unit,
          function: hMode,
          address: r.address,
          count: hCount,
          datatype: hDT,
          rw: hIsWrite ? 'W' : 'R',
          scale: hScale,
          endianness: hEnd,
          value: hIsWrite ? (r.value||'').trim() : "",
          notes: r.notes || ""
        });
      });

      // Input Registers (read only)
      const iDT = document.getElementById('input-dt').value;
      const iEnd = document.getElementById('input-endian').value;
      const iScale = Number(document.getElementById('input-scale').value);
      const iCount = (iDT==="int32"||iDT==="float32") ? 2 : 1;
      rowsFromTable(document.getElementById('input-table')).forEach(r => {
        if (r.address === '' || which === 'write') return;
        const ip = r.ip || def_ip;
        const unit = (r.unit_id === '' ? def_unit : r.unit_id);
        ops.push({
          device: "INPUT",
          ip, unit_id: unit,
          function: "read_input",
          address: r.address,
          count: iCount,
          datatype: iDT, rw: "R", scale: iScale, endianness: iEnd,
          value: "", notes: r.notes || ""
        });
      });

      return { ops, timeout, dry };
    }

    function renderResults(columns, rows) {
      const resultsDiv = document.getElementById('results');
      resultsDiv.style.display = 'block';
      let html = '<h3>Results</h3>';
      html += '<div class="muted">Rows: ' + rows.length + '</div>';
      html += '<div style="max-height:60vh;overflow:auto">';
      html += '<table><thead><tr>' + columns.map(c=>'<th>'+escHtml(c)+'</th>').join('') + '</tr></thead><tbody>';
      for (const r of rows) {
        html += '<tr>' + columns.map(c => {
          const v = r[c];
          const cls = (c.toLowerCase()==='ok') ? (v ? 'ok':'err') : '';
          const text = (typeof v === 'object') ? escHtml(JSON.stringify(v)) : escHtml(v);
          return '<td class="'+cls+'">'+text+'</td>';
        }).join('') + '</tr>';
      }
      html += '</tbody></table></div>';
      resultsDiv.innerHTML = html;

      // CSV
      const header = columns.map(escCsv).join(',');
      const body = rows.map(row => columns.map(c => {
        const v = row[c];
        return escCsv(typeof v === 'object' ? JSON.stringify(v) : (v ?? ''));
      }).join(',')).join('\n');
      const csv = header + '\n' + body;
      const blob = new Blob([csv], {type:'text/csv'});
      const url = URL.createObjectURL(blob);
      const download = document.getElementById('download');
      download.href = url;
      download.style.display = 'inline-block';
    }

    async function postOps(which) {
      const { ops, timeout, dry } = buildOps(which);
      const status = document.getElementById('status');
      status.textContent = (which==='read' ? 'Reading ' : 'Writing ') + ops.length + ' operations...';
      try {
        const resp = await fetch(window.location.origin + '/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rows: ops, timeout, dry }),
          credentials: 'same-origin'
        });
        if (!resp.ok) {
          const t = await resp.text().catch(()=> '');
          throw new Error(`HTTP ${resp.status} ${t || ''}`.trim());
        }
        const data = await resp.json();
        renderResults(data.columns || [], data.rows || []);
        status.textContent = 'Done.';
      } catch (err) {
        status.textContent = 'Error: ' + (err?.message || err);
      }
    }

    document.getElementById('read-btn').onclick  = () => postOps('read');
    document.getElementById('write-btn').onclick = () => postOps('write');
  })();
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.post("/run")
async def run_mapping(request: Request):
    payload = await request.json()
    rows: List[Dict[str, Any]] = payload.get("rows") or []
    timeout = float(payload.get("timeout", 3.0))
    dry = bool(payload.get("dry", False))

    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="No rows provided")

    clients: Dict[Tuple[str, float], ModbusTcpClient] = {}
    results: List[Dict[str, Any]] = []

    try:
        for r in rows:
            # Default normalizations + preserve notes
            norm = {
                "device": r.get("device", ""),
                "ip": r.get("ip", ""),
                "unit_id": r.get("unit_id", 1),
                "function": r.get("function", ""),
                "address": r.get("address", 0),
                "count": r.get("count", 1),
                "datatype": r.get("datatype", "int16"),
                "rw": r.get("rw", "R"),
                "scale": r.get("scale", 1.0),
                "endianness": r.get("endianness", "ABCD"),
                "value": r.get("value", ""),
                "notes": r.get("notes", "")
            }
            res = perform_row(norm, clients, timeout=timeout, dry=dry)
            # echo notes back
            out = {**norm, **res}
            results.append(out)
    finally:
        for c in list(clients.values()):
            try:
                c.close()
            except Exception:
                pass

    columns = sorted({k for r in results for k in r.keys()})
    return {"columns": columns, "rows": results}
