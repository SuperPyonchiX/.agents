"""CSV の行数を数える小さな CLI。"""
import argparse
import sys


def count_rows(lines):
    return len(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="CSV の行数を数える")
    ap.add_argument("path")
    args = ap.parse_args(argv)
    with open(args.path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    print(count_rows(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
