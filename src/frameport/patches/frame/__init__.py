"""Steam Frame fixes applied to the OVRPort output (stage "apk"). One module per fix; each registers itself."""
from __future__ import annotations

from ...core.paths import artifacts_dir
def artifact(abi: str, name: str) -> bytes:
    path = artifacts_dir() / abi / name
    if not path.exists():
        raise FileNotFoundError(f"missing prebuilt artifact {abi}/{name} (see native/README.md)")
    return path.read_bytes()


from . import (
    adapter,
    avatar_stub,
    gl_multiview_fbo,
    haptic_envelope,
    hw_video_decode,
    langpack,
    ltw_depth,
    manifest_fixes,
    meta_depth_occlusion,
    ovr_microphone,
    ovr_trace,
    pac_hints,
    platform_libs,
    sdl_clipboard,
    slz_vulkan_hooks,
    swapchain_limit,
    tbxr_vendor,
    telemetry,
    unity_no_msaa,
    unity_oculus_check,
    unity_runtime,
    unity_text_input,
    unity_user_presence,
    unreal_ovrp,
    unreal_santacruz,
    unreal_thumb_touch,
    vivox_audio_route,
    vk_sanitize,
    vrapi_bridge,
    vrapi_stub,
    zink_shader_fix,
)


