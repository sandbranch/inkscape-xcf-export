#!/usr/bin/env python3
#
# Copyright (C) 2006 Aaron Spike, aaron@ekips.org
# Copyright (C) 2010-2012 Nicolas Dufour, nicoduf@yahoo.fr
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
Save the document as a layered GIMP XCF file.

Unlike the old GIMP XCF output, this writes the XCF file itself, so it
needs no GIMP: it works with GIMP 3, in the Inkscape Flatpak and on
Windows. Inkscape renders each layer; the layer tree becomes GIMP's
layer tree (sublayers become layer groups), and visibility, opacity and
blend modes are kept as layer properties instead of being baked in.
"""

import copy
import os

import inkex
import numpy as np
from inkex.command import inkscape
from inkex.localization import inkex_gettext as _
from PIL import Image

import xcf_writer as xcf
from css_blend import INEXACT, bake_blend

# CSS mix-blend-mode to GIMP layer mode. CSS blends sRGB-encoded values,
# so these get GIMP's non-linear blend space (see layer_mode()).
BLEND_MODES = {
    "multiply": xcf.MODE_MULTIPLY,
    "screen": xcf.MODE_SCREEN,
    "overlay": xcf.MODE_OVERLAY,
    "darken": xcf.MODE_DARKEN_ONLY,
    "lighten": xcf.MODE_LIGHTEN_ONLY,
    "color-dodge": xcf.MODE_DODGE,
    "color-burn": xcf.MODE_BURN,
    "hard-light": xcf.MODE_HARDLIGHT,
    "soft-light": xcf.MODE_SOFTLIGHT,
    "difference": xcf.MODE_DIFFERENCE,
    "exclusion": xcf.MODE_EXCLUSION,
    "hue": xcf.MODE_LCH_HUE,
    "saturation": xcf.MODE_LCH_CHROMA,
    "color": xcf.MODE_LCH_COLOR,
    "luminosity": xcf.MODE_LCH_LIGHTNESS,
}

# Elements that are never drawn themselves
NOT_DRAWN = {
    "defs",
    "namedview",
    "metadata",
    "style",
    "script",
    "title",
    "desc",
}


def local_name(node):
    tag = node.tag
    if not isinstance(tag, str):
        return ""  # comments, processing instructions
    return tag.rsplit("}", 1)[-1]


def is_layer(node):
    return isinstance(node, inkex.Layer)


class Item:
    """One entry of the planned GIMP layer tree."""

    def __init__(
        self,
        name,
        node_id=None,
        children=None,
        opacity=1.0,
        visible=True,
        blend="normal",
        context=None,
    ):
        self.name = name
        self.context = context  # id of the nearest isolating layer
        self.node_id = node_id  # rendered as one pixel layer if set
        self.children = children  # a group if not None, bottom first
        self.opacity = opacity
        self.visible = visible
        self.blend = blend


class XcfOutput(inkex.OutputExtension):
    """Save the document as a layered GIMP XCF file"""

    dir_prefix = "xcf-out-"

    def add_arguments(self, pars):
        pars.add_argument("--tab")
        pars.add_argument("--dpi", type=float, default=96.0, help="Resolution")
        pars.add_argument(
            "--groups",
            type=inkex.Boolean,
            default=True,
            help="Turn sublayers into layer groups",
        )
        pars.add_argument(
            "--crop",
            type=inkex.Boolean,
            default=True,
            help="Crop each layer to its content",
        )
        pars.add_argument(
            "--hidden",
            type=inkex.Boolean,
            default=True,
            help="Include hidden layers (hidden in GIMP too)",
        )
        pars.add_argument(
            "--background",
            type=inkex.Boolean,
            default=False,
            help="Add the page colour as a bottom layer",
        )
        pars.add_argument(
            "--guides", type=inkex.Boolean, default=True, help="Save the guides"
        )
        pars.add_argument(
            "--grid",
            type=inkex.Boolean,
            default=False,
            help="Save the first rectangular grid",
        )
        pars.add_argument(
            "--blend", default="bake", help="Blend modes GIMP lacks: bake or gimp"
        )
        pars.add_argument(
            "--linear",
            type=inkex.Boolean,
            default=False,
            help="Composite in linear light (GIMP's default) instead of like Inkscape",
        )

    # -- planning: which pixel layers and groups to make

    def plan(self, doc):
        """Prepare the render copy `doc` and return the bottom-first list
        of top-level Items."""
        self._serial = 0
        return self._plan_children(
            doc.getroot(), self.svg.get("sodipodi:docname") or _("Objects"), top=True
        )

    def _wrap(self, parent, run, name):
        """Put a run of plain objects into one new group, to render them
        together as a single pixel layer."""
        self._serial += 1
        group = inkex.Group()
        group.set("id", f"xcf-export-run-{self._serial}")
        run[0].addprevious(group)
        for node in run:
            group.append(node)
        return Item(name, node_id=group.get("id"))

    def _plan_children(self, parent, name, top=False, context=None):
        items, run = [], []

        def flush():
            if run:
                items.append(run[:])
                run.clear()

        for node in list(parent):
            kind = local_name(node)
            if not kind or kind in NOT_DRAWN:
                continue
            if is_layer(node):
                flush()
                items.append(node)
            else:
                run.append(node)
        flush()

        runs = sum(1 for i in items if isinstance(i, list))
        planned, count = [], 0
        for entry in items:
            if isinstance(entry, list):
                count += 1
                label = name if runs == 1 else f"{name} ({count})"
                if top:
                    label = (
                        _("Objects outside layers")
                        if runs == 1
                        else f"{_('Objects outside layers')} ({count})"
                    )
                planned.append(self._wrap(parent, entry, label))
            else:
                item = self._plan_layer(entry, context)
                if item is not None:
                    planned.append(item)
        return planned

    def _plan_layer(self, layer, context=None):
        """Read a layer's visibility, opacity and blend mode, then remove
        them from the render copy so that they become GIMP properties
        and are not baked into the pixels."""
        style = layer.style
        visible = (
            style.get("display", "inline") != "none"
            and layer.get("display", "inline") != "none"
        )
        if not visible and not self.options.hidden:
            return None
        opacity = 1.0
        for value in (style.get("opacity"), layer.get("opacity")):
            if value not in (None, ""):
                try:
                    opacity *= min(1.0, max(0.0, float(value)))
                except ValueError:
                    pass
        blend = (style.get("mix-blend-mode") or "normal").strip()

        for key in ("display", "opacity", "mix-blend-mode"):
            if key in style:
                del style[key]
        layer.style = style
        for attr in ("display", "opacity"):
            if attr in layer.attrib:
                del layer.attrib[attr]

        name = layer.get("inkscape:label") or layer.get("id")
        has_sublayers = any(is_layer(c) for c in layer)
        # A filter, clip or mask on a layer with sublayers applies to the
        # whole group, which GIMP cannot express: render it as one layer.
        effects = any(
            style.get(k, "none") not in ("none", "") or layer.get(k)
            for k in ("filter", "clip-path", "mask")
        )
        bake = blend in INEXACT and self.options.blend == "bake"
        if not has_sublayers or not self.options.groups or effects or bake:
            return Item(
                name,
                node_id=layer.get("id"),
                opacity=opacity,
                visible=visible,
                blend=blend,
                context=context,
            )
        isolated = opacity < 1.0 or blend != "normal"
        children = self._plan_children(
            layer, name, context=layer.get("id") if isolated else context
        )
        return Item(
            name,
            children=children,
            opacity=opacity,
            visible=visible,
            blend=blend,
            context=context,
        )

    # -- rendering

    def render(self, doc, items):
        """Render every pixel layer in one Inkscape run; return
        {node_id: H x W x 4 uint8 array}."""
        ids = []

        def collect(entries):
            for item in entries:
                if item.node_id:
                    ids.append(item.node_id)
                if item.children:
                    collect(item.children)

        collect(items)
        if not ids:
            return {}
        svg_file = os.path.join(self.tempdir, "render.svg")
        doc.write(svg_file)
        actions = [
            "export-area-page",
            f"export-dpi:{self.options.dpi:g}",
            "export-background-opacity:0",
            "export-id-only",
        ]
        files = {}
        for index, node_id in enumerate(ids):
            png = os.path.join(self.tempdir, f"layer-{index}.png")
            files[node_id] = png
            actions += ["export-id:" + node_id, "export-filename:" + png, "export-do"]
        inkscape(svg_file, actions=";".join(actions))
        out = {}
        for node_id, png in files.items():
            with Image.open(png) as image:
                out[node_id] = np.asarray(image.convert("RGBA"))
        return out

    def render_backdrops(self, items):
        """For each layer to bake, render what lies below it in its
        isolation context (the page, or its nearest isolating parent
        layer) from the original document. Returns {node_id: pixels}."""
        todo = []

        def collect(entries):
            for item in entries:
                if (
                    item.node_id
                    and item.blend in INEXACT
                    and self.options.blend == "bake"
                ):
                    todo.append(item)
                if item.children:
                    collect(item.children)

        collect(items)
        out = {}
        for index, item in enumerate(todo):
            doc = copy.deepcopy(self.document)
            root = doc.getroot()
            node = root.getElementById(item.node_id)
            context = root.getElementById(item.context) if item.context else root
            # drop the layer and everything painted after it
            while node is not None and node is not context:
                parent = node.getparent()
                for later in list(node.itersiblings()):
                    parent.remove(later)
                if node.get("id") == item.node_id:
                    parent.remove(node)
                node = parent
            actions = [
                "export-area-page",
                f"export-dpi:{self.options.dpi:g}",
                "export-background-opacity:0",
            ]
            if context is not root:
                # the context's own opacity and blend apply after its content
                style = context.style
                for key in ("display", "opacity", "mix-blend-mode"):
                    if key in style:
                        del style[key]
                context.style = style
                actions += ["export-id:" + item.context, "export-id-only"]
            svg_file = os.path.join(self.tempdir, f"backdrop-{index}.svg")
            png = os.path.join(self.tempdir, f"backdrop-{index}.png")
            doc.write(svg_file)
            inkscape(
                svg_file,
                actions=";".join(actions + ["export-filename:" + png, "export-do"]),
            )
            with Image.open(png) as image:
                out[item.node_id] = np.asarray(image.convert("RGBA"))
        return out

    # -- building the XCF tree

    def layer_mode(self, blend, group=False):
        mode = BLEND_MODES.get(blend)
        if mode is None:
            if blend not in ("normal", "", None):
                inkex.errormsg(
                    _("Blend mode '{}' has no GIMP equivalent; using Normal.").format(
                        blend
                    )
                )
            mode = xcf.MODE_NORMAL
        return mode

    def build(self, items, pixels, backdrops=None):
        backdrops = backdrops or {}
        built = []
        composite = None if self.options.linear else xcf.SPACE_RGB_NON_LINEAR
        for item in items:
            mode = self.layer_mode(item.blend)
            blend_space = composite_mode = None
            if mode != xcf.MODE_NORMAL:
                # CSS blending shows the layer itself where nothing is
                # below it: GIMP's Union, not the Clip to Backdrop that
                # GIMP picks by default for most modes
                composite_mode = xcf.COMPOSITE_UNION
                if not self.options.linear:
                    blend_space = xcf.SPACE_RGB_NON_LINEAR
            if item.children is not None:
                children = self.build(item.children, pixels, backdrops)
                if not children:
                    continue
                isolated = item.opacity < 1.0 or mode != xcf.MODE_NORMAL
                built.append(
                    xcf.Group(
                        item.name,
                        children,
                        opacity=item.opacity,
                        visible=item.visible,
                        mode=mode if isolated else xcf.MODE_PASS_THROUGH,
                        blend_space=blend_space,
                        composite_space=composite if isolated else None,
                        composite_mode=composite_mode,
                    )
                )
                continue
            data = pixels.get(item.node_id)
            if data is None:
                continue
            name = item.name
            if item.node_id in backdrops:
                data = bake_blend(item.blend, data, backdrops[item.node_id])
                mode, blend_space, composite_mode = xcf.MODE_NORMAL, None, None
                name = f"{name} ({item.blend})"
            elif item.blend in INEXACT:
                self.approximate.append(item.name)
            x = y = 0
            if self.options.crop:
                cropped = xcf.crop_to_content(data)
                if cropped is None:
                    continue  # nothing to see: GIMP gets no empty layer
                data, x, y = cropped
            elif not data[:, :, 3].any():
                continue
            built.append(
                xcf.Layer(
                    name,
                    data,
                    x,
                    y,
                    opacity=item.opacity,
                    visible=item.visible,
                    mode=mode,
                    blend_space=blend_space,
                    composite_space=composite,
                    composite_mode=composite_mode,
                )
            )
        return built

    def background_layer(self, width, height):
        color = inkex.Color(self.svg.namedview.get("pagecolor") or "#ffffff")
        color = color.to_rgb()
        pixels = np.empty((height, width, 4), np.uint8)
        pixels[:, :] = (color.red, color.green, color.blue, 255)
        return xcf.Layer(_("Background"), pixels)

    # -- guides and grid, in output pixels

    @property
    def px_per_uu(self):
        return self.svg.scale * self.options.dpi / 96.0

    def add_guides(self, image):
        for guide in self.svg.namedview.get_guides():
            if guide.is_horizontal:
                image.add_guide("h", guide.position.y * self.px_per_uu)
            elif guide.is_vertical:
                image.add_guide("v", guide.position.x * self.px_per_uu)

    def uu(self, value, default):
        if value in (None, ""):
            return default
        try:
            return float(value)  # Inkscape 1.3+ writes user units
        except ValueError:
            # Older grids: "5mm". Inkscape 1.4 takes such a length in CSS
            # pixels and then uses that number as user units (SPGrid reads
            # the SVGLength's computed value), so do the same to match
            # the grid it draws.
            return inkex.units.convert_unit(value, "px")

    def grid_parasite(self):
        for grid in self.svg.namedview.findall("inkscape:grid"):
            if grid.get("type", "xygrid") not in ("xygrid", "rectangular"):
                continue
            scale = self.px_per_uu
            return xcf.grid_parasite(
                self.uu(grid.get("spacingx"), 1.0) * scale,
                self.uu(grid.get("spacingy"), 1.0) * scale,
                self.uu(grid.get("originx"), 0.0) * scale,
                self.uu(grid.get("originy"), 0.0) * scale,
            )
        return None

    # -- the whole export

    def save(self, stream):
        doc = copy.deepcopy(self.document)
        items = self.plan(doc)
        pixels = self.render(doc, items)
        self.approximate = []
        tree = self.build(items, pixels, self.render_backdrops(items))
        if self.approximate:
            inkex.errormsg(
                _(
                    "GIMP has no exact match for the blend mode of "
                    "these layers, so they look different in GIMP: "
                    "{}"
                ).format(", ".join(self.approximate))
            )
        if not tree:
            raise inkex.AbortExtension(_("There is nothing visible to save."))

        height, width = next(iter(pixels.values())).shape[:2]
        unit = self.svg.namedview.get("inkscape:document-units")
        image = xcf.XcfImage(width, height, dpi=self.options.dpi, unit=unit)
        if self.options.background:
            tree.insert(0, self.background_layer(width, height))
        image.layers = tree
        if self.options.guides:
            self.add_guides(image)
        if self.options.grid:
            parasite = self.grid_parasite()
            if parasite:
                image.parasites.append(parasite)
        image.save(stream)


if __name__ == "__main__":
    XcfOutput().run()
