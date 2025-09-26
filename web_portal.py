# web_portal.py
# Minimal HTTP portal for running the Modbus mapping from a browser.
#
# Run locally:
#   python -m uvicorn web_portal:app --reload --port 8000
#
# Requires:
#   pip install fastapi uvicorn python-multipart
#   (and your existing requirements.txt for pandas/openpyxl/pymodbus)

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from tempfile import NamedTemporaryFile
from typing import List, Dict, Any, Tuple

# Reuse core logic from the CLI file in the same folder
from pymodbus.client import ModbusTcpClient
from modbus_portal_cli import load_rows, perform_row  # save_results not needed here

app = FastAPI(title="Ultra-simple Modbus TCP Portal")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Modbus TCP Portal</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; line-height: 1.35; }
    header { margin-bottom: 16px; }
    .card { border: 1px solid #ddd; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    input[type="file"], input, button, a { font-size: 14px; }
    table { border-collapse: collapse; width: 100%; margin-top: 12px; overflow: auto; }
    th, td { border: 1px solid #eee; padding: 6px 8px; font-size: 13px; vertical-align: top; }
    th { background: #fafafa; text-align: left; position: sticky; top: 0; }
    .ok { color: #0a7a2f; font-weight: 600; }
    .err { color: #b00020; font-weight: 600; }
    .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .hint { color: #666; font-size: 12px; }
    .muted { color: #888; }
  </style>
</head>
<body>
  <header>
    <h2>Ultra-simple Modbus TCP Portal</h2>
    <div class="hint">Upload your mapping (<b>.xlsx</b>/<b>.xls</b>/<b>.csv</b>), set options, and run.</div>
  </header>

  <div class="card">
    <form id="runForm">
      <div class="row">
        <input type="file" name="mapping" id="mapping" accept=".csv,.xlsx,.xls" required />
        <label>Timeout (s) <input type="number" step="0.1" min="0.1" name="timeout" value="3.0"></label>
        <label><input type="checkbox" name="dry" checked> Dry-run</label>
        <button type="submit">Run</button>
        <a id="download" href="#" download="results.csv" style="display:none">Download results.csv</a>
      </div>
      <div class="hint" style="margin-top:6px">
        Columns (case-insensitive): <code>device, ip, unit_id, function, address, count, datatype, rw, value, scale, endianness</code>
      </div>
    </form>
  </div>

  <div id="status" class="muted"></div>
  <div id="results" class="card" style="display:none"></div>

  <script>
  const form = document.getElementById('runForm');
  const resultsDiv = document.getElementById('results');
  const statusDiv = document.getElementById('status');
  const downloadLink = document.getElementById('download');

  function escHtml(x) {
    return String(x ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const file = document.getElementById('mapping').files[0];
    if (!file) {
      alert('Please choose a mapping file first.');
      return;
    }

    resultsDiv.style.display = 'block';
    resultsDiv.textContent = 'Running...';
    statusDiv.textContent = '';
    downloadLink.style.display = 'none';

    const fd = new FormData(form);
    try {
      const resp = await fetch('/run', { method: 'POST', body: fd });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(t || ('HTTP ' + resp.status));
      }
      const data = await resp.json();

      const cols = data.columns || [];
      const rows = data.rows || [];

      // Build HTML table
      let html = '<h3>Results</h3>';
      html += '<div class="muted">Rows: ' + rows.length + '</div>';
      html += '<div style="max-height: 60vh; overflow:auto;">';
      html += '<table><thead><tr>' + cols.map(c => '<th>' + escHtml(c) + '</th>').join('') + '</tr></thead><tbody>';

      for (const r of rows) {
        html += '<tr>' + cols.map(c => {
          const v = r[c];
          const isOkCol = (c.toLowerCase() === 'ok');
          const cls = isOkCol ? (v ? 'ok' : 'err') : '';
          const text = (typeof v === 'object') ? escHtml(JSON.stringify(v)) : escHtml(v);
          return '<td class="' + cls + '">' + text + '</td>';
        }).join('') + '</tr>';
      }
      html += '</tbody></table></div>';
      resultsDiv.innerHTML = html;

      // Build CSV client-side and expose a download link
      const escCsv = (s) => '"' + String(s ?? '').replaceAll('"','""') + '"';
      const header = cols.map(escCsv).join(',');
      const body = rows.map(row => cols.map(c => {
        const v = row[c];
        return escCsv(typeof v === 'object' ? JSON.stringify(v) : (v ?? ''));
      }).join(',')).join('\\n');
      const csv = header + '\\n' + body;
      const blob = new Blob([csv], {type: 'text/csv'});
      const url = URL.createObjectURL(blob);
      downloadLink.href = url;
      downloadLink.style.display = 'inline-block';

      statusDiv.textContent = 'Done.';
    } catch (err) {
      resultsDiv.textContent = '';
      statusDiv.textContent = 'Error: ' + (err?.message || err);
    }
  });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)

@app.post("/run")
async def run_mapping(
    mapping: UploadFile = File(...),
    timeout: float = Form(3.0),
    dry: bool = Form(False)
):
    # Save uploaded file to a temp path
    with NamedTemporaryFile(delete=False) as tf:
        content = await mapping.read()
        tf.write(content)
        temp_path = tf.name

    # Load rows and execute
    rows = load_rows(temp_path)

    clients: Dict[Tuple[str, float], ModbusTcpClient] = {}
    results: List[Dict[str, Any]] = []
    try:
        for row in rows:
            res = perform_row(row, clients, timeout=timeout, dry=dry)
            results.append({**row, **res})
    finally:
        for c in list(clients.values()):
            try:
                c.close()
            except Exception:
                pass

    # Normalize to a compact table for the browser
    columns = sorted({k for r in results for k in r.keys()})
    return {"columns": columns, "rows": results}
