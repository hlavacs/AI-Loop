"""GUI-independent source project analysis.

The public :func:`analyze_project` function scans a directory containing
Python and C++ sources and returns a JSON-serializable hierarchy describing
the project, its files, and the symbols found in each file.
"""

from .analyzer import analyze_project

__all__ = ["analyze_project"]
