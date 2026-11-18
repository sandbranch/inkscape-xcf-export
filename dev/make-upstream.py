#!/usr/bin/env python3
# Copyright 2026 David
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Write this exporter into a checkout of gitlab.com/inkscape/extensions as
the replacement for its gimp_xcf extension:

    dev/make-upstream.py ../inkscape-extensions

It keeps upstream's extension id, class name (GimpXcf), short options
(-d, -r, -b, -i) and defaults (guides and grid off), uses
dev/upstream/gimp_xcf.inx, copies the test drawings and the GIMP-made
reference file, and builds tests/test_xcf_writer.py from
tests/test_writer.py with the reader from tests/xcf_dump.py inlined.
Run ruff format afterwards in the checkout.
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one {old!r}")
    return text.replace(old, new)


def extension():
    with open(os.path.join(REPO, "xcf_export.py")) as f:
        s = f.read()
    s = replace_once(s, "class XcfOutput(", "class GimpXcf(")
    s = replace_once(s, "    XcfOutput().run()", "    GimpXcf().run()")
    s = replace_once(
        s, 'pars.add_argument("--dpi",', 'pars.add_argument("-i", "--dpi",'
    )
    s = replace_once(
        s,
        '            "--background",',
        '            "-b",\n            "--background",',
    )
    s = replace_once(
        s, '            "--grid",', '            "-r",\n            "--grid",'
    )
    s = replace_once(
        s,
        '"--guides", type=inkex.Boolean, default=True,',
        '"-d", "--guides", type=inkex.Boolean, default=False,',
    )
    return s


def writer_tests():
    with open(os.path.join(REPO, "tests", "xcf_dump.py")) as f:
        dump = f.read()
    reader = dump[dump.index("PROP_NAMES = {") : dump.index("def main():")].rstrip()
    with open(os.path.join(REPO, "tests", "test_writer.py")) as f:
        tests = f.read()
    body = tests[tests.index("def pattern(") :].replace("xcf_dump.", "")
    head = '''"""
Unit tests for xcf_writer.py (the XCF writer behind gimp_xcf.py) and
css_blend.py.

The small XCF reader in this file is checked first against
data/xcf/gimp-reference.xcf, a file GIMP 3.2.8 saved itself with known
pixels (RLE tiles, a layer group, guides and a grid), so the writer is
checked against GIMP's format rather than against itself.
"""

import os
import struct
import zlib

import numpy as np
import pytest

import css_blend
import xcf_writer as xcf

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.join(HERE, "data", "xcf", "gimp-reference.xcf")


# -- a minimal XCF reader for the tests


'''
    return head + reader + "\n\n\n# -- the tests\n\n\n" + body


def main():
    target = sys.argv[1]
    if not os.path.isfile(os.path.join(target, "gimp_xcf.inx")):
        raise SystemExit(f"{target} is not an inkscape/extensions checkout")
    with open(os.path.join(target, "gimp_xcf.py"), "w") as f:
        f.write(extension())
    os.chmod(os.path.join(target, "gimp_xcf.py"), 0o755)
    for name in ("xcf_writer.py", "css_blend.py"):
        shutil.copy(os.path.join(REPO, name), os.path.join(target, name))
    shutil.copy(os.path.join(HERE, "upstream", "gimp_xcf.inx"), target)
    tests = os.path.join(target, "tests")
    with open(os.path.join(tests, "test_xcf_writer.py"), "w") as f:
        f.write(writer_tests())
    shutil.copy(os.path.join(HERE, "upstream", "test_gimp_xcf.py"), tests)
    os.makedirs(os.path.join(tests, "data", "xcf"), exist_ok=True)
    data = os.path.join(REPO, "tests", "data")
    shutil.copy(
        os.path.join(data, "gimp-reference.xcf"), os.path.join(tests, "data", "xcf")
    )
    for name in ("layers", "nested", "blend"):
        shutil.copy(
            os.path.join(data, name + ".svg"),
            os.path.join(tests, "data", "svg", f"xcf_{name}.svg"),
        )
    print("written into", target)


if __name__ == "__main__":
    main()
