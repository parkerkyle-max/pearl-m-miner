/* Isolated bridge using the unmodified BLAKE3 1.8.7 portable compression.
 * Vendor attribution/licenses: c_vendor/. No Pearl proof code is replaced.
 * ABI matches native/src/lib.rs for cross-language differential testing. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "blake3_impl.h"

static void chunk_cv(const uint8_t data[1024], uint64_t index,
                     const uint8_t key[32], uint8_t output[32]) {
    uint32_t cv[8];
    load_key_words(key, cv);
    for (size_t block = 0; block < 16; ++block) {
        uint8_t flags = KEYED_HASH;
        if (block == 0) flags |= CHUNK_START;
        if (block == 15) flags |= CHUNK_END;
        blake3_compress_in_place_portable(cv, data + block * 64, 64, index, flags);
    }
    store_cv_words(output, cv);
}

static void parent_cv(const uint8_t left[32], const uint8_t right[32],
                      const uint8_t key[32], int root, uint8_t output[32]) {
    uint8_t block[64];
    uint32_t cv[8];
    memcpy(block, left, 32);
    memcpy(block + 32, right, 32);
    load_key_words(key, cv);
    blake3_compress_in_place_portable(cv, block, 64, 0,
                                    KEYED_HASH | PARENT | (root ? ROOT : 0));
    store_cv_words(output, cv);
}

int mi_nonce_path(const uint8_t *data, size_t data_len, uint64_t index,
                  uint64_t total, const uint8_t *siblings, size_t sibling_count,
                  const uint8_t *key, uint8_t *output, size_t capacity,
                  size_t *written) {
    if (!data || !key || !output || !written || data_len != 1024 || total < 2 ||
        index >= total || index > UINT64_MAX / 1024 || sibling_count > 64 ||
        (sibling_count && !siblings)) return -1;
    *written = 0;
    size_t needed = 1, expected_siblings = 0;
    uint64_t position = index, size = total;
    while (size > 1) {
        expected_siblings += ((position & 1) || position + 1 < size) ? 1 : 0;
        ++needed;
        position /= 2;
        size = size / 2 + (size & 1);
    }
    if (expected_siblings != sibling_count) return -1;
    if (capacity < needed) return -2;
    uint8_t cv[32], merged[32];
    chunk_cv(data, index, key, cv);
    memcpy(output, cv, 32);
    position = index; size = total;
    size_t cursor = 0, level = 1;
    while (size > 1) {
        if ((position & 1) || position + 1 < size) {
            const uint8_t *sibling = siblings + cursor++ * 32;
            if (position & 1) parent_cv(sibling, cv, key, size == 2, merged);
            else parent_cv(cv, sibling, key, size == 2, merged);
            memcpy(cv, merged, 32);
        }
        memcpy(output + level++ * 32, cv, 32);
        position /= 2;
        size = size / 2 + (size & 1);
    }
    *written = level;
    return 0;
}
