# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Run inside GIMP 3 (python-fu-eval) with TEST_OUT set to a folder: makes
# test XCF files in several precisions and colour modes, and for each a
# reference: every layer's pixels as GIMP itself converts them to 8-bit
# sRGB RGBA, with its layer mask applied by GIMP (<name>.ref/<i>.rgba,
# raw bytes) and <name>.ref.json with names, sizes, offsets, opacity,
# visibility, modes and the tree.
import json
import os

from gi.repository import Gegl, Gimp, Gio

OUT = os.environ["TEST_OUT"]


def pattern(width, height, seed, alpha=True):
    out = bytearray()
    for y in range(height):
        for x in range(width):
            a = (x * 3 + y * 2 + seed) % 256 if alpha else 255
            out += bytes(
                ((x * 5 + seed) % 256, (y * 7 + seed) % 256, ((x ^ y) + seed) % 256, a)
            )
    return bytes(out)


def layer(image, name, width, height, seed, parent=None, x=0, y=0, position=0):
    item = Gimp.Layer.new(
        image,
        name,
        width,
        height,
        Gimp.ImageType.RGBA_IMAGE,
        100,
        Gimp.LayerMode.NORMAL,
    )
    image.insert_layer(item, parent, position)
    item.set_offsets(x, y)
    buffer = item.get_buffer()
    buffer.set(
        Gegl.Rectangle.new(0, 0, width, height),
        "R'G'B'A u8",
        pattern(width, height, seed),
    )
    buffer.flush()
    return item


def build():
    image = Gimp.Image.new(150, 100, Gimp.ImageBaseType.RGB)
    layer(image, "bottom", 150, 100, 1)
    group = Gimp.GroupLayer.new(image, "group")
    image.insert_layer(group, None, 0)
    inner = layer(image, "inner", 90, 70, 2, group, 10, 20)
    inner.set_opacity(60.0)
    masked = layer(image, "masked", 70, 66, 3, group, 50, 10)
    mask = masked.create_mask(Gimp.AddMaskType.WHITE)
    masked.add_mask(mask)
    mbuf = mask.get_buffer()
    ramp = bytes((x * 255 // 69) for _y in range(66) for x in range(70))
    mbuf.set(Gegl.Rectangle.new(0, 0, 70, 66), "Y' u8", ramp)
    mbuf.flush()
    hidden = layer(image, "hidden", 40, 30, 4, None, 5, 5)
    hidden.set_visible(False)
    mult = layer(
        image, "multiply", 60, 50, 5, None, -20, -15
    )  # reaches past the canvas
    mult.set_mode(Gimp.LayerMode.MULTIPLY)
    image.add_hguide(30)
    image.add_vguide(70)
    image.set_resolution(300, 300)
    return image


def reference(image, name):
    """Every layer's pixels as GIMP gives them in 8-bit sRGB, masks applied."""
    folder = os.path.join(OUT, name + ".ref")
    os.makedirs(folder, exist_ok=True)
    copy = image.duplicate()
    entries = []

    def walk(layers, path):
        for index, item in enumerate(layers):
            entry = {
                "name": item.get_name(),
                "path": [*path, index],
                "x": item.get_offsets()[1],
                "y": item.get_offsets()[2],
                "w": item.get_width(),
                "h": item.get_height(),
                "opacity": round(item.get_opacity() / 100.0, 4),
                "visible": item.get_visible(),
                "mode": int(item.get_mode()),
                "group": item.is_group(),
            }
            if item.is_group():
                entries.append(entry)
                walk(item.get_children(), [*path, index])
                continue
            if item.get_mask():
                item.remove_mask(Gimp.MaskApplyMode.APPLY)
            rect = Gegl.Rectangle.new(0, 0, item.get_width(), item.get_height())
            data = item.get_buffer().get(rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
            entry["file"] = f"{len(entries)}.rgba"
            with open(os.path.join(folder, entry["file"]), "wb") as f:
                f.write(bytes(data))
            entries.append(entry)

    walk(copy.get_layers(), [])
    with open(os.path.join(OUT, name + ".ref.json"), "w") as f:
        json.dump(
            {
                "layers": entries,
                "width": image.get_width(),
                "height": image.get_height(),
                "precision": int(image.get_precision()),
            },
            f,
            indent=1,
        )
    copy.delete()


def save(image, name):
    path = os.path.join(OUT, name + ".xcf")
    Gimp.file_save(
        Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(path), None
    )
    reference(image, name)


variants = [
    ("rgb-u8", None),
    ("rgb-u16-linear", Gimp.Precision.U16_LINEAR),
    ("rgb-float-linear", Gimp.Precision.FLOAT_LINEAR),
    ("rgb-half-nonlinear", Gimp.Precision.HALF_NON_LINEAR),
    ("rgb-u32-nonlinear", Gimp.Precision.U32_NON_LINEAR),
]
for name, precision in variants:
    image = build()
    if precision is not None:
        image.convert_precision(precision)
    save(image, name)
    image.delete()

image = build()
image.convert_grayscale()
save(image, "grey-u8")
image.delete()

image = build()
image.convert_indexed(
    Gimp.ConvertDitherType.NONE, Gimp.ConvertPaletteType.GENERATE, 64, False, False, ""
)
save(image, "indexed")
image.delete()

# a layer with a GIMP 3 effect (non-destructive filter): XCF 20 or later
image = build()
target = image.get_layers()[-1]
blur = Gimp.DrawableFilter.new(target, "gegl:gaussian-blur", "blur")
blur.update()
target.append_filter(blur)
save(image, "effects")
image.delete()

print("XCFS MADE")
