"""
Tests for ../gimp_xcf.py, which writes XCF files itself (no GIMP needed).

The Inkscape calls that render the layers are replayed from
data/cmd/inkscape; the expected XCF files are in data/refs. Their layer
structure is also checked here with the reader from test_xcf_writer.py,
so the binary reference files are not the only check.

compare_file is a tuple in the new tests so that the drawing's name
becomes part of the reference file's name.
"""

from gimp_xcf import GimpXcf
from inkex.tester import ComparisonMixin, TestCase
from inkex.tester.mock import Capture

from .test_xcf_writer import parse


class GimpXcfBasicTest(ComparisonMixin, TestCase):
    """Default options on the standard test drawing"""

    effect_class = GimpXcf
    comparisons = ((),)


class GimpXcfGuidesTest(ComparisonMixin, TestCase):
    """Guides and grid"""

    effect_class = GimpXcf
    compare_file = "svg/guides.svg"
    comparisons = (("-d=true", "-r=true"),)


class GimpXcfLayersTest(ComparisonMixin, TestCase):
    """Sublayers as groups, hidden layers, opacity, blend modes, guides,
    grid; and every option switched the other way"""

    effect_class = GimpXcf
    compare_file = ("svg/xcf_layers.svg",)
    comparisons = (
        ("-d=true", "-r=true"),
        ("--groups=false", "--hidden=false", "--crop=false", "-b=true", "-i=150"),
    )

    def test_structure(self):
        """The layer tree in the saved file"""
        effect = self.assertEffect(
            self.data_file(self.compare_file[0]), args=["-d=true"]
        )
        info = parse(effect.test_output.getvalue())
        names = [
            (item["name"], item["props"].get("ITEM_PATH")) for item in info["layers"]
        ]
        self.assertEqual(
            names,
            [
                ("Top multiply", None),
                ("Middle", None),
                ("Sub hidden", [1, 0]),
                ("Sub one", [1, 1]),
                ("Middle", [1, 2]),
                ("Back", None),
                ("Objects outside layers", None),
            ],
        )
        layers = info["layers"]
        self.assertEqual(layers[0]["props"]["MODE"], 30)  # multiply
        self.assertEqual(layers[0]["props"]["COMPOSITE_MODE"], 1)  # union, as CSS
        self.assertEqual(layers[1]["props"]["OPACITY"], 128)
        self.assertEqual(layers[2]["props"]["VISIBLE"], 0)
        self.assertEqual(info["props"]["GUIDES"], [[76, "h"], [113, "v"]])


class GimpXcfNestedTest(ComparisonMixin, TestCase):
    """Blend modes inside an isolated group, baked against their backdrop"""

    effect_class = GimpXcf
    compare_file = ("svg/xcf_nested.svg",)
    comparisons = ((),)


class GimpXcfBlendTest(ComparisonMixin, TestCase):
    """All 15 CSS blend modes; the 7 that GIMP lacks are baked"""

    effect_class = GimpXcf
    compare_file = ("svg/xcf_blend.svg",)
    comparisons = ((),)


class GimpXcfNearestBlendTest(ComparisonMixin, TestCase):
    """The 7 blend modes GIMP lacks, kept as GIMP's nearest modes, with a
    warning that those layers look different"""

    effect_class = GimpXcf
    compare_file = ("svg/xcf_blend.svg",)
    comparisons = (("--blend=gimp",),)
    stderr_protect = False

    def test_warning(self):
        """The warning names every approximated layer"""
        with Capture("stderr") as stderr:
            self.assertEffect(
                self.data_file(self.compare_file[0]), args=["--blend=gimp"]
            )
        message = stderr.getvalue()
        self.assertIn("no exact match", message)
        for mode in ("color-dodge", "color-burn", "soft-light", "hue", "luminosity"):
            self.assertIn(mode, message)
