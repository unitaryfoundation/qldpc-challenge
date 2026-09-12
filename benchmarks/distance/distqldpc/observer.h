/* Benchmark-only incumbent export for DistQLDPC.
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Model reconstruction follows SimpSolver::extendModel (Niklas Een and
 * Niklas Sorensson, MIT; see the pinned upstream src/solver/LICENSE).
 * This observer works on a copy, without modifying assignments or search state.
 */
#ifndef QLDPC_BENCHMARK_OBSERVER_H
#define QLDPC_BENCHMARK_OBSERVER_H

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string>
#include <unistd.h>
#include "SimpSolver.h"

class ObservedSimpSolver : public Minisat::SimpSolver {
    int witness_fd;
    int qubits;

    static void fail_export() {
        perror("DistQLDPC witness export");
        _exit(74);
    }

protected:
    virtual void observeIncumbent(uint64_t cost) {
        using namespace Minisat;
        if (witness_fd < 0) return;
        vec<lbool> sample;
        sample.growTo(nVars(), l_False);
        for (int v = 0; v < nVars(); ++v)
            sample[v] = value(v) == l_True ? l_True : l_False;

        // Reconstruct eliminated variables in reverse elimination order.
        for (int i = elimclauses.size() - 1; i > 0;) {
            int length = elimclauses[i--];
            int first = i - length + 1;
            bool satisfied = false;
            for (int j = i; j > first; --j) {
                Lit p = toLit(elimclauses[j]);
                if ((sample[var(p)] ^ sign(p)) == l_True) satisfied = true;
            }
            if (!satisfied) {
                Lit p = toLit(elimclauses[first]);
                sample[var(p)] = lbool(!sign(p));
            }
            i = first - 1;
        }

        char prefix[96];
        snprintf(prefix, sizeof(prefix), "{\"solver_cost\":%llu,\"x\":\"",
                 (unsigned long long)cost);
        std::string line(prefix);
        for (int i = 0; i < qubits; ++i)
            line += sample[i] == l_True ? '1' : '0';
        line += "\",\"z\":\"";
        for (int i = 0; i < qubits; ++i)
            line += sample[qubits + i] == l_True ? '1' : '0';
        line += "\"}\n";
        size_t offset = 0;
        while (offset < line.size()) {
            ssize_t written = write(witness_fd, line.data() + offset, line.size() - offset);
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0) fail_export();
            offset += (size_t)written;
        }
        if (fsync(witness_fd) != 0) fail_export();
    }

public:
    ObservedSimpSolver(const char* path, int n) : witness_fd(-1), qubits(n) {
        if (path) {
            witness_fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
            if (witness_fd < 0) fail_export();
        }
    }
    virtual ~ObservedSimpSolver() {
        if (witness_fd >= 0 && close(witness_fd) != 0) fail_export();
    }
};
#endif
