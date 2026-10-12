// SPDX-License-Identifier: GPL-3.0-only
// Pure helpers of the GL shim's per-game fixes (no GL calls; tests/test_blazerush.py builds them for the host).
//
// gl_highp_markers: vertex shaders whose source contains every '|'-separated marker get their calculation precision
//   raised: whole-word "mediump" becomes "highp" on every line that has none of the words in / out / uniform, so the
//   shader's interface (inputs, outputs to the fragment shader, uniforms and their blocks' declarations) keeps its
//   precision. BlazeRush's particle vertex shaders (markers "in uvec2 inBoneIndices;", "uniform InstanceData",
//   "void main()") computed with large encoded values at mediump and drew big coloured streaks and flashes on the
//   Frame's GPU (Klownicle's guide, GitHub #57).
// gl_int_attribs: the attribute type helpers for the integer vertex-attribute fix in glshim.c.
#pragma once
#include <stdlib.h>
#include <string.h>

static inline int glfix_ident(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
}

// `word` as a whole word in s[0..n)
static inline int glfix_has_word(const char *s, size_t n, const char *word) {
    size_t w = strlen(word);
    for (size_t i = 0; i + w <= n; ++i)
        if (!memcmp(s + i, word, w) && (i == 0 || !glfix_ident(s[i - 1])) && (i + w == n || !glfix_ident(s[i + w])))
            return 1;
    return 0;
}

// every non-empty '|'-separated marker occurs in src (and there is at least one)
static inline int glfix_markers_match(const char *src, const char *markers) {
    if (!src || !markers || !*markers) return 0;
    int any = 0;
    char piece[256];
    for (const char *p = markers; *p;) {
        const char *bar = strchr(p, '|');
        size_t n = bar ? (size_t)(bar - p) : strlen(p);
        if (n >= sizeof(piece)) return 0;
        if (n) {
            memcpy(piece, p, n);
            piece[n] = 0;
            if (!strstr(src, piece)) return 0;
            any = 1;
        }
        p += n + (bar ? 1 : 0);
    }
    return any;
}

// A copy of src with the calculation precision raised (see above), or NULL when nothing changed. *count = number of
// "mediump" replaced.
static inline char *glfix_promote_highp(const char *src, int *count) {
    if (count) *count = 0;
    if (!src) return NULL;
    size_t len = strlen(src);
    char *out = malloc(len + 1);
    if (!out) return NULL;
    size_t o = 0;
    int n = 0;
    for (const char *line = src; *line;) {
        const char *end = strchr(line, '\n');
        size_t ll = end ? (size_t)(end - line + 1) : strlen(line);
        int interface = glfix_has_word(line, ll, "in") || glfix_has_word(line, ll, "out") ||
                        glfix_has_word(line, ll, "uniform");
        for (size_t i = 0; i < ll;) {
            if (!interface && i + 7 <= ll && !memcmp(line + i, "mediump", 7) && (i == 0 || !glfix_ident(line[i - 1])) &&
                (i + 7 == ll || !glfix_ident(line[i + 7]))) {
                memcpy(out + o, "highp", 5);
                o += 5;
                i += 7;
                ++n;
            } else {
                out[o++] = line[i++];
            }
        }
        line += ll;
    }
    out[o] = 0;
    if (!n) {
        free(out);
        return NULL;
    }
    if (count) *count = n;
    return out;
}

// GL enums (numeric, so this header needs no GL headers)
#define GLFIX_BYTE 0x1400
#define GLFIX_UNSIGNED_BYTE 0x1401
#define GLFIX_SHORT 0x1402
#define GLFIX_UNSIGNED_SHORT 0x1403
#define GLFIX_INT 0x1404
#define GLFIX_UNSIGNED_INT 0x1405
#define GLFIX_INT_VEC2 0x8B53
#define GLFIX_INT_VEC3 0x8B54
#define GLFIX_INT_VEC4 0x8B55
#define GLFIX_UNSIGNED_INT_VEC2 0x8DC6
#define GLFIX_UNSIGNED_INT_VEC3 0x8DC7
#define GLFIX_UNSIGNED_INT_VEC4 0x8DC8
#define GLFIX_FLOAT_MAT2 0x8B5A
#define GLFIX_FLOAT_MAT3 0x8B5B
#define GLFIX_FLOAT_MAT4 0x8B5C
#define GLFIX_FLOAT_MAT2x3 0x8B65
#define GLFIX_FLOAT_MAT2x4 0x8B66
#define GLFIX_FLOAT_MAT3x2 0x8B67
#define GLFIX_FLOAT_MAT3x4 0x8B68
#define GLFIX_FLOAT_MAT4x2 0x8B69
#define GLFIX_FLOAT_MAT4x3 0x8B6A

// an active attribute's GLSL type: 1 signed integer (int, ivecN), 2 unsigned (uint, uvecN), 0 floating point
static inline int glfix_int_attrib_kind(unsigned type) {
    switch (type) {
        case GLFIX_INT: case GLFIX_INT_VEC2: case GLFIX_INT_VEC3: case GLFIX_INT_VEC4: return 1;
        case GLFIX_UNSIGNED_INT: case GLFIX_UNSIGNED_INT_VEC2: case GLFIX_UNSIGNED_INT_VEC3:
        case GLFIX_UNSIGNED_INT_VEC4: return 2;
        default: return 0;
    }
}

// attribute locations an active attribute uses per array element (matrices take one per column)
static inline int glfix_attrib_columns(unsigned type) {
    switch (type) {
        case GLFIX_FLOAT_MAT2: case GLFIX_FLOAT_MAT2x3: case GLFIX_FLOAT_MAT2x4: return 2;
        case GLFIX_FLOAT_MAT3: case GLFIX_FLOAT_MAT3x2: case GLFIX_FLOAT_MAT3x4: return 3;
        case GLFIX_FLOAT_MAT4: case GLFIX_FLOAT_MAT4x2: case GLFIX_FLOAT_MAT4x3: return 4;
        default: return 1;
    }
}

// vertex data glVertexAttribIPointer accepts (integer component types only)
static inline int glfix_int_component_type(unsigned type) {
    return type == GLFIX_BYTE || type == GLFIX_UNSIGNED_BYTE || type == GLFIX_SHORT || type == GLFIX_UNSIGNED_SHORT ||
           type == GLFIX_INT || type == GLFIX_UNSIGNED_INT;
}
