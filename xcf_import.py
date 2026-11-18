#!/usr/bin/env python3
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
Open a GIMP XCF file in Inkscape with its layers: each GIMP layer becomes
an Inkscape layer holding the layer's pixels at its position, layer
groups become sublayers, and visibility, opacity, blend mode (where CSS
has it) and guides are kept. Layer masks are applied to the pixels.
"""

import base64
import io
import os
import sys

import inkex
from inkex.localization import inkex_gettext as _
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import xcf_reader

# GIMP layer mode -> CSS mix-blend-mode (legacy and current modes)
BLEND = {
    3: "multiply",
    30: "multiply",
    4: "screen",
    31: "screen",
    5: "overlay",
    23: "overlay",
    6: "difference",
    32: "difference",
    9: "darken",
    35: "darken",
    10: "lighten",
    36: "lighten",
    16: "color-dodge",
    42: "color-dodge",
    17: "color-burn",
    43: "color-burn",
    18: "hard-light",
    44: "hard-light",
    19: "soft-light",
    45: "soft-light",
    52: "exclusion",
    11: "hue",
    24: "hue",
    37: "hue",
    12: "saturation",
    25: "saturation",
    38: "saturation",
    13: "color",
    26: "color",
    39: "color",
    14: "luminosity",
    27: "luminosity",
    40: "luminosity",
}
NORMAL = {0, 28, 61}  # normal (legacy, current) and pass-through


def png_uri(pixels):
    out = io.BytesIO()
    Image.fromarray(pixels, "RGBA").save(out, "PNG", optimize=False, compress_level=6)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


class XcfImport(inkex.InputExtension):
    """Open GIMP XCF files with their layers"""

    def add_arguments(self, pars):
        pars.add_argument("--tab")
        pars.add_argument("--size", default="resolution", help="resolution or pixels")
        pars.add_argument("--pixelated", type=inkex.Boolean, default=False)

    def load(self, stream):
        try:
            return xcf_reader.read(stream.read())
        except (xcf_reader.XcfError, ValueError, KeyError, IndexError) as error:
            raise inkex.AbortExtension(
                _("Could not read this XCF file: {}").format(error)
            ) from error

    def effect(self):
        image = self.document
        dpi_x, dpi_y = image.dpi
        if self.options.size == "pixels" or not (dpi_x > 0 and dpi_y > 0):
            size = (f"{image.width}px", f"{image.height}px")
        else:
            size = (
                f"{image.width / dpi_x * 25.4:.6g}mm",
                f"{image.height / dpi_y * 25.4:.6g}mm",
            )
        svg = inkex.load_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
            f'width="{size[0]}" height="{size[1]}" viewBox="0 0 {image.width} {image.height}"/>'
        ).getroot()
        self.notes = []
        for layer in reversed(image.layers):  # SVG paints the last one on top
            svg.append(self.element(layer))
        for orientation, position in image.guides:
            svg.namedview.add_guide(position, orientation == "h")
        if self.notes:
            inkex.errormsg("\n".join(self.notes))
        self.document = svg.getroottree()

    def element(self, layer):
        group = inkex.Layer.new(layer.name or _("Layer"))
        style = {}
        if not layer.visible:
            style["display"] = "none"
        if layer.opacity < 1.0:
            style["opacity"] = f"{layer.opacity:.4g}"
        if layer.mode in BLEND:
            style["mix-blend-mode"] = BLEND[layer.mode]
        elif layer.mode not in NORMAL:
            self.notes.append(
                _(
                    "Layer '{}': its GIMP layer mode has no counterpart in Inkscape; shown as Normal."
                ).format(layer.name)
            )
        if layer.has_effects:
            self.notes.append(
                _("Layer '{}': its GIMP effects (filters) are not applied.").format(
                    layer.name
                )
            )
        if style:
            group.style = style
        if layer.group:
            for child in reversed(layer.children):
                group.append(self.element(child))
            return group
        if layer.pixels is not None and layer.width and layer.height:
            picture = inkex.Image()
            picture.set("x", str(layer.x))
            picture.set("y", str(layer.y))
            picture.set("width", str(layer.width))
            picture.set("height", str(layer.height))
            picture.set("preserveAspectRatio", "none")
            if self.options.pixelated:
                picture.style["image-rendering"] = "pixelated"
            picture.set("xlink:href", png_uri(layer.pixels))
            group.append(picture)
        return group


if __name__ == "__main__":
    XcfImport().run()
