/**
 * gf2_fast.cpp — Bit-packed GF(2) linear algebra for quantum code search.
 *
 * OPTIONAL accelerator for the RIS hot path in verify/heuristic_distance.py
 * and the CI deep-refutation gate. CI builds it best-effort from the trusted
 * tree; a missing build falls back to the full Python battery. Fast-pass hits
 * count only after their witnesses are validated by the pinned Python engine.
 *
 * Build:  make fast        (or: python verify/setup_gf2_fast.py build_ext
 *                           --build-lib verify)
 *
 * Key speedup sources (measured ~28x single-thread, ~170x at 8 threads over
 * the numpy int8 path at n=400):
 *   - Row XOR is 1 word op per 64 columns (vs 1 byte op per column in numpy int8)
 *   - No Python interpreter overhead in RREF pivot loops
 *   - Hardware popcount for weight/inner-product computations
 *
 * Ported from the Sierpinski research sandbox; adds distance_rand_witness
 * (same search, but returns the best logical's support so callers can have
 * the trusted Python stack check it).
 */

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include <vector>
#include <cstdint>
#include <algorithm>
#include <numeric>
#include <cassert>
#include <stdexcept>
#include <thread>

namespace py = pybind11;

// =====================================================================
//  Bit-packed GF(2) matrix
// =====================================================================

class GF2Matrix {
public:
    int rows_, cols_;
    int wpr_;  // words per row = ceil(cols / 64)
    std::vector<uint64_t> data_;  // row-major, wpr_ words per row

    GF2Matrix() : rows_(0), cols_(0), wpr_(0) {}

    GF2Matrix(int rows, int cols)
        : rows_(rows), cols_(cols), wpr_((cols + 63) / 64),
          data_((size_t)rows * ((cols + 63) / 64), 0ULL) {}

    // ---- element access ----
    bool get(int r, int c) const {
        return (data_[(size_t)r * wpr_ + c / 64] >> (c % 64)) & 1;
    }
    void set(int r, int c, bool v) {
        uint64_t& w = data_[(size_t)r * wpr_ + c / 64];
        uint64_t mask = uint64_t(1) << (c % 64);
        w = v ? (w | mask) : (w & ~mask);
    }

    // ---- row pointers ----
    uint64_t* row_ptr(int r) { return &data_[(size_t)r * wpr_]; }
    const uint64_t* row_ptr(int r) const { return &data_[(size_t)r * wpr_]; }

    // ---- row operations (the hot inner loop) ----
    void xor_rows(int dst, int src) {
        uint64_t* d = row_ptr(dst);
        const uint64_t* s = row_ptr(src);
        for (int w = 0; w < wpr_; ++w) d[w] ^= s[w];
    }
    void swap_rows(int r1, int r2) {
        uint64_t* a = row_ptr(r1);
        uint64_t* b = row_ptr(r2);
        for (int w = 0; w < wpr_; ++w) std::swap(a[w], b[w]);
    }
    void copy_row_from(int dst, const GF2Matrix& src, int src_r) {
        uint64_t* d = row_ptr(dst);
        const uint64_t* s = src.row_ptr(src_r);
        for (int w = 0; w < wpr_; ++w) d[w] = s[w];
    }
    int row_weight(int r) const {
        const uint64_t* p = row_ptr(r);
        int wt = 0;
        for (int i = 0; i < wpr_; ++i) wt += __builtin_popcountll(p[i]);
        return wt;
    }
    bool row_is_zero(int r) const {
        const uint64_t* p = row_ptr(r);
        for (int i = 0; i < wpr_; ++i)
            if (p[i]) return false;
        return true;
    }

    // ---- numpy conversion ----
    static GF2Matrix from_numpy(py::array_t<int8_t> arr) {
        if (arr.ndim() != 2)
            throw std::runtime_error("GF2Matrix::from_numpy: expected 2D array");
        auto buf = arr.unchecked<2>();
        int rows = (int)buf.shape(0), cols = (int)buf.shape(1);
        GF2Matrix m(rows, cols);
        for (int r = 0; r < rows; ++r)
            for (int c = 0; c < cols; ++c)
                if (buf(r, c) & 1)
                    m.data_[(size_t)r * m.wpr_ + c / 64] |=
                        uint64_t(1) << (c % 64);
        return m;
    }

    py::array_t<int8_t> to_numpy() const {
        py::array_t<int8_t> arr({rows_, cols_});
        auto buf = arr.mutable_unchecked<2>();
        for (int r = 0; r < rows_; ++r) {
            const uint64_t* row = row_ptr(r);
            for (int c = 0; c < cols_; ++c)
                buf(r, c) = (int8_t)((row[c / 64] >> (c % 64)) & 1);
        }
        return arr;
    }

    // ---- structural helpers ----
    GF2Matrix first_n_rows(int n) const {
        n = std::min(n, rows_);
        GF2Matrix m(n, cols_);
        for (int r = 0; r < n; ++r)
            m.copy_row_from(r, *this, r);
        return m;
    }
};


// =====================================================================
//  GF(2) RREF — standard pivot, but with 64-wide word XOR
// =====================================================================

struct RREFResult {
    GF2Matrix matrix;
    std::vector<int> pivots;
};

RREFResult gf2_rref(GF2Matrix M) {
    // M is passed by value (copy)
    int rows = M.rows_, cols = M.cols_;
    std::vector<int> pivots;
    int r = 0;
    for (int c = 0; c < cols && r < rows; ++c) {
        // find pivot in column c at or below row r
        int piv = -1;
        for (int i = r; i < rows; ++i) {
            if (M.get(i, c)) { piv = i; break; }
        }
        if (piv < 0) continue;
        if (piv != r) M.swap_rows(r, piv);
        // eliminate column c in all other rows
        for (int i = 0; i < rows; ++i) {
            if (i != r && M.get(i, c))
                M.xor_rows(i, r);
        }
        pivots.push_back(c);
        ++r;
    }
    return {std::move(M), std::move(pivots)};
}

int gf2_rank(const GF2Matrix& M) {
    return (int)gf2_rref(M).pivots.size();
}

// RREF visiting columns in a custom order (for randomized distance).
// Returns only the r reduced (non-zero) rows.
GF2Matrix rref_perm(GF2Matrix M, const std::vector<int>& perm) {
    int rows = M.rows_;
    int r = 0;
    for (int col : perm) {
        int piv = -1;
        for (int i = r; i < rows; ++i) {
            if (M.get(i, col)) { piv = i; break; }
        }
        if (piv < 0) continue;
        if (piv != r) M.swap_rows(r, piv);
        for (int i = 0; i < rows; ++i) {
            if (i != r && M.get(i, col))
                M.xor_rows(i, r);
        }
        ++r;
        if (r == rows) break;
    }
    return M.first_n_rows(r);
}


// =====================================================================
//  GF(2) kernel basis  (right nullspace)
// =====================================================================

GF2Matrix kernel_basis(const GF2Matrix& H) {
    auto [R, piv] = gf2_rref(H);
    int n = H.cols_;
    int rank = (int)piv.size();

    // identify free (non-pivot) columns
    std::vector<bool> is_pivot(n, false);
    for (int p : piv) is_pivot[p] = true;
    std::vector<int> free_cols;
    for (int c = 0; c < n; ++c)
        if (!is_pivot[c]) free_cols.push_back(c);

    int k = (int)free_cols.size();
    if (k == 0) return GF2Matrix(0, n);

    GF2Matrix B(k, n);
    for (int idx = 0; idx < k; ++idx) {
        B.set(idx, free_cols[idx], true);  // unit vector on free column
        for (int i = 0; i < rank; ++i) {
            if (R.get(i, free_cols[idx]))
                B.set(idx, piv[i], true);  // back-substitution
        }
    }
    return B;
}


// =====================================================================
//  Logical basis: ker(HX) reduced modulo rowspace(HZ)
// =====================================================================

GF2Matrix logical_basis(const GF2Matrix& HX, const GF2Matrix& HZ) {
    // Get RREF of HZ (the stabilizer space to reduce modulo)
    auto [SZ_full, piv_z] = gf2_rref(HZ);
    int rank = (int)piv_z.size();
    GF2Matrix SZ = SZ_full.first_n_rows(rank);
    std::vector<int> piv = piv_z;

    // Get kernel of HX
    GF2Matrix K = kernel_basis(HX);
    int wpr = K.wpr_;

    // Collect independent logical representatives
    std::vector<std::vector<uint64_t>> logicals;

    for (int ki = 0; ki < K.rows_; ++ki) {
        // copy kernel vector
        std::vector<uint64_t> v(wpr);
        const uint64_t* src = K.row_ptr(ki);
        for (int w = 0; w < wpr; ++w) v[w] = src[w];

        // reduce modulo current SZ
        for (int i = 0; i < rank; ++i) {
            int p = piv[i];
            if ((v[p / 64] >> (p % 64)) & 1) {
                const uint64_t* sz_row = SZ.row_ptr(i);
                for (int w = 0; w < wpr; ++w) v[w] ^= sz_row[w];
            }
        }

        // check if nonzero
        bool nonzero = false;
        for (int w = 0; w < wpr; ++w)
            if (v[w]) { nonzero = true; break; }
        if (!nonzero) continue;

        logicals.push_back(v);

        // extend SZ with this logical and re-RREF to maintain reduced form
        GF2Matrix new_SZ(rank + 1, SZ.cols_);
        for (int r = 0; r < rank; ++r) new_SZ.copy_row_from(r, SZ, r);
        uint64_t* nr = new_SZ.row_ptr(rank);
        for (int w = 0; w < wpr; ++w) nr[w] = v[w];

        auto [rref_new, piv_new] = gf2_rref(new_SZ);
        rank = (int)piv_new.size();
        SZ = rref_new.first_n_rows(rank);
        piv = std::move(piv_new);
    }

    // pack logicals into a GF2Matrix
    int n = HX.cols_;
    int nlog = (int)logicals.size();
    GF2Matrix result(nlog, n);
    for (int i = 0; i < nlog; ++i) {
        uint64_t* dst = result.row_ptr(i);
        for (int w = 0; w < wpr; ++w) dst[w] = logicals[i][w];
    }
    return result;
}


// =====================================================================
//  xoshiro256** RNG  (fast, statistically excellent)
// =====================================================================

class Xoshiro256 {
    uint64_t s[4];

    static uint64_t splitmix64(uint64_t& x) {
        uint64_t z = (x += 0x9e3779b97f4a7c15ULL);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        return z ^ (z >> 31);
    }
    static uint64_t rotl(uint64_t x, int k) {
        return (x << k) | (x >> (64 - k));
    }

public:
    explicit Xoshiro256(uint64_t seed) {
        s[0] = splitmix64(seed);
        s[1] = splitmix64(seed);
        s[2] = splitmix64(seed);
        s[3] = splitmix64(seed);
    }

    uint64_t next() {
        uint64_t result = rotl(s[1] * 5, 7) * 9;
        uint64_t t = s[1] << 17;
        s[2] ^= s[0]; s[3] ^= s[1]; s[1] ^= s[2]; s[0] ^= s[3];
        s[2] ^= t; s[3] = rotl(s[3], 45);
        return result;
    }

    // Fisher-Yates shuffle with unbiased bounded sampling
    void shuffle(std::vector<int>& v) {
        for (int i = (int)v.size() - 1; i > 0; --i) {
            uint64_t bound = (uint64_t)(i + 1);
            // rejection sampling to avoid modulo bias
            uint64_t threshold = (-bound) % bound;
            uint64_t r;
            do { r = next(); } while (r < threshold);
            int j = (int)(r % bound);
            std::swap(v[i], v[j]);
        }
    }
};


// =====================================================================
//  GF(2) inner product parity  (used for nontriviality checks)
// =====================================================================

// Returns true if row i of A anticommutes with ANY row of B
// i.e. exists j: popcount(A[i] & B[j]) is odd
static bool row_anticommutes_any(const uint64_t* a, const GF2Matrix& B, int wpr) {
    for (int j = 0; j < B.rows_; ++j) {
        const uint64_t* b = B.row_ptr(j);
        uint64_t acc = 0;
        for (int w = 0; w < wpr; ++w) acc ^= a[w] & b[w];
        // popcount(XOR-accumulated AND) gives parity of total inner product
        if (__builtin_popcountll(acc) & 1)
            return true;
    }
    return false;
}


// =====================================================================
//  min_logical_weight_rand  (the #1 hot function)
// =====================================================================

// Core trials loop with PRECOMPUTED kernel K and logical basis LZ. Hoisting the
// (relatively expensive) basis computations out lets them be shared read-only
// across threads -- rref_perm copies its argument, so K/LZ are never mutated.
// If wit_out is non-null, the bit-packed support of the best logical found is
// copied into it (empty if none found).
static int min_logical_weight_rand_core(
    int n, const GF2Matrix& K, const GF2Matrix& LZ,
    int trials, uint64_t seed, int pair_depth,
    std::vector<uint64_t>* wit_out = nullptr)
{
    if (wit_out) wit_out->clear();
    if (K.rows_ == 0 || LZ.rows_ == 0)
        return n + 1;  // no logicals → infinite distance sentinel

    Xoshiro256 rng(seed);
    int best = n + 1;

    std::vector<int> perm(n);
    std::iota(perm.begin(), perm.end(), 0);

    for (int trial = 0; trial < trials; ++trial) {
        rng.shuffle(perm);
        GF2Matrix red = rref_perm(K, perm);

        int nred = red.rows_;
        int wpr = std::min(red.wpr_, LZ.wpr_);

        // ---- single-row candidates ----
        // Compute weights and nontriviality for each reduced row
        std::vector<int> weights(nred);
        for (int i = 0; i < nred; ++i)
            weights[i] = red.row_weight(i);

        for (int i = 0; i < nred; ++i) {
            if (weights[i] > 0 && weights[i] < best) {
                if (row_anticommutes_any(red.row_ptr(i), LZ, wpr)) {
                    best = weights[i];
                    if (wit_out)
                        wit_out->assign(red.row_ptr(i), red.row_ptr(i) + red.wpr_);
                }
            }
        }

        // ---- pairwise candidates (lightest pair_depth rows) ----
        if (pair_depth > 1 && nred >= 2) {
            int pd = std::min(pair_depth, nred);

            // indices of the pd lightest rows (partial sort)
            std::vector<int> idx(nred);
            std::iota(idx.begin(), idx.end(), 0);
            std::partial_sort(idx.begin(), idx.begin() + pd, idx.end(),
                [&](int a, int b) { return weights[a] < weights[b]; });

            for (int ii = 0; ii < pd; ++ii) {
                int a = idx[ii];
                const uint64_t* ra = red.row_ptr(a);
                for (int jj = ii + 1; jj < pd; ++jj) {
                    int b = idx[jj];
                    const uint64_t* rb = red.row_ptr(b);

                    // weight of a XOR b
                    int pw = 0;
                    for (int w = 0; w < red.wpr_; ++w)
                        pw += __builtin_popcountll(ra[w] ^ rb[w]);
                    if (pw <= 0 || pw >= best) continue;

                    // nontriviality: (a XOR b) · lz mod 2 for some lz
                    bool nontrivial = false;
                    for (int lz = 0; lz < LZ.rows_; ++lz) {
                        const uint64_t* lzr = LZ.row_ptr(lz);
                        uint64_t acc = 0;
                        for (int w = 0; w < wpr; ++w)
                            acc ^= (ra[w] ^ rb[w]) & lzr[w];
                        if (__builtin_popcountll(acc) & 1) {
                            nontrivial = true;
                            break;
                        }
                    }
                    if (nontrivial) {
                        best = pw;
                        if (wit_out) {
                            wit_out->resize(red.wpr_);
                            for (int w = 0; w < red.wpr_; ++w)
                                (*wit_out)[w] = ra[w] ^ rb[w];
                        }
                    }
                }
            }
        }
    }
    return best;
}

// Single-call wrapper: compute the bases then run the core.
static int min_logical_weight_rand_internal(
    const GF2Matrix& HX, const GF2Matrix& HZ,
    int trials, uint64_t seed, int pair_depth)
{
    GF2Matrix K = kernel_basis(HZ);
    GF2Matrix LZ = logical_basis(HX, HZ);
    return min_logical_weight_rand_core(HX.cols_, K, LZ, trials, seed, pair_depth);
}


// =====================================================================
//  Public C++ API
// =====================================================================

int distance_rand_cpp(const GF2Matrix& HX, const GF2Matrix& HZ,
                      int trials, uint64_t seed, int pair_depth) {
    int dx = min_logical_weight_rand_internal(HX, HZ, trials, seed, pair_depth);
    int dz = min_logical_weight_rand_internal(HZ, HX, trials, seed, pair_depth);
    return std::min(dx, dz);
}

// Threaded variant: trials are split across `n_threads` std::threads per side,
// each with a decorrelated seed; the minimum over independent trials is taken.
// min_logical_weight_rand_internal is self-contained (const inputs, local RNG and
// scratch), so this is a pure read-only fan-out -- no locks needed.
int distance_rand_parallel_cpp(const GF2Matrix& HX, const GF2Matrix& HZ,
                               int trials, uint64_t seed, int pair_depth,
                               int n_threads) {
    if (n_threads < 1) n_threads = 1;
    auto run_side = [&](const GF2Matrix& A, const GF2Matrix& B) -> int {
        int n = A.cols_;
        GF2Matrix K = kernel_basis(B);        // hoisted: computed once, not per thread
        GF2Matrix LZ = logical_basis(A, B);   // shared read-only (rref_perm copies)
        int per = (trials + n_threads - 1) / n_threads;
        std::vector<int> results(n_threads, n + 1);
        std::vector<std::thread> pool;
        pool.reserve(n_threads);
        for (int t = 0; t < n_threads; ++t) {
            uint64_t s = seed + 0x9e3779b97f4a7c15ULL * (uint64_t)(t + 1);
            pool.emplace_back([&, t, s]() {
                results[t] = min_logical_weight_rand_core(n, K, LZ, per, s, pair_depth);
            });
        }
        for (auto& th : pool) th.join();
        int m = n + 1;
        for (int r : results) m = std::min(m, r);
        return m;
    };
    int dx = run_side(HX, HZ);
    int dz = run_side(HZ, HX);
    return std::min(dx, dz);
}

// Witness-returning threaded variant. Same search as distance_rand_parallel_cpp,
// but each thread also records the support of its best logical; the global best
// is returned as (weight, side, packed support words, n). side: 0 = X, 1 = Z,
// -1 = nothing found.
struct WitnessResult {
    int weight;
    int side;
    std::vector<uint64_t> witness;  // wpr words, empty if side < 0
    int n;
};

WitnessResult distance_rand_witness_cpp(const GF2Matrix& HX, const GF2Matrix& HZ,
                                        int trials, uint64_t seed, int pair_depth,
                                        int n_threads) {
    if (n_threads < 1) n_threads = 1;
    int n = HX.cols_;
    auto run_side = [&](const GF2Matrix& A, const GF2Matrix& B,
                        std::vector<uint64_t>& wit) -> int {
        GF2Matrix K = kernel_basis(B);
        GF2Matrix LZ = logical_basis(A, B);
        int per = (trials + n_threads - 1) / n_threads;
        std::vector<int> results(n_threads, n + 1);
        std::vector<std::vector<uint64_t>> wits(n_threads);
        std::vector<std::thread> pool;
        pool.reserve(n_threads);
        for (int t = 0; t < n_threads; ++t) {
            uint64_t s = seed + 0x9e3779b97f4a7c15ULL * (uint64_t)(t + 1);
            pool.emplace_back([&, t, s]() {
                results[t] = min_logical_weight_rand_core(n, K, LZ, per, s,
                                                          pair_depth, &wits[t]);
            });
        }
        for (auto& th : pool) th.join();
        int m = n + 1;
        for (int t = 0; t < n_threads; ++t)
            if (results[t] < m) { m = results[t]; wit = wits[t]; }
        return m;
    };
    std::vector<uint64_t> witX, witZ;
    int dx = run_side(HX, HZ, witX);
    int dz = run_side(HZ, HX, witZ);
    WitnessResult res;
    res.n = n;
    if (dx <= dz && dx <= n) { res.weight = dx; res.side = 0; res.witness = witX; }
    else if (dz <= n)        { res.weight = dz; res.side = 1; res.witness = witZ; }
    else                     { res.weight = n + 1; res.side = -1; }
    return res;
}

int compute_k_cpp(const GF2Matrix& HX, const GF2Matrix& HZ) {
    int n = (HX.rows_ > 0) ? HX.cols_ :
            (HZ.rows_ > 0) ? HZ.cols_ : 0;
    int rx = (HX.rows_ > 0) ? gf2_rank(HX) : 0;
    int rz = (HZ.rows_ > 0) ? gf2_rank(HZ) : 0;
    return n - rx - rz;
}


// =====================================================================
//  pybind11 bindings  (numpy ↔ GF2Matrix conversion at the boundary)
// =====================================================================

static py::tuple py_gf2_rref(py::array_t<int8_t> M_np) {
    auto M = GF2Matrix::from_numpy(M_np);
    auto [R, pivots] = gf2_rref(M);
    return py::make_tuple(R.to_numpy(), py::cast(pivots));
}

static int py_gf2_rank(py::array_t<int8_t> M_np) {
    if (M_np.size() == 0) return 0;
    return gf2_rank(GF2Matrix::from_numpy(M_np));
}

static py::array_t<int8_t> py_kernel_basis(py::array_t<int8_t> H_np) {
    auto H = GF2Matrix::from_numpy(H_np);
    return kernel_basis(H).to_numpy();
}

static int py_distance_rand(py::array_t<int8_t> HX_np, py::array_t<int8_t> HZ_np,
                            int trials, uint64_t seed, int pair_depth) {
    if (HX_np.size() == 0 || HZ_np.size() == 0) {
        // degenerate: n with no constraints → distance is trivially 1 (or meaningless)
        return (HX_np.ndim() == 2) ? (int)HX_np.shape(1) + 1 : 1;
    }
    auto HX = GF2Matrix::from_numpy(HX_np);
    auto HZ = GF2Matrix::from_numpy(HZ_np);
    return distance_rand_cpp(HX, HZ, trials, seed, pair_depth);
}

static int py_distance_rand_parallel(py::array_t<int8_t> HX_np, py::array_t<int8_t> HZ_np,
                                     int trials, uint64_t seed, int pair_depth,
                                     int threads) {
    if (HX_np.size() == 0 || HZ_np.size() == 0) {
        return (HX_np.ndim() == 2) ? (int)HX_np.shape(1) + 1 : 1;
    }
    auto HX = GF2Matrix::from_numpy(HX_np);
    auto HZ = GF2Matrix::from_numpy(HZ_np);
    int result;
    {   // workers touch no Python objects -> drop the GIL so they run in parallel
        py::gil_scoped_release release;
        result = distance_rand_parallel_cpp(HX, HZ, trials, seed, pair_depth, threads);
    }
    return result;
}

static py::tuple py_distance_rand_witness(py::array_t<int8_t> HX_np,
                                          py::array_t<int8_t> HZ_np,
                                          int trials, uint64_t seed,
                                          int pair_depth, int threads) {
    if (HX_np.size() == 0 || HZ_np.size() == 0) {
        int n = (HX_np.ndim() == 2) ? (int)HX_np.shape(1) : 0;
        return py::make_tuple(n + 1, py::str(""), py::list());
    }
    auto HX = GF2Matrix::from_numpy(HX_np);
    auto HZ = GF2Matrix::from_numpy(HZ_np);
    WitnessResult res;
    {   // workers touch no Python objects -> drop the GIL so they run in parallel
        py::gil_scoped_release release;
        res = distance_rand_witness_cpp(HX, HZ, trials, seed, pair_depth, threads);
    }
    py::list support;
    if (res.side >= 0)
        for (int c = 0; c < res.n; ++c)
            if ((res.witness[c / 64] >> (c % 64)) & 1)
                support.append(c);
    const char* side = (res.side == 0) ? "X" : (res.side == 1) ? "Z" : "";
    return py::make_tuple(res.weight, py::str(side), support);
}

static int py_compute_k(py::array_t<int8_t> HX_np, py::array_t<int8_t> HZ_np) {
    GF2Matrix HX = (HX_np.size() > 0) ? GF2Matrix::from_numpy(HX_np)
                                       : GF2Matrix(0, (HZ_np.ndim() == 2) ? (int)HZ_np.shape(1) : 0);
    GF2Matrix HZ = (HZ_np.size() > 0) ? GF2Matrix::from_numpy(HZ_np)
                                       : GF2Matrix(0, (HX_np.ndim() == 2) ? (int)HX_np.shape(1) : 0);
    return compute_k_cpp(HX, HZ);
}


// =====================================================================
//  Module definition
// =====================================================================

PYBIND11_MODULE(gf2_fast, m) {
    m.doc() = "Bit-packed GF(2) linear algebra for quantum code search (C++ accelerated)";

    m.def("gf2_rref", &py_gf2_rref,
          "RREF over GF(2). Returns (RREF_matrix, pivot_columns).",
          py::arg("M"));

    m.def("gf2_rank", &py_gf2_rank,
          "Rank of a matrix over GF(2).",
          py::arg("M"));

    m.def("kernel_basis", &py_kernel_basis,
          "GF(2) kernel basis (right nullspace). Returns rows = basis vectors.",
          py::arg("H"));

    m.def("distance_rand", &py_distance_rand,
          "Randomized upper bound on code distance min(d_X, d_Z).",
          py::arg("HX"), py::arg("HZ"),
          py::arg("trials") = 300, py::arg("seed") = 0,
          py::arg("pair_depth") = 8);

    m.def("distance_rand_parallel", &py_distance_rand_parallel,
          "Threaded randomized upper bound on min(d_X, d_Z): trials split across "
          "`threads` std::threads per side (GIL released).",
          py::arg("HX"), py::arg("HZ"),
          py::arg("trials") = 300, py::arg("seed") = 0,
          py::arg("pair_depth") = 8, py::arg("threads") = 8);

    m.def("distance_rand_witness", &py_distance_rand_witness,
          "Like distance_rand_parallel, but returns (weight, side, support): the "
          "best logical's Pauli side ('X'/'Z') and sorted qubit indices, so the "
          "trusted Python stack can validate the find. side='' if none found.",
          py::arg("HX"), py::arg("HZ"),
          py::arg("trials") = 300, py::arg("seed") = 0,
          py::arg("pair_depth") = 8, py::arg("threads") = 8);

    m.def("compute_k", &py_compute_k,
          "Number of logical qubits: n - rank(HX) - rank(HZ).",
          py::arg("HX"), py::arg("HZ"));
}
