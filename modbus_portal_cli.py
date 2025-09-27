"""
modbus_portal_cli.py
- Core Modbus/TCP helpers used by the web portal (and optional CLI)
- No dependency on `pymodbus.payload` (uses `struct` + manual byte/word order)
- Supports IP strings like 'host:port' or '[IPv6]:port'
"""

from __future__ import annotations
from typing import Dict, Any, Tuple, List
import math
import re
import struct

from pymodbus.client import ModbusTcpClient  # works with pymodbus 3.x (and most 2.x)

# ----------------------------
# Host:Port parsing
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
    if not ip_text:
        return "", default_port
    m = _HOSTPORT_RE.match(ip_text)
    if not m:
        return ip_text.strip(), default_port
    host = (m.group("ipv6") or m.group("host") or "").strip()
    port = int(m.group("port")) if m.group("port") else default_port
    return host, port


# ----------------------------
# Endianness (word/byte order)
# ----------------------------
# We treat ABCD as the canonical byte order (big-endian bytes, big-endian word order).
# For a 32-bit value, bytes are A B C D (A = MSB).
# Registers are 16-bit words:
#   ABCD: reg0 = [A B], reg1 = [C D]
#   CDAB: reg0 = [C D], reg1 = [A B]        (word swap)
#   BADC: reg0 = [B A], reg1 = [D C]        (byte swap in each word)
#   DCBA: reg0 = [D C], reg1 = [B A]        (byte swap + word swap)

def _reg_from_bytes(b0: int, b1: int) -> int:
    return ((b0 & 0xFF) << 8) | (b1 & 0xFF)

def _bytes_from_reg(reg: int) -> Tuple[int, int]:
    return ((reg >> 8) & 0xFF, reg & 0xFF)

def pack_i32_to_regs(value: int, order: str) -> List[int]:
    # Build ABCD bytes using big-endian pack, then permute into two registers
    abcd = struct.pack(">i", int(value))
    A, B, C, D = abcd[0], abcd[1], abcd[2], abcd[3]
    o = (order or "ABCD").upper()
    if o == "ABCD":
        return [_reg_from_bytes(A,B), _reg_from_bytes(C,D)]
    if o == "CDAB":
        return [_reg_from_bytes(C,D), _reg_from_bytes(A,B)]
    if o == "BADC":
        return [_reg_from_bytes(B,A), _reg_from_bytes(D,C)]
    if o == "DCBA":
        return [_reg_from_bytes(D,C), _reg_from_bytes(B,A)]
    # default
    return [_reg_from_bytes(A,B), _reg_from_bytes(C,D)]

def pack_f32_to_regs(value: float, order: str) -> List[int]:
    abcd = struct.pack(">f", float(value))
    A, B, C, D = abcd[0], abcd[1], abcd[2], abcd[3]
    o = (order or "ABCD").upper()
    if o == "ABCD":
        return [_reg_from_bytes(A,B), _reg_from_bytes(C,D)]
    if o == "CDAB":
        return [_reg_from_bytes(C,D), _reg_from_bytes(A,B)]
    if o == "BADC":
        return [_reg_from_bytes(B,A), _reg_from_bytes(D,C)]
    if o == "DCBA":
        return [_reg_from_bytes(D,C), _reg_from_bytes(B,A)]
    return [_reg_from_bytes(A,B), _reg_from_bytes(C,D)]

def unpack_i32_from_regs(regs: List[int], order: str) -> int | None:
    if len(regs) < 2:
        return None
    r0, r1 = int(regs[0]), int(regs[1])
    a0, a1 = _bytes_from_reg(r0)
    b0, b1 = _bytes_from_reg(r1)
    o = (order or "ABCD").upper()
    # Reconstruct ABCD in canonical order
    if o == "ABCD":
        A, B, C, D = a0, a1, b0, b1
    elif o == "CDAB":
        A, B, C, D = b0, b1, a0, a1
    elif o == "BADC":
        A, B, C, D = a1, a0, b1, b0
    elif o == "DCBA":
        A, B, C, D = b1, b0, a1, a0
    else:
        A, B, C, D = a0, a1, b0, b1
    return struct.unpack(">i", bytes([A,B,C,D]))[0]

def unpack_f32_from_regs(regs: List[int], order: str) -> float | None:
    if len(regs) < 2:
        return None
    r0, r1 = int(regs[0]), int(regs[1])
    a0, a1 = _bytes_from_reg(r0)
    b0, b1 = _bytes_from_reg(r1)
    o = (order or "ABCD").upper()
    if o == "ABCD":
        A, B, C, D = a0, a1, b0, b1
    elif o == "CDAB":
        A, B, C, D = b0, b1, a0, a1
    elif o == "BADC":
        A, B, C, D = a1, a0, b1, b0
    elif o == "DCBA":
        A, B, C, D = b1, b0, a1, a0
    else:
        A, B, C, D = a0, a1, b0, b1
    return struct.unpack(">f", bytes([A,B,C,D]))[0]


# ----------------------------
# Encode / Decode for portal
# ----------------------------

def _to_num(token: str) -> float:
    t = (token or "").strip().lower()
    if t in ("true", "on", "yes"):
        return 1.0
    if t in ("false", "off", "no"):
        return 0.0
    return float(token)

def _apply_scale_write(v: float, scale: float) -> float:
    return v / scale if (scale not in (None, 0, 1) and not math.isclose(scale, 1.0)) else v

def _apply_scale_read(v: float, scale: float) -> float:
    return v * scale if (scale not in (None, 0, 1) and not math.isclose(scale, 1.0)) else v

def build_registers(value_text: str, datatype: str, endianness: str, scale: float = 1.0) -> List[int]:
    """
    Convert a string to Modbus register list for writes.
    - datatype: int16, uint16, int32, float32
    - For multi-write, pass comma/space/semicolon separated values; we append regs in order.
    """
    if value_text is None:
        value_text = ""
    value_text = value_text.strip()
    parts = [p for p in re.split(r"[,\s;]+", value_text) if p != ""]
    dt = (datatype or "int16").lower()
    out: List[int] = []

    if dt in ("int16", "uint16"):
        for p in (parts or ["0"]):
            v = int(round(_apply_scale_write(_to_num(p), scale)))
            if dt == "uint16":
                v &= 0xFFFF
            out.append(v & 0xFFFF)

    elif dt == "int32":
        for p in (parts or ["0"]):
            v = int(round(_apply_scale_write(_to_num(p), scale)))
            out.extend(pack_i32_to_regs(v, endianness))

    elif dt == "float32":
        for p in (parts or ["0"]):
            v = _apply_scale_write(_to_num(p), scale)
            out.extend(pack_f32_to_regs(float(v), endianness))

    else:
        # default to uint16
        for p in (parts or ["0"]):
            v = int(round(_apply_scale_write(_to_num(p), scale)))
            out.append(v & 0xFFFF)

    return out

def decode_registers(registers: List[int], datatype: str, endianness: str, scale: float = 1.0):
    """
    Convert register list to a value using datatype and endianness.
    Returns a scalar (for 1 value) or a list (for multiple).
    """
    if not registers:
        return None
    dt = (datatype or "int16").lower()
    if dt == "int16":
        vals = [_apply_scale_read((r if r < 0x8000 else r - 0x10000), scale) for r in registers]
    elif dt == "uint16":
        vals = [_apply_scale_read(int(r & 0xFFFF), scale) for r in registers]
    elif dt == "int32":
        vals = []
        for i in range(0, len(registers), 2):
            chunk = registers[i:i+2]
            if len(chunk) < 2:
                break
            v = unpack_i32_from_regs(chunk, endianness)
            if v is None:
                continue
            vals.append(_apply_scale_read(v, scale))
    elif dt == "float32":
        vals = []
        for i in range(0, len(registers), 2):
            chunk = registers[i:i+2]
            if len(chunk) < 2:
                break
            v = unpack_f32_from_regs(chunk, endianness)
            if v is None:
                continue
            vals.append(_apply_scale_read(v, scale))
    else:
        vals = [_apply_scale_read(int(r & 0xFFFF), scale) for r in registers]
    return vals[0] if len(vals) == 1 else vals


# ----------------------------
# Core executor
# ----------------------------

def perform_row(row: Dict[str, Any], clients: Dict[Tuple[str, int, float], ModbusTcpClient],
                timeout: float = 3.0, dry: bool = False) -> Dict[str, Any]:
    """
    Execute a single mapping row.
    Expected keys:
      ip (host or host:port), unit_id, function, address, count, datatype, rw, scale, endianness, value
    'clients' is a cache dict keyed by (host, port, timeout).
    Returns: dict with fields like ok, error, value, registers, etc.
    """
    result: Dict[str, Any] = {"ok": False}

    raw_ip = str(row.get("ip", "")).strip()
    host, port = parse_host_port(raw_ip or "127.0.0.1", default_port=502)

    unit = int(row.get("unit_id", 1) or 1)
    fn = str(row.get("function", "")).strip().lower()
    addr = int(row.get("address", 0) or 0)
    count = int(row.get("count", 1) or 1)
    dtype = str(row.get("datatype", "int16")).lower()
    rw = str(row.get("rw", "R")).upper()
    end = str(row.get("endianness", "ABCD"))
    scale = float(row.get("scale", 1.0) or 1.0)
    value_text = "" if row.get("value") is None else str(row.get("value"))

    if count <= 0:
        count = 1

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
            bit = str(value_text).strip().lower() in ("1", "true", "on", "yes")
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
            bits = []
            for p in re.split(r"[,\s;]+", str(value_text).strip()):
                if not p:
                    continue
                bits.append(p.strip().lower() in ("1", "true", "on", "yes"))
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
# (Optional) CSV/Excel loader for CLI mode
# ----------------------------

def load_rows(path: str) -> List[Dict[str, Any]]:
    """
    Load mapping rows from .csv or .xlsx/.xls.
    Expected headers (case-insensitive; extra fields ignored):
      device, ip, unit_id, function, address, count, datatype, rw, value, scale, endianness, notes
    """
    import os
    import pandas as pd

    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    required = {"ip", "function", "address"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(sorted(missing))}")

    out: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        out.append({
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
        })
    return out


# ----------------------------
# Simple CLI (optional)
# ----------------------------

def main():
    import argparse, json as _json, sys, time
    p = argparse.ArgumentParser(description="Simple Modbus/TCP runner (host:port supported, payload-free)")
    p.add_argument("--file", "-f", help="CSV/XLSX mapping file")
    p.add_argument("--timeout", type=float, default=3.0)
    p.add_argument("--dry", action="store_true")
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
            time.sleep(0.02)
    finally:
        for c in list(clients.values()):
            try: c.close()
            except Exception: pass

if __name__ == "__main__":
    main()
