#!/usr/bin/env python3
"""
Ultra-simple Modbus TCP portal: read/write from an Excel/CSV mapping.

Usage:
  python modbus_portal_cli.py mapping.xlsx [--timeout 3.0] [--out results.xlsx] [--dry]
  python modbus_portal_cli.py mapping.csv  [--timeout 3.0] [--out results.csv]  [--dry]

Input file:
- **Excel**: .xlsx/.xls (requires: pip install pandas openpyxl)
- **CSV**  : .csv (no extra deps)

CSV/Excel columns (case-insensitive, header required):
  device, ip, unit_id, function, address, count, datatype, rw, value, scale, endianness

- function: read_coils | read_discrete | read_holding | read_input | write_single | write_multi
- address: 0-based register/coil address (int)
- count:   number of coils/registers to read (reads only)
- datatype (reads): int16|uint16|int32|float32|bool|raw
- rw: R | W | RW (informational; writes still require function write_*)
- value (writes): integer for write_single, or comma-separated integers for write_multi
- scale (optional): numeric multiplier when decoding (default 1.0)
- endianness (optional for 32-bit): ABCD|BADC|CDAB|DCBA (default ABCD)

Examples:
  device,ip,unit_id,function,address,count,datatype,rw,scale,endianness,value
  PumpA,192.168.1.10,1,read_holding,40001,2,float32,R,1.0,CDAB,
  Valve1,192.168.1.11,1,write_single,40010,1,int16,W,,,
  GroupWrite,192.168.1.12,1,write_multi,40020,3,int16,W,,,100,101,102

Requires: pip install pymodbus==3.*
Excel support: pip install pandas openpyxl
"""

import csv
import sys
import argparse
from typing import Dict, Any, Tuple, List
from pathlib import Path

from pymodbus.client import ModbusTcpClient
from struct import pack, unpack

# Optional pandas import for Excel I/O
try:
    import pandas as pd  # type: ignore
except Exception:  # pandas is optional unless Excel I/O is used
    pd = None  # noqa: N816

FUNCTIONS = {
    "read_coils": "read_coils",
    "read_discrete": "read_discrete_inputs",
    "read_holding": "read_holding_registers",
    "read_input": "read_input_registers",
    "write_single": "write_register",
    "write_multi": "write_registers",
}


def _u16_to_i16(v: int) -> int:
    return v if v < 0x8000 else v - 0x10000


def _swap_bytes(w: int) -> int:
    return ((w & 0xFF) << 8) | ((w >> 8) & 0xFF)


def decode_registers(registers: List[int], datatype: str = "int16", endianness: str = "ABCD", scale: float = 1.0):
    datatype = (datatype or "int16").lower()
    endianness = (endianness or "ABCD").upper()

    if datatype == "raw":
        return registers

    if datatype in ("int16", "uint16"):
        if not registers:
            return None
        raw = registers[0] & 0xFFFF
        val = raw if datatype == "uint16" else _u16_to_i16(raw)
        return val * scale

    if datatype in ("int32", "float32"):
        if len(registers) < 2:
            return None
        hi, lo = registers[0] & 0xFFFF, registers[1] & 0xFFFF
        # Word order
        if endianness == "ABCD":
            w1, w2 = hi, lo
        elif endianness == "CDAB":
            w1, w2 = lo, hi
        elif endianness == "BADC":
            w1, w2 = _swap_bytes(hi), _swap_bytes(lo)
        elif endianness == "DCBA":
            w1, w2 = _swap_bytes(lo), _swap_bytes(hi)
        else:
            w1, w2 = hi, lo
        raw32 = (w1 << 16) | w2
        if datatype == "int32":
            if raw32 & 0x80000000:
                raw32 -= 0x100000000
            return raw32 * scale
        # float32 big-endian by word
        return unpack(">f", pack(">I", raw32))[0] * scale

    if datatype == "bool":
        return bool(registers[0]) if registers else None

    # default: just return list
    return registers


def perform_row(row: Dict[str, Any], client_cache: Dict[Tuple[str, float], ModbusTcpClient], timeout: float, dry: bool = False) -> Dict[str, Any]:
    # normalize
    fn = str(row.get("function", "")).strip().lower()
    ip = str(row.get("ip", "")).strip()
    unit = int(float(row.get("unit_id", 1))) if row.get("unit_id") not in ("", None) else 1
    address = int(float(row.get("address", 0)))
    count = int(float(row.get("count", 1)))
    datatype = str(row.get("datatype", "int16") or "int16").lower()
    scale = float(row.get("scale", 1.0) or 1.0)
    endianness = str(row.get("endianness", "ABCD") or "ABCD").upper()

    result: Dict[str, Any] = {"device": row.get("device", ""), "ip": ip, "function": fn, "address": address}

    if fn not in FUNCTIONS:
        result.update(ok=False, error=f"unknown-function:{fn}")
        return result

    if dry:
        result.update(ok=True, dry=True)
        return result

    key = (ip, timeout)
    client = client_cache.get(key)
    if client is None:
        client = ModbusTcpClient(host=ip, timeout=timeout)
        if not client.connect():
            result.update(ok=False, error="connect-failed")
            return result
        client_cache[key] = client

    try:
        method_name = FUNCTIONS[fn]
        method = getattr(client, method_name)

        if fn.startswith("read"):
            rr = method(address=address, count=count, unit=unit)
            if rr.isError():
                result.update(ok=False, error=str(rr))
            else:
                regs = rr.bits if fn in ("read_coils", "read_discrete") else rr.registers
                value = decode_registers(regs, datatype=datatype, endianness=endianness, scale=scale)
                result.update(ok=True, value=value, raw=regs)
        else:
            # writes
            val = row.get("value", "")
            if fn == "write_single":
                try:
                    intval = int(float(str(val).strip()))
                except Exception:
                    result.update(ok=False, error=f"bad-value:{val}")
                    return result
                wr = method(address=address, value=intval, unit=unit)
            else:
                parts = [p.strip() for p in str(val).replace(";", ",").split(",") if p.strip()]
                try:
                    intvals = [int(float(p)) for p in parts]
                except Exception:
                    result.update(ok=False, error=f"bad-values:{val}")
                    return result
                wr = method(address=address, values=intvals, unit=unit)
            if wr.isError():
                result.update(ok=False, error=str(wr))
            else:
                result.update(ok=True, result="written")
        return result
    except Exception as e:
        result.update(ok=False, error=f"exception:{e}")
        return result


REQUIRED_COLS = {"device", "ip", "unit_id", "function", "address", "count"}


def _normalize_header(cols: List[str]) -> List[str]:
    return [c.strip().lower() for c in cols]


def load_rows(path: str) -> List[Dict[str, Any]]:
    ext = Path(path).suffix.lower()
    rows: List[Dict[str, Any]] = []

    if ext in {".xlsx", ".xls"}:
        if pd is None:
            sys.exit("Excel input requires pandas (pip install pandas openpyxl)")
        df = pd.read_excel(path, dtype=str).fillna("")
        header = _normalize_header(list(df.columns))
        missing = REQUIRED_COLS - set(header)
        if missing:
            sys.exit(f"Missing required columns: {', '.join(sorted(missing))}")
        # rename columns to lowercase
        df.columns = header
        for _, r in df.iterrows():
            row = {k: (str(v).strip() if isinstance(v, str) else v) for k, v in r.to_dict().items()}
            rows.append(row)
        return rows

    # CSV path
    with open(path, newline="") as f:
        rdr = csv.DictReader(f)
        header = _normalize_header(rdr.fieldnames or [])
        missing = REQUIRED_COLS - set(header)
        if missing:
            sys.exit(f"Missing required columns: {', '.join(sorted(missing))}")
        for row in rdr:
            rows.append({k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    return rows


def save_results(out_path: str, results: List[Dict[str, Any]]):
    ext = Path(out_path).suffix.lower()
    if ext in {".xlsx", ".xls"}:
        if pd is None:
            sys.exit("Excel output requires pandas (pip install pandas openpyxl)")
        df = pd.DataFrame(results)
        # Keep a friendly column order: original + computed
        cols = sorted({k for r in results for k in r.keys()})
        df = df.reindex(columns=cols)
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="results")
        return
    # CSV fallback
    out_fields = sorted({k for r in results for k in r.keys()})
    with open(out_path, "w", newline="") as g:
        w = csv.DictWriter(g, fieldnames=out_fields)
        w.writeheader()
        for r in results:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser(description="Transfer Modbus ops from Excel/CSV to Modbus TCP packets")
    ap.add_argument("mapping", help="Path to mapping file (.xlsx/.xls/.csv)")
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--out", help="Optional path to write results (.xlsx or .csv)")
    ap.add_argument("--dry", action="store_true", help="Dry-run (no network calls)")
    args = ap.parse_args()

    rows = load_rows(args.mapping)

    clients: Dict[Tuple[str, float], ModbusTcpClient] = {}
    results: List[Dict[str, Any]] = []

    try:
        for row in rows:
            res = perform_row(row, clients, timeout=args.timeout, dry=args.dry)
            results.append({**row, **res})
            # also print a compact line
            if res.get("ok"):
                val = res.get("value")
                if isinstance(val, list):
                    val = ";".join(map(str, val))
                print(f"OK {row.get('device','')} {row.get('ip','')} {row.get('function','')} @{row.get('address','')}: {val if 'value' in res else res.get('result','')} ")
            else:
                print(f"ERR {row.get('device','')} {row.get('ip','')} {row.get('function','')} @{row.get('address','')}: {res.get('error')}")
    finally:
        for c in list(clients.values()):
            try:
                c.close()
            except Exception:
                pass

    if args.out:
        save_results(args.out, results)


if __name__ == "__main__":
    main()


# ==== web_portal.py ============================================================
# Minimal HTTP portal for running the Modbus mapping from a browser.
#
# Run:  uvicorn web_portal:app --reload --port 8000
# Deps: pip install fastapi uvicorn python-multipart
#
# Place this file next to modbus_portal_cli.py. It imports the loader/runner utils
# from there to avoid duplication.

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from tempfile import NamedTemporaryFile
from typing import List, Dict, Any, Tuple
import json

# Reuse core logic from the CLI file in the same folder
from modbus_portal_cli import load_rows, perform_row, save_results
from pymodbus.client import ModbusTcpClient

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
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }
    header { margin-bottom: 16px; }
    .card { border: 1px solid #ddd; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    input[type="file"], input, button { font-size: 14px; }
    table { border-collapse: collapse; width: 100%; margin-top: 12px; }
    th, td { border: 1px solid #eee; padding: 6px 8px; font-size: 13px; }
    th { background: #fafafa; text-align: left; }
    .ok { color: #0a7a2f; font-weight: 600; }
    .err { color: #b00020; font-weight: 600; }
    .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .hint { color: #666; font-size: 12px; }
  </style>
</head>
<body>
  <header>
    <h2>Ultra-simple Modbus TCP Portal</h2>
    <div class="hint">Upload your mapping (.xlsx/.xls/.csv), choose options, and run.</div>
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
