"""Prisma SASE MCP server -- read-only tools for Prisma Access.

The modules in this package import each other flatly (``import config``,
``from client import ...``) because they were written to be run as loose
scripts by ``run.sh``, and that launcher is still supported. Packaging them
for ``uvx`` did not change a single one of those imports. See ``__main__.py``
for why that is deliberate.

Importing this package therefore has to put its own directory on ``sys.path``,
not just ``__main__``: the Skill documents ``from prisma_sase_mcp.tools.status
import get_sase_status`` as a supported escape hatch for when the MCP layer is
unavailable, and every tool module starts with ``import config``. Without the
shim here that import raises ModuleNotFoundError, so the documented fallback
only worked when launched through the console script. Kept stdlib-only and
side-effect-free beyond the path entry -- ``setup`` runs before the
dependencies exist, so this must never import fastmcp.
"""

import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

__all__ = ["main"]


def main():
    """Console-script entry point -- see ``__main__.main``."""
    from .__main__ import main as _main
    return _main()
