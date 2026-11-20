"""Surface-code-like CSS construction from classical parity checks."""

import numpy as np


def surface_code_2d(H1, H2):
    H1 = np.asarray(H1, dtype=np.int8) % 2
    H2 = np.asarray(H2, dtype=np.int8) % 2
    m1, n1 = H1.shape
    m2, n2 = H2.shape
    HX1 = np.kron(H1.T, np.eye(n2, dtype=np.int8))
    HX2 = np.kron(np.eye(n1, dtype=np.int8), H2.T)
    HX = np.hstack([HX1, HX2]).astype(np.int8)
    HZ1 = np.kron(np.eye(m1, dtype=np.int8), H2)
    HZ2 = np.kron(H1, np.eye(m2, dtype=np.int8))
    HZ = np.hstack([HZ1, HZ2]).astype(np.int8)
    return HX, HZ


def surface_code_3d(H1, H2, H3):
    H1 = np.asarray(H1, dtype=np.int8) % 2
    H2 = np.asarray(H2, dtype=np.int8) % 2
    H3 = np.asarray(H3, dtype=np.int8) % 2
    m1, n1 = H1.shape
    m2, n2 = H2.shape
    m3, n3 = H3.shape

    n_qubits = m1 * n2 * n3 + n1 * m2 * n3 + n1 * n2 * m3
    n_x = n1 * n2 * n3
    n_z = m1 * m2 * n3 + m1 * n2 * m3 + n1 * m2 * m3

    HX = np.zeros((n_x, n_qubits), dtype=np.int8)
    HZ = np.zeros((n_z, n_qubits), dtype=np.int8)

    off0 = 0
    off1 = m1 * n2 * n3
    off2 = m1 * n2 * n3 + n1 * m2 * n3

    for v1 in range(n1):
        for v2 in range(n2):
            for v3 in range(n3):
                row = v1 * n2 * n3 + v2 * n3 + v3
                for i1 in range(m1):
                    if H1[i1, v1]:
                        col = off0 + i1 * n2 * n3 + v2 * n3 + v3
                        HX[row, col] = 1
                for i2 in range(m2):
                    if H2[i2, v2]:
                        col = off1 + v1 * m2 * n3 + i2 * n3 + v3
                        HX[row, col] = 1
                for i3 in range(m3):
                    if H3[i3, v3]:
                        col = off2 + v1 * n2 * m3 + v2 * m3 + i3
                        HX[row, col] = 1

    off_z0 = 0
    off_z1 = m1 * m2 * n3
    off_z2 = m1 * m2 * n3 + m1 * n2 * m3

    for i1 in range(m1):
        for i2 in range(m2):
            for v3 in range(n3):
                row = off_z0 + i1 * m2 * n3 + i2 * n3 + v3
                for v1 in range(n1):
                    if H1[i1, v1]:
                        col = off1 + v1 * m2 * n3 + i2 * n3 + v3
                        HZ[row, col] = 1
                for v2 in range(n2):
                    if H2[i2, v2]:
                        col = off0 + i1 * n2 * n3 + v2 * n3 + v3
                        HZ[row, col] = 1

    for i1 in range(m1):
        for v2 in range(n2):
            for i3 in range(m3):
                row = off_z1 + i1 * n2 * m3 + v2 * m3 + i3
                for v1 in range(n1):
                    if H1[i1, v1]:
                        col = off2 + v1 * n2 * m3 + v2 * m3 + i3
                        HZ[row, col] = 1
                for v3 in range(n3):
                    if H3[i3, v3]:
                        col = off0 + i1 * n2 * n3 + v2 * n3 + v3
                        HZ[row, col] = 1

    for v1 in range(n1):
        for i2 in range(m2):
            for i3 in range(m3):
                row = off_z2 + v1 * m2 * m3 + i2 * m3 + i3
                for v2 in range(n2):
                    if H2[i2, v2]:
                        col = off2 + v1 * n2 * m3 + v2 * m3 + i3
                        HZ[row, col] = 1
                for v3 in range(n3):
                    if H3[i3, v3]:
                        col = off1 + v1 * m2 * n3 + i2 * n3 + v3
                        HZ[row, col] = 1

    return HX, HZ
