"""
receipt_bundle -- build one attachable image per claim line from a folder of receipts.

CBRE attaches receipts one image per claim line (RUNBOOK.md section 6). The Chrome
extension can't reach the myfin.cbre.com upload, so the user does download+upload by
hand -- this just prepares a tidy, shrunk bundle named to each claim line so that step
is fast. Images are downscaled (longest edge <= 1300px, JPEG q72). Image-PDFs have their
first embedded image pulled via pdfplumber and shrunk the same way; anything else is
copied as-is.

Usage:
    python tools/receipt_bundle.py --receipts-dir personal/runs/trip1/receipts \\
        --plan plan.json [--out ./bundle]

plan.json is a JSON list of claimed lines:
    [ { "lineId": "L001", "receiptFile": "IMG_0001.jpeg", "merchant": "Acme Cafe" }, ... ]

VERIFY: at the end #bundled == #claimed lines that have a receiptFile (warns loudly if not).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys

from PIL import Image

MAX_EDGE = 1300
JPEG_QUALITY = 72
IMAGE_EXTS = (".png", ".jpg", ".jpeg")
SKIP_EXTS = (".mov", ".mp4", ".avi", ".heic")  # non-receipt media


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def slugify(text: str) -> str:
    """ASCII slug for a merchant name: lowercased, words joined by '-'."""
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "receipt"


def _shrink_to_jpeg(img: Image.Image, out_path: str) -> int:
    """Downscale so the longest edge <= MAX_EDGE, save JPEG. Returns longest edge of result."""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest > MAX_EDGE:
        scale = MAX_EDGE / float(longest)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return max(img.size)


def _image_from_pdf(pdf_path: str) -> Image.Image | None:
    """Try to pull the first embedded image out of an image-PDF via pdfplumber.

    The DCTDecode rawdata is JPEG bytes (RUNBOOK section 6). Returns a PIL Image or None.
    """
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                if not page.images:
                    continue
                stream = page.images[0].get("stream")
                if stream is None:
                    continue
                rawdata = getattr(stream, "rawdata", None)
                if rawdata is None and hasattr(stream, "get_rawdata"):
                    rawdata = stream.get_rawdata()
                if rawdata is None:
                    continue
                try:
                    return Image.open(io.BytesIO(rawdata))
                except Exception:
                    # not directly decodable bytes; fall through to next page/image
                    continue
    except Exception:
        return None
    return None


def bundle(receipts_dir: str, plan: list[dict], out_dir: str) -> dict:
    """Build the receipt bundle. Returns a report dict.

    For each claimed line with a receiptFile, produce exactly one file in out_dir named
    "<lineId>_<merchant-slug>.jpg" (or the copied original for non-image PDFs).
    """
    os.makedirs(out_dir, exist_ok=True)
    bundled, skipped, missing, copied, warnings = [], [], [], [], []
    claimed_with_receipt = 0

    for entry in plan:
        line_id = entry.get("lineId", "")
        receipt_file = entry.get("receiptFile")
        merchant = entry.get("merchant", "")
        if not receipt_file:
            continue  # claimed line with no receipt -> not part of the verify count
        claimed_with_receipt += 1

        src = os.path.join(receipts_dir, receipt_file)
        ext = os.path.splitext(receipt_file)[1].lower()
        base = f"{line_id}_{slugify(merchant)}"

        if ext in SKIP_EXTS:
            skipped.append(receipt_file)
            warnings.append(f"line {line_id}: '{receipt_file}' is non-receipt media ({ext}) - skipped")
            continue
        if not os.path.exists(src):
            missing.append(receipt_file)
            warnings.append(f"line {line_id}: receipt file not found: {src}")
            continue

        out_jpg = os.path.join(out_dir, base + ".jpg")
        try:
            if ext in IMAGE_EXTS:
                with Image.open(src) as img:
                    _shrink_to_jpeg(img, out_jpg)
                bundled.append(os.path.basename(out_jpg))
            elif ext == ".pdf":
                img = _image_from_pdf(src)
                if img is not None:
                    try:
                        _shrink_to_jpeg(img, out_jpg)
                    finally:
                        img.close()
                    bundled.append(os.path.basename(out_jpg))
                else:
                    out_pdf = os.path.join(out_dir, base + ".pdf")
                    shutil.copyfile(src, out_pdf)
                    copied.append(os.path.basename(out_pdf))
                    bundled.append(os.path.basename(out_pdf))
                    warnings.append(f"line {line_id}: could not extract image from PDF - copied as-is")
            else:
                # unknown extension that isn't explicitly skipped: copy through
                out_other = os.path.join(out_dir, base + ext)
                shutil.copyfile(src, out_other)
                copied.append(os.path.basename(out_other))
                bundled.append(os.path.basename(out_other))
                warnings.append(f"line {line_id}: unrecognised type '{ext}' - copied as-is")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"line {line_id}: failed to process '{receipt_file}': {exc}")

    return {
        "claimedWithReceipt": claimed_with_receipt,
        "bundled": bundled,
        "copiedAsIs": copied,
        "skipped": skipped,
        "missing": missing,
        "warnings": warnings,
        "outDir": out_dir,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Bundle receipts one image per claim line (shrunk for upload).")
    ap.add_argument("--receipts-dir", required=True, help="folder of receipt image/PDF files")
    ap.add_argument("--plan", required=True, help="JSON list of {lineId, receiptFile, merchant} for claimed lines")
    ap.add_argument("--out", default="./bundle", help="output dir for the bundle (default: ./bundle)")
    args = ap.parse_args()

    plan = load_json(args.plan)
    if not isinstance(plan, list):
        print("ERROR: --plan must be a JSON list of {lineId, receiptFile, merchant}")
        sys.exit(2)

    report = bundle(args.receipts_dir, plan, args.out)

    print(f"Receipt bundle -> {report['outDir']}")
    print(f"  claimed lines with a receiptFile : {report['claimedWithReceipt']}")
    print(f"  bundled receipts                 : {len(report['bundled'])}")
    if report["copiedAsIs"]:
        print(f"  copied as-is (no shrink)         : {len(report['copiedAsIs'])}")
    if report["skipped"]:
        print(f"  skipped non-receipt files        : {len(report['skipped'])}")
    if report["missing"]:
        print(f"  MISSING source files             : {len(report['missing'])}")
    for w in report["warnings"]:
        print(f"  WARN: {w}")

    n_bundled = len(report["bundled"])
    n_claimed = report["claimedWithReceipt"]
    if n_bundled == n_claimed:
        print(f"VERIFY OK: bundled {n_bundled} == claimed-with-receipt {n_claimed}")
    else:
        print("!" * 60)
        print(f"VERIFY FAILED: bundled {n_bundled} != claimed-with-receipt {n_claimed}")
        print("  Some claim lines will be missing a receipt attachment. Investigate the WARN lines above.")
        print("!" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
