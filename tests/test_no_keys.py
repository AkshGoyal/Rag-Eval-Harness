import os
import subprocess
import sys


def test_package_imports_with_no_environment() -> None:
    """The suite must run without credentials.

    Importing the package with the environment stripped catches the common mistake
    of reading a key at module scope, which would make every test depend on a
    developer having one.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import rag_eval, rag_eval.config, rag_eval.hashing"],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
