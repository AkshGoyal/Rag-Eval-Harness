import os
import subprocess
import sys

_CREDENTIAL_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def test_package_imports_with_no_credentials() -> None:
    """The suite must run without credentials.

    Importing the package with every credential-like variable removed catches the
    common mistake of reading a key at module scope, which would make every test
    depend on a developer having one. The rest of the environment is kept, because
    Python on Windows cannot start without variables such as SYSTEMROOT.
    """
    environment = {
        name: value
        for name, value in os.environ.items()
        if not any(marker in name.upper() for marker in _CREDENTIAL_MARKERS)
    }

    result = subprocess.run(
        [sys.executable, "-c", "import rag_eval, rag_eval.config, rag_eval.llm.client"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
