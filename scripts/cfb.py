"""Minimal reader for Compound File Binary (OLE2) files – enough to open Outlook .msg statements:
the message body and the attachments (often the actual statement as a PDF or Word file).

No dependencies (the standard library only). Format: [MS-CFB] – a FAT-chained sector file with a directory
of storages and streams; small streams live in the "mini stream" with 64-byte sectors.
"""
from __future__ import annotations

import struct

ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class CFB:
    def __init__(self, data: bytes):
        if data[:8] != MAGIC:
            raise ValueError("not a compound file")
        self.data = data
        self.ssize = 1 << struct.unpack_from("<H", data, 0x1E)[0]
        self.mssize = 1 << struct.unpack_from("<H", data, 0x20)[0]
        first_dir, = struct.unpack_from("<I", data, 0x30)
        self.cutoff, = struct.unpack_from("<I", data, 0x38)
        first_minifat, n_minifat, first_difat, n_difat = struct.unpack_from("<IIII", data, 0x3C)
        difat = [x for x in struct.unpack_from("<109I", data, 0x4C) if x not in (FREESECT, ENDOFCHAIN)]
        sect, per = first_difat, self.ssize // 4 - 1
        for _ in range(n_difat):
            if sect in (FREESECT, ENDOFCHAIN):
                break
            vals = struct.unpack_from(f"<{per + 1}I", self._sector(sect))
            difat += [x for x in vals[:per] if x not in (FREESECT, ENDOFCHAIN)]
            sect = vals[per]
        self.fat: list[int] = []
        for s in difat:
            self.fat += struct.unpack_from(f"<{self.ssize // 4}I", self._sector(s))
        dir_bytes = self._chain(first_dir)
        self.entries = []
        for off in range(0, len(dir_bytes) - 127, 128):
            e = dir_bytes[off:off + 128]
            nlen = struct.unpack_from("<H", e, 64)[0]
            name = e[:max(0, nlen - 2)].decode("utf-16le", "ignore")
            typ = e[66]
            left, right, child = struct.unpack_from("<III", e, 68)
            start, size = struct.unpack_from("<II", e, 116)
            self.entries.append({"name": name, "type": typ, "left": left, "right": right, "child": child, "start": start, "size": size})
        root = self.entries[0]
        self.ministream = self._chain(root["start"])[:root["size"]] if root["start"] not in (ENDOFCHAIN, FREESECT) else b""
        self.minifat: list[int] = []
        if n_minifat and first_minifat not in (ENDOFCHAIN, FREESECT):
            mf = self._chain(first_minifat)
            self.minifat = list(struct.unpack_from(f"<{len(mf) // 4}I", mf))

    def _sector(self, n: int) -> bytes:
        off = (n + 1) * self.ssize
        return self.data[off:off + self.ssize]

    def _chain(self, start: int) -> bytes:
        out, seen, s = [], set(), start
        while s not in (ENDOFCHAIN, FREESECT) and s < len(self.fat) and s not in seen:
            seen.add(s)
            out.append(self._sector(s))
            s = self.fat[s]
        return b"".join(out)

    def _minichain(self, start: int) -> bytes:
        out, seen, s = [], set(), start
        while s not in (ENDOFCHAIN, FREESECT) and s < len(self.minifat) and s not in seen:
            seen.add(s)
            out.append(self.ministream[s * self.mssize:(s + 1) * self.mssize])
            s = self.minifat[s]
        return b"".join(out)

    def read(self, idx: int) -> bytes:
        e = self.entries[idx]
        raw = self._minichain(e["start"]) if e["size"] < self.cutoff else self._chain(e["start"])
        return raw[:e["size"]]

    def children(self, idx: int) -> list[int]:
        """Entry ids directly inside a storage (the red-black tree of siblings under its child pointer)."""
        out, stack, seen = [], [self.entries[idx]["child"]], set()
        while stack:
            i = stack.pop()
            if i >= len(self.entries) or i in seen or i == FREESECT:
                continue
            seen.add(i)
            out.append(i)
            stack += [self.entries[i]["left"], self.entries[i]["right"]]
        return out

    def find(self, idx: int, name: str) -> int | None:
        for c in self.children(idx):
            if self.entries[c]["name"].lower() == name.lower():
                return c
        return None


def msg_parts(data: bytes, depth: int = 0) -> dict:
    """Outlook .msg -> {"subject", "body", "attachments": [(filename, bytes)]}; embedded messages are flattened."""
    f = CFB(data)

    def text(storage: int, tag: str) -> str:
        i = f.find(storage, f"__substg1.0_{tag}001F")
        if i is not None:
            return f.read(i).decode("utf-16le", "ignore").rstrip("\x00")
        i = f.find(storage, f"__substg1.0_{tag}001E")
        return f.read(i).decode("cp1252", "ignore").rstrip("\x00") if i is not None else ""

    def walk(storage: int, level: int) -> dict:
        out = {"subject": text(storage, "0037"), "body": text(storage, "1000"), "attachments": []}
        if not out["body"]:
            i = f.find(storage, "__substg1.0_10130102")  # HTML body
            if i is not None:
                out["body"] = f.read(i).decode("utf-8", "ignore")
        for c in f.children(storage):
            e = f.entries[c]
            if e["type"] != 1 or not e["name"].lower().startswith("__attach_version1.0_"):
                continue
            name = text(c, "3707") or text(c, "3704") or "liite"
            d = f.find(c, "__substg1.0_37010102")
            if d is not None:
                out["attachments"].append((name, f.read(d)))
                continue
            emb = f.find(c, "__substg1.0_3701000D")
            if emb is not None and level < 2:
                sub = walk(emb, level + 1)
                out["body"] += "\n" + sub["body"]
                out["attachments"] += sub["attachments"]
        return out

    return walk(0, depth)
