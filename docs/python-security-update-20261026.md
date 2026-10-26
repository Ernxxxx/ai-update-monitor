# Python security update — 2026-10-26

Use Python 3.13.18 and this project's isolated .venv. The Windows runtime was built from the verified [PSF release source](https://www.python.org/downloads/release/python-31318/) because this security release has no Windows installer.

The dependency lock records the tested package versions, including pip and build/test tools. The installed environment was compared locally against the public OSV PyPI archive: no known vulnerable package versions were found at verification time. This does not guarantee protection against future vulnerabilities.

Validation: 58 tests (56 existing plus 2 console-stream regressions); stable Chrome local rendering with sandbox enabled. External application connections were blocked; no Discord login, posts, edits, or command synchronization were performed. Production settings and data were excluded from testing and version control.

The monitor uses the installed stable Google Chrome through Playwright with its sandbox enabled. The scheduled launcher selects the project .venv. pythonw startup is compatible with absent stdout/stderr.
