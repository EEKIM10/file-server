import os
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from magic import Magic
from typing import Union, Tuple


logger = logging.getLogger(__name__)


__all__ = (
    "guess_mime_type",
    "mime_type_from_file_ext",
    "can_access",
    "read_or_stream",
    "has_changed",
    "get_etag",
    "is_not_special_file",
    "is_root_or_below",
    "bytes_to_human"
)


def bytes_to_human(n: int) -> Tuple[Union[float, int], str]:
    """Converts a number of bytes to a human-readable format (e.g. 1.2MB)"""
    symbols = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    prefix = {}
    for i, s in enumerate(symbols[1:]):
        prefix[s] = 1 << (i + 1) * 10

    for symbol in reversed(symbols[1:]):
        if n >= prefix[symbol]:
            value = float(n) / prefix[symbol]
            return value, symbol
    return n, symbols[0]


def is_not_special_file(file: Path) -> bool:
    """Checks if the file is not a special file."""
    # Make sure the file is not a special file, such as FIFO, /dev/null, etc.
    return not file.is_fifo() and not file.is_block_device() and not file.is_char_device() and not file.is_socket()


def is_root_or_below(app, path: Path) -> bool:
    """Checks if the path is the root or below it."""
    return path == app.state.root or path.resolve().as_posix().startswith(app.state.root.resolve().as_posix())


def get_etag(file: Path) -> str:
    """Gets the etag for a file."""
    stat_result = file.stat()
    string = str(stat_result.st_mtime) + "-" + str(stat_result.st_size)
    return hashlib.md5(string.encode()).hexdigest()


def guess_mime_type(magic_src: Magic, file: Union[Path, bytes]):
    """Guesses a mime type from content."""
    if isinstance(file, bytes):
        return magic_src.from_buffer(file)
    return magic_src.from_file(str(file.absolute()))


def mime_type_from_file_ext(file: Path, *, guess_on_unsure: bool = False, magic: Magic = None) -> str:
    """Guesses a mime type from a file extension."""
    import mimetypes

    mime, _ = mimetypes.guess_type(file.name)
    if mime is None and guess_on_unsure and magic is not None:
        logger.debug("Guessing mime type for %s from file content (<mimetypes> guess failed)." % file.name)
        return guess_mime_type(magic, file)
    return mime


def can_access(file: Path, definite: bool = True) -> bool:
    """Check if the file can be accessed by the server."""
    x = os.access(file, os.R_OK)
    if x:
        if definite:
            try:
                stat = file.stat()
            except (OSError, PermissionError) as e:
                logger.debug("File is not accessible: %s" % e)
                return False
            else:
                if not file.is_dir():
                    try:
                        with file.open("br") as f:
                            f.read(1)
                    except (OSError, PermissionError) as e:
                        logger.debug("File is not accessible: %s" % e)
                    else:
                        return True
                else:
                    return True
        else:
            return True
    return False


def read_or_stream(file: Path, max_size_mb: float = 10.0) -> int:
    """Checks if the file should be read into memory first, or streamed.

    0 = read
    1 = stream"""
    max_size_b = max_size_mb * 1024 * 1024
    stat = file.stat()
    if stat.st_size > max_size_b:
        return 1
    return 0


def has_changed(etag: str = None, last_modified: str = None, file: Path = None):
    """Checks if the file has changed since the last request."""
    if etag:
        etag = etag.replace("W/", "").replace('"', "")
        logger.debug(etag, "vs", get_etag(file))
        if etag == get_etag(file):
            return False
    else:
        logger.debug("No etag.")

    if last_modified:
        last_mod = datetime.utcfromtimestamp(file.stat().st_mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")
        logger.debug(last_modified.lower(), "vs", last_mod.lower())
        if last_modified.lower() == last_mod.lower():
            return False
    else:
        logger.debug("No last modified")

    return True
