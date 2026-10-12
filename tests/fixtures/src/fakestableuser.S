// Test fixture for patches/frame/ovr_stable_user.py: OVRPort's helper that makes up the logged-in user id
// (same instructions as libovrplatformloader.so in OVRPort runtimes 3.4.3-23204ea and 3.4.3-aa54c3f).
// Build: aarch64-linux-android29-clang -shared -fPIC -nostdlib fakestableuser.S -o ../libfakestableuser_arm64.so
    .text
    .globl random
    .type random, %function
random:
    mov x0, #7
    ret
    .size random, .-random

    .globl fake_user_id
    .type fake_user_id, %function
fake_user_id:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl random
    mov x8, #0xa7640000
    mov x9, #-0x7ffffffffffffffd
    movk x8, #0xb6b3, lsl #32
    movk x9, #1, lsl #32
    movk x8, #0xde0, lsl #48
    mul x8, x0, x8
    smulh x9, x8, x9
    add x8, x9, x8
    asr x9, x8, #30
    add x8, x9, x8, lsr #63
    mov x9, #0xec580000
    movk x9, #0x4835, lsl #32
    movk x9, #0x5344, lsl #48
    add x0, x8, x9
    ldp x29, x30, [sp], #16
    ret
    .size fake_user_id, .-fake_user_id

    .globl ovr_GetLoggedInUserID
    .type ovr_GetLoggedInUserID, %function
ovr_GetLoggedInUserID:
    b fake_user_id
    .size ovr_GetLoggedInUserID, .-ovr_GetLoggedInUserID
