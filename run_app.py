"""Точка входа для сборки exe (и для запуска без пакета)."""

import sys

from sshdrive.app import main

if __name__ == "__main__":
    sys.exit(main())
