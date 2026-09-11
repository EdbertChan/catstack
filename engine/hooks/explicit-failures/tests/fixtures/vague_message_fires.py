def load(path):
    if not path:
        raise ValueError("invalid input")
    try:
        return open(path).read()
    except OSError as err:  # noqa: F841
        raise RuntimeError(f"could not read {path}")


def parse(raw):
    if raw is None:
        raise ValueError
    raise Exception("Something went wrong.")
