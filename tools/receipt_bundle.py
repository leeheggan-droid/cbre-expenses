"""
receipt_bundle -- build one attachable image per claim line from a folder of receipts.

CBRE attaches receipts one image per claim line (RUNBOOK.md section 6). This prepares a
tidy, shrunk bundle named to each claim line, ready to push into the expense report's
File Attachment input (a real <input type=file>, so it CAN be driven from the browser --
see docs/IMPORT-SURFACE.md). Images are downscaled (longest edge <= 1300px, JPEG q72).
Image-PDFs have their first embedded image pulled via pdfplumber and shrunk the same way;
anything else is copied as-is.

THE HARD LIMIT: CBRE caps the total size of ALL attachments at 10MB PER EXPENSE REPORT.
Shrinking each image on its own does not guarantee that -- 39 phone photos will blow it.
So the bundle is fitted to a total byte budget: if it is over, every re-encodable image is
re-encoded from its ORIGINAL source down a quality/size ladder until the whole bundle fits.
If it still cannot fit, that is reported loudly and the CLI exits non-zero. Files are never
silently dropped.

Usage:
    python tools/receipt_bundle.py --receipts-dir personal/runs/trip1/receipts \\
        --plan plan.json [--out ./bundle] [--max-total-mb 9.5]

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

# CBRE states "total size of all files must be less than 10 MB per expense report".
# Sit under it with headroom -- the cap is theirs and we do not want to discover the
# boundary at submission time.
MAX_TOTAL_BYTES = int(9.5 * 1024 * 1024)

# Walked in order when the bundle is over budget. Re-encoding always happens from the
# ORIGINAL source, never from an already-compressed output, so quality degrades once.
# A receipt only has to stay READABLE, so the tail is aggressive on purpose.
SHRINK_LADDER = (
    (1300, 72),  # the default -- what a bundle gets if it already fits
    (1100, 65),
    (900, 58),
    (760, 52),
    (640, 46),
    (520, 40),
    (420, 35),
)


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def slugify(text: str) -> str:
    """ASCII slug for a merchant name: lowercased, words joined by '-'."""
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "receipt"


def _shrink_to_jpeg(img: Image.Image, out_path: str,
                    max_edge: int = MAX_EDGE, quality: int = JPEG_QUALITY) -> int:
    """Downscale so the longest edge <= max_edge, save JPEG. Returns longest edge of result."""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest > max_edge:
        scale = max_edge / float(longest)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=quality, optimize=True)
    return max(img.size)


def _dir_total_bytes(out_dir: str) -> int:
    """Total bytes of every file in the bundle -- this is what CBRE's 10MB cap measures."""
    total = 0
    for name in os.listdir(out_dir):
        path = os.path.join(out_dir, name)
        if os.path.isfile(path):
            total += os.path.getsize(path)
    return total


def _reencode(entry: dict, max_edge: int, quality: int) -> bool:
    """Re-encode one bundled image from its ORIGINAL source at the given settings."""
    src, out_path, kind = entry["src"], entry["out"], entry["kind"]
    try:
        if kind == "image":
            with Image.open(src) as img:
                _shrink_to_jpeg(img, out_path, max_edge, quality)
            return True
        if kind == "pdf":
            img = _image_from_pdf(src)
            if img is None:
                return False
            try:
                _shrink_to_jpeg(img, out_path, max_edge, quality)
            finally:
                img.close()
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _fit_to_budget(reencodable: list[dict], out_dir: str, budget_bytes: int) -> dict:
    """Re-encode the bundle down SHRINK_LADDER until the whole thing fits the budget.

    Never deletes a file. If the floor of the ladder still does not fit, say so.
    """
    total = _dir_total_bytes(out_dir)
    used = SHRINK_LADDER[0]
    warnings: list[str] = []

    if total <= budget_bytes:
        return {"totalBytes": total, "fitsBudget": True, "settingsUsed": used, "warnings": warnings}

    if not reencodable:
        warnings.append(
            f"bundle is {total} bytes, over the {budget_bytes} byte budget, and nothing "
            "in it can be re-encoded (all files were copied as-is)"
        )
        return {"totalBytes": total, "fitsBudget": False, "settingsUsed": used, "warnings": warnings}

    for max_edge, quality in SHRINK_LADDER[1:]:
        for entry in reencodable:
            _reencode(entry, max_edge, quality)
        used = (max_edge, quality)
        total = _dir_total_bytes(out_dir)
        if total <= budget_bytes:
            warnings.append(
                f"bundle exceeded the {budget_bytes} byte budget, so it was re-encoded at "
                f"{max_edge}px/q{quality} to fit ({total} bytes)"
            )
            return {"totalBytes": total, "fitsBudget": True, "settingsUsed": used,
                    "warnings": warnings}

    warnings.append(
        f"BUDGET NOT MET: bundle is {total} bytes at the smallest setting "
        f"{used[0]}px/q{used[1]}, still over the {budget_bytes} byte budget. "
        "Split the claim across reports, or drop the largest non-image attachments."
    )
    return {"totalBytes": total, "fitsBudget": False, "settingsUsed": used, "warnings": warnings}


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


def bundle(receipts_dir: str, plan: list[dict], out_dir: str,
           budget_bytes: int = MAX_TOTAL_BYTES) -> dict:
    """Build the receipt bundle. Returns a report dict.

    For each claimed line with a receiptFile, produce exactly one file in out_dir named
    "<lineId>_<merchant-slug>.jpg" (or the copied original for non-image PDFs).

    The finished bundle is then fitted to budget_bytes -- CBRE's 10MB-per-report cap on
    the total of all attachments. See _fit_to_budget.
    """
    os.makedirs(out_dir, exist_ok=True)
    bundled, skipped, missing, copied, warnings = [], [], [], [], []
    reencodable: list[dict] = []
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
                reencodable.append({"src": src, "out": out_jpg, "kind": "image"})
            elif ext == ".pdf":
                img = _image_from_pdf(src)
                if img is not None:
                    try:
                        _shrink_to_jpeg(img, out_jpg)
                    finally:
                        img.close()
                    bundled.append(os.path.basename(out_jpg))
                    reencodable.append({"src": src, "out": out_jpg, "kind": "pdf"})
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

    fit = _fit_to_budget(reencodable, out_dir, budget_bytes)
    warnings.extend(fit["warnings"])

    return {
        "claimedWithReceipt": claimed_with_receipt,
        "bundled": bundled,
        "copiedAsIs": copied,
        "skipped": skipped,
        "missing": missing,
        "warnings": warnings,
        "outDir": out_dir,
        "totalBytes": fit["totalBytes"],
        "budgetBytes": budget_bytes,
        "fitsBudget": fit["fitsBudget"],
        "settingsUsed": fit["settingsUsed"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Bundle receipts one image per claim line (shrunk for upload).")
    ap.add_argument("--receipts-dir", required=True, help="folder of receipt image/PDF files")
    ap.add_argument("--plan", required=True, help="JSON list of {lineId, receiptFile, merchant} for claimed lines")
    ap.add_argument("--out", default="./bundle", help="output dir for the bundle (default: ./bundle)")
    ap.add_argument("--max-total-mb", type=float, default=MAX_TOTAL_BYTES / (1024 * 1024),
                    help="total byte budget for ALL attachments; CBRE's cap is 10MB per "
                         "expense report (default: %(default).1f)")
    args = ap.parse_args()

    plan = load_json(args.plan)
    if not isinstance(plan, list):
        print("ERROR: --plan must be a JSON list of {lineId, receiptFile, merchant}")
        sys.exit(2)

    budget = int(args.max_total_mb * 1024 * 1024)
    report = bundle(args.receipts_dir, plan, args.out, budget_bytes=budget)

    mb = report["totalBytes"] / (1024 * 1024)
    edge, quality = report["settingsUsed"]
    print(f"Receipt bundle -> {report['outDir']}")
    print(f"  claimed lines with a receiptFile : {report['claimedWithReceipt']}")
    print(f"  bundled receipts                 : {len(report['bundled'])}")
    print(f"  total size                       : {mb:.2f} MB of {args.max_total_mb:.1f} MB budget")
    print(f"  encoded at                       : {edge}px / q{quality}")
    if report["copiedAsIs"]:
        print(f"  copied as-is (no shrink)         : {len(report['copiedAsIs'])}")
    if report["skipped"]:
        print(f"  skipped non-receipt files        : {len(report['skipped'])}")
    if report["missing"]:
        print(f"  MISSING source files             : {len(report['missing'])}")
    for w in report["warnings"]:
        print(f"  WARN: {w}")

    if not report["fitsBudget"]:
        print("!" * 60)
        print(f"VERIFY FAILED: bundle is {mb:.2f} MB, over the {args.max_total_mb:.1f} MB budget.")
        print("  CBRE rejects an expense report whose attachments exceed 10MB in total.")
        print("  Split the claim across reports, or remove non-image attachments.")
        print("!" * 60)
        sys.exit(1)

    n_bundled = len(report["bundled"])
    n_claimed = report["claimedWithReceipt"]
    if n_bundled == n_claimed:
        print(f"VERIFY OK: bundled {n_bundled} == claimed-with-receipt {n_claimed}, "
              f"{mb:.2f} MB within budget")
    else:
        print("!" * 60)
        print(f"VERIFY FAILED: bundled {n_bundled} != claimed-with-receipt {n_claimed}")
        print("  Some claim lines will be missing a receipt attachment. Investigate the WARN lines above.")
        print("!" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
