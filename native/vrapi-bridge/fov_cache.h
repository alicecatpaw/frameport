// SPDX-License-Identifier: GPL-3.0-only
// FramePort: the VrApi FOV properties (7/8) before tracking starts.
//
// VrApi games may read the FOV right after vrapi_Initialize and cache it (BlazeRush builds its projection and its
// TexCoordsFromTanAngles matrix from it once). OpenXR has no FOV before a session exists unless the runtime offers
// XR_EPIC_view_configuration_fov, which the Steam Frame's doesn't, so the bridge answered 90 x 90 degrees and those
// games kept a narrow, square view. The bridge now saves the live FOV of each session (it is a property of the
// headset, not of the game's state) in the app's external files folder and answers with it the next time the
// properties are asked for before a session has located its views. The headset's FOV is never hardcoded: the first
// session on a Frame still starts at 90 degrees (FramePort's launch test after an install is that session).
// Plain functions, no Android or OpenXR types: tests/test_blazerush.py builds them for the host.
#pragma once
#include <cmath>
#include <cstdio>
#include <cstring>

namespace ovp {
namespace fovcache {
constexpr const char* FileName = "framebridge-vrapi-fov.txt";
// symmetric coverage angles a VR headset can have (the Frame reports about 118 x 120)
inline bool plausible(float horizontal, float vertical) {
    return std::isfinite(horizontal) && std::isfinite(vertical) && horizontal >= 60.0f && horizontal <= 170.0f &&
           vertical >= 60.0f && vertical <= 170.0f;
}
// "fov_h=118.14\nfov_v=119.55\n" (other lines ignored); false unless both are there and plausible
inline bool parse(const char* text, float out[2]) {
    float h = NAN, v = NAN;
    for (const char* line = text; line && *line; line = std::strchr(line, '\n'), line = line ? line + 1 : nullptr) {
        float value = 0;
        if (std::sscanf(line, "fov_h=%f", &value) == 1) h = value;
        else if (std::sscanf(line, "fov_v=%f", &value) == 1) v = value;
    }
    if (!plausible(h, v)) return false;
    out[0] = h;
    out[1] = v;
    return true;
}
inline int format(char* buffer, size_t size, const float fov[2]) {
    return std::snprintf(buffer, size, "fov_h=%.3f\nfov_v=%.3f\n", fov[0], fov[1]);
}
// worth rewriting the saved value: none saved yet, or a change of more than 0.01 degrees on an axis
inline bool changed(bool haveSaved, const float saved[2], const float now[2]) {
    return !haveSaved || std::fabs(saved[0] - now[0]) > 0.01f || std::fabs(saved[1] - now[1]) > 0.01f;
}
// the external files folder's file for the package in /proc/self/cmdline ("pkg" or "pkg:process"); false if unknown
inline bool path(const char* cmdline, char* buffer, size_t size) {
    char package[256] = {0};
    std::strncpy(package, cmdline ? cmdline : "", sizeof(package) - 1);
    if (char* colon = std::strchr(package, ':')) *colon = 0;
    if (!*package || std::strchr(package, '/') || std::strstr(package, "..")) return false;
    const int n = std::snprintf(buffer, size, "/sdcard/Android/data/%s/files/%s", package, FileName);
    return n > 0 && static_cast<size_t>(n) < size;
}
}  // namespace fovcache
}  // namespace ovp
