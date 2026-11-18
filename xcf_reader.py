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
"""
Read GIMP XCF files: the layer tree, each layer's pixels as 8-bit sRGB
RGBA (masks applied), and the image's guides and resolution. Pure Python
plus numpy.

Follows GIMP 3.2's loader (app/xcf/xcf-load.c): XCF versions 0 to 26;
64-bit offsets from version 11; layer effect pointers from version 20
(channels and masks from 26); precision codes from version 4 (the
hundreds give the component type, xx00 means linear light); components
big-endian from version 12, in the writer's (little-endian) order
before; tiles uncompressed, RLE or zlib.

Layer effects (GIMP 3's non-destructive filters) are not applied: the
pixels are the layer's own, without its effects.
"""

import struct
import zlib

import numpy as np

TILE = 64

PROP_END = 0
PROP_COLORMAP = 1
PROP_OPACITY = 6
PROP_MODE = 7
PROP_VISIBLE = 8
PROP_APPLY_MASK = 11
PROP_OFFSETS = 15
PROP_COMPRESSION = 17
PROP_GUIDES = 18
PROP_RESOLUTION = 19
PROP_GROUP_ITEM = 29
PROP_ITEM_PATH = 30
PROP_FLOAT_OPACITY = 33

# component type by the hundreds of the precision code (version 7 on)
DTYPES = {1: "u1", 2: "u2", 3: "u4", 5: "f2", 6: "f4", 7: "f8"}


class XcfError(ValueError):
    pass


class Layer:
    def __init__(self):
        self.name = ""
        self.width = self.height = 0
        self.x = self.y = 0
        self.opacity = 1.0
        self.visible = True
        self.mode = 0
        self.group = False
        self.path = ()  # index at each level, topmost first
        self.pixels = None  # H x W x 4 uint8, sRGB, straight alpha
        self.children = []  # for groups, topmost first
        self.has_effects = False


class Image:
    def __init__(self):
        self.version = 0
        self.width = self.height = 0
        self.base_type = 0  # 0 RGB, 1 grey, 2 indexed
        self.precision = 150
        self.dpi = (72.0, 72.0)
        self.guides = []  # ("h" | "v", position in pixels)
        self.layers = []  # top-level, topmost first
        self.all_layers = []  # every layer, file order


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.pointer_size = 4

    def u32(self):
        if self.pos + 4 > len(self.data):
            raise XcfError("file ends early")
        (value,) = struct.unpack_from(">I", self.data, self.pos)
        self.pos += 4
        return value

    def i32(self):
        (value,) = struct.unpack_from(">i", self.data, self.pos)
        self.pos += 4
        return value

    def pointer(self):
        fmt = ">Q" if self.pointer_size == 8 else ">I"
        (value,) = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += self.pointer_size
        return value

    def string(self):
        length = self.u32()
        text = self.data[self.pos : self.pos + length]
        self.pos += length
        return text[:-1].decode("utf-8", "replace") if length else ""

    def properties(self):
        props = {}
        while True:
            kind, size = self.u32(), self.u32()
            if kind == PROP_END:
                return props
            props[kind] = self.data[self.pos : self.pos + size]
            self.pos += size


def _component_type(precision, version):
    if version < 4:
        return "u1", False
    if version == 4:
        return {
            0: ("u1", False),
            1: ("u2", False),
            2: ("u4", True),
            3: ("f2", True),
            4: ("f4", True),
        }[precision]
    if version in (5, 6):
        return {
            100: ("u1", True),
            150: ("u1", False),
            200: ("u2", True),
            250: ("u2", False),
            300: ("u4", True),
            350: ("u4", False),
            400: ("f2", True),
            450: ("f2", False),
            500: ("f4", True),
            550: ("f4", False),
        }[precision]
    kind = DTYPES.get(precision // 100)
    if kind is None:
        raise XcfError(f"unknown precision {precision}")
    return kind, precision % 100 == 0


def _rle(data, count, bpp):
    """GIMP's tile RLE: one stream per byte of the pixel."""
    out = np.empty((bpp, count), np.uint8)
    pos = 0
    for plane in range(bpp):
        filled = 0
        row = out[plane]
        while filled < count:
            op = data[pos]
            pos += 1
            if op <= 126:
                row[filled : filled + op + 1] = data[pos]
                filled += op + 1
                pos += 1
            elif op == 127:
                n = data[pos] * 256 + data[pos + 1]
                row[filled : filled + n] = data[pos + 2]
                filled += n
                pos += 3
            elif op == 128:
                n = data[pos] * 256 + data[pos + 1]
                row[filled : filled + n] = np.frombuffer(data, np.uint8, n, pos + 2)
                filled += n
                pos += 2 + n
            else:
                n = 256 - op
                row[filled : filled + n] = np.frombuffer(data, np.uint8, n, pos)
                filled += n
                pos += n
        if filled != count:
            raise XcfError("RLE run crosses a channel")
    return out.T.reshape(-1).tobytes()


class Decoder:
    def __init__(self, data):
        self.r = _Reader(data)
        self.image = Image()

    # -- pixels

    def hierarchy(self, offset, channels):
        """The first level of a hierarchy as an H x W x channels float
        array in 0..1 (linear or not, as stored)."""
        r = self.r
        r.pos = offset
        width, height, bpp = r.u32(), r.u32(), r.u32()
        level = r.pointer()
        r.pos = level
        lw, lh = r.u32(), r.u32()
        if (lw, lh) != (width, height):
            raise XcfError("level size differs from its hierarchy")
        kind, _linear = self.kind
        size = int(kind[1])
        if bpp != channels * size:
            raise XcfError(f"{bpp} bytes per pixel, expected {channels} x {size}")
        order = ">" if self.image.version >= 12 or size == 1 else "<"
        dtype = np.dtype(order + kind)
        rows, cols = -(-height // TILE), -(-width // TILE)
        pointers = [r.pointer() for _ in range(rows * cols)]
        out = np.zeros((height, width, channels), np.float64)
        scale = {1: 255.0, 2: 65535.0, 4: 4294967295.0}[size] if kind[0] == "u" else 1.0
        for index, start in enumerate(pointers):
            if start == 0:
                break  # empty level
            ty, tx = divmod(index, cols)
            tw, th = min(TILE, width - tx * TILE), min(TILE, height - ty * TILE)
            count = tw * th
            end = (
                pointers[index + 1]
                if index + 1 < len(pointers) and pointers[index + 1]
                else None
            )
            raw = (
                self.r.data[start:end]
                if end
                else self.r.data[start : start + int(count * bpp * 1.5) + 64]
            )
            if self.compression == 0:
                tile = raw[: count * bpp]
            elif self.compression == 1:
                tile = _rle(raw, count, bpp)
            elif self.compression == 2:
                tile = zlib.decompressobj().decompress(raw)[: count * bpp]
            else:
                raise XcfError(f"unknown compression {self.compression}")
            values = (
                np.frombuffer(tile, dtype, count * channels).astype(np.float64) / scale
            )
            out[ty * TILE : ty * TILE + th, tx * TILE : tx * TILE + tw] = (
                values.reshape(th, tw, channels)
            )
        return out

    # -- structures

    def layer(self, offset):
        r = self.r
        r.pos = offset
        layer = Layer()
        layer.width, layer.height = r.u32(), r.u32()
        layer_type = r.u32()
        layer.name = r.string()
        props = r.properties()
        hierarchy = r.pointer()
        mask = r.pointer()
        if self.image.version >= 20:
            layer.has_effects = r.pointer() != 0
        if PROP_OFFSETS in props:
            layer.x, layer.y = struct.unpack(">ii", props[PROP_OFFSETS])
        if PROP_OPACITY in props:
            layer.opacity = struct.unpack(">I", props[PROP_OPACITY])[0] / 255.0
        if PROP_FLOAT_OPACITY in props:
            layer.opacity = struct.unpack(">f", props[PROP_FLOAT_OPACITY])[0]
        if PROP_VISIBLE in props:
            layer.visible = struct.unpack(">I", props[PROP_VISIBLE])[0] != 0
        if PROP_MODE in props:
            layer.mode = struct.unpack(">I", props[PROP_MODE])[0]
        layer.group = PROP_GROUP_ITEM in props
        if PROP_ITEM_PATH in props:
            raw = props[PROP_ITEM_PATH]
            layer.path = struct.unpack(f">{len(raw) // 4}I", raw)
        apply_mask = (
            struct.unpack(">I", props[PROP_APPLY_MASK])[0] != 0
            if PROP_APPLY_MASK in props
            else True
        )
        if not layer.group and hierarchy:
            layer.pixels = self.pixels(hierarchy, layer_type)
            if mask and apply_mask:
                alpha = self.mask(mask)
                if alpha is not None and alpha.shape == layer.pixels.shape[:2]:
                    a = layer.pixels[..., 3].astype(np.float64) * alpha
                    layer.pixels[..., 3] = np.clip(np.round(a), 0, 255).astype(np.uint8)
        return layer

    def mask(self, offset):
        r = self.r
        r.pos = offset
        r.u32(), r.u32()
        r.string()
        r.properties()
        hierarchy = r.pointer()
        if self.image.version >= 26:
            r.pointer()  # effects
        values = self.hierarchy(hierarchy, 1)[..., 0]
        # GIMP uses a mask's stored value as opacity as it is, in linear
        # and non-linear images alike (checked against GIMP 3.2)
        return np.clip(values, 0, 1)

    def to_display(self, values):
        """Stored values to non-linear (sRGB-encoded) 0..1."""
        _kind, linear = self.kind
        values = np.clip(values, 0.0, 1.0)
        if linear:
            values = np.where(
                values <= 0.0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - 0.055
            )
        return values

    def pixels(self, hierarchy, layer_type):
        has_alpha = layer_type % 2 == 1
        base = layer_type // 2  # 0 RGB, 1 grey, 2 indexed
        channels = (3, 1, 1)[base] + (1 if has_alpha else 0)
        if base == 2:
            # indexed: always 8-bit indices into the colour map
            saved = self.kind
            self.kind = ("u1", False)
            values = self.hierarchy(hierarchy, channels)
            self.kind = saved
            index = np.round(values[..., 0] * 255).astype(int)
            rgb = self.colormap[np.clip(index, 0, len(self.colormap) - 1)] / 255.0
            alpha = values[..., 1] if has_alpha else np.ones(index.shape)
            return np.dstack([np.round(rgb * 255), np.round(alpha * 255)]).astype(
                np.uint8
            )
        values = self.hierarchy(hierarchy, channels)
        colour = values[..., : channels - (1 if has_alpha else 0)]
        alpha = values[..., -1] if has_alpha else np.ones(values.shape[:2])
        colour = self.to_display(colour)
        if base == 1:
            colour = np.repeat(colour, 3, axis=2)
        alpha = np.clip(alpha, 0, 1)  # alpha is always linear
        rgba = np.dstack([colour, alpha])
        return np.clip(np.round(rgba * 255), 0, 255).astype(np.uint8)

    def decode(self):
        r, image = self.r, self.image
        magic = r.data[:14]
        if not magic.startswith(b"gimp xcf "):
            raise XcfError("not an XCF file")
        tag = magic[9:13]
        image.version = 0 if tag == b"file" else int(tag[1:])
        r.pointer_size = 8 if image.version >= 11 else 4
        r.pos = 14
        image.width, image.height, image.base_type = r.u32(), r.u32(), r.u32()
        if image.version >= 4:
            image.precision = r.u32()
        self.kind = _component_type(image.precision, image.version)
        props = r.properties()
        self.compression = props.get(PROP_COMPRESSION, b"\x00")[0]
        if PROP_RESOLUTION in props:
            image.dpi = struct.unpack(">ff", props[PROP_RESOLUTION])
        if PROP_GUIDES in props:
            raw = props[PROP_GUIDES]
            for i in range(0, len(raw) - 4, 5):
                position = struct.unpack_from(">i", raw, i)[0]
                image.guides.append(("h" if raw[i + 4] == 1 else "v", position))
        self.colormap = np.zeros((1, 3))
        if PROP_COLORMAP in props:
            raw = props[PROP_COLORMAP]
            count = struct.unpack_from(">I", raw)[0]
            self.colormap = (
                np.frombuffer(raw, np.uint8, 3 * count, 4)
                .reshape(count, 3)
                .astype(float)
            )
        pointers = []
        while True:
            p = r.pointer()
            if not p:
                break
            pointers.append(p)
        for p in pointers:
            image.all_layers.append(self.layer(p))
        # rebuild the tree from the item paths, as GIMP does
        for layer in image.all_layers:
            if len(layer.path) <= 1:
                image.layers.append(layer)
            else:
                parent = image.layers
                node = None
                for index in layer.path[:-1]:
                    node = parent[index]
                    parent = node.children
                parent.append(layer)
        return image


def read(data):
    """An Image from the bytes of an XCF file."""
    return Decoder(bytes(data)).decode()
