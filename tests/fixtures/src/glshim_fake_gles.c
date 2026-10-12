// Stand-in GLES 3 + EGL for the host test of native/glshim/glshim.c (gl_int_attribs, gl_highp_markers): just enough
// state for programs with active attributes, vertex attribute arrays per vertex array object, buffer bindings and
// draws, plus test hooks (fake_*) to set up programs and read back what the shim did.
#define _GNU_SOURCE
#define GL_GLES_PROTOTYPES 0
#include <EGL/egl.h>
#include <GLES3/gl32.h>
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>

#define API __attribute__((visibility("default")))
#define NOBJ 16
#define NLOC 16

struct attrib { GLint enabled, integer, buffer, size, type, stride, normalized; const void *ptr; };
struct program { int linked, n; char names[4][32]; GLenum types[4]; GLint sizes[4], locs[4]; };
static struct program programs[NOBJ];
static GLenum shader_types[NOBJ];
static char *shader_sources[NOBJ];
static int shader_counts[NOBJ];
static struct attrib vaos[4][NLOC];
static GLuint cur_vao, cur_program, array_buffer;
static void *context = (void *)0x1000;

// hooks for the test
struct fake_draw { int draws; GLint integer[NLOC]; GLint normalized[NLOC]; GLuint i4ui_loc; GLuint i4ui[4]; };
static struct fake_draw last;
API void fake_program(GLuint id, int linked, int n, const char *const *names, const GLenum *types, const GLint *locs) {
    struct program *p = &programs[id];
    memset(p, 0, sizeof(*p));
    p->linked = linked;
    p->n = n;
    for (int i = 0; i < n; ++i) {
        strncpy(p->names[i], names[i], sizeof(p->names[i]) - 1);
        p->types[i] = types[i];
        p->sizes[i] = 1;
        p->locs[i] = locs[i];
    }
}
API void fake_shader(GLuint id, GLenum type) { shader_types[id] = type; }
API const char *fake_source(GLuint id, int *count) { if (count) *count = shader_counts[id]; return shader_sources[id]; }
API struct fake_draw *fake_last(void) { return &last; }
API void fake_context(void *ctx) { context = ctx; }
API struct attrib *fake_attrib(GLuint vao, GLuint loc) { return &vaos[vao][loc]; }

static void draw(void) {
    ++last.draws;
    for (int i = 0; i < NLOC; ++i) {
        last.integer[i] = vaos[cur_vao][i].integer;
        last.normalized[i] = vaos[cur_vao][i].normalized;
    }
}

API const GLubyte *glGetString(GLenum name) { return (const GLubyte *)(name == GL_EXTENSIONS ? "GL_EXT_a GL_EXT_b" : "fake"); }
API const GLubyte *glGetStringi(GLenum name, GLuint i) { (void)name; return (const GLubyte *)(i ? "GL_EXT_b" : "GL_EXT_a"); }
API void glGetIntegerv(GLenum pname, GLint *v) {
    switch (pname) {
        case GL_CURRENT_PROGRAM: *v = (GLint)cur_program; break;
        case GL_ARRAY_BUFFER_BINDING: *v = (GLint)array_buffer; break;
        case GL_VERTEX_ARRAY_BINDING: *v = (GLint)cur_vao; break;
        case GL_NUM_EXTENSIONS: *v = 2; break;
        default: *v = 0;
    }
}
API void glShaderSource(GLuint sh, GLsizei count, const GLchar *const *strs, const GLint *lens) {
    size_t total = 0;
    for (GLsizei i = 0; i < count; ++i) total += lens && lens[i] >= 0 ? (size_t)lens[i] : strlen(strs[i]);
    free(shader_sources[sh]);
    char *s = shader_sources[sh] = calloc(total + 1, 1);
    for (GLsizei i = 0; i < count; ++i) {
        size_t n = lens && lens[i] >= 0 ? (size_t)lens[i] : strlen(strs[i]);
        memcpy(s, strs[i], n);
        s += n;
    }
    shader_counts[sh] = count;
}
API void glGetShaderiv(GLuint sh, GLenum pname, GLint *v) { *v = pname == GL_SHADER_TYPE ? (GLint)shader_types[sh] : 1; }
API void glLinkProgram(GLuint p) { programs[p].linked = 1; }
API void glProgramBinary(GLuint p, GLenum f, const void *b, GLsizei n) { (void)f; (void)b; (void)n; programs[p].linked = 1; }
API void glDeleteProgram(GLuint p) { memset(&programs[p], 0, sizeof(programs[p])); }
API void glUseProgram(GLuint p) { cur_program = p; }
API void glGetProgramiv(GLuint p, GLenum pname, GLint *v) {
    *v = pname == GL_LINK_STATUS ? programs[p].linked : pname == GL_ACTIVE_ATTRIBUTES ? programs[p].n : 0;
}
API void glGetActiveAttrib(GLuint p, GLuint i, GLsizei cap, GLsizei *len, GLint *size, GLenum *type, GLchar *name) {
    strncpy(name, programs[p].names[i], (size_t)cap - 1);
    if (len) *len = (GLsizei)strlen(name);
    *size = programs[p].sizes[i];
    *type = programs[p].types[i];
}
API GLint glGetAttribLocation(GLuint p, const GLchar *name) {
    for (int i = 0; i < programs[p].n; ++i)
        if (!strcmp(programs[p].names[i], name)) return programs[p].locs[i];
    return -1;
}
API void glBindVertexArray(GLuint v) { cur_vao = v; }
API void glBindBuffer(GLenum target, GLuint b) { if (target == GL_ARRAY_BUFFER) array_buffer = b; }
API void glEnableVertexAttribArray(GLuint l) { vaos[cur_vao][l].enabled = 1; }
API void glDisableVertexAttribArray(GLuint l) { vaos[cur_vao][l].enabled = 0; }
static void set(GLuint l, GLint size, GLenum type, GLboolean norm, GLsizei stride, const void *ptr, int integer) {
    struct attrib *a = &vaos[cur_vao][l];
    a->buffer = (GLint)array_buffer;
    a->size = size;
    a->type = (GLint)type;
    a->normalized = norm;
    a->stride = stride;
    a->ptr = ptr;
    a->integer = integer;
}
API void glVertexAttribPointer(GLuint l, GLint size, GLenum type, GLboolean norm, GLsizei stride, const void *ptr) {
    set(l, size, type, norm, stride, ptr, 0);
}
API void glVertexAttribIPointer(GLuint l, GLint size, GLenum type, GLsizei stride, const void *ptr) {
    set(l, size, type, GL_FALSE, stride, ptr, 1);
}
API void glVertexAttribI4i(GLuint l, GLint x, GLint y, GLint z, GLint w) {
    last.i4ui_loc = l + 100;  // signed: marked with +100
    last.i4ui[0] = (GLuint)x, last.i4ui[1] = (GLuint)y, last.i4ui[2] = (GLuint)z, last.i4ui[3] = (GLuint)w;
}
API void glVertexAttribI4ui(GLuint l, GLuint x, GLuint y, GLuint z, GLuint w) {
    last.i4ui_loc = l;
    last.i4ui[0] = x, last.i4ui[1] = y, last.i4ui[2] = z, last.i4ui[3] = w;
}
API void glGetVertexAttribiv(GLuint l, GLenum pname, GLint *v) {
    struct attrib *a = &vaos[cur_vao][l];
    switch (pname) {
        case GL_VERTEX_ATTRIB_ARRAY_ENABLED: *v = a->enabled; break;
        case GL_VERTEX_ATTRIB_ARRAY_INTEGER: *v = a->integer; break;
        case GL_VERTEX_ATTRIB_ARRAY_BUFFER_BINDING: *v = a->buffer; break;
        case GL_VERTEX_ATTRIB_ARRAY_SIZE: *v = a->size; break;
        case GL_VERTEX_ATTRIB_ARRAY_TYPE: *v = a->type; break;
        case GL_VERTEX_ATTRIB_ARRAY_STRIDE: *v = a->stride; break;
        case GL_VERTEX_ATTRIB_ARRAY_NORMALIZED: *v = a->normalized; break;
        default: *v = 0;
    }
}
API void glGetVertexAttribPointerv(GLuint l, GLenum pname, void **v) { (void)pname; *v = (void *)vaos[cur_vao][l].ptr; }
API void glDrawArrays(GLenum m, GLint f, GLsizei c) { (void)m; (void)f; (void)c; draw(); }
API void glDrawElements(GLenum m, GLsizei c, GLenum t, const void *i) { (void)m; (void)c; (void)t; (void)i; draw(); }
API void glDrawArraysInstanced(GLenum m, GLint f, GLsizei c, GLsizei n) { (void)m; (void)f; (void)c; (void)n; draw(); }
API void glDrawElementsInstanced(GLenum m, GLsizei c, GLenum t, const void *i, GLsizei n) {
    (void)m; (void)c; (void)t; (void)i; (void)n; draw();
}
API void glDrawRangeElements(GLenum m, GLuint s, GLuint e, GLsizei c, GLenum t, const void *i) {
    (void)m; (void)s; (void)e; (void)c; (void)t; (void)i; draw();
}
API void glDrawElementsBaseVertexOES(GLenum m, GLsizei c, GLenum t, const void *i, GLint b) {
    (void)m; (void)c; (void)t; (void)i; (void)b; draw();
}
API EGLContext eglGetCurrentContext(void) { return context; }
API __eglMustCastToProperFunctionPointerType eglGetProcAddress(const char *name) {
    Dl_info info;
    if (!dladdr((void *)eglGetProcAddress, &info)) return NULL;
    void *self = dlopen(info.dli_fname, RTLD_NOW | RTLD_NOLOAD);
    __eglMustCastToProperFunctionPointerType fn = self ? (__eglMustCastToProperFunctionPointerType)dlsym(self, name) : NULL;
    if (self) dlclose(self);
    return fn;
}
