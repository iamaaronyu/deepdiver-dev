"""Check the existing worker's OS lock without changing ownership or creating a file."""
import fcntl


def worker_running(directory):
    try:
        with (directory/'worker.lock').open('r') as handle:
            try:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle,fcntl.LOCK_UN)
            return False
    except OSError:
        return False
