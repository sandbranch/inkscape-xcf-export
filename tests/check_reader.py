#!/usr/bin/env python3
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compare xcf_reader.py with GIMP's own per-layer pixels (made by
gimp_make_xcfs.py): structure exactly, pixels within 1 level of 255
(rounding of high-bit-depth values may differ by one)."""

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import xcf_reader


def flatten(layers, path=()):
    for index, layer in enumerate(layers):
        yield (*path, index), layer
        yield from flatten(layer.children, (*path, index))


def main(folder):
    failed = 0
    for name in sorted(n[:-4] for n in os.listdir(folder) if n.endswith(".xcf")):
        with open(os.path.join(folder, name + ".ref.json")) as f:
            ref = json.load(f)
        with open(os.path.join(folder, name + ".xcf"), "rb") as f:
            image = xcf_reader.read(f.read())
        ours = dict(flatten(image.layers))
        problems, worst = [], 0
        for entry in ref["layers"]:
            layer = ours.get(tuple(entry["path"]))
            if layer is None or layer.name != entry["name"]:
                problems.append(f"{entry['name']}: not found at {entry['path']}")
                continue
            for key, value in (
                ("x", layer.x),
                ("y", layer.y),
                ("visible", layer.visible),
                ("mode", layer.mode),
                ("group", layer.group),
            ):
                if entry[key] != value:
                    problems.append(
                        f"{entry['name']}.{key}: GIMP {entry[key]}, ours {value}"
                    )
            if abs(entry["opacity"] - layer.opacity) > 1e-3:
                problems.append(
                    f"{entry['name']}.opacity: GIMP {entry['opacity']}, ours {layer.opacity}"
                )
            if "file" in entry:
                with open(
                    os.path.join(folder, name + ".ref", entry["file"]), "rb"
                ) as f:
                    gimp = (
                        np.frombuffer(f.read(), np.uint8)
                        .reshape(entry["h"], entry["w"], 4)
                        .astype(int)
                    )
                if layer.pixels is None or layer.pixels.shape != gimp.shape:
                    problems.append(
                        f"{entry['name']}: pixels {None if layer.pixels is None else layer.pixels.shape}"
                    )
                    continue
                ours_px = layer.pixels.astype(int)
                visible = gimp[..., 3] > 0  # colour of invisible pixels does not matter
                diff = np.abs(ours_px - gimp)
                diff[..., :3] *= visible[..., None]
                worst = max(worst, int(diff.max()))
                if diff.max() > 1:
                    problems.append(
                        f"{entry['name']}: pixels differ by up to {diff.max()} "
                        f"({(diff.max(axis=2) > 1).mean() * 100:.1f} % of pixels)"
                    )
        if len(ours) != len(ref["layers"]):
            problems.append(f"{len(ours)} layers, GIMP {len(ref['layers'])}")
        status = "ok  " if not problems else "FAIL"
        print(
            f"{status} {name}: XCF {image.version}, precision {image.precision}, "
            f"{len(ref['layers'])} layers, largest pixel difference {worst}"
        )
        for p in problems:
            print("       " + p)
        failed += bool(problems)
    print("ALL PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
