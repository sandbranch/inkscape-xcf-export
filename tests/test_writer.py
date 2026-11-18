# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Unit tests for xcf_writer.py and css_blend.py. They need numpy and
pytest, not Inkscape or GIMP:

    python3 -m pytest tests/

The reader they use (xcf_dump.py) is checked first against an XCF that
GIMP 3.2 saved itself (data/gimp-reference.xcf, from
make_gimp_reference.sh), so the writer is checked against GIMP's format
rather than against itself.
"""

import os
import struct
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import xcf_dump

import css_blend
import xcf_writer as xcf

REFERENCE = os.path.join(HERE, "data", "gimp-reference.xcf")


def pattern(width, height, seed):
    """The same pixels as make_gimp_reference.py writes, as an array."""
    y, x = np.mgrid[0:height, 0:width]
    return np.stack(
        [
            (x * 7 + seed) % 256,
            (y * 5 + seed) % 256,
            ((x + y) * 3) % 256,
            (x * y + seed) % 256,
        ],
        axis=-1,
    ).astype(np.uint8)


def pixels_of(layer):
    width, height, bpp, data = layer["pixels"]
    return np.frombuffer(data, np.uint8).reshape(height, width, bpp)


def by_name(info):
    return {layer["name"]: layer for layer in info["layers"]}


# -- the reader against GIMP's own file


def test_reader_decodes_gimp_rle():
    info = xcf_dump.dump(REFERENCE, pixels=True)
    assert info["props"]["COMPRESSION"] == 1  # GIMP's default, RLE
    layers = by_name(info)
    for name, size, seed in (
        ("bottom", (150, 100), 1),
        ("inner", (130, 70), 2),
        ("top", (65, 64), 3),
    ):
        assert np.array_equal(pixels_of(layers[name]), pattern(*size, seed)), name


# -- the writer, read back


def reference_like_image():
    """Our writer's version of GIMP's reference image."""
    image = xcf.XcfImage(150, 100)
    image.layers = [
        xcf.Layer("bottom", pattern(150, 100, 1)),
        xcf.Group(
            "group",
            [xcf.Layer("inner", pattern(130, 70, 2), 10, 20)],
            mode=xcf.MODE_NORMAL,
        ),
        xcf.Layer("top", pattern(65, 64, 3), 80, 5),
    ]
    image.add_guide("h", 30)
    image.add_guide("v", 70)
    image.parasites.append(xcf.grid_parasite(16, 8))
    return image


def test_round_trip_matches_gimp_reference():
    ours = xcf_dump.parse(reference_like_image().tobytes(), pixels=True)
    gimps = xcf_dump.dump(REFERENCE, pixels=True)
    assert ours["version"] == 10 and ours["precision"] == 150
    assert ours["props"]["COMPRESSION"] == 2  # zlib
    assert [l["name"] for l in ours["layers"]] == [l["name"] for l in gimps["layers"]]
    assert sorted(ours["props"]["GUIDES"]) == sorted(gimps["props"]["GUIDES"])
    for mine, theirs in zip(ours["layers"], gimps["layers"]):
        name = mine["name"]
        assert mine["props"]["OFFSETS"] == theirs["props"]["OFFSETS"], name
        assert mine["props"].get("ITEM_PATH") == theirs["props"].get("ITEM_PATH"), name
        assert ("GROUP_ITEM" in mine["props"]) == ("GROUP_ITEM" in theirs["props"]), (
            name
        )
        assert mine["dummy_levels"] == theirs["dummy_levels"], name
        assert (mine["width"], mine["height"]) == (theirs["width"], theirs["height"]), (
            name
        )
        if name != "group":  # GIMP stores a group's projection, we store none
            assert np.array_equal(pixels_of(mine), pixels_of(theirs)), name


def test_grid_parasite_is_what_gimp_writes():
    gimps = xcf_dump.dump(REFERENCE)
    grid = next(
        p for p in gimps["props"]["PARASITES"] if p["name"] == "gimp-image-grid"
    )
    name, flags, data = xcf.grid_parasite(16, 8)
    assert name == grid["name"] and flags == grid["flags"]
    for key in ("xspacing", "yspacing"):
        assert f"({key} " in grid["data"] and f"({key} " in data.decode()


@pytest.mark.parametrize(
    "size",
    [(1, 1), (63, 63), (64, 64), (65, 64), (64, 65), (129, 3), (3, 129), (200, 150)],
)
def test_tile_edges(size):
    width, height = size
    image = xcf.XcfImage(width, height)
    image.layers = [xcf.Layer("l", pattern(width, height, 9))]
    info = xcf_dump.parse(image.tobytes(), pixels=True)
    layer = info["layers"][0]
    assert np.array_equal(pixels_of(layer), pattern(width, height, 9))
    expected, w, h = 0, width, height
    while w >= 64 or h >= 64:  # GIMP's rule, as checked above
        w, h, expected = w // 2, h // 2, expected + 1
    assert layer["dummy_levels"] == expected


def test_nested_groups_item_paths():
    leaf = xcf.Layer("leaf", np.zeros((2, 2, 4), np.uint8))
    image = xcf.XcfImage(10, 10)
    image.layers = [
        xcf.Layer("bottom", np.zeros((2, 2, 4), np.uint8)),
        xcf.Group(
            "outer",
            [
                xcf.Group(
                    "inner", [leaf, xcf.Layer("leaf2", np.zeros((2, 2, 4), np.uint8))]
                ),
                xcf.Layer("side", np.zeros((2, 2, 4), np.uint8)),
            ],
        ),
    ]
    info = xcf_dump.parse(image.tobytes())
    paths = [(l["name"], l["props"].get("ITEM_PATH")) for l in info["layers"]]
    # topmost first, depth first, index of each level from the top
    assert paths == [
        ("outer", None),
        ("side", [0, 0]),
        ("inner", [0, 1]),
        ("leaf2", [0, 1, 0]),
        ("leaf", [0, 1, 1]),
        ("bottom", None),
    ]


def test_properties():
    image = xcf.XcfImage(20, 10, dpi=300, unit="mm")
    image.layers = [
        xcf.Layer(
            "Smörgås 🙂",
            np.zeros((3, 4, 4), np.uint8),
            -2,
            5,
            opacity=0.5,
            visible=False,
            mode=xcf.MODE_MULTIPLY,
            blend_space=2,
            composite_space=2,
            composite_mode=1,
        )
    ]
    image.add_guide("h", 4)
    image.add_guide("h", 11)  # off the canvas: dropped
    image.add_guide("v", 19.6)  # rounded
    info = xcf_dump.parse(image.tobytes())
    props = info["layers"][0]["props"]
    assert info["layers"][0]["name"] == "Smörgås 🙂"
    assert props["OPACITY"] == 128 and props["FLOAT_OPACITY"] == 0.5
    assert props["VISIBLE"] == 0 and props["MODE"] == 30
    assert props["BLEND_SPACE"] == 2 and props["COMPOSITE_SPACE"] == 2
    assert props["COMPOSITE_MODE"] == 1 and props["OFFSETS"] == [-2, 5]
    assert info["props"]["RESOLUTION"] == [300.0, 300.0] and info["props"]["UNIT"] == 2
    assert info["props"]["GUIDES"] == [[4, "h"], [20, "v"]]


def test_layer_needs_rgba():
    with pytest.raises(ValueError):
        xcf.Layer("rgb", np.zeros((2, 2, 3), np.uint8))


def test_crop_to_content():
    pixels = np.zeros((10, 20, 4), np.uint8)
    assert xcf.crop_to_content(pixels) is None
    pixels[3:5, 7:12, 3] = 1
    cropped, x, y = xcf.crop_to_content(pixels)
    assert (x, y) == (7, 3) and cropped.shape == (2, 5, 4)


def test_layer_header_layout():
    """Spot check the raw bytes against the spec: name string, then
    properties, then the hierarchy and mask pointers."""
    image = xcf.XcfImage(5, 5)
    image.layers = [xcf.Layer("ab", np.zeros((5, 5, 4), np.uint8))]
    data = image.tobytes()
    assert data[:14] == b"gimp xcf v010\0"
    width, height, base, precision = struct.unpack_from(">IIII", data, 14)
    assert (width, height, base, precision) == (5, 5, 0, 150)


# -- CSS blend maths, against the W3C formulas worked by hand


def c(*values):
    return np.array([values], dtype=float)


def test_dodge_and_burn_clamp():
    assert css_blend.css_blend("color-dodge", c(0.5, 0, 0.2), c(0.75, 0.5, 1))[
        0
    ] == pytest.approx([1.0, 0.0, 1.0])
    assert css_blend.css_blend("color-burn", c(0.5, 1, 0.2), c(0.75, 0, 0))[
        0
    ] == pytest.approx([1 - 0.5 / 0.75, 1.0, 0.0])


def test_soft_light_both_branches():
    out = css_blend.css_blend("soft-light", c(0.5, 0.16, 0.5), c(0.25, 0.75, 0.75))[0]
    d = ((16 * 0.16 - 12) * 0.16 + 4) * 0.16
    assert out == pytest.approx(
        [0.375, 0.16 + 0.5 * (d - 0.16), 0.5 + 0.5 * (np.sqrt(0.5) - 0.5)]
    )


def test_non_separable_modes_keep_what_they_promise():
    rng = np.random.default_rng(1)
    cb, cs = rng.uniform(0.1, 0.9, (500, 3)), rng.uniform(0.1, 0.9, (500, 3))
    lum = css_blend._lum
    for mode, keeps in (
        ("hue", cb),
        ("saturation", cb),
        ("color", cb),
        ("luminosity", cs),
    ):
        out = css_blend.css_blend(mode, cb, cs)
        assert np.all(out >= -1e-9) and np.all(out <= 1 + 1e-9), mode
        assert lum(out) == pytest.approx(lum(keeps), abs=1e-9), mode
    out = css_blend.css_blend("luminosity", cb, cs)
    inside = (out.min(axis=1) > 1e-6) & (out.max(axis=1) < 1 - 1e-6)
    assert css_blend._sat(out)[inside] == pytest.approx(css_blend._sat(cb)[inside])


def test_bake_blend():
    layer = np.array([[[200, 100, 50, 180]]], np.uint8)
    opaque = np.array([[[90, 120, 240, 255]]], np.uint8)
    empty = np.array([[[90, 120, 240, 0]]], np.uint8)
    baked = css_blend.bake_blend("hue", layer, opaque)
    expect = css_blend.css_blend("hue", opaque[..., :3] / 255.0, layer[..., :3] / 255.0)
    assert baked[0, 0, 3] == 180
    assert baked[0, 0, :3] == pytest.approx(np.round(expect[0, 0] * 255), abs=0)
    assert np.array_equal(css_blend.bake_blend("hue", layer, empty), layer)
