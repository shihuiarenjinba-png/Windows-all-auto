"""Read-only local evidence byte verifier for accounting beginner QA.

This authenticates local file hashes and PNG structure, NOT a physical reviewer,
a signed MSIX, Checker correctness, GUI execution or E2E readiness.
The independent human reviewer remains a separate required trust boundary.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

from scripts.accounting_human_qa_gate import (
    AccountingHumanQAHold, SCENARIO_ASSERTIONS,
)

MAX_EVIDENCE_BYTES = 256 * 1024
MAX_PNG_BYTES = 12 * 1024 * 1024
MAX_CHECKER_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


MAX_MSIX_TOTAL_UNCOMPRESSED_BYTES = 4 * MAX_PACKAGE_BYTES
MAX_MSIX_XML_BYTES = {
    "AppxManifest.xml": 1024 * 1024,
    "AppxBlockMap.xml": 8 * 1024 * 1024,
    "[Content_Types].xml": 1024 * 1024,
}
_BLOCKMAP_NS = "http://schemas.microsoft.com/appx/2010/blockmap"
_BLOCKMAP_HASH_METHODS = {
    "http://www.w3.org/2001/04/xmlenc#sha256": hashlib.sha256,
    "http://www.w3.org/2001/04/xmldsig-more#sha384": hashlib.sha384,
    "http://www.w3.org/2001/04/xmlenc#sha512": hashlib.sha512,
}
_BLOCK_BYTES = 65536
# These package metadata/signature entries are not described by File nodes.
_BLOCKMAP_EXCLUDED = {
    "appxblockmap.xml", "[content_types].xml", "appxsignature.p7x",
}
_MSIX_VERSION = re.compile(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){3}\Z")
_MANIFEST_NAMESPACES = (
    "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
    "http://schemas.microsoft.com/appx/2010/manifest",
)



def _zip_local_header_size(handle, info):
    """Read actual ZIP LFH length, not the central-directory extra length."""
    handle.seek(info.header_offset)
    header = handle.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
    if struct.unpack_from("<H", header, 8)[0] != info.compress_type:
        _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
    filename_length, extra_length = struct.unpack_from("<HH", header, 26)
    size = 30 + filename_length + extra_length
    if not 30 <= size <= 65536:
        _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
    return size


def _expected_blockmap_hashes(root, names, handle):
    """Bind each uncompressed 64-KiB package block to AppxBlockMap.xml.

    ZIP CRC alone is not cryptographic content integrity. The map itself
    remains unauthenticated until the separate package signature gate.
    """
    if root.tag != f"{{{_BLOCKMAP_NS}}}BlockMap":
        _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
    algorithm = _BLOCKMAP_HASH_METHODS.get(root.get("HashMethod"))
    if algorithm is None or not list(root):
        _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
    expected = {}
    for file_node in root:
        if file_node.tag != f"{{{_BLOCKMAP_NS}}}File":
            _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
        name = file_node.get("Name")
        size = file_node.get("Size")
        if (not name or not size or re.fullmatch(r"[0-9]+", size) is None):
            _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
        key = name.replace("\\", "/").casefold()
        info = names.get(key)
        if (info is None or info.is_dir() or key in _BLOCKMAP_EXCLUDED
                or key in expected or int(size) != info.file_size):
            _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
        lfh_size = file_node.get("LfhSize")
        if (lfh_size is None or re.fullmatch(r"[0-9]+", lfh_size) is None
                or int(lfh_size) != _zip_local_header_size(handle, info)):
            _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
        blocks = []
        compressed_total = 0
        for node in file_node:
            if node.tag != f"{{{_BLOCKMAP_NS}}}Block" or len(node):
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            encoded = node.get("Hash")
            if not encoded or len(encoded) > 128:
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            try:
                digest = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            if len(digest) != algorithm().digest_size:
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            compressed_size = node.get("Size")
            if info.compress_type == zipfile.ZIP_DEFLATED:
                if (compressed_size is None
                        or re.fullmatch(r"[1-9][0-9]*", compressed_size) is None):
                    _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                compressed_total += int(compressed_size)
            elif compressed_size is not None:
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            blocks.append(digest)
        if len(blocks) != (info.file_size + _BLOCK_BYTES - 1) // _BLOCK_BYTES:
            _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
        if (info.compress_type == zipfile.ZIP_DEFLATED and blocks
                and compressed_total != info.compress_size):
            _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
        expected[key] = blocks
    required = {
        key for key, info in names.items()
        if not info.is_dir() and key not in _BLOCKMAP_EXCLUDED
    }
    if set(expected) != required:
        _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
    return algorithm, expected


def _verify_msix_container(handle) -> None:
    """Verify the hashed file is a plausible MSIX ZIP, not merely PK bytes.

    Stream ZIP CRCs and compare payloads against the untrusted block-map
    hashes; this does NOT authenticate the block-map signature, embedded Store
    Identity binding, executable provenance or installed GUI. Those remain
    separate required gates.
    """
    try:
        handle.seek(0)
        with zipfile.ZipFile(handle, "r") as archive:
            infos = archive.infolist()
            if not 3 <= len(infos) <= 10000:
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            names = {}
            total_uncompressed = 0
            for info in infos:
                name = info.filename
                parts = name.rstrip("/").split("/")
                if (not name or name.startswith("/") or "\\" in name
                        or ":" in name or "\x00" in name
                        or any(part in ("", ".", "..") for part in parts)
                        or info.flag_bits & 1
                        or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK
                        or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                folded = name.casefold()
                if folded in names:
                    _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                names[folded] = info
                if (info.file_size < 0 or info.file_size > MAX_PACKAGE_BYTES
                        or (info.is_dir() and info.file_size != 0)):
                    _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_MSIX_TOTAL_UNCOMPRESSED_BYTES:
                    _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            xml_roots = {}
            for name, limit in MAX_MSIX_XML_BYTES.items():
                info = names.get(name.casefold())
                if info is None or info.filename != name or info.is_dir() or info.file_size > limit:
                    _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                with archive.open(info) as stream:
                    raw = stream.read(limit + 1)
                if len(raw) > limit or len(raw) != info.file_size:
                    _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                xml_roots[name] = ET.fromstring(raw)
            algorithm, expected_blocks = _expected_blockmap_hashes(
                xml_roots["AppxBlockMap.xml"], names, handle
            )
            # Verify both the ZIP CRC and every mapped uncompressed 64-KiB
            # cryptographic digest. Stream bounded chunks; never extract.
            for info in infos:
                if info.is_dir():
                    continue
                with archive.open(info) as stream:
                    observed = 0
                    mapped = expected_blocks.get(info.filename.casefold())
                    if mapped is not None:
                        for digest in mapped:
                            expected_size = min(_BLOCK_BYTES, info.file_size - observed)
                            block = stream.read(expected_size)
                            if (len(block) != expected_size
                                    or algorithm(block).digest() != digest):
                                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                            observed += len(block)
                        if stream.read(1):
                            _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                    else:
                        while True:
                            block = stream.read(1024 * 1024)
                            if not block:
                                break
                            observed += len(block)
                            if observed > info.file_size:
                                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
                    if observed != info.file_size:
                        _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            manifest = xml_roots["AppxManifest.xml"]
            namespace = next(
                (ns for ns in _MANIFEST_NAMESPACES if manifest.tag == f"{{{ns}}}Package"),
                None,
            )
            if namespace is None:
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            identity = manifest.find(f"{{{namespace}}}Identity")
            if identity is None or any(
                not identity.get(k) for k in ("Name", "Publisher", "Version")
            ):
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            version = identity.get("Version")
            if not _MSIX_VERSION.fullmatch(version) or any(
                int(v) > 65535 for v in version.split(".")
            ):
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
            if xml_roots["[Content_Types].xml"].tag != (
                "{http://schemas.openxmlformats.org/package/2006/content-types}Types"
            ):
                _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")
    except AccountingHumanQAHold:
        raise
    except (OSError, ValueError, RuntimeError, OverflowError,
            zipfile.BadZipFile, ET.ParseError, NotImplementedError,
            EOFError, zlib.error):
        _hold("HOLD_ACCOUNTING_EVIDENCE_MSIX_INVALID")



def _hold(code: str):
    raise AccountingHumanQAHold(code)


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _hold("HOLD_ACCOUNTING_EVIDENCE_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_constant(_value):
    _hold("HOLD_ACCOUNTING_EVIDENCE_JSON_INVALID")


def _check_no_symlink(path: Path):
    path = path.absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            _hold("HOLD_ACCOUNTING_EVIDENCE_SYMLINK")


def _read_file(path: Path, limit: int) -> bytes:
    _check_no_symlink(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            meta = os.fstat(handle.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
                _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_INVALID")
            data = handle.read(limit + 1)
            if len(data) > limit or len(data) != meta.st_size:
                _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_INVALID")
            return data
    except AccountingHumanQAHold:
        raise
    except (OSError, ValueError):
        _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_UNAVAILABLE")


def _hash_file(path: Path, limit: int, *, verify_msix: bool = False,
               expected_sha256: str | None = None) -> tuple[str, bytes]:
    """Stream large MSIX/checker files; never buffer a 2 GiB package in RAM."""
    _check_no_symlink(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            meta = os.fstat(handle.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
                _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_INVALID")
            digest = hashlib.sha256()
            total = 0
            header = b""
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                if not header:
                    header = block[:4]
                total += len(block)
                if total > limit:
                    _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_INVALID")
                digest.update(block)
            if total != meta.st_size:
                _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_INVALID")
            actual_sha256 = digest.hexdigest()
            if expected_sha256 is not None and actual_sha256 != expected_sha256:
                _hold("HOLD_ACCOUNTING_EVIDENCE_PACKAGE_MISMATCH")
            if verify_msix:
                _verify_msix_container(handle)
            return actual_sha256, header
    except AccountingHumanQAHold:
        raise
    except (OSError, ValueError):
        _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_UNAVAILABLE")


def _png_dimensions(data: bytes):
    """Fail closed on corrupt PNG pixel streams, not just chunk CRCs.

    The screenshot contract is exactly 1024x768. For that resolution accept
    non-interlaced 8-bit RGB/RGBA, as emitted by standard Windows screenshot
    capture. Indexed/interlaced/16-bit formats require a separately reviewed
    decoder; accepting their CRCs alone would not validate their pixels.
    """
    if not data.startswith(PNG_SIGNATURE):
        _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
    offset = len(PNG_SIGNATURE)
    dimensions = None
    channels = None
    seen_idat = False
    idat_closed = False
    seen_plte = False
    idat_parts = []
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
        chunk_type = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if (any(not (65 <= c <= 90 or 97 <= c <= 122) for c in chunk_type)
                or not (65 <= chunk_type[2] <= 90)
                or zlib.crc32(chunk_type + payload) & 0xffffffff != crc):
            _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
        if dimensions is None:
            if chunk_type != b"IHDR" or length != 13:
                _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", payload))
            if (not width or not height or depth != 8 or color not in (2, 6)
                    or compression != 0 or filtering != 0 or interlace != 0):
                _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
            dimensions = (width, height)
            channels = 3 if color == 2 else 4
        elif chunk_type == b"IHDR":
            _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
        elif chunk_type == b"PLTE":
            if seen_plte or seen_idat or length == 0 or length % 3 or length > 768:
                _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
            seen_plte = True
        elif chunk_type == b"IDAT":
            if idat_closed:
                _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
            seen_idat = True
            idat_parts.append(payload)
        elif chunk_type == b"IEND":
            if length != 0 or end != len(data) or not seen_idat:
                _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
            if dimensions == (1024, 768):
                row_bytes = dimensions[0] * channels
                expected = dimensions[1] * (row_bytes + 1)
                try:
                    decoder = zlib.decompressobj()
                    raw = decoder.decompress(b"".join(idat_parts), expected + 1)
                    raw += decoder.flush(expected + 1 - len(raw))
                except (zlib.error, ValueError):
                    _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
                if (len(raw) != expected or not decoder.eof
                        or decoder.unused_data or decoder.unconsumed_tail
                        or any(raw[row * (row_bytes + 1)] > 4
                               for row in range(dimensions[1]))):
                    _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
            return dimensions
        else:
            if not (chunk_type[0] & 0x20):
                _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
        if seen_idat and chunk_type != b"IDAT":
            idat_closed = True
        offset = end
    _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")


def read_local_accounting_human_evidence(
    job: dict, *, evidence_root: str | Path,
    package_path: str | Path, checker_report_path: str | Path,
) -> dict:
    """Return local evidence only when every exact file digest is verified.

    Evidence layout is fixed: evidence.json and screenshots/<scenario>.png.
    The job and evidence are still validated by validate_accounting_human_qa.
    Never trust the returned data as a GUI_QA_PASS or E2E_PASS.
    """
    if type(job) is not dict:
        _hold("HOLD_ACCOUNTING_EVIDENCE_JOB_INVALID")
    root = Path(evidence_root).absolute()
    _check_no_symlink(root)
    if not root.is_dir():
        _hold("HOLD_ACCOUNTING_EVIDENCE_ROOT_INVALID")
    try:
        evidence = json.loads(
            _read_file(root / "evidence.json", MAX_EVIDENCE_BYTES).decode("utf-8"),
            object_pairs_hook=_strict_pairs, parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError):
        _hold("HOLD_ACCOUNTING_EVIDENCE_JSON_INVALID")
    if type(evidence) is not dict or type(evidence.get("scenarios")) is not dict:
        _hold("HOLD_ACCOUNTING_EVIDENCE_SCHEMA")
    if set(evidence["scenarios"]) != set(SCENARIO_ASSERTIONS):
        _hold("HOLD_ACCOUNTING_EVIDENCE_SCHEMA")
    if type(job.get("package_sha256")) is not str or type(job.get("checker_report_sha256")) is not str:
        _hold("HOLD_ACCOUNTING_EVIDENCE_JOB_INVALID")
    package_digest, package_header = _hash_file(Path(package_path), MAX_PACKAGE_BYTES, verify_msix=True,
                                               expected_sha256=job["package_sha256"])
    if package_header != bytes((80, 75, 3, 4)) or package_digest != job["package_sha256"]:
        _hold("HOLD_ACCOUNTING_EVIDENCE_PACKAGE_MISMATCH")
    checker_digest, _ = _hash_file(Path(checker_report_path), MAX_CHECKER_BYTES)
    if checker_digest != job["checker_report_sha256"]:
        _hold("HOLD_ACCOUNTING_EVIDENCE_CHECKER_MISMATCH")
    seen = set()
    for name in SCENARIO_ASSERTIONS:
        screenshot = _read_file(root / "screenshots" / (name + ".png"), MAX_PNG_BYTES)
        if _png_dimensions(screenshot) != (1024, 768):
            _hold("HOLD_ACCOUNTING_EVIDENCE_RESOLUTION")
        digest = hashlib.sha256(screenshot).hexdigest()
        scenario = evidence["scenarios"][name]
        if type(scenario) is not dict or scenario.get("screenshot_sha256") != digest:
            _hold("HOLD_ACCOUNTING_EVIDENCE_SCREENSHOT_MISMATCH")
        if digest in seen:
            _hold("HOLD_ACCOUNTING_EVIDENCE_SCREENSHOT_REUSED")
        seen.add(digest)
    return evidence
