# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Run inside GIMP 3 (python-fu-eval) with TEST_OUT set to a file name:
# writes a small XCF that GIMP itself saved, with known pixels (see
# pattern() in test_writer.py), a layer group, guides and a grid. It is
# kept in tests/data/gimp-reference.xcf so the unit tests can check the
# dump tool, and our writer's layout, against GIMP's own output.
#
#   tests/make_gimp_reference.sh
import os

from gi.repository import Gegl, Gimp, Gio


def pattern(width, height, seed):
    """Deterministic RGBA bytes, same as test_writer.pattern()."""
    out = bytearray()
    for y in range(height):
        for x in range(width):
            out += bytes(
                (
                    (x * 7 + seed) % 256,
                    (y * 5 + seed) % 256,
                    ((x + y) * 3) % 256,
                    (x * y + seed) % 256,
                )
            )
    return bytes(out)


def layer(image, name, width, height, seed, parent, x=0, y=0):
    item = Gimp.Layer.new(
        image,
        name,
        width,
        height,
        Gimp.ImageType.RGBA_IMAGE,
        100,
        Gimp.LayerMode.NORMAL,
    )
    image.insert_layer(item, parent, 0)
    item.set_offsets(x, y)
    buffer = item.get_buffer()
    buffer.set(
        Gegl.Rectangle.new(0, 0, width, height),
        "R'G'B'A u8",
        pattern(width, height, seed),
    )
    buffer.flush()
    return item


image = Gimp.Image.new(150, 100, Gimp.ImageBaseType.RGB)
layer(image, "bottom", 150, 100, 1, None)
group = Gimp.GroupLayer.new(image, "group")
image.insert_layer(group, None, 0)
layer(image, "inner", 130, 70, 2, group, 10, 20)
layer(image, "top", 65, 64, 3, None, 80, 5)
image.add_hguide(30)
image.add_vguide(70)
image.grid_set_spacing(16, 8)
Gimp.file_save(
    Gimp.RunMode.NONINTERACTIVE,
    image,
    Gio.File.new_for_path(os.environ["TEST_OUT"]),
    None,
)
print("REFERENCE SAVED")
