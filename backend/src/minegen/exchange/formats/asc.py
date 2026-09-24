"""ESRI ASCII grid (``.asc``) writer / reader for the terrain NODE grid.

Convention (ESRI ArcGIS "ASCII raster format", cell-CENTER variant)::

    ncols        <nx>
    nrows        <ny>
    xllcenter    <x of the WEST column's node centre>
    yllcenter    <y of the SOUTH row's node centre>
    cellsize     <spacing>
    NODATA_value -9999
    <row 0: NORTH-most row, values west → east>
    ...
    <row nrows-1: SOUTH-most row>

MineGen terrain is ``z[i, j]`` with ``i → X (east)`` and ``j → Y (north)``
(``world/terrain.py``): the ASC row ``r`` is therefore ``j = ny − 1 − r`` and
the value at column ``c`` is ``z[c, j]``. The four-corner fixture test pins
this against transposition and Y-flip errors.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

NODATA = -9999.0


def write_esri_ascii_grid(x0: float, y0: float, spacing: float, z: FloatArray) -> str:
    zz = np.asarray(z, dtype=np.float64)
    if zz.ndim != 2:
        raise ValueError("z must be a 2-D node grid z[nx, ny]")
    nx, ny = zz.shape
    lines = [
        f"ncols {nx}",
        f"nrows {ny}",
        f"xllcenter {float(x0)!r}",
        f"yllcenter {float(y0)!r}",
        f"cellsize {float(spacing)!r}",
        f"NODATA_value {int(NODATA)}",
    ]
    for r in range(ny):
        j = ny - 1 - r
        lines.append(" ".join(repr(float(v)) for v in zz[:, j]))
    return "\n".join(lines) + "\n"


_HEADER_KEYS = frozenset(
    {
        "ncols",
        "nrows",
        "xllcenter",
        "yllcenter",
        "xllcorner",
        "yllcorner",
        "cellsize",
        "nodata_value",
    }
)


def read_esri_ascii_grid(text: str) -> tuple[float, float, float, FloatArray]:
    """→ ``(x0, y0, spacing, z[nx, ny])`` in MineGen node-grid convention.
    Accepts ``xllcorner`` / ``yllcorner`` too (converted to node centres)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header: dict[str, float] = {}
    idx = 0
    while idx < len(lines):
        key, _, value = lines[idx].partition(" ")
        k = key.strip().lower()
        if k in _HEADER_KEYS:
            header[k] = float(value)
            idx += 1
        else:
            break
    ncols, nrows = int(header["ncols"]), int(header["nrows"])
    spacing = header["cellsize"]
    if "xllcenter" in header:
        x0, y0 = header["xllcenter"], header["yllcenter"]
    else:
        x0, y0 = header["xllcorner"] + spacing / 2.0, header["yllcorner"] + spacing / 2.0
    rows = [np.asarray(ln.split(), dtype=np.float64) for ln in lines[idx : idx + nrows]]
    if len(rows) != nrows or any(len(r) != ncols for r in rows):
        raise ValueError("ASC body does not match ncols x nrows")
    z = np.zeros((ncols, nrows), dtype=np.float64)
    for r, row in enumerate(rows):
        z[:, nrows - 1 - r] = row
    return x0, y0, spacing, z
