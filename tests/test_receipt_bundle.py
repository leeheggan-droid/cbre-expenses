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


def _noisy_image(w, h, seed):
    """An image that does NOT compress to nothing -- flat colour would defeat the budget test."""
    import random
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                 for _ in range(w * h)])
    return img


def _make_receipts(receipts_dir, n, seed0=0):
    plan = []
    for i in range(n):
        name = f"IMG_{i:03d}.png"
        _noisy_image(1600, 1200, seed0 + i).save(os.path.join(receipts_dir, name))
        plan.append({"lineId": f"L{i:03d}", "receiptFile": name, "merchant": f"Merchant {i}"})
    return plan


def test_bundle_fits_total_budget():
    """CBRE caps ALL attachments at 10MB per expense report -- the bundle must fit."""
    with tempfile.TemporaryDirectory() as tmp:
        receipts = os.path.join(tmp, "receipts")
        out = os.path.join(tmp, "bundle")
        os.makedirs(receipts)
        plan = _make_receipts(receipts, 6)

        budget = 120_000  # deliberately tight: individually-shrunk images blow this
        report = RB.bundle(receipts, plan, out, budget_bytes=budget)

        assert len(report["bundled"]) == 6, "every receipt must still be bundled"
        assert report["budgetBytes"] == budget
        total = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out))
        assert report["totalBytes"] == total, "reported total must match what is on disk"
        assert total <= budget, f"bundle is {total}B, over the {budget}B budget"
        assert report["fitsBudget"] is True


def test_budget_impossible_fails_loudly():
    """An unreachable budget must be reported, not silently truncated or ignored."""
    with tempfile.TemporaryDirectory() as tmp:
        receipts = os.path.join(tmp, "receipts")
        out = os.path.join(tmp, "bundle")
        os.makedirs(receipts)
        plan = _make_receipts(receipts, 4, seed0=100)

        report = RB.bundle(receipts, plan, out, budget_bytes=500)

        assert report["fitsBudget"] is False
        assert len(report["bundled"]) == 4, "files are kept -- we report, we do not delete"
        assert any("budget" in w.lower() for w in report["warnings"]), \
            "an over-budget bundle must warn loudly"


def test_default_budget_is_under_cbre_cap():
    """Default must leave headroom under CBRE's stated 10MB limit."""
    assert RB.MAX_TOTAL_BYTES < 10 * 1024 * 1024, "no headroom under the 10MB cap"
    assert RB.MAX_TOTAL_BYTES >= 9 * 1024 * 1024, "default budget is needlessly small"


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")


if __name__ == "__main__":
    _run_standalone()
