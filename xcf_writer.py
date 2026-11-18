#!/usr/bin/env python3
# coding=utf-8
#
# Copyright (C) 2026 David
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
"""
A small writer for GIMP's XCF format: 8-bit RGBA layers, layer groups,
guides, a grid and the resolution. Pure Python plus numpy, so it needs
no GIMP: it works inside a Flatpak sandbox and on every platform.

The layout follows GIMP's own writer (app/xcf/xcf-save.c in GIMP 3.2)
and the format description in GIMP's devel-docs. It writes XCF version
10 (GIMP 2.10 and later), with zlib-compressed tiles, the way GIMP
itself saves an 8-bit image that uses the modern layer modes.
"""

import struct
import zlib

import numpy as np

TILE = 64

# Property types, see app/xcf/xcf-private.h
PROP_END = 0
PROP_OPACITY = 6
PROP_MODE = 7
PROP_VISIBLE = 8
PROP_OFFSETS = 15
PROP_COMPRESSION = 17
PROP_GUIDES = 18
PROP_RESOLUTION = 19
PROP_PARASITES = 21
PROP_UNIT = 22
PROP_GROUP_ITEM = 29
PROP_ITEM_PATH = 30
PROP_GROUP_ITEM_FLAGS = 31
PROP_FLOAT_OPACITY = 33
PROP_COMPOSITE_MODE = 35
PROP_COMPOSITE_SPACE = 36
PROP_BLEND_SPACE = 37

COMPRESS_ZLIB = 2

# Layer modes (GimpLayerMode), the "since XCF 9/10" ones
MODE_OVERLAY = 23
MODE_LCH_HUE = 24
MODE_LCH_CHROMA = 25
MODE_LCH_COLOR = 26
MODE_LCH_LIGHTNESS = 27
MODE_NORMAL = 28
MODE_MULTIPLY = 30
MODE_SCREEN = 31
MODE_DIFFERENCE = 32
MODE_DARKEN_ONLY = 35
MODE_LIGHTEN_ONLY = 36
MODE_DODGE = 42
MODE_BURN = 43
MODE_HARDLIGHT = 44
MODE_SOFTLIGHT = 45
MODE_EXCLUSION = 52
MODE_PASS_THROUGH = 61

# GimpLayerColorSpace
SPACE_RGB_LINEAR = 1
SPACE_RGB_NON_LINEAR = 2

# GimpLayerCompositeMode
COMPOSITE_UNION = 1

# PROP_UNIT values
UNITS = {"in": 1, "mm": 2, "pt": 3, "pc": 4}

XCF_VERSION = 10
PRECISION_U8_NON_LINEAR = 150


class Layer:
    """A pixel layer: an H x W x 4 uint8 RGBA array (not premultiplied)
    placed at (x, y) on the canvas."""

    def __init__(
        self,
        name,
        pixels,
        x=0,
        y=0,
        opacity=1.0,
        visible=True,
        mode=MODE_NORMAL,
        blend_space=None,
        composite_space=None,
        composite_mode=None,
    ):
        pixels = np.ascontiguousarray(pixels, dtype=np.uint8)
        if pixels.ndim != 3 or pixels.shape[2] != 4:
            raise ValueError("a layer needs H x W x 4 RGBA pixels")
        self.name = name
        self.pixels = pixels
        self.x, self.y = int(x), int(y)
        self.opacity = float(opacity)
        self.visible = bool(visible)
        self.mode = mode
        self.blend_space = blend_space
        self.composite_space = composite_space
        self.composite_mode = composite_mode

    @property
    def bounds(self):
        h, w = self.pixels.shape[:2]
        return self.x, self.y, self.x + w, self.y + h


class Group:
    """A layer group; children are listed bottom first (document order)."""

    def __init__(
        self,
        name,
        children,
        opacity=1.0,
        visible=True,
        mode=MODE_PASS_THROUGH,
        expanded=True,
        blend_space=None,
        composite_space=None,
        composite_mode=None,
    ):
        self.name = name
        self.children = list(children)
        self.opacity = float(opacity)
        self.visible = bool(visible)
        self.mode = mode
        self.expanded = bool(expanded)
        self.blend_space = blend_space
        self.composite_space = composite_space
        self.composite_mode = composite_mode

    @property
    def bounds(self):
        boxes = [c.bounds for c in self.children]
        if not boxes:
            return 0, 0, 1, 1
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )


def _string(text):
    data = text.encode("utf-8")
    return struct.pack(">I", len(data) + 1) + data + b"\0"


def _prop(ptype, payload=b""):
    return struct.pack(">II", ptype, len(payload)) + payload


def _u32(value):
    return struct.pack(">I", value)


def _i32(value):
    return struct.pack(">i", value)


class _Out:
    """A growing byte buffer with 32-bit pointers that are patched later."""

    def __init__(self):
        self.buf = bytearray()

    @property
    def pos(self):
        return len(self.buf)

    def write(self, data):
        self.buf += data

    def pointer_slot(self):
        """Reserve a pointer, return its position for patch()."""
        slot = self.pos
        self.buf += b"\0\0\0\0"
        return slot

    def patch(self, slot, value):
        if value >= 1 << 32:
            raise ValueError("XCF file too large for 32-bit offsets (over 4 GB)")
        self.buf[slot : slot + 4] = _u32(value)


def _flatten(items, path=()):
    """Depth-first, topmost first, as GIMP lists layers: yields
    (item, item_path) where item_path is the index at each level."""
    top_first = list(reversed(items))
    for index, item in enumerate(top_first):
        here = path + (index,)
        yield item, here
        if isinstance(item, Group):
            yield from _flatten(item.children, here)


def grid_parasite(xspacing, yspacing, xoffset=0.0, yoffset=0.0):
    """The "gimp-image-grid" parasite as GIMP 3.2 writes it (only the
    spacing and offset, in pixels; GIMP fills in the rest)."""
    text = (
        "(xspacing {:f})\n(yspacing {:f})\n(spacing-unit pixels)\n"
        "(xoffset {:f})\n(yoffset {:f})\n(offset-unit pixels)\n"
    ).format(xspacing, yspacing, xoffset, yoffset)
    return "gimp-image-grid", 1, text.encode("utf-8") + b"\0"


class XcfImage:
    """An RGB image to save as XCF."""

    def __init__(self, width, height, dpi=96.0, unit=None):
        self.width = int(width)
        self.height = int(height)
        self.dpi = float(dpi)
        self.unit = unit
        self.layers = []  # bottom first
        self.guides = []  # (orientation "h" or "v", pixel position)
        self.parasites = []  # (name, flags, bytes)

    def add_guide(self, orientation, position):
        self.guides.append((orientation, int(round(position))))

    def save(self, stream):
        stream.write(self.tobytes())

    def tobytes(self):
        out = _Out()
        out.write(b"gimp xcf v%03d\0" % XCF_VERSION)
        out.write(
            struct.pack(">IIII", self.width, self.height, 0, PRECISION_U8_NON_LINEAR)
        )
        self._write_image_props(out)

        items = list(_flatten(self.layers))
        slots = [out.pointer_slot() for _ in items]
        out.write(_u32(0))  # end of layers
        out.write(_u32(0))  # no channels

        for (item, path), slot in zip(items, slots):
            out.patch(slot, out.pos)
            self._write_layer(out, item, path)
        return bytes(out.buf)

    def _write_image_props(self, out):
        out.write(_prop(PROP_COMPRESSION, bytes([COMPRESS_ZLIB])))
        guides = [
            g
            for g in self.guides
            if 0 <= g[1] <= (self.height if g[0] == "h" else self.width)
        ]
        if guides:
            payload = b"".join(
                _i32(pos) + bytes([1 if orient == "h" else 2]) for orient, pos in guides
            )
            out.write(_prop(PROP_GUIDES, payload))
        out.write(_prop(PROP_RESOLUTION, struct.pack(">ff", self.dpi, self.dpi)))
        if self.unit in UNITS:
            out.write(_prop(PROP_UNIT, _u32(UNITS[self.unit])))
        if self.parasites:
            payload = b"".join(
                _string(name) + _u32(flags) + _u32(len(data)) + data
                for name, flags, data in self.parasites
            )
            out.write(_prop(PROP_PARASITES, payload))
        out.write(_prop(PROP_END))

    def _write_layer(self, out, item, path):
        x0, y0, x1, y1 = item.bounds
        width, height = max(1, x1 - x0), max(1, y1 - y0)
        out.write(struct.pack(">III", width, height, 1))  # 1: RGBA
        out.write(_string(item.name))

        is_group = isinstance(item, Group)
        if is_group:
            out.write(_prop(PROP_GROUP_ITEM))
        if len(path) > 1:
            out.write(_prop(PROP_ITEM_PATH, b"".join(_u32(i) for i in path)))
        opacity = min(1.0, max(0.0, item.opacity))
        out.write(_prop(PROP_OPACITY, _u32(int(round(opacity * 255)))))
        out.write(_prop(PROP_FLOAT_OPACITY, struct.pack(">f", opacity)))
        out.write(_prop(PROP_VISIBLE, _u32(1 if item.visible else 0)))
        out.write(_prop(PROP_MODE, _u32(item.mode)))
        if item.blend_space is not None:
            out.write(_prop(PROP_BLEND_SPACE, _i32(item.blend_space)))
        if item.composite_space is not None:
            out.write(_prop(PROP_COMPOSITE_SPACE, _i32(item.composite_space)))
        if item.composite_mode is not None:
            out.write(_prop(PROP_COMPOSITE_MODE, _i32(item.composite_mode)))
        out.write(_prop(PROP_OFFSETS, _i32(x0) + _i32(y0)))
        if is_group:
            out.write(_prop(PROP_GROUP_ITEM_FLAGS, _u32(1 if item.expanded else 0)))
        out.write(_prop(PROP_END))

        hptr = out.pointer_slot()
        out.write(_u32(0))  # no layer mask
        out.patch(hptr, out.pos)
        if is_group:
            # GIMP ignores a group's pixels when loading; keep them empty
            pixels = np.zeros((height, width, 4), np.uint8)
        else:
            pixels = item.pixels
        self._write_hierarchy(out, pixels)

    @staticmethod
    def _write_hierarchy(out, pixels):
        height, width = pixels.shape[:2]
        out.write(struct.pack(">III", width, height, 4))
        level = out.pointer_slot()
        # GIMP also writes dummy levels, each half the size, until both
        # sides are below 64 pixels
        dummies = []
        w, h = width, height
        while w >= TILE or h >= TILE:
            w, h = w // 2, h // 2
            dummies.append((w, h, out.pointer_slot()))
        out.write(_u32(0))

        out.patch(level, out.pos)
        out.write(struct.pack(">II", width, height))
        rows, cols = -(-height // TILE), -(-width // TILE)
        slots = [out.pointer_slot() for _ in range(rows * cols)]
        out.write(_u32(0))
        tiles = (
            pixels[r * TILE : (r + 1) * TILE, c * TILE : (c + 1) * TILE]
            for r in range(rows)
            for c in range(cols)
        )
        for slot, tile in zip(slots, tiles):
            out.patch(slot, out.pos)
            out.write(zlib.compress(np.ascontiguousarray(tile).tobytes(), 6))

        for w, h, slot in dummies:
            out.patch(slot, out.pos)
            out.write(struct.pack(">III", w, h, 0))


def crop_to_content(pixels):
    """Return (cropped pixels, x, y) without fully transparent borders, or
    None when nothing is visible."""
    alpha = pixels[:, :, 3]
    rows = np.flatnonzero(alpha.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(alpha.any(axis=0))
    y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    return pixels[y0:y1, x0:x1], int(x0), int(y0)
