#!/usr/bin/env python3
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Compare GIMP's flattened XCF with Inkscape's own render of the same SVG,
and GIMP's view of the layer tree with tests/data/<name>.expect.json.

    compare.py WORKDIR NAME [NAME...]

Pixels are compared premultiplied (the colour of a fully transparent
pixel does not matter), on a 0-255 scale. A file passes when the mean
difference is under 0.5 and no more than 0.5 % of the pixels differ
by over 8 (anti-aliased edges round differently in the two renderers).
"""

import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))


def premultiplied(path):
    a = np.asarray(Image.open(path).convert("RGBA")).astype(np.float64)
    a[:, :, :3] *= a[:, :, 3:] / 255.0
    return a


def pixel_check(work, name, variant):
    ref = premultiplied(os.path.join(work, name + ".ink.png"))
    got_path = os.path.join(work, variant + ".flat.png")
    if not os.path.exists(got_path):
        return False, "no flattened image from GIMP"
    got = premultiplied(got_path)
    if ref.shape != got.shape:
        return False, "size %s, Inkscape %s" % (got.shape[:2], ref.shape[:2])
    diff = np.abs(ref - got).max(axis=2)
    mean, worst = diff.mean(), diff.max()
    over = (diff > 8).mean() * 100
    ok = mean < 0.5 and over <= 0.5
    return ok, "mean %.3f, max %d, %.3f %% of pixels over 8" % (mean, worst, over)


def subset(expect, got, where="layers"):
    """Every key in `expect` must match in `got`; lists match item by item."""
    if isinstance(expect, dict):
        if not isinstance(got, dict):
            return ["%s: expected an object" % where]
        errors = []
        for key, value in expect.items():
            if key not in got:
                errors.append("%s.%s missing" % (where, key))
            else:
                errors += subset(value, got[key], "%s.%s" % (where, key))
        return errors
    if isinstance(expect, list):
        if not isinstance(got, list) or len(got) != len(expect):
            return [
                "%s: expected %d entries, got %s"
                % (where, len(expect), len(got) if isinstance(got, list) else got)
            ]
        errors = []
        for i, (e, g) in enumerate(zip(expect, got)):
            errors += subset(e, g, "%s[%d]" % (where, i))
        return errors
    if expect != got:
        return ["%s: expected %r, got %r" % (where, expect, got)]
    return []


# Variant suffixes: -linear blends in linear light (looks different on
# purpose), -gimp keeps GIMP's nearest blend modes (looks different on
# purpose), -ext went through Inkscape's own export path. Other variants
# (-opts) have their own .expect.json and .ink.png.
SAME_STRUCTURE = ("-linear", "-ext")
NO_PIXELS = ("-linear", "-gimp")


def base_name(variant):
    for suffix in SAME_STRUCTURE + NO_PIXELS:
        if variant.endswith(suffix):
            return variant[: -len(suffix)]
    return variant


def main():
    work, variants = sys.argv[1], sys.argv[2:]
    failed = 0
    for variant in variants:
        base = base_name(variant)
        gimp_json = os.path.join(work, variant + ".gimp.json")
        if not os.path.exists(gimp_json):
            print("FAIL %s: GIMP wrote no report" % variant)
            failed += 1
            continue
        with open(gimp_json) as f:
            info = json.load(f)
        if "error" in info:
            print("FAIL %s: GIMP could not load it: %s" % (variant, info["error"]))
            failed += 1
            continue
        expect_path = os.path.join(HERE, "data", variant + ".expect.json")
        if not os.path.exists(expect_path) and variant.endswith(SAME_STRUCTURE):
            expect_path = os.path.join(HERE, "data", base + ".expect.json")
        if os.path.exists(expect_path):
            with open(expect_path) as f:
                errors = subset(json.load(f), info, "image")
            for error in errors:
                print("FAIL %s structure: %s" % (variant, error))
            failed += bool(errors)
            if not errors:
                print("ok   %s structure" % variant)
        else:
            print("--   %s structure: no expectations" % variant)
        if variant.endswith(NO_PIXELS):
            continue
        ref = (
            variant
            if os.path.exists(os.path.join(work, variant + ".ink.png"))
            else base
        )
        ok, detail = pixel_check(work, ref, variant)
        print("%s %s pixels: %s" % ("ok  " if ok else "FAIL", variant, detail))
        failed += not ok
    print("ALL PASS" if not failed else "%d FAILED" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
