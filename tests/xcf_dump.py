#!/usr/bin/env python3
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Dump the structure of an XCF file: header, image properties, parasites
and each layer's properties. An independent reader for the tests, so
that we check the writer against the format rather than against itself.

    xcf_dump.py FILE.xcf          human-readable
    xcf_dump.py --json FILE.xcf   JSON
"""

import json
import struct
import sys

PROP_NAMES = {
    0: "END", 6: "OPACITY", 7: "MODE", 8: "VISIBLE", 15: "OFFSETS",
    17: "COMPRESSION", 18: "GUIDES", 19: "RESOLUTION", 20: "TATTOO",
    21: "PARASITES", 22: "UNIT", 29: "GROUP_ITEM", 30: "ITEM_PATH",
    31: "GROUP_ITEM_FLAGS", 33: "FLOAT_OPACITY", 34: "COLOR_TAG",
    35: "COMPOSITE_MODE", 36: "COMPOSITE_SPACE", 37: "BLEND_SPACE",
}


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.ptr = 4

    def u32(self):
        (v,) = struct.unpack_from(">I", self.data, self.pos)
        self.pos += 4
        return v

    def pointer(self):
        fmt = ">Q" if self.ptr == 8 else ">I"
        (v,) = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += self.ptr
        return v

    def string(self):
        n = self.u32()
        s = self.data[self.pos:self.pos + n]
        self.pos += n
        return s[:-1].decode("utf-8") if n else ""

    def props(self):
        out = []
        while True:
            ptype, size = self.u32(), self.u32()
            payload = self.data[self.pos:self.pos + size]
            self.pos += size
            if ptype == 0:
                return out
            out.append((ptype, payload))


def parasites(payload):
    r = Reader(payload)
    found = []
    while r.pos < len(payload):
        name = r.string()
        flags = r.u32()
        n = r.u32()
        data = payload[r.pos:r.pos + n]
        r.pos += n
        found.append({"name": name, "flags": flags,
                      "data": data.rstrip(b"\0").decode("utf-8", "replace")})
    return found


def decode(ptype, payload):
    if ptype in (6, 7, 8, 22, 31, 34):
        return struct.unpack(">I", payload)[0]
    if ptype in (35, 36, 37):
        return struct.unpack(">i", payload)[0]
    if ptype == 33:
        return round(struct.unpack(">f", payload)[0], 4)
    if ptype == 15:
        return list(struct.unpack(">ii", payload))
    if ptype == 17:
        return payload[0]
    if ptype == 19:
        return [round(v, 3) for v in struct.unpack(">ff", payload)]
    if ptype == 30:
        return list(struct.unpack(">%dI" % (len(payload) // 4), payload))
    if ptype == 18:
        return [[struct.unpack_from(">i", payload, i)[0], "hv"[payload[i + 4] - 1]]
                for i in range(0, len(payload), 5)]
    if ptype == 21:
        return parasites(payload)
    if ptype == 29:
        return True
    return payload.hex()


def named(props):
    return {PROP_NAMES.get(t, str(t)): decode(t, p) for t, p in props}


def dump(path):
    with open(path, "rb") as f:
        data = f.read()
    r = Reader(data)
    magic = data[:14]
    if not magic.startswith(b"gimp xcf "):
        raise ValueError("not an XCF file")
    tag = magic[9:13].decode()
    version = 0 if tag == "file" else int(tag[1:])
    r.pos = 14
    r.ptr = 8 if version >= 11 else 4
    info = {"version": version, "width": r.u32(), "height": r.u32(),
            "base_type": r.u32()}
    if version >= 4:
        info["precision"] = r.u32()
    info["props"] = named(r.props())
    layer_ptrs = []
    while True:
        p = r.pointer()
        if not p:
            break
        layer_ptrs.append(p)
    layers = []
    for p in layer_ptrs:
        r.pos = p
        w, h, t = r.u32(), r.u32(), r.u32()
        name = r.string()
        props = named(r.props())
        layers.append({"name": name, "width": w, "height": h, "type": t,
                       "props": props})
    info["layers"] = layers
    return info


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    info = dump(args[0])
    if as_json:
        print(json.dumps(info, indent=1))
        return
    layers = info.pop("layers")
    print(json.dumps(info))
    for layer in layers:
        print(" ", json.dumps(layer))


if __name__ == "__main__":
    main()
