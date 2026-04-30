"""Read-only parser for Mitsuba 3's `tensor_file` binary format.

Used by the hpBRDF compression pipeline to introspect a .hpbrdf / .pbsdf
without depending on a Mitsuba install (the inspector runs on machines
that don't have CUDA / patched Mitsuba). Mirrors the loader in
`modules/mitsuba3/src/core/tensor.cpp`.

Binary layout (little-endian throughout):
    [0..12]    b"tensor_file\\x00" (12 bytes; trailing NUL pads the literal)
    [12..14]   uint8 version[2]
    [14..18]   uint32 n_fields
    For each field, sequentially:
        uint16 name_length
        char[name_length] name (no NUL terminator)
        uint16 ndim
        uint8  dtype (Struct::Type enum: see DTYPE_* below)
        uint64 offset
        uint64[ndim] shape

The raw tensor data is at `offset` from the start of the file. The header
section above only describes WHERE each tensor lives — we never need to
copy the heavy `pbrdf` tensor into Python.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

# Struct::Type enum from modules/mitsuba3/include/mitsuba/core/struct.h
DTYPE_INVALID = 0
DTYPE_UINT8 = 1
DTYPE_INT8 = 2
DTYPE_UINT16 = 3
DTYPE_INT16 = 4
DTYPE_UINT32 = 5
DTYPE_INT32 = 6
DTYPE_UINT64 = 7
DTYPE_INT64 = 8
DTYPE_FLOAT16 = 9
DTYPE_FLOAT32 = 10
DTYPE_FLOAT64 = 11

DTYPE_NAMES = {
    DTYPE_INVALID: "invalid",
    DTYPE_UINT8: "uint8",
    DTYPE_INT8: "int8",
    DTYPE_UINT16: "uint16",
    DTYPE_INT16: "int16",
    DTYPE_UINT32: "uint32",
    DTYPE_INT32: "int32",
    DTYPE_UINT64: "uint64",
    DTYPE_INT64: "int64",
    DTYPE_FLOAT16: "float16",
    DTYPE_FLOAT32: "float32",
    DTYPE_FLOAT64: "float64",
}

DTYPE_ITEMSIZE = {
    DTYPE_UINT8: 1, DTYPE_INT8: 1,
    DTYPE_UINT16: 2, DTYPE_INT16: 2,
    DTYPE_UINT32: 4, DTYPE_INT32: 4,
    DTYPE_UINT64: 8, DTYPE_INT64: 8,
    DTYPE_FLOAT16: 2, DTYPE_FLOAT32: 4, DTYPE_FLOAT64: 8,
}

DTYPE_NUMPY = {
    DTYPE_UINT8: "uint8", DTYPE_INT8: "int8",
    DTYPE_UINT16: "uint16", DTYPE_INT16: "int16",
    DTYPE_UINT32: "uint32", DTYPE_INT32: "int32",
    DTYPE_UINT64: "uint64", DTYPE_INT64: "int64",
    DTYPE_FLOAT16: "float16", DTYPE_FLOAT32: "float32", DTYPE_FLOAT64: "float64",
}


@dataclass
class Field:
    name: str
    dtype: int
    shape: tuple[int, ...]
    offset: int  # absolute byte offset in the file

    @property
    def dtype_name(self) -> str:
        return DTYPE_NAMES.get(self.dtype, f"unknown({self.dtype})")

    @property
    def numpy_dtype(self) -> str | None:
        return DTYPE_NUMPY.get(self.dtype)

    @property
    def n_elements(self) -> int:
        n = 1
        for d in self.shape:
            n *= d
        return n

    @property
    def n_bytes(self) -> int:
        item = DTYPE_ITEMSIZE.get(self.dtype, 0)
        return item * self.n_elements


class TensorFile:
    """Header-only TensorFile reader. Holds field metadata; never reads
    the big tensor payload unless the caller explicitly asks via
    `read_field()`.
    """

    MAGIC = b"tensor_file\x00"  # 12 bytes

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.file_size = self.path.stat().st_size
        self.fields: dict[str, Field] = {}
        with self.path.open("rb") as f:
            self._parse_header(f)

    def _parse_header(self, f) -> None:
        magic = f.read(12)
        if magic != self.MAGIC:
            raise ValueError(
                f"{self.path}: not a tensor_file (got magic {magic!r})"
            )
        version = f.read(2)
        self.version = (version[0], version[1])
        (n_fields,) = struct.unpack("<I", f.read(4))
        for _ in range(n_fields):
            (name_length,) = struct.unpack("<H", f.read(2))
            name = f.read(name_length).decode("utf-8")
            (ndim,) = struct.unpack("<H", f.read(2))
            (dtype,) = struct.unpack("<B", f.read(1))
            (offset,) = struct.unpack("<Q", f.read(8))
            shape = struct.unpack(f"<{ndim}Q", f.read(8 * ndim))
            self.fields[name] = Field(
                name=name, dtype=dtype, shape=tuple(shape), offset=offset,
            )

    def read_field(self, name: str):
        """Materialise a tensor field as a numpy array.

        The caller is responsible for restraint — calling this on `pbrdf`
        will pull the full ~13 GB cube into memory. Use it only on small
        metadata fields (theta_h, theta_d, phi_d, wvls).
        """
        import numpy as np
        field = self.fields[name]
        np_dtype = field.numpy_dtype
        if np_dtype is None:
            raise ValueError(f"unsupported dtype {field.dtype} for field {name}")
        with self.path.open("rb") as f:
            f.seek(field.offset)
            buf = f.read(field.n_bytes)
        return np.frombuffer(buf, dtype=np_dtype).reshape(field.shape)
