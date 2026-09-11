def load(path):
    if not path:
        raise ValueError(f"expected a file path, got {path!r}")
    try:
        return open(path).read()
    except OSError as err:
        raise RuntimeError(f"could not read {path}") from err


def parse(raw, last_exc):
    try:
        return int(raw)
    except ValueError:
        raise
    except TypeError as err:
        raise TypeError(f"expected a number, got {type(raw).__name__}: {err}")
    except KeyError:
        raise last_exc


def reject(unit):
    raise ValueError("review-unit-conflict: " + unit)


def quiet():
    raise ValueError("invalid input")  # pragma: explicit-failures: allow
