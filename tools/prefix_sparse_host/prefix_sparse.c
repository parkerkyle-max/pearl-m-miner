/* Exact zero-signal + immutable nonce-leaf prefix scatter. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>

int zf_build_zero_nonce_prefix(const int8_t *u, const uint32_t *pa,
    const uint32_t *qb, const int8_t *nonce_leaf, uint64_t nonce_index,
    uint32_t m, uint32_t k, uint32_t rank, uint32_t row_start,
    uint32_t row_count, int32_t *out) {
    if (!u || !pa || !qb || !nonce_leaf || !out || !m || k != 4096 || rank != 128 ||
        row_start > m || row_count > m-row_start || nonce_index >= (uint64_t)m*k/1024) return -1;
    for (uint32_t l=0; l<k; ++l)
        if (pa[2*l]>=rank || pa[2*l+1]>=rank || qb[2*l]>=rank || qb[2*l+1]>=rank ||
            pa[2*l]==pa[2*l+1] || qb[2*l]==qb[2*l+1]) return -2;
    for (uint32_t j=0; j<1024; ++j)
        if (nonce_leaf[j] < -1 || nonce_leaf[j] > 1) return -3;
    uint64_t nonce_lo=nonce_index*1024, nonce_hi=nonce_lo+1024;
    for (uint32_t row=row_start; row<row_start+row_count; ++row) {
        int32_t accum[128]={0};
        const int8_t *ur=u+(size_t)row*rank;
        uint64_t row_lo=(uint64_t)row*k;
        int nonce_row=(row_lo < nonce_hi && row_lo+k > nonce_lo);
        for (uint32_t l=0; l<k; ++l) {
            uint64_t pos=row_lo+l;
            int32_t a=(int32_t)ur[pa[2*l]]-ur[pa[2*l+1]];
            if (nonce_row && pos>=nonce_lo && pos<nonce_hi) a+=nonce_leaf[pos-nonce_lo];
            if (a < -64 || a > 64) return -4;
            accum[qb[2*l]] += a;
            accum[qb[2*l+1]] -= a;
            if ((l+1)%rank==0)
                memcpy(out+(((l+1)/rank-1)*(size_t)m+row)*rank,accum,sizeof(accum));
        }
    }
    return 0;
}
