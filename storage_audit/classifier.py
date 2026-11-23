"""File-type classification.

Extension-derived, best-effort, filename-based only. Never a claim about
file contents. Every record carries CLASSIFICATION_VERSION so old reports
remain interpretable.
"""

import mimetypes

CLASSIFICATION_RULE_VERSION = "1.0.0"

CATEGORY_IMAGES = "image"
CATEGORY_VIDEO = "video"
CATEGORY_AUDIO = "audio"
CATEGORY_DOCUMENT = "document"
CATEGORY_ARCHIVE = "archive"
CATEGORY_PACKAGE = "package"       # android packages / installers
CATEGORY_CODE = "code"
CATEGORY_DATABASE = "database"
CATEGORY_FONT = "font"
CATEGORY_BACKUP = "backup"
CATEGORY_SYSTEM = "system/unknown"
CATEGORY_OTHER = "other"
CATEGORY_UNKNOWN = "unknown"

CATEGORIES = [
    CATEGORY_IMAGES,
    CATEGORY_VIDEO,
    CATEGORY_AUDIO,
    CATEGORY_DOCUMENT,
    CATEGORY_ARCHIVE,
    CATEGORY_PACKAGE,
    CATEGORY_CODE,
    CATEGORY_DATABASE,
    CATEGORY_FONT,
    CATEGORY_BACKUP,
    CATEGORY_SYSTEM,
    CATEGORY_OTHER,
    CATEGORY_UNKNOWN,
]

_IMAGE = ["jpg", "jpeg", "png", "webp", "gif", "heic", "heif", "bmp", "tif",
          "tiff", "svg", "avif", "raw", "cr2", "cr3", "nef", "arw", "dng",
          "orf", "rw2", "raf", "pef"]
_VIDEO = ["mp4", "mkv", "mov", "avi", "webm", "3gp", "m4v", "ts", "mpeg",
          "mpg", "wmv", "flv", "3g2"]
_AUDIO = ["mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "amr", "mid",
          "midi", "wma", "aiff", "ape"]
_DOCUMENT = ["pdf", "doc", "docx", "odt", "rtf", "txt", "md", "csv", "tsv",
             "xls", "xlsx", "ppt", "pptx", "epub", "odp", "ods", "pages",
             "numbers", "key", "log", "nfo", "srt", "vtt"]
_ARCHIVE = ["zip", "7z", "rar", "tar", "gz", "bz2", "xz", "zst", "lz", "lzma",
            "br", "iso", "cab", "jar", "war", "cpio", "tgz", "tbz2"]
_PACKAGE = ["apk", "apks", "xapk", "aab", "exe", "msi", "dmg", "deb", "rpm",
            "appimage"]
_CODE = ["py", "js", "jsx", "tsx", "html", "htm", "css", "scss", "less",
         "java", "kt", "kts", "c", "cc", "cpp", "h", "hpp", "rs", "go", "rb",
         "php", "swift", "m", "scala", "sh", "bash", "zsh", "fish", "json",
         "xml", "yaml", "yml", "toml", "ini", "sql", "gradle", "properties",
         "makefile", "cmake", "cfg", "conf"]
_DATABASE = ["db", "sqlite", "sqlite3", "mdb"]
_FONT = ["ttf", "otf", "woff", "woff2", "eot"]
_BACKUP = ["bak", "backup", "old", "~"]
_SYSTEM = ["nomedia", "thumbnails", "tmp", "temp", "cache", "lock", "pid",
           "sys", "drv"]

_EXTENSION_TO_CATEGORY = {}
for _cat, _exts in (
    (CATEGORY_IMAGES, _IMAGE),
    (CATEGORY_VIDEO, _VIDEO),
    (CATEGORY_AUDIO, _AUDIO),
    (CATEGORY_DOCUMENT, _DOCUMENT),
    (CATEGORY_ARCHIVE, _ARCHIVE),
    (CATEGORY_PACKAGE, _PACKAGE),
    (CATEGORY_CODE, _CODE),
    (CATEGORY_DATABASE, _DATABASE),
    (CATEGORY_FONT, _FONT),
    (CATEGORY_BACKUP, _BACKUP),
    (CATEGORY_SYSTEM, _SYSTEM),
):
    for _e in _exts:
        _EXTENSION_TO_CATEGORY[_e] = _cat

# Extensions deliberately treated as unknown/ambiguous: guessing would invent
# a type. Anything not in this table and not known above is also unknown.
_AMBIGUOUS = {"bin", "dat", "img", "chk", "000"}

COMPRESSOR_SUFFIXES = {"gz", "bz2", "xz", "zst", "lz", "lzma", "br"}


def split_extension(name):
    """Split a filename into (final_extension, compound_extension, extension_original).

    Deterministic rules (see docs/ARCHITECTURE.md):

    - Leading dots are skipped for the extension search, so a dotfile such as
      ``.nomedia`` has no extension.
    - A name with no dot after the leading-dot-stripped stem has no extension.
    - A name ending with a trailing dot has no extension.
    - Otherwise the final suffix is the substring after the last dot.
    - ``archive.tar.gz`` additionally yields compound extension ``tar.gz``
      when the layer before the final compressor suffix is ``tar``.

    Returns (extension_lower_or_None, compound_lower_or_None, original_suffix_or_None).
    """
    if not name:
        return None, None, None

    stripped = name.lstrip(".")
    leading_dots = len(name) - len(stripped)

    if stripped == "":
        return None, None, None  # name consisting only of dots

    if "." not in stripped:
        return None, None, None  # dotfile with no other dot (e.g. .gitignore)

    if stripped.endswith("."):
        return None, None, None  # trailing dot: deterministic no-extension

    final = stripped.rsplit(".", 1)[1]
    if final == "":
        return None, None, None

    compound = None
    if final.lower() in COMPRESSOR_SUFFIXES:
        stem = stripped.rsplit(".", 1)[0]
        if stem.lower() == "tar" or stem.lower().endswith(".tar"):
            compound = "tar." + final.lower()

    return final.lower(), compound, final


def classify_extension(extension_lower):
    """Map a normalized lowercase extension to a category.

    Unknown or ambiguous extensions return CATEGORY_UNKNOWN. Never raises.
    """
    if not extension_lower:
        return CATEGORY_UNKNOWN
    if extension_lower in _AMBIGUOUS:
        return CATEGORY_UNKNOWN
    return _EXTENSION_TO_CATEGORY.get(extension_lower, CATEGORY_UNKNOWN)


def mime_guess_for(extension_lower):
    """Best-effort filename-derived MIME guess. Returns None when unknown.

    The result is always an inference from the filename, never verified
    content. Callers must label it as such.
    """
    if not extension_lower:
        return None
    if extension_lower in _AMBIGUOUS:
        return None
    guess, _encoding = mimetypes.guess_type("file." + extension_lower)
    return guess  # may be None; callers must handle


def normalize_compare_name(name):
    """Case-insensitive comparison key for sorting/search.

    Never stored as a replacement for the original name.
    """
    return name.casefold() if name else ""


def all_categories():
    return list(CATEGORIES)


def known_extensions():
    return sorted(_EXTENSION_TO_CATEGORY)
