#include <Accelerate/Accelerate.h>

#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;

std::string json_string(const char* value) {
    if (!value) return "null";
    std::ostringstream out;
    out << '"';
    for (const unsigned char c : std::string(value)) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 0x20) {
            out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                << static_cast<unsigned>(c) << std::dec;
        } else out << c;
    }
    out << '"';
    return out.str();
}

uint32_t next_u32(uint32_t& state) {
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

int parse_int(const char* text, int minimum, int maximum) {
    std::size_t used = 0;
    const long value = std::stol(text, &used);
    if (used != std::string(text).size() || value < minimum || value > maximum)
        throw std::invalid_argument("integer argument out of range");
    return static_cast<int>(value);
}

struct Check {
    uint64_t mismatches = 0;
    uint64_t nonfinite = 0;
    double max_abs_error = 0;
    int64_t checksum = 0;
};

Check compare(const std::vector<float>& actual, const std::vector<int64_t>& expected) {
    Check result;
    for (std::size_t i = 0; i < actual.size(); ++i) {
        if (!std::isfinite(actual[i])) {
            ++result.nonfinite;
            ++result.mismatches;
            continue;
        }
        const double error = std::abs(static_cast<double>(actual[i]) - expected[i]);
        if (error != 0) ++result.mismatches;
        if (error > result.max_abs_error) result.max_abs_error = error;
        // Cast only on exact matches; avoid any out-of-range float-to-int conversion.
        if (error == 0) result.checksum += expected[i];
    }
    return result;
}

void emit_check(const Check& value) {
    std::cout << "{\"mismatches\":" << value.mismatches
              << ",\"nonfinite\":" << value.nonfinite
              << ",\"max_abs_error\":" << value.max_abs_error
              << ",\"matching_cells_checksum\":" << value.checksum << '}';
}
}  // namespace

int main(int argc, char** argv) {
    try {
        int size = 512;
        int inner = 512;
        double seconds = 60;
        uint32_t seed = 0x12345678u;
        for (int i = 1; i < argc; ++i) {
            const std::string flag = argv[i];
            if (flag == "--help") {
                std::cout << "accelerate_exact [--seconds 0.1..900] [--size 16..1024] "
                             "[--k 16..1024] [--seed 1..2147483647]\n";
                return 0;
            }
            if (i + 1 == argc) throw std::invalid_argument("missing option value");
            const char* value = argv[++i];
            if (flag == "--size") size = parse_int(value, 16, 1024);
            else if (flag == "--k") inner = parse_int(value, 16, 1024);
            else if (flag == "--seed") seed = static_cast<uint32_t>(parse_int(value, 1, 2147483647));
            else if (flag == "--seconds") {
                std::size_t used = 0;
                seconds = std::stod(value, &used);
                if (used != std::string(value).size() || !std::isfinite(seconds)
                    || seconds < 0.1 || seconds > 900)
                    throw std::invalid_argument("seconds out of range");
            } else throw std::invalid_argument("unknown option: " + flag);
        }

        const auto whole_start = Clock::now();
        const std::size_t cells = static_cast<std::size_t>(size) * size;
        const std::size_t input_cells = static_cast<std::size_t>(size) * inner;
        std::vector<float> a(input_cells), b(input_cells), c(cells);
        std::vector<int64_t> oracle(cells);
        uint32_t rng = seed;
        for (float& value : a) value = static_cast<int>(next_u32(rng) % 5) - 2;
        for (float& value : b) value = static_cast<int>(next_u32(rng) % 5) - 2;

        // Independent full int64 dot-product oracle. B is stored transposed.
        const auto oracle_start = Clock::now();
        for (int row = 0; row < size; ++row) {
            for (int col = 0; col < size; ++col) {
                int64_t sum = 0;
                for (int k = 0; k < inner; ++k) {
                    sum += static_cast<int64_t>(a[static_cast<std::size_t>(row) * inner + k])
                         * static_cast<int64_t>(b[static_cast<std::size_t>(col) * inner + k]);
                }
                oracle[static_cast<std::size_t>(row) * size + col] = sum;
            }
        }
        const double oracle_seconds = std::chrono::duration<double>(Clock::now() - oracle_start).count();

        auto gemm = [&] {
            cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasTrans,
                        size, size, inner, 1.0f, a.data(), inner,
                        b.data(), inner, 0.0f, c.data(), size);
        };
        gemm();
        gemm();
        const Check before = compare(c, oracle);
        if (before.mismatches) {
            std::cout << "{\"benchmark\":\"accelerate_exact_sgemm\",\"status\":\"warmup_incorrect\",\"check\":";
            emit_check(before);
            std::cout << "}\n";
            return 2;
        }

        std::cerr << "Accelerate SGEMM: " << size << 'x' << size << " K=" << inner
                  << "; timed window " << seconds << " s; AMX execution unverified\n";
        uint64_t iterations = 0;
        const auto timed_start = Clock::now();
        double elapsed = 0;
        do {
            gemm();
            ++iterations;
            elapsed = std::chrono::duration<double>(Clock::now() - timed_start).count();
        } while (elapsed < seconds);
        const Check after = compare(c, oracle);
        const double whole_seconds = std::chrono::duration<double>(Clock::now() - whole_start).count();
        const uint64_t macs_per_iteration = static_cast<uint64_t>(size) * size * inner;
        const double macs = static_cast<double>(iterations) * macs_per_iteration;

        std::cout << std::setprecision(12)
                  << "{\"benchmark\":\"accelerate_exact_sgemm\",\"status\":"
                  << json_string(after.mismatches ? "incorrect" : "ok")
                  << ",\"backend\":\"public Accelerate cblas_sgemm\""
                  << ",\"actual_amx_execution_verified\":false"
                  << ",\"mining_work_verified\":false"
                  << ",\"m\":" << size << ",\"n\":" << size << ",\"k\":" << inner
                  << ",\"seed\":" << seed
                  << ",\"input_integer_min\":-2,\"input_integer_max\":2"
                  << ",\"partial_sum_absolute_bound\":" << 4 * inner
                  << ",\"float32_exact_integer_bound\":16777216"
                  << ",\"oracle_cells_checked_each_time\":" << cells
                  << ",\"oracle_seconds\":" << oracle_seconds
                  << ",\"warmup_iterations\":2"
                  << ",\"requested_timed_seconds\":" << seconds
                  << ",\"timed_wall_seconds\":" << elapsed
                  << ",\"whole_wall_seconds\":" << whole_seconds
                  << ",\"timed_iterations\":" << iterations
                  << ",\"macs_per_iteration\":" << macs_per_iteration
                  << ",\"timed_macs\":" << macs
                  << ",\"timed_flops\":" << 2 * macs
                  << ",\"mac_per_second\":" << macs / elapsed
                  << ",\"flop_per_second\":" << 2 * macs / elapsed
                  << ",\"veclib_maximum_threads_requested\":" << json_string(std::getenv("VECLIB_MAXIMUM_THREADS"))
                  << ",\"thread_limit_enforcement_verified\":false"
                  << ",\"first_complete_check\":";
        emit_check(before);
        std::cout << ",\"last_complete_check\":";
        emit_check(after);
        std::cout << "}\n";
        return after.mismatches ? 2 : 0;
    } catch (const std::exception& error) {
        std::cerr << "accelerate_exact: " << error.what() << '\n';
        return 1;
    }
}
