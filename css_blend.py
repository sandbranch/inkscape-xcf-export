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
CSS blend modes (W3C Compositing and Blending Level 1) on numpy arrays,
for the blend modes GIMP computes differently. Needs only numpy.
"""

import numpy as np

# GIMP's modes for these differ from CSS: Dodge and Burn do not clamp
# before mixing in opacity, Soft Light uses another formula, and GIMP has
# no luma-based hue/saturation/color/luminosity modes. By default such
# layers are baked: blended with what lies below them, exactly as CSS
# says, into a Normal layer.
INEXACT = {
    "color-dodge",
    "color-burn",
    "soft-light",
    "hue",
    "saturation",
    "color",
    "luminosity",
}


def _lum(c):
    return c[..., 0] * 0.3 + c[..., 1] * 0.59 + c[..., 2] * 0.11


def _clip_color(c):
    lum = _lum(c)[..., None]
    lo = c.min(axis=-1, keepdims=True)
    hi = c.max(axis=-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(lo < 0, lum + (c - lum) * lum / (lum - lo), c)
        c = np.where(hi > 1, lum + (c - lum) * (1 - lum) / (hi - lum), c)
    return np.nan_to_num(c)


def _set_lum(c, lum):
    return _clip_color(c + (lum - _lum(c))[..., None])


def _sat(c):
    return c.max(axis=-1) - c.min(axis=-1)


def _set_sat(c, sat):
    lo = c.min(axis=-1, keepdims=True)
    hi = c.max(axis=-1, keepdims=True)
    span = hi - lo
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(span > 0, (c - lo) * sat[..., None] / span, 0.0)
    return np.nan_to_num(out)


def css_blend(mode, cb, cs):
    """The W3C Compositing and Blending Level 1 blend function B(Cb, Cs)
    on non-premultiplied colours in 0..1, arrays of shape (..., 3)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        if mode == "color-dodge":
            out = np.where(cs >= 1, 1.0, np.minimum(1.0, cb / (1 - cs)))
            return np.where(cb <= 0, 0.0, out)
        if mode == "color-burn":
            out = np.where(cs <= 0, 0.0, 1 - np.minimum(1.0, (1 - cb) / cs))
            return np.where(cb >= 1, 1.0, out)
    if mode == "soft-light":
        d = np.where(cb <= 0.25, ((16 * cb - 12) * cb + 4) * cb, np.sqrt(cb))
        return np.where(
            cs <= 0.5, cb - (1 - 2 * cs) * cb * (1 - cb), cb + (2 * cs - 1) * (d - cb)
        )
    if mode == "hue":
        return _set_lum(_set_sat(cs, _sat(cb)), _lum(cb))
    if mode == "saturation":
        return _set_lum(_set_sat(cb, _sat(cs)), _lum(cb))
    if mode == "color":
        return _set_lum(cs, _lum(cb))
    if mode == "luminosity":
        return _set_lum(cb, _lum(cs))
    raise ValueError(mode)


def bake_blend(mode, layer, backdrop):
    """A Normal layer that, composited over `backdrop`, looks like `layer`
    blended in `mode`: Cs' = (1 - ab) Cs + ab B(Cb, Cs), alpha unchanged.
    Both are H x W x 4 uint8, not premultiplied."""
    cs = layer[..., :3] / 255.0
    cb = backdrop[..., :3] / 255.0
    ab = backdrop[..., 3:] / 255.0
    mixed = (1 - ab) * cs + ab * np.clip(css_blend(mode, cb, cs), 0, 1)
    out = layer.copy()
    out[..., :3] = np.round(mixed * 255).astype(np.uint8)
    return out
