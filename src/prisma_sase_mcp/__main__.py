"""Entry point for ``uvx --from git+... prisma-sase-mcp``.

Why this shim exists
--------------------
Every module here imports its siblings by bare name -- ``import config``,
``from client import SaseClient``, ``from tools.alerts import ...``. That works
when ``mcp/run.sh`` runs ``python server.py``, because Python puts the script's
own directory on ``sys.path``. It does not work when the same files are
imported as a package, where those names would have to be relative.

Rewriting eight modules to relative imports was the alternative. It would have
touched every file, and broken ``run.sh``, ``--selfcheck`` and the standalone
bundle, all of which still execute the modules as scripts. Prepending this
directory to ``sys.path`` instead keeps one import style working under both
launchers, at the cost of the modules being importable under two names
(``config`` and ``prisma_sase_mcp.config``). Nothing in the server keeps
module-level mutable state that two identities would desynchronise -- config
is read once from the environment -- so the duplication is harmless.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _ensure_flat_imports():
    """Make the sibling modules importable by bare name, as run.sh does."""
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)


def main():
    """Start the MCP server on stdio."""
    _ensure_flat_imports()
    import server
    return server.main()


def setup():
    """Run the guided credential setup."""
    _ensure_flat_imports()
    import setup_wizard
    return setup_wizard.main()


if __name__ == "__main__":
    main()
