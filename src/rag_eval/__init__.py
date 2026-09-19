"""An evaluation harness for retrieval-augmented generation configurations.

Importing this package must never read an API key, open a network connection, or
touch the filesystem. The test suite enforces that property (tests/test_no_keys.py)
so that the whole suite can run without credentials.
"""

__version__ = "0.1.0"
