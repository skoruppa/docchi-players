#include <stdint.h>
#include <string.h>
#include <stdio.h>

#define BUFFER_SIZE 512
#define BUFFER_MASK 511
#define MIX_ROUNDS 2
#define INIT_CONST 2654435761U
#define FINAL_CONST 2246822519U

static inline uint32_t rotate_left(uint32_t val, int shift) {
    return (val << shift) | (val >> (32 - shift));
}

static inline void quarter_round(uint32_t *s0, uint32_t *s1, uint32_t *s2, uint32_t *s3) {
    *s0 += *s1; *s3 = rotate_left(*s3 ^ *s0, 16);
    *s2 += *s3; *s1 = rotate_left(*s1 ^ *s2, 12);
    *s0 += *s1; *s3 = rotate_left(*s3 ^ *s0, 8);
    *s2 += *s3; *s1 = rotate_left(*s1 ^ *s2, 7);
}

static int count_leading_zeros_u32(uint32_t val) {
    if (val == 0) return 32;
    return __builtin_clz(val);
}

static int solve_single(const char *input, int input_len, int difficulty) {
    uint32_t s0 = 1779033703U, s1 = 3144134277U, s2 = 1013904242U, s3 = 2773480762U;
    uint32_t buf[BUFFER_SIZE];
    
    // Mix in input bytes
    for (int i = 0; i < input_len; i++) {
        s0 += (uint8_t)input[i];
        s0 = rotate_left(s0, 7);
        quarter_round(&s0, &s1, &s2, &s3);
    }
    
    // 8 additional rounds
    for (int i = 0; i < 8; i++) {
        quarter_round(&s0, &s1, &s2, &s3);
    }
    
    // Generate buffer
    for (int i = 0; i < BUFFER_SIZE; i++) {
        quarter_round(&s0, &s1, &s2, &s3);
        buf[i] = s0 ^ s2;
    }
    
    // Mix rounds
    for (int r = 0; r < MIX_ROUNDS; r++) {
        for (int s = 0; s < BUFFER_SIZE; s++) {
            uint32_t a_idx = buf[s] & BUFFER_MASK;
            uint32_t c = buf[s] + buf[a_idx];
            c = rotate_left(c, 13);
            c ^= (uint32_t)((uint64_t)buf[(s + 1) & BUFFER_MASK] * INIT_CONST);
            buf[s] = c;
            s0 ^= c;
            quarter_round(&s0, &s1, &s2, &s3);
        }
    }
    
    // Compute output - for difficulty <= 32, only need first word
    quarter_round(&s0, &s1, &s2, &s3);
    uint32_t out_val = s0;
    int chunk = BUFFER_SIZE / 8;  // 64
    for (int c = 0; c < chunk; c++) {
        uint32_t d = buf[c];
        out_val += d;
        out_val = rotate_left(out_val, 5);
        out_val ^= (uint32_t)((uint64_t)d * FINAL_CONST);
    }
    out_val ^= s2;
    
    int leading = count_leading_zeros_u32(out_val);
    
    if (difficulty <= 32) {
        return leading >= difficulty ? 1 : 0;
    }
    
    // For difficulty > 32, need more output words
    if (leading < 32) return 0;
    
    int total_zeros = 32;
    int remaining = difficulty - 32;
    
    // Compute more output words
    for (int i = 1; i < 8 && remaining > 0; i++) {
        quarter_round(&s0, &s1, &s2, &s3);
        uint32_t val = s0;
        int base = i * chunk;
        for (int c = 0; c < chunk; c++) {
            uint32_t d = buf[base + c];
            val += d;
            val = rotate_left(val, 5);
            val ^= (uint32_t)((uint64_t)d * FINAL_CONST);
        }
        val ^= s2;
        
        int lz = count_leading_zeros_u32(val);
        total_zeros += lz;
        if (lz < 32) break;
        remaining -= 32;
    }
    
    return total_zeros >= difficulty ? 1 : 0;
}

// Main exported function
int pow_solve(const char *nonce, int difficulty, int max_iter, char *solution_out, int solution_buf_size) {
    char input[512];
    int nonce_len = strlen(nonce);
    
    // Prefix is "nonce:"
    memcpy(input, nonce, nonce_len);
    input[nonce_len] = ':';
    int prefix_len = nonce_len + 1;
    
    for (int counter = 0; counter < max_iter; counter++) {
        // Convert counter to string
        char counter_str[16];
        int counter_len = snprintf(counter_str, sizeof(counter_str), "%d", counter);
        
        // Build full input
        memcpy(input + prefix_len, counter_str, counter_len);
        int total_len = prefix_len + counter_len;
        
        if (solve_single(input, total_len, difficulty)) {
            if (counter_len < solution_buf_size) {
                memcpy(solution_out, counter_str, counter_len);
                solution_out[counter_len] = '\0';
                return counter;
            }
            return -2; // buffer too small
        }
    }
    
    return -1; // not found
}
