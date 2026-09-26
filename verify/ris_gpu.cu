/*
 * ris_gpu -- standalone GPU random-information-set distance search for CSS
 * codes. OPTIONAL deep-search accelerator, like gf2_fast.cpp: the pure-Python
 * verifier stays the reference, and every operator this tool reports is
 * re-verified on the CPU by verify/ris_gpu.py before anyone believes it.
 *
 * The two device kernels are ported verbatim from sqetch by Muzhou Ma
 * (https://github.com/Muzhou-Ma/sqetch, MIT License, Copyright (c) 2026
 * Muzhou Ma). The host side replaces sqetch's torch JIT wrappers with plain
 * CUDA runtime calls so the binary has no Python or torch dependency.
 *
 * Build:   make ris          (nvcc -O3 -arch=native -o build/ris_gpu ...)
 * Input:   packed matrix file written by verify/ris_gpu.py ("RISGPU01"
 *          header; W_null = basis of ker(H_check), W_logical = opposite-type
 *          logical basis; rows bit-packed LSB-first into uint64 words).
 * Output:  key=value lines on stdout; recover mode adds "support=..." with
 *          the qubit indices of the best logical operator found.
 *
 * Each trial draws a random column permutation and a k_sub-row random sketch
 * of W_null, row-reduces the sketch in permuted column order, and keeps the
 * lightest row that anticommutes with a logical -- i.e. a random-ISD trial.
 * Weights found are upper bounds on d; nothing here is a proof.
 */

#include <cuda_runtime.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <string>
#include <vector>

#define BLOCK_SIZE 128

#define CUDA_CHECK(call)                                                    \
    do {                                                                    \
        cudaError_t err_ = (call);                                          \
        if (err_ != cudaSuccess) {                                          \
            fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__,          \
                    __LINE__, cudaGetErrorString(err_));                    \
            exit(2);                                                        \
        }                                                                   \
    } while (0)

/* ------------------------------------------------------------------ */
/*  Device code, ported verbatim from sqetch (MIT, Muzhou Ma)          */
/* ------------------------------------------------------------------ */

__device__ __forceinline__ uint64_t xorshift64(uint64_t* state) {
    uint64_t x = *state;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    *state = x;
    return x;
}

__device__ __forceinline__ int row_weight(const uint64_t* row, int nw) {
    int w = 0;
    for (int i = 0; i < nw; i++) w += __popcll(row[i]);
    return w;
}

__device__ __forceinline__ int gf2_dot(const uint64_t* a, const uint64_t* b, int nw) {
    uint64_t acc = 0;
    for (int i = 0; i < nw; i++) acc ^= (a[i] & b[i]);
    acc ^= acc >> 32; acc ^= acc >> 16; acc ^= acc >> 8;
    acc ^= acc >> 4;  acc ^= acc >> 2;  acc ^= acc >> 1;
    return (int)(acc & 1);
}

__global__ void __launch_bounds__(BLOCK_SIZE)
sqetch_ksub_kernel(
    const uint64_t* __restrict__ W_null,
    const uint64_t* __restrict__ W_logical,
    int k,
    int kx,
    int nw,
    int n,
    int k_sub,
    int* global_best,
    unsigned long long base_seed,
    int d_target,
    int* found_flag
) {
    const int bid = blockIdx.x;
    const int tid = threadIdx.x;

    extern __shared__ char raw_shmem[];

    uint16_t* perm = (uint16_t*)raw_shmem;
    int perm_bytes = (n * 2 + 7) & ~7;

    uint64_t* W_sub = (uint64_t*)(raw_shmem + perm_bytes);
    int wsub_bytes = k_sub * nw * 8;

    uint64_t* pivot_row_shmem = (uint64_t*)(raw_shmem + perm_bytes + wsub_bytes);
    int pivot_bytes = nw * 8;

    int* control = (int*)(raw_shmem + perm_bytes + wsub_bytes + pivot_bytes);
    int* thread_best = control + 2;

    uint64_t block_seed = base_seed ^ ((uint64_t)bid * 6364136223846793005ULL + 1442695040888963407ULL);

    if (tid == 0) {
        uint64_t rng = block_seed;
        xorshift64(&rng);
        for (int i = 0; i < n; i++) perm[i] = (uint16_t)i;
        for (int i = n - 1; i > 0; i--) {
            int j = (int)(xorshift64(&rng) % (uint64_t)(i + 1));
            uint16_t tmp = perm[i]; perm[i] = perm[j]; perm[j] = tmp;
        }
        control[1] = 0;
    }

    uint64_t thread_rng = block_seed ^ ((uint64_t)tid * 2685821657736338717ULL + 1);
    xorshift64(&thread_rng);

    for (int s = tid; s < k_sub; s += BLOCK_SIZE) {
        int src_row = (int)(xorshift64(&thread_rng) % (uint64_t)k);
        const uint64_t* src = W_null + (size_t)src_row * nw;
        uint64_t* dst = W_sub + (size_t)s * nw;
        for (int w = 0; w < nw; w++) dst[w] = __ldg(src + w);
    }
    __syncthreads();

    for (int c_virt = 0; c_virt < n; c_virt++) {
        int pr = control[1];
        if (pr >= k_sub) { __syncthreads(); __syncthreads(); continue; }

        int c_phys = (int)perm[c_virt];
        int word = c_phys >> 6;
        int bit_pos = c_phys & 63;
        uint64_t mask = (uint64_t)1 << bit_pos;

        if (tid == 0) {
            int found = -1;
            for (int r = pr; r < k_sub; r++) {
                if (W_sub[(size_t)r * nw + word] & mask) { found = r; break; }
            }
            control[0] = found;
            if (found != -1) {
                if (found != pr) {
                    for (int w = 0; w < nw; w++) {
                        uint64_t tmp = W_sub[(size_t)pr * nw + w];
                        W_sub[(size_t)pr * nw + w] = W_sub[(size_t)found * nw + w];
                        W_sub[(size_t)found * nw + w] = tmp;
                    }
                }
                for (int w = 0; w < nw; w++)
                    pivot_row_shmem[w] = W_sub[(size_t)pr * nw + w];
                control[1] = pr + 1;
            }
        }
        __syncthreads();

        if (control[0] == -1) { __syncthreads(); continue; }

        int pr2 = pr;
        for (int r = tid; r < k_sub; r += BLOCK_SIZE) {
            if (r != pr2 && (W_sub[(size_t)r * nw + word] & mask)) {
                for (int w = 0; w < nw; w++)
                    W_sub[(size_t)r * nw + w] ^= pivot_row_shmem[w];
            }
        }
        __syncthreads();
    }

    thread_best[tid] = n + 1;

    for (int r = tid; r < k_sub; r += BLOCK_SIZE) {
        uint64_t* row = W_sub + (size_t)r * nw;
        int all_zero = 1;
        for (int w = 0; w < nw; w++) if (row[w]) { all_zero = 0; break; }
        if (all_zero) continue;

        int wt = row_weight(row, nw);
        if (wt >= thread_best[tid]) continue;

        int is_logical = 0;
        for (int rx = 0; rx < kx && !is_logical; rx++)
            if (gf2_dot(W_logical + (size_t)rx * nw, row, nw)) is_logical = 1;

        if (is_logical && wt < thread_best[tid])
            thread_best[tid] = wt;
    }
    __syncthreads();

    for (int stride = BLOCK_SIZE / 2; stride > 0; stride >>= 1) {
        if (tid < stride)
            if (thread_best[tid + stride] < thread_best[tid])
                thread_best[tid] = thread_best[tid + stride];
        __syncthreads();
    }

    if (tid == 0 && thread_best[0] <= n) {
        atomicMin(global_best, thread_best[0]);
        if (d_target >= 0 && thread_best[0] < d_target && found_flag)
            atomicExch(found_flag, 1);
    }
}


__global__ void __launch_bounds__(BLOCK_SIZE)
sqetch_ksub_recover_kernel(
    const uint64_t* __restrict__ W_null,
    const uint64_t* __restrict__ W_logical,
    int k, int kx, int nw, int n, int k_sub,
    int* global_best,
    unsigned long long base_seed,
    int d_target,
    int* found_flag,
    uint64_t* out_vec,
    int32_t* out_perm,
    int* done_flag
) {
    const int bid = blockIdx.x;
    const int tid = threadIdx.x;

    extern __shared__ char raw_shmem[];

    uint16_t* perm = (uint16_t*)raw_shmem;
    int perm_bytes = (n * 2 + 7) & ~7;

    uint64_t* W_sub = (uint64_t*)(raw_shmem + perm_bytes);
    int wsub_bytes = k_sub * nw * 8;

    uint64_t* pivot_row_shmem = (uint64_t*)(raw_shmem + perm_bytes + wsub_bytes);
    int pivot_bytes = nw * 8;

    int* control = (int*)(raw_shmem + perm_bytes + wsub_bytes + pivot_bytes);
    int* thread_best = control + 2;
    int* thread_best_row = thread_best + BLOCK_SIZE;

    uint64_t block_seed = base_seed ^ ((uint64_t)bid * 6364136223846793005ULL + 1442695040888963407ULL);

    if (tid == 0) {
        uint64_t rng = block_seed;
        xorshift64(&rng);
        for (int i = 0; i < n; i++) perm[i] = (uint16_t)i;
        for (int i = n - 1; i > 0; i--) {
            int j = (int)(xorshift64(&rng) % (uint64_t)(i + 1));
            uint16_t tmp = perm[i]; perm[i] = perm[j]; perm[j] = tmp;
        }
        control[1] = 0;
    }

    uint64_t thread_rng = block_seed ^ ((uint64_t)tid * 2685821657736338717ULL + 1);
    xorshift64(&thread_rng);

    for (int s = tid; s < k_sub; s += BLOCK_SIZE) {
        int src_row = (int)(xorshift64(&thread_rng) % (uint64_t)k);
        const uint64_t* src = W_null + (size_t)src_row * nw;
        uint64_t* dst = W_sub + (size_t)s * nw;
        for (int w = 0; w < nw; w++) dst[w] = __ldg(src + w);
    }
    __syncthreads();

    for (int c_virt = 0; c_virt < n; c_virt++) {
        int pr = control[1];
        if (pr >= k_sub) { __syncthreads(); __syncthreads(); continue; }

        int c_phys = (int)perm[c_virt];
        int word = c_phys >> 6;
        int bit_pos = c_phys & 63;
        uint64_t mask = (uint64_t)1 << bit_pos;

        if (tid == 0) {
            int found = -1;
            for (int r = pr; r < k_sub; r++) {
                if (W_sub[(size_t)r * nw + word] & mask) { found = r; break; }
            }
            control[0] = found;
            if (found != -1) {
                if (found != pr) {
                    for (int w = 0; w < nw; w++) {
                        uint64_t tmp = W_sub[(size_t)pr * nw + w];
                        W_sub[(size_t)pr * nw + w] = W_sub[(size_t)found * nw + w];
                        W_sub[(size_t)found * nw + w] = tmp;
                    }
                }
                for (int w = 0; w < nw; w++)
                    pivot_row_shmem[w] = W_sub[(size_t)pr * nw + w];
                control[1] = pr + 1;
            }
        }
        __syncthreads();

        if (control[0] == -1) { __syncthreads(); continue; }

        int pr2 = pr;
        for (int r = tid; r < k_sub; r += BLOCK_SIZE) {
            if (r != pr2 && (W_sub[(size_t)r * nw + word] & mask)) {
                for (int w = 0; w < nw; w++)
                    W_sub[(size_t)r * nw + w] ^= pivot_row_shmem[w];
            }
        }
        __syncthreads();
    }

    thread_best[tid] = n + 1;
    thread_best_row[tid] = -1;
    for (int r = tid; r < k_sub; r += BLOCK_SIZE) {
        uint64_t* row = W_sub + (size_t)r * nw;
        int all_zero = 1;
        for (int w = 0; w < nw; w++) if (row[w]) { all_zero = 0; break; }
        if (all_zero) continue;

        int wt = row_weight(row, nw);
        if (wt >= thread_best[tid]) continue;

        int is_logical = 0;
        for (int rx = 0; rx < kx && !is_logical; rx++)
            if (gf2_dot(W_logical + (size_t)rx * nw, row, nw)) is_logical = 1;

        if (is_logical && wt < thread_best[tid]) {
            thread_best[tid] = wt;
            thread_best_row[tid] = r;
        }
    }
    __syncthreads();

    for (int stride = BLOCK_SIZE / 2; stride > 0; stride >>= 1) {
        if (tid < stride && thread_best[tid + stride] < thread_best[tid]) {
            thread_best[tid] = thread_best[tid + stride];
            thread_best_row[tid] = thread_best_row[tid + stride];
        }
        __syncthreads();
    }

    /* control[0] still holds the last pivot-search result of the column loop;
       a block that found no logical must clear it, or the copy-out below hands
       the host a stabilizer row and the host commits its weight. */
    if (tid == 0) control[0] = -1;
    if (tid == 0 && thread_best[0] <= n) {
        int wt = thread_best[0];
        atomicMin(global_best, wt);
        if (d_target >= 0 && wt < d_target) {
            if (found_flag) atomicExch(found_flag, 1);
            if (out_vec && out_perm && done_flag &&
                atomicExch(done_flag, 1) == 0) {
                control[0] = thread_best_row[0];
            } else {
                control[0] = -1;
            }
        } else {
            control[0] = -1;
        }
    }
    __syncthreads();

    int winner_row = control[0];
    if (winner_row >= 0) {
        const uint64_t* wrow = W_sub + (size_t)winner_row * nw;
        for (int w = tid; w < nw; w += BLOCK_SIZE)
            out_vec[w] = wrow[w];
        for (int i = tid; i < n; i += BLOCK_SIZE)
            out_perm[i] = (int32_t)perm[i];
    }
}

/* ------------------------------------------------------------------ */
/*  Deep kernel: full-basis RREF + depth-2 pair stage (this repo).     */
/*                                                                     */
/*  Motivation: the sketch kernels above are depth-1 Prange -- a trial */
/*  succeeds only if the permutation isolates the target's ENTIRE      */
/*  support. Empirically (two-orbit GB campaign, 2026-08-19) 1e5 CPU   */
/*  information sets with a pair stage beat 4e7 sketched GPU trials at */
/*  n >= 500. This kernel gives GPU trials the same per-trial power:   */
/*  when k_sub >= k_null the whole kernel basis is copied (no          */
/*  with-replacement rank loss), and after the RREF the lightest       */
/*  pair_top rows are XORed pairwise (Leon/Stern-style depth 2).       */
/*  Recover-capable: the winning vector (row or row-pair XOR) is       */
/*  written back for CPU re-verification.                              */
/* ------------------------------------------------------------------ */

#define MAX_PAIR_TOP 32

__global__ void __launch_bounds__(BLOCK_SIZE)
deep_pair_kernel(
    const uint64_t* __restrict__ W_null,
    const uint64_t* __restrict__ W_logical,
    int k, int kx, int nw, int n, int k_sub, int pair_top,
    int* global_best,
    unsigned long long base_seed,
    int d_target,
    int* found_flag,
    uint64_t* out_vec,
    int* done_flag
) {
    const int bid = blockIdx.x;
    const int tid = threadIdx.x;

    extern __shared__ char raw_shmem[];

    uint16_t* perm = (uint16_t*)raw_shmem;
    int perm_bytes = (n * 2 + 7) & ~7;
    uint64_t* W_sub = (uint64_t*)(raw_shmem + perm_bytes);
    int wsub_bytes = k_sub * nw * 8;
    uint64_t* pivot_row_shmem = (uint64_t*)(raw_shmem + perm_bytes + wsub_bytes);
    int pivot_bytes = nw * 8;
    int16_t* wts = (int16_t*)(raw_shmem + perm_bytes + wsub_bytes + pivot_bytes);
    int wts_bytes = (k_sub * 2 + 7) & ~7;
    int* control = (int*)(raw_shmem + perm_bytes + wsub_bytes + pivot_bytes + wts_bytes);
    /* control[0..1] as above; control[2..2+MAX_PAIR_TOP) top row indices */
    int* thread_best = control + 2 + MAX_PAIR_TOP;
    int* thread_ra = thread_best + BLOCK_SIZE;
    int* thread_rb = thread_ra + BLOCK_SIZE;

    uint64_t block_seed = base_seed ^ ((uint64_t)bid * 6364136223846793005ULL + 1442695040888963407ULL);

    if (tid == 0) {
        uint64_t rng = block_seed;
        xorshift64(&rng);
        for (int i = 0; i < n; i++) perm[i] = (uint16_t)i;
        for (int i = n - 1; i > 0; i--) {
            int j = (int)(xorshift64(&rng) % (uint64_t)(i + 1));
            uint16_t tmp = perm[i]; perm[i] = perm[j]; perm[j] = tmp;
        }
        control[1] = 0;
    }

    /* full copy when the whole basis fits; sketch draw otherwise */
    if (k_sub >= k) {
        for (size_t i = tid; i < (size_t)k * nw; i += BLOCK_SIZE)
            W_sub[i] = __ldg(W_null + i);
    } else {
        uint64_t thread_rng = block_seed ^ ((uint64_t)tid * 2685821657736338717ULL + 1);
        xorshift64(&thread_rng);
        for (int s = tid; s < k_sub; s += BLOCK_SIZE) {
            int src_row = (int)(xorshift64(&thread_rng) % (uint64_t)k);
            const uint64_t* src = W_null + (size_t)src_row * nw;
            uint64_t* dst = W_sub + (size_t)s * nw;
            for (int w = 0; w < nw; w++) dst[w] = __ldg(src + w);
        }
    }
    int rows = k_sub < k ? k_sub : k;
    __syncthreads();

    for (int c_virt = 0; c_virt < n; c_virt++) {
        int pr = control[1];
        if (pr >= rows) { __syncthreads(); __syncthreads(); continue; }

        int c_phys = (int)perm[c_virt];
        int word = c_phys >> 6;
        uint64_t mask = (uint64_t)1 << (c_phys & 63);

        if (tid == 0) {
            int found = -1;
            for (int r = pr; r < rows; r++)
                if (W_sub[(size_t)r * nw + word] & mask) { found = r; break; }
            control[0] = found;
            if (found != -1) {
                if (found != pr) {
                    for (int w = 0; w < nw; w++) {
                        uint64_t tmp = W_sub[(size_t)pr * nw + w];
                        W_sub[(size_t)pr * nw + w] = W_sub[(size_t)found * nw + w];
                        W_sub[(size_t)found * nw + w] = tmp;
                    }
                }
                for (int w = 0; w < nw; w++)
                    pivot_row_shmem[w] = W_sub[(size_t)pr * nw + w];
                control[1] = pr + 1;
            }
        }
        __syncthreads();
        if (control[0] == -1) { __syncthreads(); continue; }

        int pr2 = pr;
        for (int r = tid; r < rows; r += BLOCK_SIZE) {
            if (r != pr2 && (W_sub[(size_t)r * nw + word] & mask)) {
                for (int w = 0; w < nw; w++)
                    W_sub[(size_t)r * nw + w] ^= pivot_row_shmem[w];
            }
        }
        __syncthreads();
    }

    /* weights + single-row candidates */
    thread_best[tid] = n + 1;
    thread_ra[tid] = -1;
    thread_rb[tid] = -1;
    for (int r = tid; r < rows; r += BLOCK_SIZE) {
        uint64_t* row = W_sub + (size_t)r * nw;
        int wt = row_weight(row, nw);
        wts[r] = (int16_t)(wt > 32000 ? 32000 : wt);
        if (wt == 0 || wt >= thread_best[tid]) continue;
        int is_logical = 0;
        for (int rx = 0; rx < kx && !is_logical; rx++)
            if (gf2_dot(W_logical + (size_t)rx * nw, row, nw)) is_logical = 1;
        if (is_logical) {
            thread_best[tid] = wt;
            thread_ra[tid] = r;
            thread_rb[tid] = -1;
        }
    }
    __syncthreads();

    /* pair_top lightest rows (thread 0 selection sort) */
    int top = pair_top < MAX_PAIR_TOP ? pair_top : MAX_PAIR_TOP;
    if (top > rows) top = rows;
    if (tid == 0) {
        for (int t = 0; t < top; t++) {
            int bi = -1, bw = 1 << 30;
            for (int r = 0; r < rows; r++) {
                if (wts[r] <= 0 || wts[r] >= bw) continue;
                int used = 0;
                for (int u = 0; u < t; u++)
                    if (control[2 + u] == r) { used = 1; break; }
                if (!used) { bw = wts[r]; bi = r; }
            }
            control[2 + t] = bi;
        }
    }
    __syncthreads();

    /* depth-2: pairs among the top rows, threads strided over pairs */
    int npairs = top * (top - 1) / 2;
    for (int p = tid; p < npairs; p += BLOCK_SIZE) {
        int a = 0, rem = p;
        while (rem >= top - 1 - a) { rem -= top - 1 - a; a++; }
        int b = a + 1 + rem;
        int ra = control[2 + a], rb = control[2 + b];
        if (ra < 0 || rb < 0) continue;
        const uint64_t* pa = W_sub + (size_t)ra * nw;
        const uint64_t* pb = W_sub + (size_t)rb * nw;
        int wt = 0;
        for (int w = 0; w < nw; w++) wt += __popcll(pa[w] ^ pb[w]);
        if (wt == 0 || wt >= thread_best[tid]) continue;
        int is_logical = 0;
        for (int rx = 0; rx < kx && !is_logical; rx++) {
            uint64_t acc = 0;
            const uint64_t* lr = W_logical + (size_t)rx * nw;
            for (int w = 0; w < nw; w++) acc ^= ((pa[w] ^ pb[w]) & lr[w]);
            acc ^= acc >> 32; acc ^= acc >> 16; acc ^= acc >> 8;
            acc ^= acc >> 4;  acc ^= acc >> 2;  acc ^= acc >> 1;
            is_logical = (int)(acc & 1);
        }
        if (is_logical) {
            thread_best[tid] = wt;
            thread_ra[tid] = ra;
            thread_rb[tid] = rb;
        }
    }
    __syncthreads();

    for (int stride = BLOCK_SIZE / 2; stride > 0; stride >>= 1) {
        if (tid < stride && thread_best[tid + stride] < thread_best[tid]) {
            thread_best[tid] = thread_best[tid + stride];
            thread_ra[tid] = thread_ra[tid + stride];
            thread_rb[tid] = thread_rb[tid + stride];
        }
        __syncthreads();
    }

    if (tid == 0) {
        control[0] = -1;
        if (thread_best[0] <= n) {
            atomicMin(global_best, thread_best[0]);
            if (d_target >= 0 && thread_best[0] < d_target) {
                if (found_flag) atomicExch(found_flag, 1);
                if (out_vec && done_flag && atomicExch(done_flag, 1) == 0)
                    control[0] = 0;   /* we own the output slot */
            }
        }
    }
    __syncthreads();

    if (control[0] == 0) {
        int ra = thread_ra[0], rb = thread_rb[0];
        const uint64_t* pa = W_sub + (size_t)ra * nw;
        for (int w = tid; w < nw; w += BLOCK_SIZE) {
            uint64_t v = pa[w];
            if (rb >= 0) v ^= W_sub[(size_t)rb * nw + w];
            out_vec[w] = v;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Host                                                               */
/* ------------------------------------------------------------------ */

struct Input {
    int n = 0;
    int k_null = 0;
    int k_logical = 0;
    int nw = 0;
    std::vector<uint64_t> w_null;
    std::vector<uint64_t> w_logical;
};

struct DeviceBuffers {
    uint64_t *d_null = nullptr, *d_logical = nullptr, *d_vec = nullptr;
    int *d_best = nullptr, *d_flag = nullptr, *d_done = nullptr;
    int32_t *d_perm = nullptr;
    size_t null_capacity = 0, logical_capacity = 0, vec_capacity = 0;
    int perm_capacity = 0;
};

/* Kept at process scope so batch requests reuse allocations.  A larger
   request grows only the affected buffer; smaller requests reuse it. */
static DeviceBuffers device_buffers;

static void ensure_device_buffers(const Input& in) {
    size_t null_words = in.w_null.size();
    size_t logical_words = in.w_logical.size();
    if (null_words > device_buffers.null_capacity) {
        if (device_buffers.d_null) CUDA_CHECK(cudaFree(device_buffers.d_null));
        CUDA_CHECK(cudaMalloc(&device_buffers.d_null, null_words * 8));
        device_buffers.null_capacity = null_words;
    }
    if (logical_words > device_buffers.logical_capacity) {
        if (device_buffers.d_logical) CUDA_CHECK(cudaFree(device_buffers.d_logical));
        CUDA_CHECK(cudaMalloc(&device_buffers.d_logical, logical_words * 8));
        device_buffers.logical_capacity = logical_words;
    }
    if (in.nw > (int)device_buffers.vec_capacity) {
        if (device_buffers.d_vec) CUDA_CHECK(cudaFree(device_buffers.d_vec));
        CUDA_CHECK(cudaMalloc(&device_buffers.d_vec, (size_t)in.nw * 8));
        device_buffers.vec_capacity = in.nw;
    }
    if (in.n > device_buffers.perm_capacity) {
        if (device_buffers.d_perm) CUDA_CHECK(cudaFree(device_buffers.d_perm));
        CUDA_CHECK(cudaMalloc(&device_buffers.d_perm, (size_t)in.n * 4));
        device_buffers.perm_capacity = in.n;
    }
    if (!device_buffers.d_best) CUDA_CHECK(cudaMalloc(&device_buffers.d_best, 4));
    if (!device_buffers.d_flag) CUDA_CHECK(cudaMalloc(&device_buffers.d_flag, 4));
    if (!device_buffers.d_done) CUDA_CHECK(cudaMalloc(&device_buffers.d_done, 4));
}

static Input read_input(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(2); }
    char magic[8];
    if (fread(magic, 1, 8, f) != 8 || memcmp(magic, "RISGPU01", 8) != 0) {
        fprintf(stderr, "%s: bad magic (want RISGPU01)\n", path);
        exit(2);
    }
    Input in;
    int32_t hdr[4];
    if (fread(hdr, 4, 4, f) != 4) { fprintf(stderr, "%s: truncated header\n", path); exit(2); }
    in.n = hdr[0]; in.k_null = hdr[1]; in.k_logical = hdr[2]; in.nw = hdr[3];
    if (in.n <= 0 || in.n > 65535 || in.k_null <= 0 || in.k_logical <= 0 ||
        in.nw != (in.n + 63) / 64) {
        fprintf(stderr, "%s: implausible header n=%d k_null=%d k_logical=%d nw=%d\n",
                path, in.n, in.k_null, in.k_logical, in.nw);
        exit(2);
    }
    in.w_null.resize((size_t)in.k_null * in.nw);
    in.w_logical.resize((size_t)in.k_logical * in.nw);
    if (fread(in.w_null.data(), 8, in.w_null.size(), f) != in.w_null.size() ||
        fread(in.w_logical.data(), 8, in.w_logical.size(), f) != in.w_logical.size()) {
        fprintf(stderr, "%s: truncated matrix data\n", path);
        exit(2);
    }
    fclose(f);
    return in;
}

static bool read_exact(FILE* f, void* data, size_t size) {
    return fread(data, 1, size, f) == size;
}

/* The Python wrapper owns JSON.  CUDA receives this compact stream so the
   process/context stays alive for the whole campaign.  Each request is
   translated to the existing single-input path, preserving its semantics. */
static int run_batch_file(const char* path, int argc, char** argv);

static int shmem_bytes_for(int n, int nw, int k_sub, bool recover) {
    int perm_bytes = (n * 2 + 7) & ~7;
    int wsub_bytes = k_sub * nw * 8;
    int pivot_bytes = nw * 8;
    int ctrl_bytes = 8;
    int best_bytes = BLOCK_SIZE * 4;
    int brow_bytes = recover ? BLOCK_SIZE * 4 : 0;
    return perm_bytes + wsub_bytes + pivot_bytes + ctrl_bytes + best_bytes + brow_bytes;
}

static int shmem_bytes_deep(int n, int nw, int k_sub) {
    int perm_bytes = (n * 2 + 7) & ~7;
    int wsub_bytes = k_sub * nw * 8;
    int pivot_bytes = nw * 8;
    int wts_bytes = (k_sub * 2 + 7) & ~7;
    int ctrl_bytes = (2 + MAX_PAIR_TOP) * 4;
    int best_bytes = 3 * BLOCK_SIZE * 4;
    return perm_bytes + wsub_bytes + pivot_bytes + wts_bytes + ctrl_bytes + best_bytes;
}

static void usage(const char* argv0) {
    fprintf(stderr,
        "usage: %s <input.risgpu> [--mode recover|estimate] [--trials N]\n"
        "          [--batch N] [--seed S] [--k-sub K] [--target D]\n"
        "          [--pair-depth P]\n"
        "  recover (default): ladder toward the lightest logical operator it\n"
        "  can find within the budget; prints its support. estimate: weight\n"
        "  only, slightly faster. --target D stops early once a weight < D\n"
        "  is committed. --pair-depth P > 0 switches to the deep kernel:\n"
        "  full-basis RREF (k_sub defaults to the whole kernel) plus XOR\n"
        "  combinations of the P lightest rows per trial -- far stronger per\n"
        "  trial at large n, at lower trial throughput. P is capped at %d;\n"
        "  larger values are rejected.\n", argv0, MAX_PAIR_TOP);
    exit(2);
}

int main(int argc, char** argv) {
    if (argc == 3 && !strcmp(argv[1], "--batch-input"))
        return run_batch_file(argv[2], argc, argv);
    const char* path = nullptr;
    long long trials = 50000000;
    int batch = 50000;
    unsigned long long seed = 1;
    int k_sub = 64;
    int d_target = -1;
    bool recover = true;
    int pair_depth = 0;
    bool k_sub_given = false;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--mode") && i + 1 < argc) {
            i++;
            if (!strcmp(argv[i], "recover")) recover = true;
            else if (!strcmp(argv[i], "estimate")) recover = false;
            else usage(argv[0]);
        } else if (!strcmp(argv[i], "--trials") && i + 1 < argc) {
            trials = atoll(argv[++i]);
        } else if (!strcmp(argv[i], "--batch") && i + 1 < argc) {
            batch = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--seed") && i + 1 < argc) {
            seed = strtoull(argv[++i], nullptr, 10);
        } else if (!strcmp(argv[i], "--k-sub") && i + 1 < argc) {
            k_sub = atoi(argv[++i]);
            k_sub_given = true;
        } else if (!strcmp(argv[i], "--pair-depth") && i + 1 < argc) {
            pair_depth = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--target") && i + 1 < argc) {
            d_target = atoi(argv[++i]);
        } else if (argv[i][0] == '-') {
            usage(argv[0]);
        } else if (!path) {
            path = argv[i];
        } else {
            usage(argv[0]);
        }
    }
    if (!path || trials <= 0 || batch <= 0 || k_sub <= 0) usage(argv[0]);
    if (pair_depth < 0 || pair_depth > MAX_PAIR_TOP) {
        fprintf(stderr, "--pair-depth %d out of range (max %d)\n",
                pair_depth, MAX_PAIR_TOP);
        exit(2);
    }

    Input in = read_input(path);
    int n = in.n, nw = in.nw;
    if (pair_depth > 0 && !k_sub_given)
        k_sub = in.k_null;                 /* deep mode defaults to full basis */
    int k_sub_eff = k_sub < in.k_null ? k_sub : in.k_null;

    int shmem = pair_depth > 0 ? shmem_bytes_deep(n, nw, k_sub_eff)
                               : shmem_bytes_for(n, nw, k_sub_eff, recover);
    int max_shmem = 0;
    CUDA_CHECK(cudaDeviceGetAttribute(&max_shmem,
        cudaDevAttrMaxSharedMemoryPerBlockOptin, 0));
    if (shmem > max_shmem) {
        int overhead = pair_depth > 0 ? shmem_bytes_deep(n, nw, 0)
                                      : shmem_bytes_for(n, nw, 0, recover);
        int k_cap = (max_shmem - overhead) / (nw * 8 + (pair_depth > 0 ? 2 : 0));
        fprintf(stderr, "k_sub=%d needs %d bytes shared memory, device max %d; "
                "max k_sub for n=%d is %d\n", k_sub_eff, shmem, max_shmem, n, k_cap);
        exit(2);
    }
    int shmem_request = (shmem + 4095) & ~4095;
    if (pair_depth > 0) {
        CUDA_CHECK(cudaFuncSetAttribute(deep_pair_kernel,
            cudaFuncAttributeMaxDynamicSharedMemorySize, shmem_request));
        CUDA_CHECK(cudaFuncSetCacheConfig(deep_pair_kernel,
            cudaFuncCachePreferShared));
    } else if (recover) {
        CUDA_CHECK(cudaFuncSetAttribute(sqetch_ksub_recover_kernel,
            cudaFuncAttributeMaxDynamicSharedMemorySize, shmem_request));
        CUDA_CHECK(cudaFuncSetCacheConfig(sqetch_ksub_recover_kernel,
            cudaFuncCachePreferShared));
    } else {
        CUDA_CHECK(cudaFuncSetAttribute(sqetch_ksub_kernel,
            cudaFuncAttributeMaxDynamicSharedMemorySize, shmem_request));
        CUDA_CHECK(cudaFuncSetCacheConfig(sqetch_ksub_kernel,
            cudaFuncCachePreferShared));
    }

    ensure_device_buffers(in);
    uint64_t *d_null = device_buffers.d_null, *d_logical = device_buffers.d_logical,
             *d_vec = device_buffers.d_vec;
    int *d_best = device_buffers.d_best, *d_flag = device_buffers.d_flag,
        *d_done = device_buffers.d_done;
    int32_t *d_perm = device_buffers.d_perm;
    CUDA_CHECK(cudaMemcpy(d_null, in.w_null.data(), in.w_null.size() * 8,
                          cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_logical, in.w_logical.data(), in.w_logical.size() * 8,
                          cudaMemcpyHostToDevice));

    int best_overall = n + 1;
    std::vector<uint64_t> best_vec;
    long long trials_done = 0;
    unsigned long long batch_seed = seed;
    /* recover ladder: any strictly lighter operator than the best committed
       so far claims the output slot; estimate: plain d_target early stop. */
    int current_target = recover ? n + 1 : d_target;

    while (trials_done < trials) {
        int B = (int)((trials - trials_done < batch) ? (trials - trials_done) : batch);
        int init_best = n + 1, zero = 0;
        CUDA_CHECK(cudaMemcpy(d_best, &init_best, 4, cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_flag, &zero, 4, cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_done, &zero, 4, cudaMemcpyHostToDevice));

        if (pair_depth > 0) {
            deep_pair_kernel<<<B, BLOCK_SIZE, shmem>>>(
                d_null, d_logical, in.k_null, in.k_logical, nw, n, k_sub_eff,
                pair_depth, d_best, batch_seed,
                recover ? current_target : d_target, d_flag,
                recover ? d_vec : nullptr, recover ? d_done : nullptr);
        } else if (recover) {
            sqetch_ksub_recover_kernel<<<B, BLOCK_SIZE, shmem>>>(
                d_null, d_logical, in.k_null, in.k_logical, nw, n, k_sub_eff,
                d_best, batch_seed, current_target, d_flag, d_vec, d_perm, d_done);
        } else {
            sqetch_ksub_kernel<<<B, BLOCK_SIZE, shmem>>>(
                d_null, d_logical, in.k_null, in.k_logical, nw, n, k_sub_eff,
                d_best, batch_seed, current_target, d_flag);
        }
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaDeviceSynchronize());

        trials_done += B;
        batch_seed += (unsigned long long)B * 100003ULL;

        int batch_best = 0, done = 0;
        CUDA_CHECK(cudaMemcpy(&batch_best, d_best, 4, cudaMemcpyDeviceToHost));
        if (batch_best < best_overall && !recover) best_overall = batch_best;

        if (recover) {
            CUDA_CHECK(cudaMemcpy(&done, d_done, 4, cudaMemcpyDeviceToHost));
            if (done) {
                std::vector<uint64_t> vec(nw);
                CUDA_CHECK(cudaMemcpy(vec.data(), d_vec, (size_t)nw * 8,
                                      cudaMemcpyDeviceToHost));
                int w = 0;
                for (int i = 0; i < nw; i++) w += __builtin_popcountll(vec[i]);
                if (w < best_overall) {
                    best_overall = w;
                    best_vec = vec;
                    current_target = w;
                    fprintf(stderr, "trials %lld: committed weight %d\n",
                            trials_done, w);
                    if (d_target >= 0 && w < d_target) break;
                }
            }
        } else {
            int flag = 0;
            CUDA_CHECK(cudaMemcpy(&flag, d_flag, 4, cudaMemcpyDeviceToHost));
            if (flag) break;
        }
    }

    printf("mode=%s\n", recover ? "recover" : "estimate");
    printf("n=%d\nk_null=%d\nk_logical=%d\nk_sub=%d\npair_depth=%d\n",
           n, in.k_null, in.k_logical, k_sub_eff, pair_depth);
    printf("seed=%llu\ntrials=%lld\n", seed, trials_done);
    printf("best_weight=%d\n", best_overall <= n ? best_overall : -1);
    if (recover && !best_vec.empty()) {
        printf("support=");
        int first = 1;
        for (int j = 0; j < n; j++) {
            if ((best_vec[j >> 6] >> (j & 63)) & 1) {
                printf(first ? "%d" : ",%d", j);
                first = 0;
            }
        }
        printf("\n");
    }
    return 0;
}

static int run_batch_file(const char* path, int argc, char** argv) {
    (void)argc; (void)argv;
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open batch input %s\n", path); return 2; }
    char magic[9]; int32_t version = 0, count = 0;
    if (!read_exact(f, magic, 9) || memcmp(magic, "RISBATCH1", 9) != 0 ||
        !read_exact(f, &version, 4) || !read_exact(f, &count, 4) ||
        version != 1 || count <= 0) {
        fprintf(stderr, "%s: invalid RISBATCH1 header\n", path);
        fclose(f); return 2;
    }
    int status = 0;
    for (int item = 0; item < count; item++) {
        int32_t h[9], mode = 0, pair_depth = 0;
        uint64_t seed = 0;
        if (!read_exact(f, h, sizeof(h)) || !read_exact(f, &seed, 8) ||
            !read_exact(f, &mode, 4) || !read_exact(f, &pair_depth, 4)) {
            fprintf(stderr, "%s: truncated request %d\n", path, item);
            status = 2; break;
        }
        int request_id = h[0], n = h[1], k_null = h[2], k_logical = h[3], nw = h[4];
        size_t words = (size_t)k_null * nw + (size_t)k_logical * nw;
        std::vector<uint64_t> matrices(words);
        if (!read_exact(f, matrices.data(), words * 8)) {
            fprintf(stderr, "%s: truncated matrices for request %d\n", path, item);
            status = 2; break;
        }
        char temp[128];
        snprintf(temp, sizeof(temp), "/tmp/risgpu-%d-%d.risgpu", (int)getpid(), item);
        FILE* out = fopen(temp, "wb");
        if (!out) { fprintf(stderr, "cannot create temporary request\n"); status = 2; break; }
        fwrite("RISGPU01", 1, 8, out);
        int32_t ih[4] = {n, k_null, k_logical, nw};
        fwrite(ih, 4, 4, out);
        fwrite(matrices.data(), 8, words, out);
        fclose(out);

        char id_buf[32], trials_buf[32], batch_buf[32], seed_buf[32], ksub_buf[32], target_buf[32], pair_buf[32];
        snprintf(id_buf, sizeof(id_buf), "%d", request_id);
        snprintf(trials_buf, sizeof(trials_buf), "%d", h[5]);
        snprintf(batch_buf, sizeof(batch_buf), "%d", h[6]);
        snprintf(seed_buf, sizeof(seed_buf), "%llu", (unsigned long long)seed);
        snprintf(ksub_buf, sizeof(ksub_buf), "%d", h[7]);
        snprintf(target_buf, sizeof(target_buf), "%d", h[8]);
        snprintf(pair_buf, sizeof(pair_buf), "%d", pair_depth);
        char* sub_argv[20];
        int sub_argc = 0;
        sub_argv[sub_argc++] = argv[0]; sub_argv[sub_argc++] = temp;
        sub_argv[sub_argc++] = (char*)"--mode";
        sub_argv[sub_argc++] = mode ? (char*)"recover" : (char*)"estimate";
        sub_argv[sub_argc++] = (char*)"--trials"; sub_argv[sub_argc++] = trials_buf;
        sub_argv[sub_argc++] = (char*)"--batch"; sub_argv[sub_argc++] = batch_buf;
        sub_argv[sub_argc++] = (char*)"--seed"; sub_argv[sub_argc++] = seed_buf;
        /* Zero means omitted: deep mode then gets its existing full-basis
           default, while shallow mode retains the normal default of 64. */
        if (h[7] > 0) {
            sub_argv[sub_argc++] = (char*)"--k-sub"; sub_argv[sub_argc++] = ksub_buf;
        }
        sub_argv[sub_argc++] = (char*)"--target"; sub_argv[sub_argc++] = target_buf;
        sub_argv[sub_argc++] = (char*)"--pair-depth"; sub_argv[sub_argc++] = pair_buf;
        sub_argv[sub_argc] = nullptr;
        printf("request_id=%d\n", request_id);
        int rc = main(sub_argc, sub_argv);
        unlink(temp);
        if (rc != 0) status = rc;
    }
    fclose(f);
    return status;
}
