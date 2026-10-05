"""Reproduce the submitted CPM check matrices with NumPy."""
import numpy as np
P = 71
EX = [[61,36,7,60,1,43,13,29],
      [26,57,18,70,8,26,66,6],
      [22,65,41,34,66,63,9,12]]
EZ = [[1,59,20,3,12,57,26,52],
      [15,56,32,36,68,63,9,5],
      [63,13,55,24,36,53,23,31]]
def lift(E):
    H = np.zeros((3*P,8*P), dtype=np.int8)
    r = np.arange(P)
    for i in range(3):
        for j in range(8):
            H[i*P+r,j*P+(r-E[i][j])%P] = 1
    return H
HX,HZ = lift(EX),lift(EZ)
assert not np.any((HX @ HZ.T) % 2)

if __name__ == "__main__":
    np.savez("code.npz", H_X=HX, H_Z=HZ)
