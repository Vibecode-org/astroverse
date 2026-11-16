"""Filesystem primitives shared by cooperating catalog publishers."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


class RevisionConflict(ValueError):
    """The active publication no longer matches the expected revision."""


@contextmanager
def publication_lock(path):
    # Keep the lock inode: removing it lets waiters lock different inodes.
    with Path(str(path) + ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def fsync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
