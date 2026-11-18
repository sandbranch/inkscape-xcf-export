# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
"""Unit tests for xcf_reader.py: GIMP's own reference file (RLE tiles,
XCF 11) and files from our writer (zlib, XCF 10). The full check against
GIMP in every precision is tests/run_import.sh."""

import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from test_writer import REFERENCE, pattern

import xcf_reader
import xcf_writer as xcf


def test_reads_gimps_own_file():
    with open(REFERENCE, "rb") as f:
        image = xcf_reader.read(f.read())
    assert image.version == 11 and (image.width, image.height) == (150, 100)
    names = [layer.name for layer in image.layers]
    assert names == ["top", "group", "bottom"]
    group = image.layers[1]
    assert group.group and [c.name for c in group.children] == ["inner"]
    inner = group.children[0]
    assert (inner.x, inner.y) == (10, 20)
    assert np.array_equal(inner.pixels, pattern(130, 70, 2))
    assert sorted(image.guides) == [("h", 30), ("v", 70)]


def test_reads_our_writer():
    image = xcf.XcfImage(80, 60, dpi=300)
    image.layers = [
        xcf.Layer("a", pattern(80, 60, 1)),
        xcf.Group(
            "g", [xcf.Layer("b", pattern(30, 20, 2), -5, 7, opacity=0.5, visible=False)]
        ),
        xcf.Layer("c", pattern(70, 65, 3), 3, 4, mode=xcf.MODE_MULTIPLY),
    ]
    image.add_guide("v", 12)
    got = xcf_reader.read(image.tobytes())
    assert got.version == 10 and got.dpi == pytest.approx((300, 300))
    c, g, a = got.layers
    assert (c.name, c.mode, c.x, c.y) == ("c", xcf.MODE_MULTIPLY, 3, 4)
    assert np.array_equal(c.pixels, pattern(70, 65, 3))
    b = g.children[0]
    assert (b.x, b.y, b.visible) == (-5, 7, False) and b.opacity == pytest.approx(0.5)
    assert np.array_equal(a.pixels, pattern(80, 60, 1))
    assert got.guides == [("v", 12)]


def test_not_an_xcf():
    with pytest.raises(xcf_reader.XcfError):
        xcf_reader.read(b"not an xcf file at all")
