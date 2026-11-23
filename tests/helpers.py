"""Shared test helpers: synthetic fixture trees (never user data).

ALL fixtures built here are SYNTHETIC TEST DATA. They are created fresh in a
temporary directory for each test and deleted afterwards.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_rich_fixture(root):
    """Build the standard rich fixture used across tests. Returns root path."""
    os.makedirs(root, exist_ok=True)

    def write(rel, data, binary=False):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if binary else "w"
        with open(path, mode) as fh:
            fh.write(data)

    # Nested folders + deep path
    write("Documents/report.txt", "hello world")
    write("Documents/Reports/2024/annual report.pdf", "year-end")
    write("Documents/Reports/2025/q1,v2 \"final\".xlsx", "Q1")
    write("DCIM/deep/a/b/c/d/e/f/deepfile.txt", "deep")
    # Empty folders (must be recorded, must be reported empty)
    os.makedirs(os.path.join(root, "EmptyDir/nested_empty"))
    # Hidden folder + hidden file
    write(".hidden_dir/inner/.secret_inner.txt", "inner secret")
    write(".hidden_dir/secret.txt", "hidden content")
    write(".hidden_file", "dotfile")
    # Common extensions
    write("DCIM/Camera/IMG_0001.JPG", "jpg")
    write("DCIM/Camera/IMG_0002.png", "png")
    write("Music/track one.mp3", "audio")
    write("Pictures/emoji 🎉 photo.jpg", "emoji")
    # No extension / dotfile / zero-byte
    write("Download/README", "noext")
    write("Download/zero.bin", "")
    # Compound archive extension
    write("Download/data.tar.gz", "data")
    # Backups + packages + databases + code + fonts
    write("Download/photos.zip.bak", "backup")
    write("Download/app.apk", "apk")
    write("Documents/app.sqlite3", "db")
    write("Documents/script.py", "code")
    write("Documents/font.ttf", "font")
    # Unicode / emoji / punctuation
    write("Documents/रिपोर्ट.txt", "unicode")
    write("Documents/comma \"quoted\" name.txt", "comma,quote")
    # Control characters (host-dependent but Linux permits them)
    write("Documents/tab\tname.txt", "tab")
    write("Documents/new\nline.txt", "newline")
    # Duplicate sizes, different content
    write("Documents/dup_a.bin", "same-size-a")
    write("Documents/dup_b.bin", "same-size-a")
    # Case-only extension difference
    write("Documents/upper.PNG", "png")
    # Symlinks (loop, to file, broken)
    try:
        os.symlink("../Documents/report.txt", os.path.join(root, "Download/report_link.txt"))
        os.symlink("../Documents", os.path.join(root, "Download/docs_dir_link"))
        os.symlink("/nonexistent_path_xyz_123", os.path.join(root, "Download/broken_link"))
    except (OSError, NotImplementedError):
        pass  # filesystem without symlink support; tests skip themselves

    # HTML/script-injection filename (must render as text)
    write("Download/<img src=x onerror=alert(1)>.html", "x")

    # A directory whose name looks like a file extension
    os.makedirs(os.path.join(root, "weird.d"), exist_ok=True)
    write("weird.d/file.txt", "x")

    # Sparse large file (avoid real allocation)
    sparse = os.path.join(root, "Download/sparse_large.bin")
    with open(sparse, "wb") as fh:
        fh.truncate(256 * 1024 * 1024)  # 256 MiB logical, ~0 allocated

    return root


def snapshot_tree(root):
    """Map relpath -> (st_size, st_mtime_ns) for read-only verification."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
                snap[os.path.relpath(path, root)] = (st.st_size, st.st_mtime_ns)
            except OSError:
                snap[os.path.relpath(path, root)] = None
    return snap
