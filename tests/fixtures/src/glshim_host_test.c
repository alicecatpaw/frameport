// Host test of native/glshim/glshim.c's per-game fixes against glshim_fake_gles.c, driven like BlazeRush drives GL:
// glShaderSource / glDrawElements / glDrawArrays as direct imports (the shim's exports), glDrawElementsBaseVertexOES
// through eglGetProcAddress. Usage: glshim_host_test <shim> <fake GL> on|off   (settings: FRAMEBRIDGE_CONFIG)
#define GL_GLES_PROTOTYPES 0
#include <EGL/egl.h>
#include <GLES3/gl32.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

struct attrib { GLint enabled, integer, buffer, size, type, stride, normalized; const void *ptr; };
struct fake_draw { int draws; GLint integer[16]; GLint normalized[16]; GLuint i4ui_loc; GLuint i4ui[4]; };
typedef __eglMustCastToProperFunctionPointerType (*GPA)(const char *);
typedef void (*DEBV)(GLenum, GLsizei, GLenum, const void *, GLint);
typedef void (*FAKE_PROGRAM)(GLuint, int, int, const char *const *, const GLenum *, const GLint *);
typedef void (*FAKE_SHADER)(GLuint, GLenum);
typedef const char *(*FAKE_SOURCE)(GLuint, int *);
typedef struct fake_draw *(*FAKE_LAST)(void);
typedef void (*FAKE_CONTEXT)(void *);
typedef struct attrib *(*FAKE_ATTRIB)(GLuint, GLuint);

static int failures;
#define CHECK(cond, ...)                                 \
    do {                                                 \
        if (!(cond)) {                                   \
            ++failures;                                  \
            fprintf(stderr, "FAIL line %d: ", __LINE__); \
            fprintf(stderr, __VA_ARGS__);                \
            fputc('\n', stderr);                         \
        }                                                \
    } while (0)

static const char *PARTICLE_VS_A =
    "#version 300 es\n"
    "precision mediump float;\n"
    "layout(location = 3) in uvec2 inBoneIndices;\n"
    "in mediump vec4 inPosition;\n"
    "out mediump vec4 vColor;\n";
static const char *PARTICLE_VS_B =
    "uniform InstanceData { mediump vec4 data[64]; };\n"
    "uniform mediump float uScale;\n"
    "void main()\n"
    "{\n"
    "    mediump vec4 p = data[inBoneIndices.x] * uScale;\n"
    "    mediump float d = p.x - p.y; // mediump_not_a_word stays\n"
    "    vColor = vec4(d);\n"
    "    gl_Position = inPosition + p;\n"
    "}\n";

int main(int argc, char **argv) {
    if (argc < 4) return 2;
    int on = !strcmp(argv[3], "on");
    void *shim = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!shim) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    void *fake = dlopen(argv[2], RTLD_NOW | RTLD_NOLOAD);
    if (!fake) { fprintf(stderr, "fake GL not loaded with the shim: %s\n", dlerror()); return 2; }
#define S(type, name) type name = (type)dlsym(shim, #name)
#define F(type, name) type name = (type)dlsym(fake, #name)
    S(PFNGLSHADERSOURCEPROC, glShaderSource);
    S(PFNGLDRAWELEMENTSPROC, glDrawElements);
    S(PFNGLDRAWARRAYSPROC, glDrawArrays);
    S(PFNGLLINKPROGRAMPROC, glLinkProgram);
    S(PFNGLPROGRAMBINARYPROC, glProgramBinary);
    S(GPA, eglGetProcAddress);
    F(PFNGLUSEPROGRAMPROC, glUseProgram);
    F(PFNGLBINDVERTEXARRAYPROC, glBindVertexArray);
    F(PFNGLBINDBUFFERPROC, glBindBuffer);
    F(PFNGLVERTEXATTRIBPOINTERPROC, glVertexAttribPointer);
    F(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray);
    F(PFNGLDISABLEVERTEXATTRIBARRAYPROC, glDisableVertexAttribArray);
    F(PFNGLGETINTEGERVPROC, glGetIntegerv);
    F(FAKE_PROGRAM, fake_program);
    F(FAKE_SHADER, fake_shader);
    F(FAKE_SOURCE, fake_source);
    F(FAKE_LAST, fake_last);
    F(FAKE_CONTEXT, fake_context);
    F(FAKE_ATTRIB, fake_attrib);
    if (!glShaderSource || !glDrawElements || !eglGetProcAddress || !fake_program || !glUseProgram) return 2;

    // ---- gl_highp_markers: two strings (one with an explicit length), all three markers, vertex stage only
    const GLchar *parts[2] = {PARTICLE_VS_A, PARTICLE_VS_B};
    GLint lens[2] = {(GLint)strlen(PARTICLE_VS_A), -1};
    fake_shader(1, GL_VERTEX_SHADER);
    fake_shader(2, GL_FRAGMENT_SHADER);
    fake_shader(3, GL_VERTEX_SHADER);
    glShaderSource(1, 2, parts, lens);
    glShaderSource(2, 2, parts, lens);
    const char *plain[1] = {"#version 300 es\nprecision mediump float;\nin vec4 p;\nvoid main() { mediump float x = 1.0; gl_Position = p * x; }\n"};
    glShaderSource(3, 1, plain, NULL);
    int count = 0;
    const char *vs = fake_source(1, &count);
    if (on) {
        CHECK(count == 1, "the fixed source is one string (%d)", count);
        CHECK(strstr(vs, "precision highp float;\n"), "default precision raised: %s", vs);
        CHECK(strstr(vs, "    highp vec4 p = data[inBoneIndices.x] * uScale;"), "calculation raised: %s", vs);
        CHECK(strstr(vs, "    highp float d = p.x - p.y; // mediump_not_a_word stays"), "whole words only: %s", vs);
        CHECK(strstr(vs, "in mediump vec4 inPosition;"), "inputs keep their precision: %s", vs);
        CHECK(strstr(vs, "out mediump vec4 vColor;"), "outputs keep theirs: %s", vs);
        CHECK(strstr(vs, "uniform InstanceData { mediump vec4 data[64]; };"), "uniform blocks keep theirs: %s", vs);
        CHECK(strstr(vs, "uniform mediump float uScale;"), "uniforms keep theirs: %s", vs);
    } else {
        CHECK(count == 2 && strstr(vs, "precision mediump float;"), "off: unchanged (%d strings)", count);
    }
    CHECK(fake_source(2, &count) && count == 2 && !strstr(fake_source(2, NULL), "highp"), "fragment shader unchanged");
    CHECK(strstr(fake_source(3, NULL), "mediump float x"), "a shader without the markers is unchanged");

    // ---- gl_int_attribs
    const char *names1[2] = {"inPosition", "inBoneIndices"};
    const GLenum types1[2] = {GL_FLOAT_VEC4, GL_UNSIGNED_INT_VEC4};
    const GLint locs1[2] = {0, 3};
    fake_program(1, 1, 2, names1, types1, locs1);
    const char *names2[2] = {"inPosition", "inColor"};
    const GLenum types2[2] = {GL_FLOAT_VEC4, GL_FLOAT_VEC4};
    fake_program(2, 1, 2, names2, types2, locs1);
    glBindVertexArray(1);
    glBindBuffer(GL_ARRAY_BUFFER, 5);
    glVertexAttribPointer(0, 4, GL_FLOAT, GL_FALSE, 16, (void *)0);
    glVertexAttribPointer(3, 4, GL_UNSIGNED_BYTE, GL_TRUE, 16, (void *)8);
    glEnableVertexAttribArray(0);
    glEnableVertexAttribArray(3);
    glBindBuffer(GL_ARRAY_BUFFER, 7);
    glUseProgram(1);
    glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, NULL);
    struct fake_draw *last = fake_last();
    struct attrib *a3 = fake_attrib(1, 3);
    GLint bound = 0;
    glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &bound);
    CHECK(last->draws == 1, "drawn once (%d)", last->draws);
    CHECK(last->integer[3] == on, "integer input fed as integers at the draw: %d", last->integer[3]);
    CHECK(last->integer[0] == 0, "float input unchanged");
    CHECK(a3->buffer == 5 && a3->size == 4 && a3->type == GL_UNSIGNED_BYTE && a3->stride == 16 && a3->ptr == (void *)8,
          "same buffer/size/type/stride/offset (%d %d 0x%x %d %p)", a3->buffer, a3->size, a3->type, a3->stride, a3->ptr);
    CHECK(bound == 7, "the game's GL_ARRAY_BUFFER binding is restored (%d)", bound);
    // a program with a float input at that location gets floats again, with the game's normalization
    glUseProgram(2);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    CHECK(last->integer[3] == 0 && last->normalized[3] == 1, "back to normalized floats: %d %d", last->integer[3],
          last->normalized[3]);
    // eglGetProcAddress draws (BlazeRush looks up glDrawElementsBaseVertex*)
    DEBV bv = (DEBV)eglGetProcAddress("glDrawElementsBaseVertexOES");
    glUseProgram(1);
    CHECK(bv != NULL, "glDrawElementsBaseVertexOES found");
    if (bv) bv(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, NULL, 0);
    CHECK(last->integer[3] == on, "eglGetProcAddress draw converts too: %d", last->integer[3]);
    // a disabled integer input gets the integer default (0, 0, 0, 1)
    glDisableVertexAttribArray(3);
    glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, NULL);
    if (on)
        CHECK(last->i4ui_loc == 3 && last->i4ui[3] == 1 && !last->i4ui[0], "typed default (loc %u)", last->i4ui_loc);
    glEnableVertexAttribArray(3);
    // float vertex data can't be read as integers: left alone
    glBindBuffer(GL_ARRAY_BUFFER, 5);
    glVertexAttribPointer(3, 2, GL_FLOAT, GL_FALSE, 8, (void *)4);
    glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, NULL);
    CHECK(last->integer[3] == 0, "float data stays float");
    // relinked with a float input there (program names are reused): reflected again, nothing converted
    glVertexAttribPointer(3, 4, GL_UNSIGNED_BYTE, GL_FALSE, 16, (void *)8);
    fake_program(1, 1, 2, names2, types2, locs1);
    glLinkProgram(1);
    glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, NULL);
    CHECK(last->integer[3] == 0, "relinked program re-reflected: %d", last->integer[3]);
    // loaded from a program binary with the integer input again
    fake_program(1, 1, 2, names1, types1, locs1);
    glProgramBinary(1, 0, "", 0);
    glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, NULL);
    CHECK(last->integer[3] == on, "program binary re-reflected: %d", last->integer[3]);
    // another (not shared) context with its own program 1 that has float inputs: its own cache entry
    glVertexAttribPointer(3, 4, GL_UNSIGNED_BYTE, GL_FALSE, 16, (void *)8);
    fake_context((void *)0x2000);
    fake_program(1, 1, 2, names2, types2, locs1);
    glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, NULL);
    CHECK(last->integer[3] == 0, "per-context reflection: %d", last->integer[3]);
    fprintf(stderr, "glshim host test (%s): %d failure(s)\n", argv[3], failures);
    return failures ? 1 : 0;
}
