"""Compares the sizes of local files with a Drive folder listing and fails on any difference."""

import argparse
import json
import os
import sys


def read_listing(listing_path):
    with open(listing_path) as handle:
        entries = json.load(handle)
    return {entry["title"]: int(entry["fileSize"]) for entry in entries if "fileSize" in entry}


def list_local_files(local_directory):
    sizes = {}
    for name in sorted(os.listdir(local_directory)):
        path = os.path.join(local_directory, name)
        if os.path.isfile(path):
            sizes[name] = os.path.getsize(path)
    return sizes


def compare(local_sizes, drive_sizes):
    rows = []
    for name in sorted(set(local_sizes) | set(drive_sizes)):
        local_bytes = local_sizes.get(name)
        drive_bytes = drive_sizes.get(name)
        if drive_bytes is None:
            status = "missing in Drive"
        elif local_bytes is None:
            status = "missing locally"
        elif local_bytes != drive_bytes:
            status = f"size differs by {abs(local_bytes - drive_bytes)} bytes"
        else:
            status = "ok"
        rows.append((name, local_bytes, drive_bytes, status))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-directory", required=True)
    parser.add_argument("--listing", required=True)
    arguments = parser.parse_args(argv)
    try:
        rows = compare(list_local_files(arguments.local_directory), read_listing(arguments.listing))
    except (OSError, ValueError, KeyError) as error:
        print(f"ERROR could not compare: {error!r}", file=sys.stderr)
        return 2
    print("title\tlocal_bytes\tdrive_bytes\tstatus")
    for name, local_bytes, drive_bytes, status in rows:
        print(f"{name}\t{local_bytes}\t{drive_bytes}\t{status}")
    return 0 if all(status == "ok" for *_, status in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
