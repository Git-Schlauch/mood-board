#!/usr/bin/env python3
"""Backfill native_width and native_height for existing image records.

Reads all image records from the database, looks up each file on disk,
extracts the native pixel dimensions from PNG and JPEG headers using only
the standard library, and updates the database.

Usage::

    python scripts/backfill_native_dims.py
"""

from __future__ import annotations

import os
import struct
import sys

# Ensure the project root is on sys.path so we can import backend.database.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.database import Database


def get_png_dimensions(file_path: str) -> tuple[int, int]:
    """Extract width and height from a PNG file header.

    PNG stores the image dimensions in the IHDR chunk at a fixed offset.
    Bytes 16-19 are the 4-byte big-endian width and bytes 20-23 are the
    4-byte big-endian height.

    Args:
        file_path: Path to the PNG file.

    Returns:
        A (width, height) tuple, or (0, 0) on failure.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(24)
            if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
                return (0, 0)
            width, height = struct.unpack(">II", header[16:24])
            return (width, height)
    except OSError:
        return (0, 0)


def get_jpeg_dimensions(file_path: str) -> tuple[int, int]:
    """Extract width and height from a JPEG file by scanning for SOF markers.

    Scans through JPEG markers looking for a Start Of Frame marker
    (0xFFC0-0xFFC3) which contains the image dimensions.  Height is
    stored at offset +5 and width at offset +7 within the marker data.

    Args:
        file_path: Path to the JPEG file.

    Returns:
        A (width, height) tuple, or (0, 0) on failure.
    """
    try:
        with open(file_path, "rb") as f:
            data = f.read()

        if len(data) < 2 or data[0:2] != b"\xff\xd8":
            return (0, 0)

        offset = 2
        while offset < len(data) - 1:
            if data[offset] != 0xFF:
                offset += 1
                continue

            marker = data[offset + 1]

            # SOF markers: 0xC0-0xC3 contain image dimensions.
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                if offset + 9 < len(data):
                    height = struct.unpack(">H", data[offset + 5 : offset + 7])[0]
                    width = struct.unpack(">H", data[offset + 7 : offset + 9])[0]
                    return (width, height)
                return (0, 0)

            # Skip non-SOF markers by reading their length field.
            if marker == 0xD9:  # EOI
                break
            if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01):
                # Standalone markers — no payload.
                offset += 2
                continue

            if offset + 3 < len(data):
                length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
                offset += 2 + length
            else:
                break

        return (0, 0)
    except OSError:
        return (0, 0)


def get_image_dimensions(file_path: str) -> tuple[int, int]:
    """Detect image type and extract native pixel dimensions.

    Supports PNG and JPEG formats.  Returns (0, 0) for unrecognised
    formats or if the file cannot be read.

    Args:
        file_path: Path to the image file.

    Returns:
        A (width, height) tuple.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".png":
        return get_png_dimensions(file_path)
    if ext in (".jpg", ".jpeg"):
        return get_jpeg_dimensions(file_path)

    # Try PNG first, then JPEG as a fallback for unknown extensions.
    dims = get_png_dimensions(file_path)
    if dims != (0, 0):
        return dims
    return get_jpeg_dimensions(file_path)


def main() -> None:
    """Run the backfill: read all images, extract dims, update the database."""
    db = Database()
    db.initialize()

    projects = db.list_projects()
    updated = 0
    skipped = 0
    failed = 0

    for project in projects:
        images = db.list_images(project["id"])
        for img in images:
            # Skip records that already have native dimensions.
            if img.get("native_width", 0) > 0 and img.get("native_height", 0) > 0:
                skipped += 1
                continue

            file_path = db.get_image_path(project["name"], img["filename"])
            if not os.path.isfile(file_path):
                print(f"  MISSING: {file_path}")
                failed += 1
                continue

            width, height = get_image_dimensions(file_path)
            if width == 0 or height == 0:
                print(f"  UNREADABLE: {file_path}")
                failed += 1
                continue

            with db.connect() as conn:
                conn.execute(
                    "UPDATE images SET native_width = ?, native_height = ? WHERE id = ?",
                    (width, height, img["id"]),
                )
            print(f"  UPDATED: {img['filename']} -> {width}x{height}")
            updated += 1

    print(f"\nDone. Updated: {updated}, Skipped: {skipped}, Failed: {failed}")


if __name__ == "__main__":
    main()
