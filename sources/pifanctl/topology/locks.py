"""Cooperative host locks shared by local commands and Kubernetes hostPath mounts."""
import fcntl
import os
from pathlib import Path


class HostLock:
    def __init__(self, directory='/var/lock/pifanctl'):
        self.directory = Path(directory)
        self.file = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / 'worker.lock'
        # Never follow an untrusted symlink and never unlink a live lock inode.
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self.file = os.fdopen(fd, 'r+')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file = None
            raise RuntimeError('another pifanctl process owns this host PWM lock') from None
        self.file.seek(0); self.file.truncate(); self.file.write(str(os.getpid())); self.file.flush()
        return self

    def __exit__(self, *args):
        if self.file is not None:
            self.file.close(); self.file = None
