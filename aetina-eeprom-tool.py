#!/usr/bin/env python3
"""Aetina EEPROM Tool (Python)

A drop‑in replacement for the original C++ `aetina‑eeprom‑tool` that can:
  • Generate a 256‑byte EEPROM image from command‑line arguments (sub‑command **gen**)
  • Dump an existing EEPROM (either from a .bin file or directly over I²C) in
    JSON or classic hex‑dump form (sub‑command **dump**)

Dependencies
============
* Python ≥ 3.8
* **smbus2** – only required for live I²C access (`pip install smbus2`)

Usage examples
==============
Generate an EEPROM image::

    $ ./aetina_eeprom_tool.py gen \
        -b MX01-MX02-A2 \
        -s 00000001 \
        -p 699-13767-0000-300 \
        -S ABCD1234EF567890 \
        -B AIB-MX01 \
        -d JP_R36_4_3_ORIN_AGX_AIB-MX01-MX02-A2_ES_v2.0.0_Aetina \
        -o eeprom.bin

Dump the contents of an EEPROM on bus 0, address 0x50::

    $ sudo ./aetina_eeprom_tool.py dump -c 0 -a 0x50

Dump a previously‑saved image::

    $ ./aetina_eeprom_tool.py dump -b eeprom.bin
"""
from __future__ import annotations

import argparse
import binascii
import json
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "aetina-eeprom-tool"

try:
    sys.path.insert(0, '.')

    from smbus2 import SMBus, i2c_msg  # type: ignore

    _HAVE_SMBUS2 = True
except ModuleNotFoundError:  # pragma: no cover – running without I²C access
    _HAVE_SMBUS2 = False

#
# Helpers & utilities
#

def crc32_update(data: bytes, crc: int = 0) -> int:
    """Compute CRC‑32 (Ethernet/ZIP/PNG polynomial 0xEDB88320)."""
    return binascii.crc32(data, crc) & 0xFFFFFFFF


def epoch_to_tag(seconds: int) -> str:
    """Convert Unix epoch seconds → "YYYYMMDDThhmmss" (UTC)."""
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime(seconds))


def timestamp_now() -> int:
    """Current Unix epoch (seconds)."""
    return int(time.time())


def version_to_int(major: int, minor: int, patch: int) -> int:
    """Pack *major.minor.patch* → MMMmmmppp (decimal, same as original tool)."""
    return major * 1_000_000 + minor * 1_000 + patch


#
# EEPROM binary layout (exactly 256 bytes, packed)
#
@dataclass
class AetinaCBEeprom:
    # Header (8 bytes)
    magic: bytes = b"ATNA"                # 4 B
    major: int = 1                        # 1 B
    minor: int = 0                        # 1 B
    length: int = 0                       # 2 B – filled automatically

    # Product info (88 bytes)
    model_num: bytes = b""                # 20 B
    serial_num: bytes = b""               # 20 B
    part_num: bytes = b""                 # 16 B
    soc_serial_num: bytes = b""           # 16 B
    mfg_timestamp: int = 0                # 8 B (Unix epoch)
    reserved1: bytes = b"\x00" * 8        # 8 B

    # HW board info (32 bytes)
    board_name: bytes = b""               # 8 B
    board_revision: int = 0               # 1 B
    reserved2: bytes = b"\x00" * 23       # 23 B

    # SW info (64 bytes)
    bsp_vendor_tag: bytes = b""           # 2 B (e.g. b"JP")
    bsp_vendor_ver: int = 0               # 4 B (MMMmmppp)
    bsp_vendor_soc_name: bytes = b""      # 12 B ('ORIN-NANO')
    bsp_ver: int = 0                      # 4 B (MMMmmppp)
    bsp_tag: bytes = b""                  # 16 B
    git_hash: bytes = b""                 # 8 B
    reserved3: bytes = b"\x00" * 18       # 18 B

    # Future use (60 bytes)
    reserved4: bytes = b"\x00" * 60       # 60 B

    # Trailer (4 bytes)
    crc32: int = 0                        # 4 B – calculated automatically

    # Struct format string (little‑endian, packed)
    _FMT: str = "<4sBBH20s20s16s16sQ8s8sB23s2sI12sI16s8s18s60sI"

    def _pad(self, data: bytes, length: int) -> bytes:
        """Return *data* NUL‑padded to *length* bytes, raising if too long."""
        if len(data) > length:
            raise ValueError(f"Field too long (max {length} bytes): {data!r}")
        return data.ljust(length, b"\x00")

    #
    # (Un)packing helpers
    #
    def pack(self) -> bytes:
        """Return a 256‑byte blob ready to be written to the EEPROM."""
        self.length = struct.calcsize(self._FMT) - 4  # up to but excl. CRC

        # Ensure every byte‑array field is the right size
        def pad(val: bytes, size: int) -> bytes:  # local helper
            return self._pad(val, size)

        blob = struct.pack(
            self._FMT,
            pad(self.magic, 4),
            self.major,
            self.minor,
            self.length,
            pad(self.model_num, 20),
            pad(self.serial_num, 20),
            pad(self.part_num, 16),
            pad(self.soc_serial_num, 16),
            self.mfg_timestamp,
            pad(self.reserved1, 8),
            pad(self.board_name, 8),
            self.board_revision,
            pad(self.reserved2, 23),
            pad(self.bsp_vendor_tag, 2),
            self.bsp_vendor_ver,
            pad(self.bsp_vendor_soc_name, 12),
            self.bsp_ver,
            pad(self.bsp_tag, 16),
            pad(self.git_hash, 8),
            pad(self.reserved3, 18),
            pad(self.reserved4, 60),
            0,  # placeholder for CRC
        )

        self.crc32 = crc32_update(blob[:-4])
        return blob[:-4] + struct.pack("<I", self.crc32)

    @classmethod
    def unpack(cls, data: bytes) -> "AetinaCBEeprom":
        if len(data) != 256:
            raise ValueError("EEPROM blob must be exactly 256 bytes")

        # Verify CRC first
        stored_crc, = struct.unpack_from("<I", data, 252)
        calc_crc = crc32_update(data[:-4])
        if stored_crc != calc_crc:
            raise ValueError(
                f"CRC mismatch: stored {stored_crc:08x} ≠ calc {calc_crc:08x}")

        # Unpack all fields
        unpacked = struct.unpack(cls._FMT, data)

        def strip(b: bytes) -> bytes:  # remove trailing NULs for readability
            return b.rstrip(b"\x00")

        return cls(
            magic=unpacked[0],
            major=unpacked[1],
            minor=unpacked[2],
            length=unpacked[3],
            model_num=strip(unpacked[4]),
            serial_num=strip(unpacked[5]),
            part_num=strip(unpacked[6]),
            soc_serial_num=strip(unpacked[7]),
            mfg_timestamp=unpacked[8],
            reserved1=unpacked[9],
            board_name=strip(unpacked[10]),
            board_revision=unpacked[11],
            reserved2=unpacked[12],
            bsp_vendor_tag=unpacked[13],
            bsp_vendor_ver=unpacked[14],
            bsp_vendor_soc_name=strip(unpacked[15]),
            bsp_ver=unpacked[16],
            bsp_tag=strip(unpacked[17]),
            git_hash=strip(unpacked[18]),
            reserved3=unpacked[19],
            reserved4=unpacked[20],
            crc32=stored_crc,
        )

    #
    # Convenience helpers
    #
    def as_readable_dict(self) -> dict[str, Any]:
        """Return a human‑friendly JSON‑serialisable structure."""
        def _b(b: bytes) -> str:
            return b.decode("ascii", errors="ignore")

        return {
            "magic": _b(self.magic),
            "version": f"{self.major}.{self.minor}",
            "len": self.length,
            "model_num": _b(self.model_num),
            "serial_num": _b(self.serial_num),
            "soc_serial_num": _b(self.soc_serial_num),
            "part_num": _b(self.part_num),
            "mfg_timestamp": epoch_to_tag(self.mfg_timestamp),
            "board_name": _b(self.board_name),
            "board_revision": self.board_revision,
            "bsp_vendor_tag": _b(self.bsp_vendor_tag),
            "bsp_vendor_ver": self.bsp_vendor_ver,
            "bsp_vendor_soc_name": _b(self.bsp_vendor_soc_name),
            "bsp_ver": self.bsp_ver,
            "bsp_tag": _b(self.bsp_tag),
            "git_hash": _b(self.git_hash),
        }

    # Printable representation (used by ``dump`` command)
    def __str__(self) -> str:  # noqa: DunderStr
        return json.dumps(self.as_readable_dict(), indent=2)


#
# I²C helpers – read a full 256‑byte page in a single repeated‑start cycle
#

def _need():
    if not _HAVE_SMBUS2:
        raise RuntimeError("smbus2 is required for live I²C access (pip install smbus2)")

def i2c_read_eeprom(bus: int, addr: int = 0x50) -> bytes:
    _need()
    with SMBus(bus) as b:
        write = i2c_msg.write(addr, [0x00])       # set internal offset 0x00
        read = i2c_msg.read(addr, 256)            # read 256 bytes
        b.i2c_rdwr(write, read)
        return bytes(read)

def i2c_write_eeprom(bus: int, addr: int, data: bytes, page: int = 8):
    _need()
    if len(data) != 256:
        raise ValueError("input must be 256 bytes")
    with SMBus(bus) as b:
        offset = 0
        while offset < 256:
            # Calculate max bytes we can write before hitting the next page boundary
            page_bound = ((offset // page) + 1) * page
            chunk_len = min(page_bound - offset, 256 - offset)
            payload = bytes([offset]) + data[offset : offset + chunk_len]
            b.i2c_rdwr(i2c_msg.write(addr, list(payload)))
            time.sleep(0.01)  # tWR – allow internal write cycle
            offset += chunk_len

#
# Hex‑dump helper (for non‑Aetina or CRC‑broken blobs)
#

def dump_hex(data: bytes) -> None:
    print("    " + " ".join(f"{i:02x}" for i in range(16)) + "   0123456789abcdef")
    for off in range(0, len(data), 16):
        chunk = data[off : off + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk).ljust(16 * 3 - 1)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{off:02x}: {hex_part}   {ascii_part}")


#
# BSP‑DTS name → EEPROM fields
#

def parse_bsp_dts_name(name: str, eep: AetinaCBEeprom) -> None:
    """Parse strings such as

    ``JP_R36_4_3_ORIN_AGX_AIB-MX01-MX02-A2_ES_v2.0.0_Aetina``

    or

    ``RK_V5_15_0_RK3588_AIB-MX01-MX02-A2_ES_v2.0.0_Aetina``
    """
    parts = name.split("_")
    if len(parts) < 9:
        raise ValueError("Unexpected BSP‑DTS naming format (expected 9 fields)")

    print(parts)

    #eep.model-num = parse[7].encode()
    eep.model_num = parts[6].encode()[:20].ljust(20, b"\x00")

    # BSP vendor tag (first 2 chars, e.g. JP, RK, TI …)
    eep.bsp_vendor_tag = parts[0][:2].encode()

    # Vendor BSP version R<maj>_<min>_<pat>
    eep.bsp_vendor_ver = version_to_int(int(parts[1][1:]), int(parts[2]), int(parts[3]))

    # Vendor SOC name
    eep.bsp_vendor_soc_name = (parts[4] + '-' + parts[5]).encode()[:12].ljust(12, b"\x00")

    # BSP tag (concatenate the four middle parts)
    # eep.bsp_tag = "_".join(parts[:8]).encode()[:28].ljust(28, b"\x00")
    eep.bsp_tag = parts[7].encode()[:16].ljust(16, b"\x00")

    # Aetina BSP version v<maj>.<min>.<pat>
    v_major, v_minor, v_patch = map(int, parts[8][1:].split("."))
    eep.bsp_ver = version_to_int(v_major, v_minor, v_patch)


#
# Command‑handlers
#

def handle_gen(args: argparse.Namespace) -> None:
    eep = AetinaCBEeprom()

    # Copy text fields with proper length checks
    def set_field(attr: str, text: str, length: int) -> None:
        setattr(eep, attr, text.encode()[:length].ljust(length, b"\x00"))

    set_field("model_num", args.model_num, 20)
    set_field("serial_num", args.serial_num, 20)
    set_field("part_num", args.part_num, 16)
    set_field("soc_serial_num", args.soc_serial_num, 16)
    set_field("board_name", args.board_name, 8)

    eep.board_revision = args.board_revision
    eep.mfg_timestamp = timestamp_now()

    if args.bsp_dts_name:
        parse_bsp_dts_name(args.bsp_dts_name, eep)

    out_file = Path(args.out_file)
    out_file.write_bytes(eep.pack())
    print(f"[gen] Wrote {out_file} ({out_file.stat().st_size} bytes)")


def handle_dump(args: argparse.Namespace) -> None:
    write_to_file = False

    if args.bin_file:
        data = Path(args.bin_file).read_bytes()
    else:
        data = i2c_read_eeprom(args.i2c_bus, args.i2c_addr)

        if args.out_file:
            write_to_file = True

    try:
        eep = AetinaCBEeprom.unpack(data)
        print(eep)
    except Exception as exc:
        print(f"[dump] Note: could not parse as Aetina block ({exc}). Falling back to raw dump.", file=sys.stderr)
        dump_hex(data)

    # dump to out file
    if write_to_file:
        out_file = Path(args.out_file)
        out_file.write_bytes(data)

def handle_flash(args: argparse.Namespace):
    data = Path(args.bin_file).read_bytes()
    i2c_write_eeprom(args.i2c_bus, args.i2c_addr, data)
    print("[flash] flash complete")

def handle_verify(args: argparse.Namespace):
    data1 = Path(args.bin_file).read_bytes()
    data2 = i2c_read_eeprom(args.i2c_bus, args.i2c_addr)
    if data1 == data2:
        print("[verify] EEPROM data matches bin file.")
    else:
        print("[verify] EEPROM data does not match bin file.")

#
# Command‑line interface
#

def main(argv: list[str] | None = None) -> None:  # noqa: D401 – imperative mood
    parser = argparse.ArgumentParser(APP_NAME)
    sub = parser.add_subparsers(dest="cmd", required=True)

    # gen
    gen = sub.add_parser("gen", help="Generate EEPROM .bin file")
    gen.add_argument("-m", "--model-num", default="")
    gen.add_argument("-s", "--serial-num", required=True)
    gen.add_argument("-p", "--part-num", required=True)
    gen.add_argument("-S", "--soc-serial-num", default="")
    gen.add_argument("-B", "--board-name", default="")
    gen.add_argument("--board-revision", default=0, type=int)
    gen.add_argument("-o", "--out-file", default="data.bin")
    gen.add_argument("-d", "--bsp-dts-name", default="")
    gen.set_defaults(func=handle_gen)

    # dump
    dump = sub.add_parser("dump", help="Dump EEPROM contents")
    dump.add_argument("-b", "--bin-file", default="")
    dump.add_argument("-c", "--i2c-bus", type=int, default=0, help="I²C bus number (/dev/i2c-<n>)")
    dump.add_argument("-a", "--i2c-addr", type=lambda x: int(x, 0), default=0x50, help="EEPROM 7‑bit address")
    dump.add_argument("-o", "--out-file", required=False)
    dump.set_defaults(func=handle_dump)

    # write
    flash = sub.add_parser("flash", help="Flash .bin into EEPROM")
    flash.add_argument("-b", "--bin-file", required=True)
    flash.add_argument("-c", "--i2c-bus", type=int, default=0, help="I²C bus number (/dev/i2c-<n>)")
    flash.add_argument("-a", "--i2c-addr", type=lambda x: int(x, 0), default=0x50, help="EEPROM 7‑bit address")
    flash.set_defaults(func=handle_flash)

    # verify
    verify = sub.add_parser("verify", help="Verify EEPROM contents")
    verify.add_argument("-b", "--bin-file", required=True)
    verify.add_argument("-c", "--i2c-bus", type=int, default=0, help="I²C bus number (/dev/i2c-<n>)")
    verify.add_argument("-a", "--i2c-addr", type=lambda x: int(x, 0), default=0x50, help="EEPROM 7‑bit address")
    verify.set_defaults(func=handle_verify)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

