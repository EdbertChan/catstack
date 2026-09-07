import logging

log = logging.getLogger(__name__)


def read_config(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError as exc:
        log.warning("config unreadable, using empty config: %s (%s)", path, exc)
    return ""


def parse_int(raw):
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"not an int: {raw!r}") from exc
