# -*- coding: utf-8 -*-
import ctypes
import io
import struct

import pytest

import env
from pybind11_tests import ConstructorStats
from pybind11_tests import buffers as m

np = pytest.importorskip("numpy")


def test_from_python():
    with pytest.raises(RuntimeError) as excinfo:
        m.Matrix(np.array([1, 2, 3]))  # trying to assign a 1D array
    assert str(excinfo.value) == "Incompatible buffer format!"

    m3 = np.array([[1, 2, 3], [4, 5, 6]]).astype(np.float32)
    m4 = m.Matrix(m3)

    for i in range(m4.rows()):
        for j in range(m4.cols()):
            assert m3[i, j] == m4[i, j]

    cstats = ConstructorStats.get(m.Matrix)
    assert cstats.alive() == 1
    del m3, m4
    assert cstats.alive() == 0
    assert cstats.values() == ["2x3 matrix"]
    assert cstats.copy_constructions == 0
    # assert cstats.move_constructions >= 0  # Don't invoke any
    assert cstats.copy_assignments == 0
    assert cstats.move_assignments == 0


# https://foss.heptapod.net/pypy/pypy/-/issues/2444
# TODO: fix on recent PyPy
@pytest.mark.xfail(
    env.PYPY, reason="PyPy 7.3.7 doesn't clear this anymore", stict=False
)
def test_to_python():
    mat = m.Matrix(5, 4)
    assert memoryview(mat).shape == (5, 4)

    assert mat[2, 3] == 0
    mat[2, 3] = 4.0
    mat[3, 2] = 7.0
    assert mat[2, 3] == 4
    assert mat[3, 2] == 7
    assert struct.unpack_from("f", mat, (3 * 4 + 2) * 4) == (7,)
    assert struct.unpack_from("f", mat, (2 * 4 + 3) * 4) == (4,)

    mat2 = np.array(mat, copy=False)
    assert mat2.shape == (5, 4)
    assert abs(mat2).sum() == 11
    assert mat2[2, 3] == 4 and mat2[3, 2] == 7
    mat2[2, 3] = 5
    assert mat2[2, 3] == 5

    cstats = ConstructorStats.get(m.Matrix)
    assert cstats.alive() == 1
    del mat
    pytest.gc_collect()
    assert cstats.alive() == 1
    del mat2  # holds a mat reference
    pytest.gc_collect()
    assert cstats.alive() == 0
    assert cstats.values() == ["5x4 matrix"]
    assert cstats.copy_constructions == 0
    # assert cstats.move_constructions >= 0  # Don't invoke any
    assert cstats.copy_assignments == 0
    assert cstats.move_assignments == 0


def test_inherited_protocol():
    """SquareMatrix is derived from Matrix and inherits the buffer protocol"""

    matrix = m.SquareMatrix(5)
    assert memoryview(matrix).shape == (5, 5)
    assert np.asarray(matrix).shape == (5, 5)


def test_pointer_to_member_fn():
    for cls in [m.Buffer, m.ConstBuffer, m.DerivedBuffer]:
        buf = cls()
        buf.value = 0x12345678
        value = struct.unpack("i", bytearray(buf))[0]
        assert value == 0x12345678


def test_readonly_buffer():
    buf = m.BufferReadOnly(0x64)
    view = memoryview(buf)
    assert view[0] == b"d" if env.PY2 else 0x64
    assert view.readonly
    with pytest.raises(TypeError):
        view[0] = b"\0" if env.PY2 else 0


def test_selective_readonly_buffer():
    buf = m.BufferReadOnlySelect()

    memoryview(buf)[0] = b"d" if env.PY2 else 0x64
    assert buf.value == 0x64

    io.BytesIO(b"A").readinto(buf)
    assert buf.value == ord(b"A")

    buf.readonly = True
    with pytest.raises(TypeError):
        memoryview(buf)[0] = b"\0" if env.PY2 else 0
    with pytest.raises(TypeError):
        io.BytesIO(b"1").readinto(buf)


def test_ctypes_array_1d():
    char1d = (ctypes.c_char * 10)()
    int1d = (ctypes.c_int * 15)()
    long1d = (ctypes.c_long * 7)()

    for carray in (char1d, int1d, long1d):
        info = m.get_buffer_info(carray)
        assert info.itemsize == ctypes.sizeof(carray._type_)
        assert info.size == len(carray)
        assert info.ndim == 1
        assert info.shape == [info.size]
        assert info.strides == [info.itemsize]
        assert not info.readonly


def test_ctypes_array_2d():
    char2d = ((ctypes.c_char * 10) * 4)()
    int2d = ((ctypes.c_int * 15) * 3)()
    long2d = ((ctypes.c_long * 7) * 2)()

    for carray in (char2d, int2d, long2d):
        info = m.get_buffer_info(carray)
        assert info.itemsize == ctypes.sizeof(carray[0]._type_)
        assert info.size == len(carray) * len(carray[0])
        assert info.ndim == 2
        assert info.shape == [len(carray), len(carray[0])]
        assert info.strides == [info.itemsize * len(carray[0]), info.itemsize]
        assert not info.readonly


@pytest.mark.skipif(
    "env.PYPY and env.PY2", reason="PyPy2 bytes buffer not reported as readonly"
)
def test_ctypes_from_buffer():
    test_pystr = b"0123456789"
    for pyarray in (test_pystr, bytearray(test_pystr)):
        pyinfo = m.get_buffer_info(pyarray)

        if pyinfo.readonly:
            cbytes = (ctypes.c_char * len(pyarray)).from_buffer_copy(pyarray)
            cinfo = m.get_buffer_info(cbytes)
        else:
            cbytes = (ctypes.c_char * len(pyarray)).from_buffer(pyarray)
            cinfo = m.get_buffer_info(cbytes)

        assert cinfo.size == pyinfo.size
        assert cinfo.ndim == pyinfo.ndim
        assert cinfo.shape == pyinfo.shape
        assert cinfo.strides == pyinfo.strides
        assert not cinfo.readonly
