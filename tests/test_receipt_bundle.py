"""Unit tests for receipt_bundle: image downscale, naming, and the #receipts==#lines verify.

Run with pytest, or standalone:  python tests/test_receipt_bundle.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import receipt_bundle as RB  # noqa: E402
from PIL import Image  # noqa: E402


def test_slugify():
    assert RB.slugify("Acme Cafe, Docklands") == "acme-cafe-docklands"
    assert RB.slugify("Rideshare (Some Provider)") == "rideshare-some-provider"
    assert RB.slugify("") == "receipt"
    assert RB.slugify("---") == "receipt"


def test_image_downscaled_and_named():
    with tempfile.TemporaryDirectory() as tmp:
        receipts = os.path.join(tmp, "receipts")
        out = os.path.join(tmp, "bundle")
        os.makedirs(receipts)
        # large PNG -> must be shrunk to <= 1300px longest edge
        big = Image.new("RGB", (2600, 1800), (123, 50, 200))
        big.save(os.path.join(receipts, "IMG_TEST.png"))

        plan = [{"lineId": "L001", "receiptFile": "IMG_TEST.png", "merchant": "Acme Cafe"}]
        report = RB.bundle(receipts, plan, out)

        out_jpg = os.path.join(out, "L001_acme-cafe.jpg")
        assert os.path.exists(out_jpg), "expected output JPEG was not produced"
        with Image.open(out_jpg) as im:
            assert im.format == "JPEG"
            assert max(im.size) <= RB.MAX_EDGE, f"longest edge {max(im.size)} > {RB.MAX_EDGE}"
        assert report["bundled"] == ["L001_acme-cafe.jpg"]


def test_small_image_not_upscaled():
    with tempfile.TemporaryDirectory() as tmp:
        receipts = os.path.join(tmp, "receipts")
        out = os.path.join(tmp, "bundle")
        os.makedirs(receipts)
        small = Image.new("RGB", (400, 300), (10, 20, 30))
        small.save(os.path.join(receipts, "small.jpg"))

        plan = [{"lineId": "L9", "receiptFile": "small.jpg", "merchant": "Cafe"}]
        RB.bundle(receipts, plan, out)
        with Image.open(os.path.join(out, "L9_cafe.jpg")) as im:
            assert im.size == (400, 300), "small images should not be upscaled"


def test_skip_non_receipt_and_verify_mismatch():
    with tempfile.TemporaryDirectory() as tmp:
        receipts = os.path.join(tmp, "receipts")
        out = os.path.join(tmp, "bundle")
        os.makedirs(receipts)
        Image.new("RGB", (500, 500), (0, 0, 0)).save(os.path.join(receipts, "ok.png"))
        # .mov is skipped; a missing file is also not bundled
        plan = [
            {"lineId": "L1", "receiptFile": "ok.png", "merchant": "Bar"},
            {"lineId": "L2", "receiptFile": "clip.MOV", "merchant": "Nope"},
            {"lineId": "L3", "receiptFile": "gone.jpg", "merchant": "Missing"},
            {"lineId": "L4"},  # claimed line with no receipt -> not counted
        ]
        report = RB.bundle(receipts, plan, out)
        assert report["claimedWithReceipt"] == 3  # L1, L2, L3 (L4 has no receiptFile)
        assert len(report["bundled"]) == 1        # only L1 bundled -> verify would fail
        assert "clip.MOV" in report["skipped"]
        assert "gone.jpg" in report["missing"]


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")


if __name__ == "__main__":
    _run_standalone()
