# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Run inside GIMP 3 (python-fu-eval). For each XCF named in
# $TEST_XCFS (space-separated), load it, write <name>.gimp.json with the
# layer tree, guides and grid as GIMP sees them, and <name>.flat.png with
# the image flattened by GIMP.
import json
import os

from gi.repository import Gimp, Gio


def tree(layers):
    out = []
    for layer in layers:
        x, y = layer.get_offsets()[1:]
        entry = {
            "name": layer.get_name(),
            "visible": layer.get_visible(),
            "opacity": round(layer.get_opacity(), 2),
            "mode": int(layer.get_mode()),
            "x": x, "y": y,
            "w": layer.get_width(), "h": layer.get_height(),
        }
        if layer.is_group():
            entry["children"] = tree(layer.get_children())
        out.append(entry)
    return out


for path in os.environ["TEST_XCFS"].split():
    try:
        image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                               Gio.File.new_for_path(path))
    except Exception as error:  # report, keep going
        with open(path[:-4] + ".gimp.json", "w") as f:
            json.dump({"error": str(error)}, f)
        continue
    guides, guide = [], image.find_next_guide(0)
    while guide:
        guides.append([image.get_guide_position(guide),
                       "h" if image.get_guide_orientation(guide)
                       == Gimp.OrientationType.HORIZONTAL else "v"])
        guide = image.find_next_guide(guide)
    info = {
        "width": image.get_width(), "height": image.get_height(),
        "resolution": [round(v, 2) for v in image.get_resolution()[1:]],
        "layers": tree(image.get_layers()),
        "guides": guides,
        "grid_spacing": [round(v, 3) for v in image.grid_get_spacing()[1:]],
        "grid_offset": [round(v, 3) for v in image.grid_get_offset()[1:]],
    }
    with open(path[:-4] + ".gimp.json", "w") as f:
        json.dump(info, f, indent=1)
    flat = image.duplicate()
    flat.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, flat,
                   Gio.File.new_for_path(path[:-4] + ".flat.png"), None)
    flat.delete()
    image.delete()
print("GIMP CHECK DONE")
