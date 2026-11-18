#!/usr/bin/env python3
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Check the XCF import in Inkscape: for every <name>.xcf in a folder made
by gimp_make_xcfs.py, Inkscape opens it through xcf_import and renders
it (<name>.ink.png, made by run_import.sh); that render must equal the
layers GIMP itself decoded (<name>.ref/), stacked the way SVG stacks
them (sRGB, opacity, visibility, multiply): mean difference under 1 of
255, no pixel off by more than 8.

GIMP's own flattened image differs where layers are partly transparent:
GIMP composites differently (in linear light by default, among other
things), which no SVG can reproduce.
"""

import json
import os
import sys

import numpy as np
from PIL import Image


def composite(folder, name):
    with open(os.path.join(folder, name + ".ref.json")) as f:
        ref = json.load(f)
    height, width = ref["height"], ref["width"]
    out = np.zeros((height, width, 4))
    layers = ref["layers"]

    def hidden(entry):
        return any(
            not other["visible"]
            for other in layers
            if other["path"] == entry["path"][: len(other["path"])]
        )

    def opacity(entry):
        value = 1.0
        for other in layers:
            if other["path"] == entry["path"][: len(other["path"])]:
                value *= other["opacity"]
        return value

    for entry in reversed(layers):  # bottom first
        if entry["group"] or hidden(entry):
            continue
        with open(os.path.join(folder, name + ".ref", entry["file"]), "rb") as f:
            px = (
                np.frombuffer(f.read(), np.uint8).reshape(entry["h"], entry["w"], 4)
                / 255.0
            )
        layer = np.zeros((height, width, 4))
        x0, y0 = entry["x"], entry["y"]
        sx, sy, dx, dy = max(0, -x0), max(0, -y0), max(0, x0), max(0, y0)
        w, h = min(entry["w"] - sx, width - dx), min(entry["h"] - sy, height - dy)
        if w > 0 and h > 0:
            layer[dy : dy + h, dx : dx + w] = px[sy : sy + h, sx : sx + w]
        a = layer[..., 3:] * opacity(entry)
        cs, cb, ab = layer[..., :3], out[..., :3], out[..., 3:]
        blended = (1 - ab) * cs + ab * cs * cb if entry["mode"] in (3, 30) else cs
        alpha = a + ab * (1 - a)
        colour = np.where(
            alpha > 0, (blended * a + cb * ab * (1 - a)) / np.maximum(alpha, 1e-12), 0
        )
        out = np.concatenate([colour, alpha], axis=2)
    out[..., :3] *= out[..., 3:]
    return out * 255


def main(folder):
    failed = 0
    for name in sorted(n[:-4] for n in os.listdir(folder) if n.endswith(".xcf")):
        render = os.path.join(folder, name + ".ink.png")
        if not os.path.exists(render):
            print(f"FAIL {name}: Inkscape did not import it")
            failed += 1
            continue
        ink = np.asarray(Image.open(render).convert("RGBA")).astype(float)
        ink[..., :3] *= ink[..., 3:] / 255
        expected = composite(folder, name)
        if ink.shape != expected.shape:
            print(f"FAIL {name}: size {ink.shape[:2]}, expected {expected.shape[:2]}")
            failed += 1
            continue
        d = np.abs(ink - expected).max(axis=2)
        ok = d.mean() < 1 and d.max() <= 8
        print(
            f"{'ok  ' if ok else 'FAIL'} {name}: mean {d.mean():.2f}, max {d.max():.0f}"
        )
        failed += not ok
    print("ALL PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
