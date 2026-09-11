// Benchmark instrumentation around the repository's unmodified search core.
// The original module is compiled too, but this extension exports only the
// additional prepared, per-side interface under benchmark_native.
#include "../../verify/gf2_fast.cpp"

class PreparedSearch {
    int n_;
    GF2Matrix logicals_;
    std::vector<GF2Matrix> kernels_;
public:
    PreparedSearch(py::array_t<int8_t> own, py::array_t<int8_t> opposite,
                   bool circulant = false, int block_size = -1) {
        auto a = GF2Matrix::from_numpy(own);
        auto b = GF2Matrix::from_numpy(opposite);
        n_ = a.cols_;
        py::gil_scoped_release release;
        if (circulant) {
            int size = block_size < 0 ? circulant_block_size(a) : block_size;
            if (!size) return;
            if (2 * size != n_) throw std::invalid_argument("invalid circulant block size");
            for (int half = 0; half < 2; ++half) {
                auto kernel = single_block_kernel(b, half * size, size, n_);
                if (kernel.rows_) kernels_.push_back(std::move(kernel));
            }
        } else {
            kernels_.push_back(kernel_basis(b));
        }
        logicals_ = logical_basis(a, b);
    }

    bool applicable() const { return !kernels_.empty() && logicals_.rows_ > 0; }
    py::array_t<int8_t> opposite_logicals() const { return logicals_.to_numpy(); }

    py::tuple batch(int trials, uint64_t seed, int pairs, int threads, int block) const {
        if (trials < 1 || threads < 1 || pairs < 0) throw std::invalid_argument("invalid search budget");
        if (!applicable()) return py::make_tuple(n_ + 1, std::vector<int>{}, 0);
        const auto &kernel = kernels_.at(block % kernels_.size());
        threads = std::min(threads, trials);
        std::vector<int> weights(threads, n_ + 1);
        std::vector<std::vector<uint64_t>> witnesses(threads);
        {
            py::gil_scoped_release release;
            std::vector<std::thread> pool;
            for (int t = 0; t < threads; ++t) {
                int count = trials / threads + (t < trials % threads);
                uint64_t child_seed = seed + 0x9e3779b97f4a7c15ULL * uint64_t(t + 1);
                pool.emplace_back([&, t, count, child_seed]() {
                    weights[t] = min_logical_weight_rand_core(
                        n_, kernel, logicals_, count, child_seed, pairs, &witnesses[t]);
                });
            }
            for (auto &thread : pool) thread.join();
        }
        int best = int(std::min_element(weights.begin(), weights.end()) - weights.begin());
        std::vector<int> support;
        if (weights[best] <= n_)
            for (int c = 0; c < n_; ++c)
                if ((witnesses[best][c / 64] >> (c % 64)) & 1) support.push_back(c);
        return py::make_tuple(weights[best], support, trials);
    }
};

PYBIND11_MODULE(benchmark_native, module) {
    module.def("circulant_size", [](py::array_t<int8_t> hx) {
        return circulant_block_size(GF2Matrix::from_numpy(hx));
    });
    py::class_<PreparedSearch>(module, "PreparedSearch")
        .def(py::init<py::array_t<int8_t>, py::array_t<int8_t>, bool, int>(),
             py::arg("own"), py::arg("opposite"), py::arg("circulant") = false,
             py::arg("block_size") = -1)
        .def("applicable", &PreparedSearch::applicable)
        .def("opposite_logicals", &PreparedSearch::opposite_logicals)
        .def("batch", &PreparedSearch::batch, py::arg("trials"), py::arg("seed"),
             py::arg("pairs"), py::arg("threads"), py::arg("block") = 0);
}
