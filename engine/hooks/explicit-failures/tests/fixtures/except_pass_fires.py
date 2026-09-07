def read_config(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        pass
    return ""


def parse_int(raw):
    try:
        return int(raw)
    except ValueError: pass
    return None
