INDEX_HTML = """
...
"""
==== web_portal.py ============================================================
<input type="file" name="mapping" id="mapping" accept=".csv,.xlsx,.xls" required />
<label>Timeout (s) <input type="number" step="0.1" min="0.1" name="timeout" value="3.0"></label>
<label><input type="checkbox" name="dry" checked> Dry-run</label>
<button type="submit">Run</button>
<a id="download" href="#" download="results.csv" style="display:none">Download results.csv</a>
</div>
</form>
</div>


<div id="results" class="card" style="display:none"></div>


<script>
const form = document.getElementById('runForm');
const resultsDiv = document.getElementById('results');
const downloadLink = document.getElementById('download');


form.addEventListener('submit', async (e) => {
e.preventDefault();
resultsDiv.style.display = 'block';
resultsDiv.textContent = 'Running...';
downloadLink.style.display = 'none';


const fd = new FormData(form);
const resp = await fetch('/run', { method: 'POST', body: fd });
const data = await resp.json();


// Build HTML table
const cols = data.columns;
const rows = data.rows;
let html = `<h3>Results</h3><table><thead><tr>` + cols.map(c=>`<th>${c}</th>`).join('') + `</tr></thead><tbody>`;
for (const r of rows) {
html += '<tr>' + cols.map(c => {
const v = r[c];
const cls = (c === 'ok') ? (v ? 'ok' : 'err') : '';
return `<td class="${cls}">${typeof v === 'object' ? JSON.stringify(v) : (v ?? '')}</td>`;
}).join('') + '</tr>';
}
html += '</tbody></table>';
resultsDiv.innerHTML = html;


// Create a CSV client-side and expose a download link
const csvCols = cols;
const esc = (s) => '"' + String(s ?? '').replaceAll('"', '""') + '"';
const csv = [csvCols.map(esc).join(',')]
.concat(rows.map(row => csvCols.map(c => esc(typeof row[c] === 'object' ? JSON.stringify(row[c]) : row[c])).join(',')))
.join('
');
const blob = new Blob([csv], {type: 'text/csv'});
const url = URL.createObjectURL(blob);
downloadLink.href = url;
downloadLink.style.display = 'inline-block';
});
</script>
</body>
</html>
"""




@app.get("/", response_class=HTMLResponse)
async def index():
return HTMLResponse(INDEX_HTML)




@app.post("/run")
async def run_mapping(mapping: UploadFile = File(...), timeout: float = Form(3.0), dry: bool = Form(False)):
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
