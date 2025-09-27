"""
modbus_portal_cli.py
- Core Modbus/TCP execution helpers used by the web portal (and optional CLI)
- NEW: Accept 'host:port' (and IPv6 '[addr]:port') in the IP field.
"""

from __future__ import annotations
from typing import Dict, Any, Tuple, List, Optional
import math
import re

from pymodbus.client import ModbusTcpClient
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder
from pymodbus.constants import Endian

# ----------------------------
# Host:Port parsing (NEW)
# ----------------------------

_HOSTPORT_RE = re.compile(
    r"""
    ^\s*
    (?:\[(?P<ipv6>[^]]+)\]|(?P<host>[^:\s]+))   # [IPv6] or hostname/IPv4
    (?::(?P<port>\d{1,5}))?                     # optional :port
    \s*$
    """,
    re.X,
)

def parse_host_port(ip_text: str, default_port: int = 502) -> Tuple[str, int]:
    """
    Accepts 'host', 'host:port', '[IPv6]', or '[IPv6]:port'.
    Returns (host, port). Whitespace is ignored.
    """
    if not ip_text:
        return "", default_port
    m = _HOSTPORT_RE.match(ip_text)
    if not m:
        return ip_text.strip(), default_port
    host = (m.group("ipv6") or m.group("host") or "").strip()
    port = int(m.group("port")) if m.group("port") else default_port
    return host, port


# ----------------------------
# Endianness helpers
# ----------------------------

def endian_from_code(code: str) -> Tuple[Endian, Endian]:
    """
    Map 4-letter word order codes to (byteorder, wordorder).

    ABCD : Big byte, Big word
    DCBA : Little byte, Little word
    BADC : Big byte, Little word
    CDAB : Little byte, Big word
    """
    c = (code or "ABCD").upper()
    if c == "ABCD":
        return Endian.Big, Endian.Big
    if c == "DCBA":
        return Endian.Little, Endian.Little
    if c == "BADC":
        return Endian.Big, Endian.Little
    if c == "CDAB":
        return Endian.Little, Endian.Big
    return Endian.Big, Endian.Big


# ----------------------------
# Encode / Decode helpers
# ----------------------------

def build_registers(value_text: str, datatype: str, endianness: str, scale: float = 1.0) -> List[int]:
    """
    Convert a string to Modbus register list for writes.
    - datatype: int16, uint16, int32, float32
    - scale: if provided, 'raw' = value/scale (for numeric types)
    Supports:
      * single scalar for single-register write
      * comma/semicolon separated for multi-write (each element encoded independently)
    """
    if value_text is None:
        value_text = ""
    value_text = value_text.strip()
    parts = [p for p in re.split(r"[,\s;]+", value_text) if p != ""]

    bo, wo = endian_from_code(endianness)
    out: List[int] = []

    def to_num(token: str) -> float:
        if token.lower() in ("true", "on"):  # convenience
            return 1.0
        if token.lower() in ("false", "off"):
            return 0.0
        return float(token)

    def apply_scale_for_write(v: float) -> float:
        return v / scale if (scale not in (None, 0, 1) and not math.isclose(scale, 1.0)) else v

    if datatype in ("int16", "uint16"):
        for p in (parts or ["0"]):
            v = int(round(apply_scale_for_write(to_num(p))))
            if datatype == "uint16":
                v &= 0xFFFF
            out.append(v)

    elif datatype in ("int32", "float32"):
        # 32-bit -> 2 registers each
        for p in (parts or ["0"]):
            builder = BinaryPayloadBuilder(byteorder=bo, wordorder=wo)
            if datatype == "int32":
                v = int(round(apply_scale_for_write(to_num(p))))
                builder.add_32bit_int(v)
            else:
                v = apply_scale_for_write(to_num(p))
                builder.add_32bit_float(v)
            regs = builder.to_registers()
            out.extend(regs)

    else:
        # default: treat as uint16
        for p in (parts or ["0"]):
            v = int(round(apply_scale_for_write(to_num(p))))
            out.append(v & 0xFFFF)

    return out


def decode_registers(registers: List[int], datatype: str, endianness: str, scale: float = 1.0) -> Any:
    """
    Convert register list to a value using datatype and endianness.
    Returns a scalar (for 1 value) or list.
    """
    if not registers:
        return None

    bo, wo = endian_from_code(endianness)

    def apply_scale_for_read(v: float) -> float:
        return v * scale if (scale not in (None, 0, 1) and not math.isclose(scale, 1.0)) else v

    def chunk(lst: List[int], size: int) -> List[List[int]]:
        return [lst[i:i+size] for i in range(0, len(lst), size)]

    if datatype == "int16":
        vals = [apply_scale_for_read(int((r if r < 0x8000 else r - 0x10000))) for r in registers]
    elif datatype == "uint16":
        vals = [apply_scale_for_read(int(r & 0xFFFF)) for r in registers]
    elif datatype in ("int32", "float32"):
        need = 2
        vals = []
        for pair in chunk(registers, need):
            if len(pair) < need:
                break
            decoder = BinaryPayloadDecoder.fromRegisters(pair, byteorder=bo, wordorder=wo)
            if datatype == "int32":
                vals.append(apply_scale_for_read(decoder.decode_32bit_int()))
            else:
                vals.append(apply_scale_for_read(decoder.decode_32bit_float()))
    else:
        vals = [apply_scale_for_read(int(r & 0xFFFF)) for r in registers]

    return vals[0] if len(vals) == 1 else vals


# ----------------------------
# Core executor
# ----------------------------

def perform_row(row: Dict[str, Any], clients: Dict[Tuple[str, int, float], ModbusTcpClient],
                timeout: float = 3.0, dry: bool = False) -> Dict[str, Any]:
    """
    Execute a single mapping row.
    Expected keys in row:
      ip (host or host:port), unit_id, function, address, count, datatype, rw, scale, endianness, value
    'clients' is a cache dict keyed by (host, port, timeout).
    Returns: dict with fields like ok, error, data/value, etc.
    """
    result: Dict[str, Any] = {"ok": False}

    ip_raw = str(row.get("ip", "")).strip()
    host, port = parse_host_port(ip_raw or "127.0.0.1", default_port=502)

    unit = int(row.get("unit_id", 1) or 1)
    fn = str(row.get("function", "")).strip().lower()
    addr = int(row.get("address", 0) or 0)
    count = int(row.get("count", 1) or 1)
    dtype = str(row.get("datatype", "int16")).lower()
    rw = str(row.get("rw", "R")).upper()
    end = str(row.get("endianness", "ABCD"))
    scale = float(row.get("scale", 1.0) or 1.0)
    value_text = str(row.get("value", "") if row.get("value", "") is not None else "")

    # Normalize negative or silly counts
    if count <= 0:
        count = 1

    # Client cache key includes PORT now (NEW)
    key = (host, port, float(timeout))
    client = clients.get(key)
    if client is None:
        client = ModbusTcpClient(host=host, port=port, timeout=timeout)
        clients[key] = client

    if not client.connect():
        result["error"] = f"connect failed: {host}:{port}"
        return result

    try:
        # ----------- COILS -----------
        if fn in ("read_coils", "read coil", "read_coil"):
            rr = client.read_coils(addr, count, unit=unit)
            if rr.isError():
                result["error"] = str(rr)
            else:
                bits = list(rr.bits[:count])
                result["ok"] = True
                result["value"] = bits[0] if len(bits) == 1 else bits

        elif fn in ("write_single", "write_single_coil", "write coil", "write_coil"):
            v = value_text.strip().lower()
            bit = v in ("1", "true", "on", "yes")
            if dry:
                result["ok"] = True
                result["value"] = bit
            else:
                wr = client.write_coil(addr, bit, unit=unit)
                result["ok"] = not wr.isError()
                if wr.isError():
                    result["error"] = str(wr)
                result["value"] = bit

        elif fn in ("write_multi", "write_multiple_coils", "write coils", "write_coils"):
            # values like "1,0,1"
            bits = []
            for p in re.split(r"[,\s;]+", value_text.strip()):
                if not p:
                    continue
                b = p.strip().lower() in ("1", "true", "on", "yes")
                bits.append(b)
            if not bits:
                bits = [False]
            if dry:
                result["ok"] = True
                result["value"] = bits
            else:
                wr = client.write_coils(addr, bits, unit=unit)
                result["ok"] = not wr.isError()
                if wr.isError():
                    result["error"] = str(wr)
                result["value"] = bits

        # -------- DISCRETE INPUTS --------
        elif fn in ("read_discrete", "read_discrete_inputs", "read di", "read_discrete_input"):
            rr = client.read_discrete_inputs(addr, count, unit=unit)
            if rr.isError():
                result["error"] = str(rr)
            else:
                bits = list(rr.bits[:count])
                result["ok"] = True
                result["value"] = bits[0] if len(bits) == 1 else bits

        # -------- HOLDING REGISTERS --------
        elif fn in ("read_holding", "read_holding_registers", "read hr"):
            rr = client.read_holding_registers(addr, count, unit=unit)
            if rr.isError():
                result["error"] = str(rr)
            else:
                regs = list(rr.registers or [])[:count]
                val = decode_registers(regs, dtype, end, scale)
                result["ok"] = True
                result["value"] = val
                result["registers"] = regs

        elif fn in ("write_single_register", "write_single_reg", "write single reg", "write_register"):
            regs = build_registers(value_text, dtype, end, scale)
            if not regs:
                regs = [0]
            if dry:
                result["ok"] = True
                result["registers"] = regs[:1]
                result["value"] = value_text
            else:
                wr = client.write_register(addr, regs[0] & 0xFFFF, unit=unit)
                result["ok"] = not wr.isError()
                if wr.isError():
                    result["error"] = str(wr)
                result["registers"] = regs[:1]
                result["value"] = value_text

        elif fn in ("write_multi_registers", "write_multiple_registers", "write regs", "write_regs"):
            regs = build_registers(value_text, dtype, end, scale)
            if not regs:
                regs = [0]
            if dry:
                result["ok"] = True
                result["registers"] = regs
                result["value"] = value_text
            else:
                wr = client.write_registers(addr, regs, unit=unit)
                result["ok"] = not wr.isError()
                if wr.isError():
                    result["error"] = str(wr)
                result["registers"] = regs
                result["value"] = value_text

        # -------- INPUT REGISTERS --------
        elif fn in ("read_input", "read_input_registers", "read ir"):
            rr = client.read_input_registers(addr, count, unit=unit)
            if rr.isError():
                result["error"] = str(rr)
            else:
                regs = list(rr.registers or [])[:count]
                val = decode_registers(regs, dtype, end, scale)
                result["ok"] = True
                result["value"] = val
                result["registers"] = regs

        else:
            result["error"] = f"unsupported function: {fn}"

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


# ----------------------------
# (Optional) CSV/Excel loader used by CLI mode
# ----------------------------

def load_rows(path: str) -> List[Dict[str, Any]]:
    """
    Load mapping rows from .csv or .xlsx/.xls.
    Expected headers (case-insensitive, extra fields ignored):
      device, ip, unit_id, function, address, count, datatype, rw, value, scale, endianness, notes
    """
    import os
    import pandas as pd

    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)

    # Normalize headers
    df.columns = [str(c).strip().lower() for c in df.columns]

    required = {"ip", "function", "address"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(sorted(missing))}")

    out: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        row = {
            "device": r.get("device", ""),
            "ip": str(r.get("ip", "")).strip(),
            "unit_id": r.get("unit_id", 1),
            "function": r.get("function", ""),
            "address": r.get("address", 0),
            "count": r.get("count", 1),
            "datatype": r.get("datatype", "int16"),
            "rw": r.get("rw", "R"),
            "value": r.get("value", ""),
            "scale": r.get("scale", 1.0),
            "endianness": r.get("endianness", "ABCD"),
            "notes": r.get("notes", ""),
        }
        out.append(row)
    return out


# ----------------------------
# Basic CLI for ad-hoc testing
# ----------------------------

def main():
    import argparse, json as _json, sys, time
    p = argparse.ArgumentParser(description="Simple Modbus/TCP runner (host:port supported)")
    p.add_argument("--file", "-f", help="CSV/XLSX mapping file")
    p.add_argument("--timeout", type=float, default=3.0)
    p.add_argument("--dry", action="store_true", help="Dry-run (don't actually write)")
    args = p.parse_args()

    if not args.file:
        print("Provide --file mapping", file=sys.stderr)
        sys.exit(2)

    rows = load_rows(args.file)
    clients: Dict[Tuple[str, int, float], ModbusTcpClient] = {}
    try:
        for r in rows:
            res = perform_row(r, clients, timeout=args.timeout, dry=args.dry)
            print(_json.dumps({**r, **res}, ensure_ascii=False))
            # tiny delay to be friendly
            time.sleep(0.02)
    finally:
        for c in list(clients.values()):
            try: c.close()
            except Exception: pass


if __name__ == "__main__":
    main()
