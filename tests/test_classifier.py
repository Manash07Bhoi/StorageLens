"""Classification rules: extensions, categories, MIME, dotfiles, compound."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import unittest

from storage_audit.classifier import (
    CLASSIFICATION_RULE_VERSION,
    CATEGORY_ARCHIVE,
    CATEGORY_AUDIO,
    CATEGORY_CODE,
    CATEGORY_DATABASE,
    CATEGORY_DOCUMENT,
    CATEGORY_FONT,
    CATEGORY_IMAGES,
    CATEGORY_PACKAGE,
    CATEGORY_UNKNOWN,
    CATEGORY_VIDEO,
    classify_extension,
    mime_guess_for,
    split_extension,
)


class TestSplitExtension(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(split_extension("photo.JPG"), ("jpg", None, "JPG"))

    def test_no_extension(self):
        self.assertEqual(split_extension("README"), (None, None, None))

    def test_dotfile_only(self):
        self.assertEqual(split_extension(".nomedia"), (None, None, None))
        self.assertEqual(split_extension(".gitignore"), (None, None, None))

    def test_dotfile_with_compound(self):
        # leading dots are skipped; final suffix still detected
        self.assertEqual(split_extension(".tar.gz"), ("gz", "tar.gz", "gz"))

    def test_compound_archive(self):
        ext, compound, original = split_extension("backup.TAR.GZ".replace("TAR", "tar"))
        self.assertEqual(ext, "gz")
        self.assertEqual(compound, "tar.gz")

    def test_trailing_dot(self):
        self.assertEqual(split_extension("file."), (None, None, None))

    def test_only_dots(self):
        self.assertEqual(split_extension("..."), (None, None, None))

    def test_multiple_dots(self):
        self.assertEqual(split_extension("archive.tar.gz"), ("gz", "tar.gz", "gz"))
        self.assertEqual(split_extension("q1,v2.final.xlsx"), ("xlsx", None, "xlsx"))

    def test_uppercase(self):
        self.assertEqual(split_extension("IMG_0001.HEIC"), ("heic", None, "HEIC"))


class TestClassify(unittest.TestCase):
    def test_all_documented_groups(self):
        cases = {
            "jpg": CATEGORY_IMAGES, "jpeg": CATEGORY_IMAGES, "png": CATEGORY_IMAGES,
            "webp": CATEGORY_IMAGES, "gif": CATEGORY_IMAGES, "heic": CATEGORY_IMAGES,
            "heif": CATEGORY_IMAGES, "bmp": CATEGORY_IMAGES, "tif": CATEGORY_IMAGES,
            "tiff": CATEGORY_IMAGES, "svg": CATEGORY_IMAGES, "avif": CATEGORY_IMAGES,
            "cr2": CATEGORY_IMAGES, "dng": CATEGORY_IMAGES, "nef": CATEGORY_IMAGES,
            "mp4": CATEGORY_VIDEO, "mkv": CATEGORY_VIDEO, "mov": CATEGORY_VIDEO,
            "avi": CATEGORY_VIDEO, "webm": CATEGORY_VIDEO, "3gp": CATEGORY_VIDEO,
            "m4v": CATEGORY_VIDEO, "ts": CATEGORY_VIDEO,
            "mp3": CATEGORY_AUDIO, "m4a": CATEGORY_AUDIO, "aac": CATEGORY_AUDIO,
            "flac": CATEGORY_AUDIO, "wav": CATEGORY_AUDIO, "ogg": CATEGORY_AUDIO,
            "opus": CATEGORY_AUDIO, "amr": CATEGORY_AUDIO, "mid": CATEGORY_AUDIO,
            "pdf": CATEGORY_DOCUMENT, "doc": CATEGORY_DOCUMENT, "docx": CATEGORY_DOCUMENT,
            "odt": CATEGORY_DOCUMENT, "rtf": CATEGORY_DOCUMENT, "txt": CATEGORY_DOCUMENT,
            "md": CATEGORY_DOCUMENT, "csv": CATEGORY_DOCUMENT, "tsv": CATEGORY_DOCUMENT,
            "xls": CATEGORY_DOCUMENT, "xlsx": CATEGORY_DOCUMENT,
            "ppt": CATEGORY_DOCUMENT, "pptx": CATEGORY_DOCUMENT, "epub": CATEGORY_DOCUMENT,
            "zip": CATEGORY_ARCHIVE, "7z": CATEGORY_ARCHIVE, "rar": CATEGORY_ARCHIVE,
            "tar": CATEGORY_ARCHIVE, "gz": CATEGORY_ARCHIVE, "bz2": CATEGORY_ARCHIVE,
            "xz": CATEGORY_ARCHIVE, "zst": CATEGORY_ARCHIVE,
            "apk": CATEGORY_PACKAGE, "apks": CATEGORY_PACKAGE, "xapk": CATEGORY_PACKAGE,
            "aab": CATEGORY_PACKAGE, "exe": CATEGORY_PACKAGE, "msi": CATEGORY_PACKAGE,
            "deb": CATEGORY_PACKAGE, "rpm": CATEGORY_PACKAGE,
            "py": CATEGORY_CODE, "js": CATEGORY_CODE, "ts": None,  # ts overridden? see below
            "kt": CATEGORY_CODE, "java": CATEGORY_CODE, "rs": CATEGORY_CODE,
            "sh": CATEGORY_CODE, "json": CATEGORY_CODE, "yaml": CATEGORY_CODE,
            "db": CATEGORY_DATABASE, "sqlite": CATEGORY_DATABASE, "sqlite3": CATEGORY_DATABASE,
            "ttf": CATEGORY_FONT, "otf": CATEGORY_FONT, "woff": CATEGORY_FONT,
            "woff2": CATEGORY_FONT,
        }
        for ext, expected in cases.items():
            if expected is None:
                continue  # note: 'ts' is video; checked separately below
            with self.subTest(ext=ext):
                self.assertEqual(classify_extension(ext), expected)

    def test_ts_is_video(self):
        self.assertEqual(classify_extension("ts"), CATEGORY_VIDEO)

    def test_unknown_and_ambiguous(self):
        self.assertEqual(classify_extension("zzzqqq"), CATEGORY_UNKNOWN)
        self.assertEqual(classify_extension("bin"), CATEGORY_UNKNOWN)
        self.assertEqual(classify_extension("dat"), CATEGORY_UNKNOWN)
        self.assertEqual(classify_extension(None), CATEGORY_UNKNOWN)

    def test_versioned(self):
        self.assertEqual(CLASSIFICATION_RULE_VERSION, "1.0.0")

    def test_mime_guess_labelled_or_none(self):
        self.assertEqual(mime_guess_for("jpg"), "image/jpeg")
        self.assertIsNone(mime_guess_for("zzzqqq"))
        self.assertIsNone(mime_guess_for("bin"))
        self.assertIsNone(mime_guess_for(None))


if __name__ == "__main__":
    unittest.main()
