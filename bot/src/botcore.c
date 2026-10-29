/*
 * botcore for RF Online (client build 2010-03-10, "RF_Online.bin", 4GB patched).
 *
 * This is HPBars with ALL cosmetics removed. No HP bars, no level labels, no ground markers,
 * no hiding of the game's own overhead windows, no Direct3D drawing. What remains is the bot core:
 *   - bot state export to named shared memory (own character, target, monsters / animus / players /
 *     npcs with world positions, effects on you, belt with cooldowns, ground items),
 *   - commands the bot sends that run on the game thread (select / clear target via CTargetMgr::
 *     CheckTarget, walk via MoveRequest, use a belt slot via CLinkBoard::UseSlot, press a key,
 *     summon / select animus, loot), 
 *   - the combat packet read (_attack_monster_inform_zocl) so the bot knows who attacks you / your animus.
 *
 * The DLL is loaded by an external MANUAL MAPPER (see tools/manualmap.py), NOT by LoadLibrary, and the
 * mapper then unlinks it from the PEB loader lists -> it does not show up in Module32 / EnumProcessModules.
 * Because of that DllMain must find its own folder from the path the mapper passes in `reserved`
 * (GetModuleFileNameA does not work for an unlinked module).
 *
 * Hooks (vtable slots only, no code patching), 3 slots instead of the old 5:
 *   CAvatar  vtbl+0x84  -> per-frame bot export + command execution (the single game-thread entry)
 *   CNetMsgProcessor_Combat vtbl+0x04 -> read _attack_monster_inform_zocl (who attacks whom)
 * (CMonster+0x24 and the two CGUIWindow+0x04 SetPos slots are NOT hooked anymore: the bars/labels
 *  and the overhead-window hiding are gone, and so is their drawing code; only the signatures of the
 *  functions the export calls gate the start.)
 *
 * Robustness (BOT_VERSION 10):
 *   - a fault in the export pauses it and retries after 10 s, 20 s, ... up to 60 s (it used to stay off
 *     until a game restart); the animus list is retried up to 3 times;
 *   - a held key is released and every hook must be restored before the injector may free the module
 *     (status.ejectWanted); a hook another mod chained after keeps the module mapped;
 *   - BOT_CMD_LOOT finds the item processor by its class (RTTI) among all processors (it is not processors[7],
 *     that one is CNetMsgProcessor_Map) and checks that the drop is still on the ground;
 *   - commands older than BOT_CMD_STALE_MS (1 s) are dropped: the bot waits 1.2 s for an answer, so a
 *     command it gave up on never runs late.
 */

#include "win32_min.h"

/* ============================== CRT replacements =============================== */

int _fltused = 1;

void *memset(void *dst, int value, unsigned int size)
{
    volatile unsigned char *p = (volatile unsigned char *)dst;
    while (size--) *p++ = (unsigned char)value;
    return dst;
}

void *memcpy(void *dst, const void *src, unsigned int size)
{
    volatile unsigned char *d = (volatile unsigned char *)dst;
    const unsigned char *s = (const unsigned char *)src;
    while (size--) *d++ = *s++;
    return dst;
}

/* ============================= String masking (anti-scan) ======================= */
#define MASK 0x5Au
static char *DecodeS(const unsigned char *src, int n, char *dst)
{
    volatile const unsigned char *v = src;   /* volatile: stop clang from constant-folding the table back to plain */
    int i;
    for (i = 0; i + 1 < n; i++) dst[i] = (char)(v[i] ^ MASK);
    dst[n - 1] = 0;
    return dst;
}
#define MS(name) DecodeS((name), (int)sizeof(name), (char[400]){0})
#define MASKSTR(dst, name) do { const volatile unsigned char *_s = (name); int _i; for (_i = 0; _i + 1 < (int)sizeof(name); _i++) (dst)[_i] = (char)(_s[_i] ^ MASK); (dst)[sizeof(name) - 1] = 0; } while (0)

/* Obfuscated string table (XOR 0x5A). Decode with MS() when used. */
static const unsigned char S_00[] = { 0x18, 0x35, 0x2E, 0x19, 0x35, 0x28, 0x3F, 0x74, 0x33, 0x34, 0x33, 0x00 };
static const unsigned char S_01[] = { 0x18, 0x35, 0x2E, 0x19, 0x35, 0x28, 0x3F, 0x74, 0x36, 0x35, 0x3D, 0x00 };
static const unsigned char S_02[] = { 0x16, 0x35, 0x39, 0x3B, 0x36, 0x08, 0x1C, 0x18, 0x35, 0x2E, 0x09, 0x2E, 0x3B, 0x2E, 0x3F, 0x00 };
static const unsigned char S_03[] = { 0x61, 0x7A, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x57, 0x50, 0x61, 0x7A, 0x7A, 0x18, 0x35, 0x2E, 0x19, 0x35, 0x28, 0x3F, 0x7A, 0x3C, 0x35, 0x28, 0x7A, 0x08, 0x1C, 0x7A, 0x15, 0x34, 0x36, 0x33, 0x34, 0x3F, 0x7A, 0x77, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x29, 0x2E, 0x3B, 0x2E, 0x3F, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x7A, 0x71, 0x7A, 0x39, 0x35, 0x37, 0x37, 0x3B, 0x34, 0x3E, 0x29, 0x7A, 0x3C, 0x35, 0x28, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x35, 0x2E, 0x7A, 0x72, 0x34, 0x35, 0x7A, 0x39, 0x35, 0x29, 0x37, 0x3F, 0x2E, 0x33, 0x39, 0x29, 0x73, 0x57, 0x50, 0x61, 0x7A, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x57, 0x50, 0x57, 0x50, 0x01, 0x12, 0x0A, 0x18, 0x3B, 0x28, 0x29, 0x07, 0x57, 0x50, 0x61, 0x7A, 0x11, 0x3F, 0x2A, 0x2E, 0x7A, 0x3C, 0x35, 0x28, 0x7A, 0x39, 0x35, 0x37, 0x2A, 0x3B, 0x2E, 0x33, 0x38, 0x33, 0x36, 0x33, 0x2E, 0x23, 0x74, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x3F, 0x34, 0x3B, 0x38, 0x36, 0x3F, 0x3E, 0x76, 0x7A, 0x6A, 0x7A, 0x67, 0x7A, 0x3E, 0x33, 0x29, 0x3B, 0x38, 0x36, 0x3F, 0x3E, 0x57, 0x50, 0x1F, 0x34, 0x3B, 0x38, 0x36, 0x3F, 0x3E, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x18, 0x3B, 0x28, 0x7A, 0x29, 0x33, 0x20, 0x3F, 0x7A, 0x33, 0x34, 0x7A, 0x2A, 0x33, 0x22, 0x3F, 0x36, 0x29, 0x57, 0x50, 0x0D, 0x33, 0x3E, 0x2E, 0x32, 0x67, 0x6F, 0x6A, 0x57, 0x50, 0x12, 0x3F, 0x33, 0x3D, 0x32, 0x2E, 0x67, 0x6F, 0x57, 0x50, 0x61, 0x7A, 0x0C, 0x3F, 0x28, 0x2E, 0x33, 0x39, 0x3B, 0x36, 0x7A, 0x35, 0x3C, 0x3C, 0x29, 0x3F, 0x2E, 0x7A, 0x35, 0x3C, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x7A, 0x2E, 0x35, 0x2A, 0x7A, 0x3C, 0x28, 0x35, 0x37, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x7A, 0x32, 0x3F, 0x3B, 0x3E, 0x7A, 0x2A, 0x35, 0x33, 0x34, 0x2E, 0x7A, 0x72, 0x34, 0x3F, 0x3D, 0x3B, 0x2E, 0x33, 0x2C, 0x3F, 0x7A, 0x67, 0x7A, 0x32, 0x33, 0x3D, 0x32, 0x3F, 0x28, 0x73, 0x57, 0x50, 0x15, 0x3C, 0x3C, 0x29, 0x3F, 0x2E, 0x03, 0x67, 0x77, 0x6D, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x3E, 0x28, 0x3B, 0x2D, 0x7A, 0x3B, 0x7A, 0x6B, 0x2A, 0x22, 0x7A, 0x38, 0x35, 0x28, 0x3E, 0x3F, 0x28, 0x7A, 0x3B, 0x28, 0x35, 0x2F, 0x34, 0x3E, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x57, 0x50, 0x18, 0x35, 0x28, 0x3E, 0x3F, 0x28, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x18, 0x3B, 0x28, 0x7A, 0x35, 0x2A, 0x3B, 0x39, 0x33, 0x2E, 0x23, 0x7A, 0x6A, 0x74, 0x74, 0x68, 0x6F, 0x6F, 0x57, 0x50, 0x15, 0x2A, 0x3B, 0x39, 0x33, 0x2E, 0x23, 0x67, 0x68, 0x68, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x39, 0x35, 0x36, 0x35, 0x28, 0x7A, 0x38, 0x23, 0x7A, 0x12, 0x0A, 0x7A, 0x72, 0x3D, 0x28, 0x3F, 0x3F, 0x34, 0x7A, 0x77, 0x64, 0x7A, 0x23, 0x3F, 0x36, 0x36, 0x35, 0x2D, 0x7A, 0x77, 0x64, 0x7A, 0x28, 0x3F, 0x3E, 0x73, 0x76, 0x7A, 0x6A, 0x7A, 0x67, 0x7A, 0x3B, 0x36, 0x2D, 0x3B, 0x23, 0x29, 0x7A, 0x1C, 0x33, 0x36, 0x36, 0x19, 0x35, 0x36, 0x35, 0x28, 0x57, 0x50, 0x19, 0x35, 0x36, 0x35, 0x28, 0x17, 0x35, 0x3E, 0x3F, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x19, 0x35, 0x36, 0x35, 0x28, 0x29, 0x7A, 0x33, 0x34, 0x7A, 0x32, 0x3F, 0x22, 0x7A, 0x08, 0x1D, 0x18, 0x57, 0x50, 0x1C, 0x33, 0x36, 0x36, 0x19, 0x35, 0x36, 0x35, 0x28, 0x67, 0x6A, 0x22, 0x1E, 0x6A, 0x68, 0x6A, 0x68, 0x6A, 0x57, 0x50, 0x18, 0x3B, 0x39, 0x31, 0x19, 0x35, 0x36, 0x35, 0x28, 0x67, 0x6A, 0x22, 0x68, 0x6A, 0x68, 0x6A, 0x68, 0x6A, 0x57, 0x50, 0x18, 0x35, 0x28, 0x3E, 0x3F, 0x28, 0x19, 0x35, 0x36, 0x35, 0x28, 0x67, 0x6A, 0x22, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x32, 0x33, 0x3E, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x7A, 0x3B, 0x34, 0x3E, 0x7A, 0x36, 0x3B, 0x38, 0x3F, 0x36, 0x7A, 0x2D, 0x32, 0x33, 0x36, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x7A, 0x32, 0x3B, 0x29, 0x7A, 0x3C, 0x2F, 0x36, 0x36, 0x7A, 0x12, 0x0A, 0x57, 0x50, 0x12, 0x33, 0x3E, 0x3F, 0x1C, 0x2F, 0x36, 0x36, 0x12, 0x0A, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x34, 0x35, 0x2E, 0x32, 0x33, 0x34, 0x3D, 0x7A, 0x3C, 0x35, 0x28, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x39, 0x2F, 0x28, 0x28, 0x3F, 0x34, 0x2E, 0x7A, 0x2E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x76, 0x7A, 0x6A, 0x7A, 0x67, 0x7A, 0x38, 0x3B, 0x28, 0x75, 0x36, 0x3B, 0x38, 0x3F, 0x36, 0x75, 0x39, 0x33, 0x28, 0x39, 0x36, 0x3F, 0x7A, 0x3B, 0x36, 0x29, 0x35, 0x7A, 0x35, 0x34, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x2E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x57, 0x50, 0x09, 0x31, 0x33, 0x2A, 0x0E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x3B, 0x36, 0x29, 0x35, 0x7A, 0x3E, 0x28, 0x3B, 0x2D, 0x7A, 0x3C, 0x35, 0x28, 0x7A, 0x3E, 0x3F, 0x3B, 0x3E, 0x7A, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x29, 0x7A, 0x72, 0x12, 0x0A, 0x7A, 0x6A, 0x73, 0x57, 0x50, 0x09, 0x32, 0x35, 0x2D, 0x1E, 0x3F, 0x3B, 0x3E, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x17, 0x3B, 0x22, 0x7A, 0x3E, 0x33, 0x29, 0x2E, 0x3B, 0x34, 0x39, 0x3F, 0x7A, 0x3C, 0x28, 0x35, 0x37, 0x7A, 0x23, 0x35, 0x2F, 0x28, 0x7A, 0x39, 0x32, 0x3B, 0x28, 0x3B, 0x39, 0x2E, 0x3F, 0x28, 0x7A, 0x33, 0x34, 0x7A, 0x2D, 0x35, 0x28, 0x36, 0x3E, 0x7A, 0x2F, 0x34, 0x33, 0x2E, 0x29, 0x76, 0x7A, 0x6A, 0x7A, 0x67, 0x7A, 0x2F, 0x34, 0x36, 0x33, 0x37, 0x33, 0x2E, 0x3F, 0x3E, 0x57, 0x50, 0x17, 0x3B, 0x22, 0x1E, 0x33, 0x29, 0x2E, 0x3B, 0x34, 0x39, 0x3F, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x3E, 0x28, 0x3B, 0x2D, 0x7A, 0x12, 0x0A, 0x7A, 0x2A, 0x3F, 0x28, 0x39, 0x3F, 0x34, 0x2E, 0x7A, 0x2E, 0x3F, 0x22, 0x2E, 0x7A, 0x2E, 0x35, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x28, 0x33, 0x3D, 0x32, 0x2E, 0x7A, 0x35, 0x3C, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x57, 0x50, 0x09, 0x32, 0x35, 0x2D, 0x0A, 0x3F, 0x28, 0x39, 0x3F, 0x34, 0x2E, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x16, 0x3B, 0x38, 0x3F, 0x36, 0x7A, 0x3B, 0x38, 0x35, 0x2C, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x60, 0x7A, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x7A, 0x34, 0x3B, 0x37, 0x3F, 0x7A, 0x3B, 0x34, 0x3E, 0x75, 0x35, 0x28, 0x7A, 0x36, 0x3F, 0x2C, 0x3F, 0x36, 0x57, 0x50, 0x09, 0x32, 0x35, 0x2D, 0x14, 0x3B, 0x37, 0x3F, 0x67, 0x6B, 0x57, 0x50, 0x09, 0x32, 0x35, 0x2D, 0x16, 0x3F, 0x2C, 0x3F, 0x36, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x16, 0x3B, 0x38, 0x3F, 0x36, 0x7A, 0x39, 0x35, 0x36, 0x35, 0x28, 0x7A, 0x33, 0x34, 0x7A, 0x32, 0x3F, 0x22, 0x7A, 0x08, 0x1D, 0x18, 0x7A, 0x72, 0x2D, 0x32, 0x33, 0x2E, 0x3F, 0x73, 0x76, 0x7A, 0x16, 0x3B, 0x38, 0x3F, 0x36, 0x18, 0x3B, 0x28, 0x19, 0x35, 0x36, 0x35, 0x28, 0x67, 0x6B, 0x7A, 0x67, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x39, 0x35, 0x36, 0x35, 0x28, 0x7A, 0x35, 0x3C, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x7A, 0x33, 0x34, 0x29, 0x2E, 0x3F, 0x3B, 0x3E, 0x57, 0x50, 0x16, 0x3B, 0x38, 0x3F, 0x36, 0x19, 0x35, 0x36, 0x35, 0x28, 0x67, 0x6A, 0x22, 0x1C, 0x1C, 0x1C, 0x1C, 0x1C, 0x1C, 0x57, 0x50, 0x16, 0x3B, 0x38, 0x3F, 0x36, 0x18, 0x3B, 0x28, 0x19, 0x35, 0x36, 0x35, 0x28, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x6A, 0x7A, 0x67, 0x7A, 0x78, 0x14, 0x3B, 0x37, 0x3F, 0x7A, 0x16, 0x2C, 0x74, 0x14, 0x78, 0x76, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x78, 0x16, 0x2C, 0x74, 0x14, 0x7A, 0x14, 0x3B, 0x37, 0x3F, 0x78, 0x76, 0x7A, 0x68, 0x7A, 0x67, 0x7A, 0x78, 0x01, 0x14, 0x07, 0x7A, 0x14, 0x3B, 0x37, 0x3F, 0x78, 0x57, 0x50, 0x16, 0x3B, 0x38, 0x3F, 0x36, 0x09, 0x2E, 0x23, 0x36, 0x3F, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x0A, 0x33, 0x22, 0x3F, 0x36, 0x29, 0x7A, 0x38, 0x3F, 0x2E, 0x2D, 0x3F, 0x3F, 0x34, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x36, 0x3B, 0x38, 0x3F, 0x36, 0x7A, 0x3B, 0x34, 0x3E, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x57, 0x50, 0x16, 0x3B, 0x38, 0x3F, 0x36, 0x1D, 0x3B, 0x2A, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x32, 0x33, 0x3E, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7D, 0x29, 0x7A, 0x35, 0x2D, 0x34, 0x7A, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x7A, 0x34, 0x3B, 0x37, 0x3F, 0x7A, 0x72, 0x29, 0x32, 0x35, 0x2D, 0x34, 0x7A, 0x35, 0x34, 0x7A, 0x37, 0x35, 0x2F, 0x29, 0x3F, 0x77, 0x35, 0x2C, 0x3F, 0x28, 0x73, 0x7A, 0x2E, 0x35, 0x7A, 0x3B, 0x2C, 0x35, 0x33, 0x3E, 0x7A, 0x3B, 0x7A, 0x3E, 0x35, 0x2F, 0x38, 0x36, 0x3F, 0x7A, 0x34, 0x3B, 0x37, 0x3F, 0x57, 0x50, 0x08, 0x3F, 0x2A, 0x36, 0x3B, 0x39, 0x3F, 0x1D, 0x3B, 0x37, 0x3F, 0x14, 0x3B, 0x37, 0x3F, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x31, 0x3F, 0x3F, 0x2A, 0x7A, 0x38, 0x3B, 0x28, 0x75, 0x39, 0x33, 0x28, 0x39, 0x36, 0x3F, 0x7A, 0x2D, 0x32, 0x3F, 0x34, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x32, 0x33, 0x3E, 0x3F, 0x29, 0x7A, 0x35, 0x2C, 0x3F, 0x28, 0x32, 0x3F, 0x3B, 0x3E, 0x7A, 0x33, 0x34, 0x3C, 0x35, 0x7A, 0x72, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x7A, 0x38, 0x3F, 0x32, 0x33, 0x34, 0x3E, 0x7A, 0x23, 0x35, 0x2F, 0x76, 0x7A, 0x23, 0x35, 0x2F, 0x28, 0x7A, 0x2A, 0x3F, 0x2E, 0x7A, 0x35, 0x28, 0x7A, 0x29, 0x2A, 0x3F, 0x36, 0x36, 0x7A, 0x3F, 0x3C, 0x3C, 0x3F, 0x39, 0x2E, 0x29, 0x73, 0x57, 0x50, 0x13, 0x3D, 0x34, 0x35, 0x28, 0x3F, 0x15, 0x39, 0x39, 0x36, 0x2F, 0x29, 0x33, 0x35, 0x34, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x32, 0x33, 0x3E, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7D, 0x29, 0x7A, 0x35, 0x2D, 0x34, 0x7A, 0x34, 0x3B, 0x37, 0x3F, 0x7A, 0x71, 0x7A, 0x38, 0x3B, 0x28, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x3B, 0x38, 0x35, 0x2C, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x39, 0x2F, 0x28, 0x28, 0x3F, 0x34, 0x2E, 0x7A, 0x2E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x7A, 0x72, 0x2E, 0x32, 0x3F, 0x7A, 0x2E, 0x35, 0x2A, 0x77, 0x35, 0x3C, 0x77, 0x29, 0x39, 0x28, 0x3F, 0x3F, 0x34, 0x7A, 0x2E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x29, 0x2E, 0x3B, 0x23, 0x29, 0x73, 0x57, 0x50, 0x12, 0x33, 0x3E, 0x3F, 0x0E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x0D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x32, 0x33, 0x3E, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x12, 0x0A, 0x75, 0x1C, 0x0A, 0x75, 0x09, 0x0A, 0x7A, 0x38, 0x3B, 0x28, 0x29, 0x7A, 0x3B, 0x34, 0x3E, 0x7A, 0x33, 0x39, 0x35, 0x34, 0x7A, 0x3B, 0x38, 0x35, 0x2C, 0x3F, 0x7A, 0x23, 0x35, 0x2F, 0x28, 0x7A, 0x35, 0x2D, 0x34, 0x7A, 0x39, 0x32, 0x3B, 0x28, 0x3B, 0x39, 0x2E, 0x3F, 0x28, 0x7A, 0x72, 0x23, 0x35, 0x2F, 0x28, 0x7A, 0x34, 0x3B, 0x37, 0x3F, 0x7A, 0x29, 0x2E, 0x3B, 0x23, 0x29, 0x73, 0x57, 0x50, 0x12, 0x33, 0x3E, 0x3F, 0x15, 0x2D, 0x34, 0x18, 0x3B, 0x28, 0x29, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x1C, 0x33, 0x36, 0x36, 0x3F, 0x3E, 0x7A, 0x39, 0x33, 0x28, 0x39, 0x36, 0x3F, 0x7A, 0x28, 0x33, 0x3D, 0x32, 0x2E, 0x7A, 0x2F, 0x34, 0x3E, 0x3F, 0x28, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x37, 0x33, 0x3E, 0x3E, 0x36, 0x3F, 0x7A, 0x35, 0x3C, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x7A, 0x72, 0x6B, 0x7A, 0x67, 0x7A, 0x35, 0x34, 0x73, 0x57, 0x50, 0x1E, 0x35, 0x2E, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x19, 0x33, 0x28, 0x39, 0x36, 0x3F, 0x7A, 0x28, 0x3B, 0x3E, 0x33, 0x2F, 0x29, 0x7A, 0x3B, 0x34, 0x3E, 0x7A, 0x3D, 0x3B, 0x2A, 0x7A, 0x38, 0x3F, 0x36, 0x35, 0x2D, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3B, 0x28, 0x76, 0x7A, 0x33, 0x34, 0x7A, 0x2A, 0x33, 0x22, 0x3F, 0x36, 0x29, 0x57, 0x50, 0x1E, 0x35, 0x2E, 0x08, 0x3B, 0x3E, 0x33, 0x2F, 0x29, 0x67, 0x6B, 0x6A, 0x57, 0x50, 0x1E, 0x35, 0x2E, 0x1D, 0x3B, 0x2A, 0x67, 0x68, 0x57, 0x50, 0x61, 0x7A, 0x19, 0x33, 0x28, 0x39, 0x36, 0x3F, 0x7A, 0x39, 0x35, 0x36, 0x35, 0x28, 0x7A, 0x33, 0x34, 0x7A, 0x32, 0x3F, 0x22, 0x7A, 0x08, 0x1D, 0x18, 0x7A, 0x72, 0x28, 0x3F, 0x3E, 0x73, 0x7A, 0x3B, 0x34, 0x3E, 0x7A, 0x35, 0x2A, 0x3B, 0x39, 0x33, 0x2E, 0x23, 0x7A, 0x6A, 0x74, 0x74, 0x68, 0x6F, 0x6F, 0x57, 0x50, 0x1E, 0x35, 0x2E, 0x19, 0x35, 0x36, 0x35, 0x28, 0x67, 0x6A, 0x22, 0x1C, 0x1C, 0x6A, 0x6A, 0x6A, 0x6A, 0x57, 0x50, 0x1E, 0x35, 0x2E, 0x15, 0x2A, 0x3B, 0x39, 0x33, 0x2E, 0x23, 0x67, 0x68, 0x6F, 0x6F, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x6B, 0x2A, 0x22, 0x7A, 0x3E, 0x3B, 0x28, 0x31, 0x7A, 0x35, 0x2F, 0x2E, 0x36, 0x33, 0x34, 0x3F, 0x7A, 0x3B, 0x28, 0x35, 0x2F, 0x34, 0x3E, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x39, 0x33, 0x28, 0x39, 0x36, 0x3F, 0x57, 0x50, 0x1E, 0x35, 0x2E, 0x15, 0x2F, 0x2E, 0x36, 0x33, 0x34, 0x3F, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x0E, 0x35, 0x3D, 0x3D, 0x36, 0x3F, 0x7A, 0x32, 0x35, 0x2E, 0x31, 0x3F, 0x23, 0x60, 0x7A, 0x2C, 0x33, 0x28, 0x2E, 0x2F, 0x3B, 0x36, 0x77, 0x31, 0x3F, 0x23, 0x7A, 0x39, 0x35, 0x3E, 0x3F, 0x7A, 0x72, 0x6A, 0x22, 0x6E, 0x62, 0x7A, 0x67, 0x7A, 0x12, 0x73, 0x7A, 0x71, 0x7A, 0x37, 0x35, 0x3E, 0x33, 0x3C, 0x33, 0x3F, 0x28, 0x29, 0x74, 0x7A, 0x0E, 0x35, 0x3D, 0x3D, 0x36, 0x3F, 0x11, 0x3F, 0x23, 0x67, 0x6A, 0x7A, 0x3E, 0x33, 0x29, 0x3B, 0x38, 0x36, 0x3F, 0x29, 0x7A, 0x33, 0x2E, 0x57, 0x50, 0x0E, 0x35, 0x3D, 0x3D, 0x36, 0x3F, 0x11, 0x3F, 0x23, 0x67, 0x6A, 0x22, 0x6E, 0x62, 0x57, 0x50, 0x0E, 0x35, 0x3D, 0x3D, 0x36, 0x3F, 0x19, 0x2E, 0x28, 0x36, 0x67, 0x6B, 0x57, 0x50, 0x0E, 0x35, 0x3D, 0x3D, 0x36, 0x3F, 0x09, 0x32, 0x33, 0x3C, 0x2E, 0x67, 0x6B, 0x57, 0x50, 0x0E, 0x35, 0x3D, 0x3D, 0x36, 0x3F, 0x1B, 0x36, 0x2E, 0x67, 0x6A, 0x57, 0x50, 0x57, 0x50, 0x01, 0x17, 0x3B, 0x28, 0x31, 0x3F, 0x28, 0x29, 0x07, 0x57, 0x50, 0x61, 0x7A, 0x1D, 0x28, 0x35, 0x2F, 0x34, 0x3E, 0x7A, 0x37, 0x3B, 0x28, 0x31, 0x3F, 0x28, 0x29, 0x60, 0x7A, 0x17, 0x3B, 0x28, 0x31, 0x11, 0x3F, 0x23, 0x7A, 0x3E, 0x28, 0x35, 0x2A, 0x29, 0x7A, 0x3B, 0x7A, 0x3E, 0x35, 0x2E, 0x7A, 0x2F, 0x34, 0x3E, 0x3F, 0x28, 0x7A, 0x23, 0x35, 0x2F, 0x28, 0x7A, 0x39, 0x32, 0x3B, 0x28, 0x3B, 0x39, 0x2E, 0x3F, 0x28, 0x76, 0x7A, 0x2A, 0x28, 0x3F, 0x29, 0x29, 0x33, 0x34, 0x3D, 0x7A, 0x33, 0x2E, 0x7A, 0x3B, 0x3D, 0x3B, 0x33, 0x34, 0x7A, 0x34, 0x3F, 0x3B, 0x28, 0x7A, 0x3B, 0x34, 0x57, 0x50, 0x61, 0x7A, 0x3F, 0x22, 0x33, 0x29, 0x2E, 0x33, 0x34, 0x3D, 0x7A, 0x3E, 0x35, 0x2E, 0x7A, 0x28, 0x3F, 0x37, 0x35, 0x2C, 0x3F, 0x29, 0x7A, 0x2E, 0x32, 0x3B, 0x2E, 0x7A, 0x3E, 0x35, 0x2E, 0x74, 0x7A, 0x19, 0x36, 0x3F, 0x3B, 0x28, 0x11, 0x3F, 0x23, 0x7A, 0x28, 0x3F, 0x37, 0x35, 0x2C, 0x3F, 0x29, 0x7A, 0x3B, 0x36, 0x36, 0x7A, 0x3E, 0x35, 0x2E, 0x29, 0x74, 0x7A, 0x1E, 0x35, 0x2E, 0x29, 0x7A, 0x3B, 0x28, 0x3F, 0x7A, 0x31, 0x3F, 0x2A, 0x2E, 0x7A, 0x2F, 0x34, 0x2E, 0x33, 0x36, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x3F, 0x22, 0x33, 0x2E, 0x29, 0x74, 0x57, 0x50, 0x1F, 0x34, 0x3B, 0x38, 0x36, 0x3F, 0x3E, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x1E, 0x35, 0x2E, 0x7A, 0x28, 0x3B, 0x3E, 0x33, 0x2F, 0x29, 0x7A, 0x33, 0x34, 0x7A, 0x2D, 0x35, 0x28, 0x36, 0x3E, 0x7A, 0x2F, 0x34, 0x33, 0x2E, 0x29, 0x76, 0x7A, 0x33, 0x34, 0x7A, 0x2E, 0x3F, 0x34, 0x2E, 0x32, 0x29, 0x7A, 0x72, 0x6E, 0x6A, 0x7A, 0x67, 0x7A, 0x6E, 0x74, 0x6A, 0x73, 0x57, 0x50, 0x08, 0x3B, 0x3E, 0x33, 0x2F, 0x29, 0x67, 0x6B, 0x6F, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x17, 0x3B, 0x28, 0x31, 0x11, 0x3F, 0x23, 0x7A, 0x28, 0x3F, 0x37, 0x35, 0x2C, 0x3F, 0x29, 0x7A, 0x3B, 0x7A, 0x3E, 0x35, 0x2E, 0x7A, 0x33, 0x3C, 0x7A, 0x23, 0x35, 0x2F, 0x7A, 0x29, 0x2E, 0x3B, 0x34, 0x3E, 0x7A, 0x2D, 0x33, 0x2E, 0x32, 0x33, 0x34, 0x7A, 0x2E, 0x32, 0x33, 0x29, 0x7A, 0x3E, 0x33, 0x29, 0x2E, 0x3B, 0x34, 0x39, 0x3F, 0x7A, 0x35, 0x3C, 0x7A, 0x33, 0x2E, 0x76, 0x7A, 0x33, 0x34, 0x7A, 0x2E, 0x3F, 0x34, 0x2E, 0x32, 0x29, 0x7A, 0x72, 0x6B, 0x6A, 0x6A, 0x7A, 0x67, 0x7A, 0x6B, 0x6A, 0x74, 0x6A, 0x73, 0x57, 0x50, 0x08, 0x3F, 0x37, 0x35, 0x2C, 0x3F, 0x08, 0x3B, 0x3E, 0x33, 0x2F, 0x29, 0x67, 0x6E, 0x6A, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x16, 0x33, 0x3C, 0x2E, 0x7A, 0x3B, 0x38, 0x35, 0x2C, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x28, 0x35, 0x2F, 0x34, 0x3E, 0x7A, 0x2A, 0x35, 0x33, 0x34, 0x2E, 0x7A, 0x33, 0x34, 0x7A, 0x2E, 0x3F, 0x34, 0x2E, 0x32, 0x29, 0x7A, 0x72, 0x3B, 0x2C, 0x35, 0x33, 0x3E, 0x29, 0x7A, 0x20, 0x77, 0x3C, 0x33, 0x3D, 0x32, 0x2E, 0x33, 0x34, 0x3D, 0x7A, 0x36, 0x35, 0x35, 0x31, 0x7A, 0x35, 0x34, 0x7A, 0x29, 0x36, 0x35, 0x2A, 0x3F, 0x29, 0x73, 0x57, 0x50, 0x16, 0x33, 0x3C, 0x2E, 0x67, 0x69, 0x57, 0x50, 0x61, 0x7A, 0x19, 0x33, 0x28, 0x39, 0x36, 0x3F, 0x7A, 0x29, 0x37, 0x35, 0x35, 0x2E, 0x32, 0x34, 0x3F, 0x29, 0x29, 0x7A, 0x62, 0x74, 0x74, 0x6E, 0x62, 0x57, 0x50, 0x09, 0x3F, 0x3D, 0x37, 0x3F, 0x34, 0x2E, 0x29, 0x67, 0x68, 0x6E, 0x57, 0x50, 0x61, 0x7A, 0x19, 0x35, 0x36, 0x35, 0x28, 0x7A, 0x33, 0x34, 0x7A, 0x32, 0x3F, 0x22, 0x7A, 0x08, 0x1D, 0x18, 0x7A, 0x72, 0x23, 0x3F, 0x36, 0x36, 0x35, 0x2D, 0x73, 0x7A, 0x3B, 0x34, 0x3E, 0x7A, 0x35, 0x2A, 0x3B, 0x39, 0x33, 0x2E, 0x23, 0x7A, 0x6A, 0x74, 0x74, 0x68, 0x6F, 0x6F, 0x57, 0x50, 0x19, 0x35, 0x36, 0x35, 0x28, 0x67, 0x6A, 0x22, 0x1C, 0x1C, 0x1E, 0x62, 0x6A, 0x6A, 0x57, 0x50, 0x15, 0x2A, 0x3B, 0x39, 0x33, 0x2E, 0x23, 0x67, 0x68, 0x6A, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x3E, 0x3B, 0x28, 0x31, 0x7A, 0x35, 0x2F, 0x2E, 0x36, 0x33, 0x34, 0x3F, 0x7A, 0x3B, 0x28, 0x35, 0x2F, 0x34, 0x3E, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3E, 0x35, 0x2E, 0x57, 0x50, 0x15, 0x2F, 0x2E, 0x36, 0x33, 0x34, 0x3F, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x17, 0x3B, 0x28, 0x31, 0x7A, 0x75, 0x7A, 0x2F, 0x34, 0x37, 0x3B, 0x28, 0x31, 0x60, 0x7A, 0x19, 0x2E, 0x28, 0x36, 0x71, 0x09, 0x32, 0x33, 0x3C, 0x2E, 0x71, 0x17, 0x57, 0x50, 0x17, 0x3B, 0x28, 0x31, 0x11, 0x3F, 0x23, 0x67, 0x6A, 0x22, 0x6E, 0x1E, 0x57, 0x50, 0x17, 0x3B, 0x28, 0x31, 0x19, 0x2E, 0x28, 0x36, 0x67, 0x6B, 0x57, 0x50, 0x17, 0x3B, 0x28, 0x31, 0x09, 0x32, 0x33, 0x3C, 0x2E, 0x67, 0x6B, 0x57, 0x50, 0x17, 0x3B, 0x28, 0x31, 0x1B, 0x36, 0x2E, 0x67, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x19, 0x36, 0x3F, 0x3B, 0x28, 0x7A, 0x3B, 0x36, 0x36, 0x60, 0x7A, 0x19, 0x2E, 0x28, 0x36, 0x71, 0x09, 0x32, 0x33, 0x3C, 0x2E, 0x71, 0x14, 0x57, 0x50, 0x19, 0x36, 0x3F, 0x3B, 0x28, 0x11, 0x3F, 0x23, 0x67, 0x6A, 0x22, 0x6E, 0x1F, 0x57, 0x50, 0x19, 0x36, 0x3F, 0x3B, 0x28, 0x19, 0x2E, 0x28, 0x36, 0x67, 0x6B, 0x57, 0x50, 0x19, 0x36, 0x3F, 0x3B, 0x28, 0x09, 0x32, 0x33, 0x3C, 0x2E, 0x67, 0x6B, 0x57, 0x50, 0x19, 0x36, 0x3F, 0x3B, 0x28, 0x1B, 0x36, 0x2E, 0x67, 0x6A, 0x57, 0x50, 0x57, 0x50, 0x01, 0x18, 0x35, 0x2E, 0x07, 0x57, 0x50, 0x61, 0x7A, 0x1D, 0x3B, 0x37, 0x3F, 0x7A, 0x29, 0x2E, 0x3B, 0x2E, 0x3F, 0x7A, 0x29, 0x34, 0x3B, 0x2A, 0x29, 0x32, 0x35, 0x2E, 0x7A, 0x33, 0x34, 0x7A, 0x29, 0x32, 0x3B, 0x28, 0x3F, 0x3E, 0x7A, 0x37, 0x3F, 0x37, 0x35, 0x28, 0x23, 0x7A, 0x3C, 0x35, 0x28, 0x7A, 0x28, 0x3C, 0x74, 0x2A, 0x23, 0x7A, 0x72, 0x39, 0x32, 0x3B, 0x28, 0x3B, 0x39, 0x2E, 0x3F, 0x28, 0x76, 0x7A, 0x2E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x76, 0x7A, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x29, 0x76, 0x7A, 0x37, 0x3B, 0x28, 0x31, 0x3F, 0x28, 0x29, 0x76, 0x7A, 0x3F, 0x3C, 0x3C, 0x3F, 0x39, 0x2E, 0x29, 0x73, 0x57, 0x50, 0x1F, 0x34, 0x3B, 0x38, 0x36, 0x3F, 0x3E, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x17, 0x33, 0x36, 0x36, 0x33, 0x29, 0x3F, 0x39, 0x35, 0x34, 0x3E, 0x29, 0x7A, 0x38, 0x3F, 0x2E, 0x2D, 0x3F, 0x3F, 0x34, 0x7A, 0x29, 0x34, 0x3B, 0x2A, 0x29, 0x32, 0x35, 0x2E, 0x29, 0x7A, 0x72, 0x6F, 0x6A, 0x74, 0x74, 0x6B, 0x6A, 0x6A, 0x6A, 0x73, 0x57, 0x50, 0x13, 0x34, 0x2E, 0x3F, 0x28, 0x2C, 0x3B, 0x36, 0x17, 0x29, 0x67, 0x6B, 0x6A, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x17, 0x33, 0x36, 0x36, 0x33, 0x29, 0x3F, 0x39, 0x35, 0x34, 0x3E, 0x29, 0x7A, 0x33, 0x34, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x2D, 0x35, 0x28, 0x36, 0x3E, 0x7A, 0x38, 0x3F, 0x3C, 0x35, 0x28, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3C, 0x33, 0x28, 0x29, 0x2E, 0x7A, 0x29, 0x34, 0x3B, 0x2A, 0x29, 0x32, 0x35, 0x2E, 0x7A, 0x72, 0x36, 0x3F, 0x2E, 0x29, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x39, 0x36, 0x33, 0x3F, 0x34, 0x2E, 0x7A, 0x3C, 0x33, 0x34, 0x33, 0x29, 0x32, 0x7A, 0x36, 0x35, 0x3B, 0x3E, 0x33, 0x34, 0x3D, 0x73, 0x57, 0x50, 0x09, 0x2E, 0x3B, 0x28, 0x2E, 0x1E, 0x3F, 0x36, 0x3B, 0x23, 0x17, 0x29, 0x67, 0x69, 0x6A, 0x6A, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x19, 0x35, 0x3E, 0x3F, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x35, 0x3C, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x2E, 0x3F, 0x22, 0x2E, 0x29, 0x76, 0x7A, 0x34, 0x3B, 0x37, 0x3F, 0x29, 0x7A, 0x3B, 0x28, 0x3F, 0x7A, 0x2A, 0x3B, 0x29, 0x29, 0x3F, 0x3E, 0x7A, 0x35, 0x34, 0x7A, 0x3B, 0x29, 0x7A, 0x0F, 0x0E, 0x1C, 0x77, 0x62, 0x7A, 0x72, 0x6B, 0x68, 0x6F, 0x68, 0x7A, 0x67, 0x7A, 0x0D, 0x3F, 0x29, 0x2E, 0x3F, 0x28, 0x34, 0x76, 0x7A, 0x6B, 0x68, 0x6F, 0x6B, 0x7A, 0x67, 0x7A, 0x19, 0x23, 0x28, 0x33, 0x36, 0x36, 0x33, 0x39, 0x73, 0x57, 0x50, 0x19, 0x35, 0x3E, 0x3F, 0x2A, 0x3B, 0x3D, 0x3F, 0x67, 0x6B, 0x68, 0x6F, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x17, 0x33, 0x36, 0x36, 0x33, 0x29, 0x3F, 0x39, 0x35, 0x34, 0x3E, 0x29, 0x7A, 0x3B, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x2A, 0x28, 0x3F, 0x29, 0x29, 0x3F, 0x3E, 0x7A, 0x38, 0x23, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x35, 0x2E, 0x7A, 0x33, 0x29, 0x7A, 0x32, 0x3F, 0x36, 0x3E, 0x7A, 0x3E, 0x35, 0x2D, 0x34, 0x57, 0x50, 0x11, 0x3F, 0x23, 0x12, 0x35, 0x36, 0x3E, 0x17, 0x29, 0x67, 0x6B, 0x6F, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x6B, 0x7A, 0x67, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x35, 0x2E, 0x7D, 0x29, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x2A, 0x28, 0x3F, 0x29, 0x29, 0x3F, 0x29, 0x7A, 0x3B, 0x36, 0x29, 0x35, 0x7A, 0x2D, 0x35, 0x28, 0x31, 0x7A, 0x2D, 0x32, 0x33, 0x36, 0x3F, 0x7A, 0x3B, 0x34, 0x35, 0x2E, 0x32, 0x3F, 0x28, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x33, 0x29, 0x7A, 0x3B, 0x39, 0x2E, 0x33, 0x2C, 0x3F, 0x7A, 0x72, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x39, 0x35, 0x2F, 0x34, 0x2E, 0x29, 0x7A, 0x3B, 0x29, 0x7A, 0x3B, 0x39, 0x2E, 0x33, 0x2C, 0x3F, 0x7A, 0x2D, 0x32, 0x33, 0x36, 0x3F, 0x57, 0x50, 0x61, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x33, 0x29, 0x7A, 0x32, 0x3F, 0x36, 0x3E, 0x73, 0x76, 0x7A, 0x6A, 0x7A, 0x67, 0x7A, 0x35, 0x34, 0x36, 0x23, 0x7A, 0x2D, 0x32, 0x33, 0x36, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x33, 0x29, 0x7A, 0x3B, 0x39, 0x2E, 0x33, 0x2C, 0x3F, 0x57, 0x50, 0x11, 0x3F, 0x23, 0x29, 0x0D, 0x32, 0x33, 0x36, 0x3F, 0x13, 0x34, 0x3B, 0x39, 0x2E, 0x33, 0x2C, 0x3F, 0x67, 0x6B, 0x57, 0x50, 0x61, 0x7A, 0x11, 0x3F, 0x23, 0x29, 0x7A, 0x35, 0x3C, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x29, 0x7A, 0x6B, 0x74, 0x74, 0x6B, 0x6A, 0x7A, 0x33, 0x34, 0x7A, 0x35, 0x28, 0x3E, 0x3F, 0x28, 0x7A, 0x72, 0x3F, 0x37, 0x2A, 0x2E, 0x23, 0x7A, 0x67, 0x7A, 0x6B, 0x68, 0x69, 0x6E, 0x6F, 0x6C, 0x6D, 0x62, 0x63, 0x6A, 0x73, 0x76, 0x7A, 0x3B, 0x2F, 0x2E, 0x35, 0x7A, 0x67, 0x7A, 0x3B, 0x29, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7D, 0x29, 0x7A, 0x11, 0x3F, 0x23, 0x17, 0x3B, 0x2A, 0x7A, 0x38, 0x33, 0x34, 0x3E, 0x29, 0x7A, 0x2E, 0x32, 0x3F, 0x37, 0x74, 0x57, 0x50, 0x61, 0x7A, 0x1B, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x35, 0x3C, 0x7A, 0x3B, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x7A, 0x2F, 0x29, 0x3F, 0x29, 0x7A, 0x2E, 0x32, 0x3B, 0x2E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x7A, 0x3E, 0x33, 0x28, 0x3F, 0x39, 0x2E, 0x36, 0x23, 0x7A, 0x72, 0x2D, 0x32, 0x3B, 0x2E, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x3E, 0x35, 0x3F, 0x29, 0x73, 0x76, 0x7A, 0x35, 0x2E, 0x32, 0x3F, 0x28, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x7A, 0x3B, 0x28, 0x3F, 0x7A, 0x29, 0x3F, 0x34, 0x2E, 0x7A, 0x2E, 0x35, 0x7A, 0x2E, 0x32, 0x3F, 0x57, 0x50, 0x61, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x74, 0x7A, 0x28, 0x3C, 0x74, 0x2A, 0x23, 0x7A, 0x3B, 0x39, 0x2E, 0x33, 0x35, 0x34, 0x29, 0x7A, 0x2D, 0x33, 0x2E, 0x32, 0x7A, 0x3B, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x72, 0x6B, 0x77, 0x6F, 0x73, 0x7A, 0x2F, 0x29, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x7A, 0x35, 0x3C, 0x7A, 0x2E, 0x32, 0x3B, 0x2E, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x3E, 0x33, 0x28, 0x3F, 0x39, 0x2E, 0x36, 0x23, 0x76, 0x7A, 0x2D, 0x32, 0x3B, 0x2E, 0x3F, 0x2C, 0x3F, 0x28, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x2E, 0x32, 0x3F, 0x57, 0x50, 0x61, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x29, 0x32, 0x35, 0x2D, 0x29, 0x57, 0x50, 0x18, 0x3F, 0x36, 0x2E, 0x11, 0x3F, 0x23, 0x29, 0x67, 0x6B, 0x68, 0x69, 0x6E, 0x6F, 0x6C, 0x6D, 0x62, 0x63, 0x6A, 0x57, 0x50, 0x61, 0x7A, 0x09, 0x32, 0x3B, 0x28, 0x3F, 0x3E, 0x7A, 0x37, 0x3F, 0x37, 0x35, 0x28, 0x23, 0x7A, 0x34, 0x3B, 0x37, 0x3F, 0x76, 0x7A, 0x37, 0x2F, 0x29, 0x2E, 0x7A, 0x37, 0x3B, 0x2E, 0x39, 0x32, 0x7A, 0x78, 0x29, 0x32, 0x3B, 0x28, 0x3F, 0x3E, 0x74, 0x34, 0x3B, 0x37, 0x3F, 0x78, 0x7A, 0x33, 0x34, 0x7A, 0x28, 0x3C, 0x05, 0x38, 0x35, 0x2E, 0x05, 0x39, 0x35, 0x34, 0x3C, 0x33, 0x3D, 0x74, 0x30, 0x29, 0x35, 0x34, 0x57, 0x50, 0x09, 0x32, 0x3B, 0x28, 0x3F, 0x3E, 0x14, 0x3B, 0x37, 0x3F, 0x67, 0x16, 0x35, 0x39, 0x3B, 0x36, 0x06, 0x08, 0x1C, 0x18, 0x35, 0x2E, 0x09, 0x2E, 0x3B, 0x2E, 0x3F, 0x57, 0x50, 0x00 };
static const unsigned char S_04[] = { 0x39, 0x35, 0x34, 0x3C, 0x33, 0x3D, 0x7A, 0x01, 0x18, 0x35, 0x2E, 0x07, 0x60, 0x7A, 0x1F, 0x34, 0x3B, 0x38, 0x36, 0x3F, 0x3E, 0x67, 0x7F, 0x3E, 0x7A, 0x13, 0x34, 0x2E, 0x3F, 0x28, 0x2C, 0x3B, 0x36, 0x17, 0x29, 0x67, 0x7F, 0x3E, 0x7A, 0x09, 0x2E, 0x3B, 0x28, 0x2E, 0x1E, 0x3F, 0x36, 0x3B, 0x23, 0x17, 0x29, 0x67, 0x7F, 0x3E, 0x7A, 0x19, 0x35, 0x3E, 0x3F, 0x2A, 0x3B, 0x3D, 0x3F, 0x67, 0x7F, 0x2F, 0x7A, 0x11, 0x3F, 0x23, 0x12, 0x35, 0x36, 0x3E, 0x17, 0x29, 0x67, 0x7F, 0x3E, 0x7A, 0x11, 0x3F, 0x23, 0x29, 0x0D, 0x32, 0x33, 0x36, 0x3F, 0x13, 0x34, 0x3B, 0x39, 0x2E, 0x33, 0x2C, 0x3F, 0x67, 0x7F, 0x3E, 0x7A, 0x18, 0x3F, 0x36, 0x2E, 0x11, 0x3F, 0x23, 0x29, 0x67, 0x7F, 0x29, 0x7A, 0x09, 0x32, 0x3B, 0x28, 0x3F, 0x3E, 0x14, 0x3B, 0x37, 0x3F, 0x67, 0x7F, 0x29, 0x00 };
static const unsigned char S_05[] = { 0x08, 0x1C, 0x18, 0x09, 0x00 };
static const unsigned char S_06[] = { 0x08, 0x1C, 0x18, 0x0B, 0x00 };
static const unsigned char S_07[] = { 0x1F, 0x08, 0x08, 0x15, 0x08, 0x60, 0x7A, 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x3F, 0x22, 0x39, 0x3F, 0x2A, 0x2E, 0x33, 0x35, 0x34, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x3B, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x2D, 0x32, 0x33, 0x36, 0x3F, 0x7A, 0x28, 0x3F, 0x3B, 0x3E, 0x33, 0x34, 0x3D, 0x7A, 0x7F, 0x29, 0x7A, 0x72, 0x35, 0x38, 0x30, 0x3F, 0x39, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x73, 0x76, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x7A, 0x3E, 0x33, 0x29, 0x3B, 0x38, 0x36, 0x3F, 0x3E, 0x7A, 0x2F, 0x34, 0x2E, 0x33, 0x36, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x28, 0x3F, 0x29, 0x2E, 0x3B, 0x28, 0x2E, 0x29, 0x00 };
static const unsigned char S_08[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x3F, 0x22, 0x39, 0x3F, 0x2A, 0x2E, 0x33, 0x35, 0x34, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x3B, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x28, 0x3F, 0x3B, 0x3E, 0x33, 0x34, 0x3D, 0x7A, 0x39, 0x32, 0x3B, 0x28, 0x3B, 0x39, 0x2E, 0x3F, 0x28, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x76, 0x7A, 0x33, 0x2E, 0x7A, 0x33, 0x29, 0x7A, 0x29, 0x31, 0x33, 0x2A, 0x2A, 0x3F, 0x3E, 0x7A, 0x72, 0x36, 0x35, 0x3D, 0x3D, 0x3F, 0x3E, 0x7A, 0x35, 0x34, 0x39, 0x3F, 0x73, 0x00 };
static const unsigned char S_09[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x68, 0x36, 0x02, 0x7A, 0x72, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x37, 0x3F, 0x29, 0x29, 0x3B, 0x3D, 0x3F, 0x73, 0x60, 0x7A, 0x28, 0x3F, 0x3B, 0x39, 0x32, 0x3F, 0x3E, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3F, 0x34, 0x3D, 0x33, 0x34, 0x3F, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x3B, 0x28, 0x28, 0x3B, 0x23, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x2E, 0x3B, 0x31, 0x3F, 0x34, 0x7A, 0x38, 0x23, 0x7A, 0x3B, 0x7A, 0x11, 0x3F, 0x23, 0x17, 0x3B, 0x2A, 0x7A, 0x3B, 0x39, 0x2E, 0x33, 0x35, 0x34, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x7F, 0x29, 0x00 };
static const unsigned char S_10[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x7A, 0x7F, 0x3E, 0x60, 0x7A, 0x7F, 0x29, 0x7A, 0x12, 0x0A, 0x7A, 0x7F, 0x3E, 0x7A, 0x75, 0x7A, 0x7F, 0x3E, 0x7A, 0x36, 0x3F, 0x2C, 0x3F, 0x36, 0x7A, 0x7F, 0x36, 0x2F, 0x7F, 0x29, 0x00 };
static const unsigned char S_11[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x60, 0x7A, 0x34, 0x35, 0x34, 0x3F, 0x7A, 0x3C, 0x35, 0x2F, 0x34, 0x3E, 0x7A, 0x35, 0x34, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x7A, 0x38, 0x35, 0x3B, 0x28, 0x3E, 0x7F, 0x29, 0x00 };
static const unsigned char S_12[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x60, 0x7A, 0x3F, 0x22, 0x39, 0x3F, 0x2A, 0x2E, 0x33, 0x35, 0x34, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x3B, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x28, 0x3F, 0x3B, 0x3E, 0x33, 0x34, 0x3D, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x7A, 0x36, 0x33, 0x29, 0x2E, 0x76, 0x7A, 0x33, 0x2E, 0x7A, 0x33, 0x29, 0x7A, 0x35, 0x3C, 0x3C, 0x00 };
static const unsigned char S_13[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3D, 0x28, 0x35, 0x2F, 0x34, 0x3E, 0x60, 0x7A, 0x3F, 0x22, 0x39, 0x3F, 0x2A, 0x2E, 0x33, 0x35, 0x34, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x3B, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x28, 0x3F, 0x3B, 0x3E, 0x33, 0x34, 0x3D, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x28, 0x35, 0x2F, 0x34, 0x3E, 0x7A, 0x33, 0x2E, 0x3F, 0x37, 0x7A, 0x36, 0x33, 0x29, 0x2E, 0x76, 0x7A, 0x33, 0x2E, 0x7A, 0x33, 0x29, 0x7A, 0x35, 0x3C, 0x3C, 0x00 };
static const unsigned char S_14[] = { 0x38, 0x35, 0x2E, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x60, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x7F, 0x3E, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x7F, 0x3E, 0x7A, 0x67, 0x7A, 0x7F, 0x29, 0x7A, 0x7D, 0x7F, 0x29, 0x7D, 0x7A, 0x72, 0x2E, 0x23, 0x2A, 0x3F, 0x7A, 0x7F, 0x36, 0x2F, 0x73, 0x60, 0x7A, 0x28, 0x3F, 0x3B, 0x3E, 0x23, 0x7A, 0x7F, 0x3E, 0x76, 0x7A, 0x39, 0x35, 0x35, 0x36, 0x3E, 0x35, 0x2D, 0x34, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x75, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x37, 0x29, 0x00 };
static const unsigned char S_15[] = { 0x38, 0x35, 0x2E, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x60, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x7F, 0x3E, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x7F, 0x3E, 0x7A, 0x67, 0x7A, 0x7F, 0x29, 0x7A, 0x7D, 0x7F, 0x29, 0x7D, 0x00 };
static const unsigned char S_16[] = { 0x38, 0x35, 0x2E, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x60, 0x7A, 0x3F, 0x22, 0x39, 0x3F, 0x2A, 0x2E, 0x33, 0x35, 0x34, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x3B, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x72, 0x35, 0x38, 0x30, 0x3F, 0x39, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x73, 0x7A, 0x28, 0x3F, 0x3B, 0x3E, 0x33, 0x34, 0x3D, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x39, 0x35, 0x35, 0x36, 0x3E, 0x35, 0x2D, 0x34, 0x29, 0x76, 0x7A, 0x2E, 0x32, 0x3F, 0x23, 0x7A, 0x3B, 0x28, 0x3F, 0x7A, 0x35, 0x3C, 0x3C, 0x00 };
static const unsigned char S_17[] = { 0x38, 0x35, 0x2E, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x60, 0x7A, 0x3F, 0x22, 0x39, 0x3F, 0x2A, 0x2E, 0x33, 0x35, 0x34, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x3B, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x72, 0x35, 0x38, 0x30, 0x3F, 0x39, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x73, 0x7A, 0x28, 0x3F, 0x3B, 0x3E, 0x33, 0x34, 0x3D, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x76, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x7A, 0x33, 0x29, 0x7A, 0x35, 0x3C, 0x3C, 0x00 };
static const unsigned char S_18[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x60, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x38, 0x33, 0x34, 0x3E, 0x33, 0x34, 0x3D, 0x29, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x3C, 0x35, 0x2F, 0x34, 0x3E, 0x7A, 0x72, 0x34, 0x35, 0x7A, 0x19, 0x1D, 0x0A, 0x05, 0x17, 0x3B, 0x33, 0x34, 0x1D, 0x3B, 0x37, 0x3F, 0x7A, 0x75, 0x7A, 0x19, 0x11, 0x3F, 0x23, 0x17, 0x3B, 0x2A, 0x73, 0x00 };
static const unsigned char S_19[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x60, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x77, 0x31, 0x3F, 0x23, 0x7A, 0x37, 0x35, 0x3E, 0x3F, 0x7A, 0x7F, 0x3E, 0x7A, 0x72, 0x7F, 0x29, 0x73, 0x76, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x00 };
static const unsigned char S_20[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x60, 0x7A, 0x3C, 0x33, 0x22, 0x3F, 0x3E, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x2E, 0x3B, 0x38, 0x36, 0x3F, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x60, 0x00 };
static const unsigned char S_21[] = { 0x61, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x7F, 0x3E, 0x61, 0x7A, 0x01, 0x18, 0x35, 0x2E, 0x07, 0x7A, 0x18, 0x3F, 0x36, 0x2E, 0x11, 0x3F, 0x23, 0x29, 0x67, 0x7F, 0x29, 0x00 };
static const unsigned char S_22[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x60, 0x7A, 0x11, 0x3F, 0x23, 0x17, 0x3B, 0x2A, 0x00 };
static const unsigned char S_23[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x68, 0x36, 0x02, 0x7A, 0x67, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x7A, 0x7F, 0x3E, 0x60, 0x7A, 0x2F, 0x29, 0x3F, 0x3E, 0x7A, 0x3E, 0x33, 0x28, 0x3F, 0x39, 0x2E, 0x36, 0x23, 0x7A, 0x72, 0x19, 0x16, 0x33, 0x34, 0x31, 0x18, 0x35, 0x3B, 0x28, 0x3E, 0x60, 0x60, 0x0F, 0x29, 0x3F, 0x09, 0x36, 0x35, 0x2E, 0x73, 0x76, 0x7A, 0x28, 0x3F, 0x29, 0x2F, 0x36, 0x2E, 0x7A, 0x7F, 0x36, 0x2F, 0x00 };
static const unsigned char S_24[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x68, 0x36, 0x02, 0x7A, 0x72, 0x1C, 0x6B, 0x6A, 0x7A, 0x75, 0x7A, 0x1B, 0x36, 0x2E, 0x73, 0x7A, 0x33, 0x29, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x29, 0x3F, 0x34, 0x2E, 0x60, 0x7A, 0x0D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x29, 0x7A, 0x2E, 0x2F, 0x28, 0x34, 0x29, 0x7A, 0x33, 0x2E, 0x7A, 0x33, 0x34, 0x2E, 0x35, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x37, 0x3F, 0x34, 0x2F, 0x76, 0x7A, 0x2D, 0x32, 0x33, 0x39, 0x32, 0x7A, 0x29, 0x2E, 0x3B, 0x36, 0x36, 0x29, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x61, 0x7A, 0x2A, 0x2F, 0x2E, 0x7A, 0x2E, 0x32, 0x3B, 0x2E, 0x7A, 0x3B, 0x39, 0x2E, 0x33, 0x35, 0x34, 0x7A, 0x35, 0x34, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x3B, 0x34, 0x3E, 0x7A, 0x2F, 0x29, 0x3F, 0x7A, 0x33, 0x2E, 0x29, 0x7A, 0x31, 0x3F, 0x23, 0x00 };
static const unsigned char S_25[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x68, 0x36, 0x02, 0x7A, 0x33, 0x29, 0x7A, 0x34, 0x35, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x60, 0x7A, 0x29, 0x3F, 0x34, 0x2E, 0x7A, 0x2E, 0x35, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x00 };
static const unsigned char S_26[] = { 0x38, 0x35, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x60, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x37, 0x3F, 0x29, 0x29, 0x3B, 0x3D, 0x3F, 0x29, 0x7A, 0x3D, 0x35, 0x7A, 0x2E, 0x35, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x00 };
static const unsigned char S_27[] = { 0x38, 0x35, 0x2E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x60, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x35, 0x3C, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x29, 0x32, 0x35, 0x2D, 0x34, 0x7A, 0x2F, 0x29, 0x3F, 0x3E, 0x7A, 0x3E, 0x33, 0x28, 0x3F, 0x39, 0x2E, 0x36, 0x23, 0x7A, 0x72, 0x19, 0x16, 0x33, 0x34, 0x31, 0x18, 0x35, 0x3B, 0x28, 0x3E, 0x60, 0x60, 0x0F, 0x29, 0x3F, 0x09, 0x36, 0x35, 0x2E, 0x73, 0x76, 0x7A, 0x28, 0x3F, 0x29, 0x2F, 0x36, 0x2E, 0x7A, 0x7F, 0x36, 0x2F, 0x00 };
static const unsigned char S_28[] = { 0x38, 0x35, 0x2E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x60, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x7A, 0x7F, 0x3E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x2F, 0x29, 0x3F, 0x3E, 0x7A, 0x3E, 0x33, 0x28, 0x3F, 0x39, 0x2E, 0x36, 0x23, 0x7A, 0x72, 0x19, 0x16, 0x33, 0x34, 0x31, 0x18, 0x35, 0x3B, 0x28, 0x3E, 0x60, 0x60, 0x0F, 0x29, 0x3F, 0x09, 0x36, 0x35, 0x2E, 0x73, 0x76, 0x7A, 0x28, 0x3F, 0x29, 0x2F, 0x36, 0x2E, 0x7A, 0x7F, 0x36, 0x2F, 0x00 };
static const unsigned char S_29[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x3C, 0x33, 0x28, 0x29, 0x2E, 0x7A, 0x29, 0x34, 0x3B, 0x2A, 0x29, 0x32, 0x35, 0x2E, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x37, 0x29, 0x7A, 0x3B, 0x3C, 0x2E, 0x3F, 0x28, 0x7A, 0x3F, 0x34, 0x2E, 0x3F, 0x28, 0x33, 0x34, 0x3D, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x2D, 0x35, 0x28, 0x36, 0x3E, 0x60, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x39, 0x32, 0x3B, 0x28, 0x3B, 0x39, 0x2E, 0x3F, 0x28, 0x29, 0x7A, 0x29, 0x3F, 0x3F, 0x34, 0x76, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x3F, 0x3E, 0x76, 0x7A, 0x2E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x7A, 0x7F, 0x3E, 0x76, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x3F, 0x3C, 0x3C, 0x3F, 0x39, 0x2E, 0x29, 0x76, 0x7A, 0x7F, 0x36, 0x2F, 0x7A, 0x37, 0x3B, 0x28, 0x31, 0x3F, 0x28, 0x29, 0x00 };
static const unsigned char S_30[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x19, 0x1B, 0x2C, 0x3B, 0x2E, 0x3B, 0x28, 0x60, 0x60, 0x08, 0x3F, 0x34, 0x3E, 0x3F, 0x28, 0x15, 0x2C, 0x3F, 0x28, 0x32, 0x3F, 0x3B, 0x3E, 0x7A, 0x3B, 0x36, 0x29, 0x35, 0x7A, 0x28, 0x2F, 0x34, 0x29, 0x7A, 0x3C, 0x35, 0x28, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x72, 0x35, 0x2D, 0x34, 0x7A, 0x39, 0x32, 0x3B, 0x28, 0x3B, 0x39, 0x2E, 0x3F, 0x28, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x73, 0x76, 0x7A, 0x33, 0x3D, 0x34, 0x35, 0x28, 0x3F, 0x3E, 0x00 };
static const unsigned char S_31[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x34, 0x35, 0x7A, 0x36, 0x35, 0x3B, 0x3E, 0x3F, 0x3E, 0x7A, 0x36, 0x3F, 0x2C, 0x3F, 0x36, 0x7A, 0x3C, 0x35, 0x28, 0x7A, 0x69, 0x6A, 0x7A, 0x29, 0x7A, 0x72, 0x3D, 0x05, 0x2A, 0x16, 0x3F, 0x2C, 0x3F, 0x36, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x73, 0x76, 0x7A, 0x2D, 0x3B, 0x33, 0x2E, 0x33, 0x34, 0x3D, 0x00 };
static const unsigned char S_32[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x19, 0x19, 0x32, 0x3B, 0x28, 0x3B, 0x39, 0x2E, 0x3F, 0x28, 0x17, 0x3D, 0x28, 0x7A, 0x08, 0x0E, 0x0E, 0x13, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x28, 0x3F, 0x39, 0x35, 0x3D, 0x34, 0x33, 0x20, 0x3F, 0x3E, 0x76, 0x7A, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x29, 0x7A, 0x3B, 0x34, 0x3E, 0x7A, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x7A, 0x37, 0x3B, 0x23, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x38, 0x3F, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x3F, 0x3E, 0x00 };
static const unsigned char S_33[] = { 0x1F, 0x08, 0x08, 0x15, 0x08, 0x60, 0x7A, 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x19, 0x28, 0x3F, 0x3B, 0x2E, 0x3F, 0x1C, 0x33, 0x36, 0x3F, 0x17, 0x3B, 0x2A, 0x2A, 0x33, 0x34, 0x3D, 0x7A, 0x7D, 0x7F, 0x29, 0x7D, 0x7A, 0x3C, 0x3B, 0x33, 0x36, 0x3F, 0x3E, 0x00 };
static const unsigned char S_34[] = { 0x1F, 0x08, 0x08, 0x15, 0x08, 0x60, 0x7A, 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x17, 0x3B, 0x2A, 0x0C, 0x33, 0x3F, 0x2D, 0x15, 0x3C, 0x1C, 0x33, 0x36, 0x3F, 0x7A, 0x7D, 0x7F, 0x29, 0x7D, 0x7A, 0x3C, 0x3B, 0x33, 0x36, 0x3F, 0x3E, 0x00 };
static const unsigned char S_35[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x19, 0x16, 0x3F, 0x2C, 0x3F, 0x36, 0x1F, 0x37, 0x2A, 0x2E, 0x23, 0x7A, 0x08, 0x0E, 0x0E, 0x13, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x28, 0x3F, 0x39, 0x35, 0x3D, 0x34, 0x33, 0x20, 0x3F, 0x3E, 0x76, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x36, 0x35, 0x3B, 0x3E, 0x3F, 0x3E, 0x77, 0x36, 0x3F, 0x2C, 0x3F, 0x36, 0x7A, 0x39, 0x32, 0x3F, 0x39, 0x31, 0x7A, 0x33, 0x29, 0x7A, 0x35, 0x3C, 0x3C, 0x00 };
static const unsigned char S_36[] = { 0x38, 0x35, 0x2E, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x60, 0x7A, 0x39, 0x35, 0x35, 0x36, 0x3E, 0x35, 0x2D, 0x34, 0x29, 0x7A, 0x35, 0x3C, 0x3C, 0x76, 0x7A, 0x39, 0x35, 0x3E, 0x3F, 0x7A, 0x35, 0x3C, 0x7A, 0x19, 0x3B, 0x34, 0x0F, 0x29, 0x3F, 0x09, 0x1C, 0x00 };
static const unsigned char S_37[] = { 0x38, 0x35, 0x2E, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x60, 0x7A, 0x39, 0x35, 0x35, 0x36, 0x3E, 0x35, 0x2D, 0x34, 0x29, 0x7A, 0x35, 0x3C, 0x3C, 0x76, 0x7A, 0x39, 0x35, 0x3E, 0x3F, 0x7A, 0x35, 0x3C, 0x7A, 0x09, 0x1C, 0x18, 0x3B, 0x29, 0x3F, 0x1E, 0x3F, 0x36, 0x3B, 0x23, 0x00 };
static const unsigned char S_38[] = { 0x38, 0x35, 0x2E, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x60, 0x7A, 0x39, 0x35, 0x35, 0x36, 0x3E, 0x35, 0x2D, 0x34, 0x29, 0x7A, 0x35, 0x3C, 0x3C, 0x76, 0x7A, 0x39, 0x35, 0x3E, 0x3F, 0x7A, 0x35, 0x3C, 0x7A, 0x09, 0x1C, 0x1E, 0x3F, 0x36, 0x3B, 0x23, 0x00 };
static const unsigned char S_39[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x39, 0x35, 0x37, 0x37, 0x3B, 0x34, 0x3E, 0x29, 0x7A, 0x77, 0x7A, 0x29, 0x3F, 0x36, 0x3F, 0x39, 0x2E, 0x7A, 0x75, 0x7A, 0x39, 0x36, 0x3F, 0x3B, 0x28, 0x7A, 0x2E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x7A, 0x2E, 0x32, 0x28, 0x35, 0x2F, 0x3D, 0x32, 0x7A, 0x19, 0x0E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x17, 0x3D, 0x28, 0x60, 0x60, 0x19, 0x32, 0x3F, 0x39, 0x31, 0x0E, 0x3B, 0x28, 0x3D, 0x3F, 0x2E, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x7A, 0x2F, 0x29, 0x3F, 0x3E, 0x7A, 0x3E, 0x33, 0x28, 0x3F, 0x39, 0x2E, 0x36, 0x23, 0x7A, 0x72, 0x19, 0x16, 0x33, 0x34, 0x31, 0x18, 0x35, 0x3B, 0x28, 0x3E, 0x60, 0x60, 0x0F, 0x29, 0x3F, 0x09, 0x36, 0x35, 0x2E, 0x73, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x29, 0x36, 0x35, 0x2E, 0x29, 0x7A, 0x35, 0x3C, 0x7A, 0x3B, 0x34, 0x23, 0x7A, 0x2A, 0x3B, 0x3D, 0x3F, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x35, 0x2E, 0x32, 0x3F, 0x28, 0x7A, 0x31, 0x3F, 0x23, 0x7A, 0x2A, 0x28, 0x3F, 0x29, 0x29, 0x3F, 0x29, 0x7A, 0x72, 0x0D, 0x17, 0x05, 0x11, 0x1F, 0x03, 0x1E, 0x15, 0x0D, 0x14, 0x75, 0x0D, 0x17, 0x05, 0x11, 0x1F, 0x03, 0x0F, 0x0A, 0x7A, 0x2E, 0x35, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x73, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x31, 0x3F, 0x23, 0x29, 0x7A, 0x2D, 0x32, 0x33, 0x36, 0x3F, 0x7A, 0x3B, 0x34, 0x35, 0x2E, 0x32, 0x3F, 0x28, 0x7A, 0x2D, 0x33, 0x34, 0x3E, 0x35, 0x2D, 0x7A, 0x33, 0x29, 0x7A, 0x3B, 0x39, 0x2E, 0x33, 0x2C, 0x3F, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x2D, 0x3B, 0x36, 0x31, 0x33, 0x34, 0x3D, 0x7A, 0x2E, 0x32, 0x28, 0x35, 0x2F, 0x3D, 0x32, 0x7A, 0x17, 0x35, 0x2C, 0x3F, 0x08, 0x3F, 0x2B, 0x2F, 0x3F, 0x29, 0x2E, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x29, 0x2F, 0x37, 0x37, 0x35, 0x34, 0x3F, 0x3E, 0x77, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x7A, 0x39, 0x32, 0x3F, 0x39, 0x31, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x7A, 0x36, 0x33, 0x29, 0x2E, 0x7A, 0x71, 0x7A, 0x29, 0x2F, 0x37, 0x37, 0x35, 0x34, 0x60, 0x7A, 0x7F, 0x29, 0x76, 0x7A, 0x38, 0x3F, 0x36, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x7F, 0x29, 0x00 };
static const unsigned char S_40[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x29, 0x32, 0x3B, 0x28, 0x3F, 0x3E, 0x7A, 0x37, 0x3F, 0x37, 0x35, 0x28, 0x23, 0x7A, 0x7D, 0x7F, 0x29, 0x7D, 0x76, 0x7A, 0x29, 0x34, 0x3B, 0x2A, 0x29, 0x32, 0x35, 0x2E, 0x7A, 0x7F, 0x2F, 0x7A, 0x38, 0x23, 0x2E, 0x3F, 0x29, 0x7A, 0x72, 0x3F, 0x34, 0x2E, 0x33, 0x2E, 0x23, 0x7A, 0x7F, 0x2F, 0x76, 0x7A, 0x3F, 0x3C, 0x3C, 0x3F, 0x39, 0x2E, 0x7A, 0x7F, 0x2F, 0x73, 0x76, 0x7A, 0x3F, 0x2C, 0x3F, 0x28, 0x23, 0x7A, 0x7F, 0x3E, 0x7A, 0x37, 0x29, 0x00 };
static const unsigned char S_41[] = { 0x1F, 0x08, 0x08, 0x15, 0x08, 0x60, 0x7A, 0x39, 0x36, 0x33, 0x3F, 0x34, 0x2E, 0x7A, 0x36, 0x3B, 0x23, 0x35, 0x2F, 0x2E, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x28, 0x3F, 0x39, 0x35, 0x3D, 0x34, 0x33, 0x20, 0x3F, 0x3E, 0x7A, 0x3B, 0x3C, 0x2E, 0x3F, 0x28, 0x7A, 0x6B, 0x6A, 0x7A, 0x37, 0x33, 0x34, 0x7A, 0x72, 0x3E, 0x33, 0x3C, 0x3C, 0x3F, 0x28, 0x3F, 0x34, 0x2E, 0x7A, 0x39, 0x36, 0x33, 0x3F, 0x34, 0x2E, 0x7A, 0x38, 0x2F, 0x33, 0x36, 0x3E, 0x65, 0x73, 0x76, 0x7A, 0x18, 0x35, 0x2E, 0x19, 0x35, 0x28, 0x3F, 0x7A, 0x3E, 0x33, 0x29, 0x3B, 0x38, 0x36, 0x3F, 0x3E, 0x00 };
static const unsigned char S_42[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x19, 0x1B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x7A, 0x2C, 0x2E, 0x3B, 0x38, 0x36, 0x3F, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x28, 0x3F, 0x39, 0x35, 0x3D, 0x34, 0x33, 0x20, 0x3F, 0x3E, 0x76, 0x7A, 0x3B, 0x34, 0x33, 0x37, 0x2F, 0x29, 0x7A, 0x3B, 0x28, 0x3F, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x3F, 0x3E, 0x00 };
static const unsigned char S_43[] = { 0x38, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x60, 0x7A, 0x39, 0x35, 0x37, 0x38, 0x3B, 0x2E, 0x7A, 0x2A, 0x3B, 0x39, 0x31, 0x3F, 0x2E, 0x7A, 0x32, 0x3B, 0x34, 0x3E, 0x36, 0x3F, 0x28, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x28, 0x3F, 0x39, 0x35, 0x3D, 0x34, 0x33, 0x20, 0x3F, 0x3E, 0x76, 0x7A, 0x37, 0x35, 0x34, 0x29, 0x2E, 0x3F, 0x28, 0x7A, 0x3B, 0x2E, 0x2E, 0x3B, 0x39, 0x31, 0x29, 0x7A, 0x3B, 0x28, 0x3F, 0x7A, 0x34, 0x35, 0x2E, 0x7A, 0x3F, 0x22, 0x2A, 0x35, 0x28, 0x2E, 0x3F, 0x3E, 0x00 };
static const unsigned char S_44[] = { 0x18, 0x35, 0x2E, 0x19, 0x35, 0x28, 0x3F, 0x7A, 0x36, 0x35, 0x3B, 0x3E, 0x3F, 0x3E, 0x7A, 0x3B, 0x2E, 0x7A, 0x6A, 0x22, 0x7F, 0x6A, 0x62, 0x36, 0x02, 0x7A, 0x33, 0x34, 0x2E, 0x35, 0x7A, 0x2E, 0x32, 0x3F, 0x7A, 0x3D, 0x3B, 0x37, 0x3F, 0x7A, 0x2A, 0x28, 0x35, 0x39, 0x3F, 0x29, 0x29, 0x00 };


/* path strings used with MASKSTR (decode into caller buffer) */
static const unsigned char S_INI[]    = { 0x18,0x35,0x2E,0x19,0x35,0x28,0x3F,0x74,0x33,0x34,0x33,0x00 };
static const unsigned char S_LOG[]    = { 0x18,0x35,0x2E,0x19,0x35,0x28,0x3F,0x74,0x36,0x35,0x3D,0x00 };
static const unsigned char S_SHM[]    = { 0x16,0x35,0x39,0x3B,0x36,0x06,0x08,0x1C,0x18,0x35,0x2E,0x09,0x2E,0x3B,0x2E,0x3F,0x00 };
static const unsigned char S_DBG[]    = { 0x37,0x37,0x05,0x3E,0x3F,0x38,0x2F,0x3D,0x74,0x36,0x35,0x3D,0x00 };

/* ================================ Game addresses ================================ */

#define ADDR_CMONSTER_VTBL     0x00A450BCu   /* CMonster vftable                                     */
#define ADDR_CAVATAR_VTBL      0x00A41E4Cu   /* CAvatar vftable                                      */
#define ADDR_RENDERNAME        0x004346E0u   /* CCharacter::RenderName (vtbl+0x24), int __thiscall()   */
#define ADDR_AVATAR_OVERHEAD   0x00403880u   /* CAvatar::RenderOverhead (vtbl+0x84), void __thiscall() */
#define ADDR_IS_TARGET         0x005056B0u   /* CTargetMgr::IsTarget(obj), int __thiscall             */
#define ADDR_GET_BBOX          0x006FD5A0u   /* CResObject::GetBBox(float out[6], int), __thiscall     */
#define ADDR_WORLD_TO_SCREEN   0x007B5B60u   /* int __cdecl(float out[4] (x,y,z,rhw), const float pos[3]) */
#define ADDR_DRAW_TEXT         0x007C6430u   /* void __cdecl(float pos[4] (x,y,z,rhw), text, color, flags, scale) */
#define ADDR_MEASURE_TEXT      0x007C6690u   /* void __cdecl(text, int out[2] (w,h), int len, flags)   */
#define ADDR_GET_HPRATE        0x00409410u   /* CCharacter::GetHPRate (vtbl+0xEC), float __thiscall()  */
#define ADDR_MONSTER_LEVEL     0x0044F140u   /* CMonster::GetLevel, BYTE __thiscall() (record+0x2A)    */
#define ADDR_PLAYER_LEVEL      0x0041B680u   /* CPlayer::GetLevel, DWORD __thiscall() (this+0x4024)    */
#define ADDR_SF_DURATION       0x00456F80u   /* CSFItem::GetDurationMs, DWORD __thiscall()             */
#define ADDR_IAT_GAME_TIME     0x00A415ECu   /* import slot of the time function the game uses for effects */

/* Effect container (CCharacter+0x384), see CCharacter::AddEffect 0x437300 / update 0x43C5E0 */
#define OBJ_EFFECTS            0x384
#define EFF_ITEMS              0x00          /* CSFItem*[2]  : [kind] -> CSFItem[capacity] (kind 0 harmful = debuff, 1 helpful = buff) */
#define EFF_REMAIN             0x10          /* DWORD*[2]    : [kind] -> remaining ms per slot              */
#define EFF_CAPACITY           0x1E          /* BYTE         : slots per kind (8)                           */
#define EFF_LAST_TICK          0x24          /* DWORD        : game time of the last remaining-time update  */
#define EFF_OWNER              0x28          /* owner pointer, non-null once initialised                    */
#define EFF_SLOT5_ITEM         0x54          /* CSFItem      : single slot, record kind 5, no timer          */
#define EFF_SLOT4_ITEMS        0xB0          /* CSFItem[2]   : record kind 4, timed                         */
#define EFF_SLOT4_REMAIN       0x170         /* DWORD[2]     : remaining ms for the kind-4 slots            */
#define SFITEM_SIZE            0x5C
#define SFITEM_INDEX           0x04          /* DWORD, -1 = empty slot */
#define SFITEM_RECORD          0x10          /* data table record*     */
#define SFITEM_TYPE            0x18          /* BYTE SF type           */
#define SFITEM_LEVEL           0x20          /* BYTE level             */
#define SFITEM_LEVEL_BONUS     0x21          /* BYTE extra level       */
#define VT_SF_GETNAME          0x18          /* const char* __thiscall() -> record+0x70 */
#define VT_SF_GETINDEX         0x1C          /* DWORD __thiscall() -> record[0]          */
#define VT_SF_GETCODE          0x20          /* DWORD __thiscall() -> record[4]          */

/* Doping potions (CAvatar), see use 0x41AAB0 / discharge 0x41AE00 */
#define AVATAR_DOPING_SLOTS    2
#define AVATAR_DOPING_ITEM     0x5934        /* item record*[2], NULL = empty slot        */
#define AVATAR_DOPING_END      0x593C        /* DWORD[2] game time when the potion ends   */
#define ITEMREC_NAME           0x08          /* char[] item name                          */
#define ITEMREC_EFFECT_CODE    0xB8          /* DWORD code of the type-5 SF effect        */
#define SFREC_NAME             0x70          /* char[] effect name                        */
#define SFREC_DURATION         0x1A8         /* DWORD effect duration, ms                 */
#define ADDR_PTR_SF_TABLES     0x0233B628u   /* SF data tables (skill/force/class/type-5)  */
#define ADDR_SF_FIND_TYPE5     0x005AA120u   /* record* __thiscall(tables, DWORD code)    */

#define ADDR_PTR_D3DDEVICE     0x0243FBE0u   /* IDirect3DDevice9*                                      */
#define ADDR_PTR_TARGETMGR     0x00F41214u   /* CTargetMgr* (current target + overhead GUI windows)    */
#define ADDR_PTR_AVATAR        0x0233B5F8u   /* CAvatar* (own character)                                */
#define ADDR_PTR_CHARACTERMGR  0x0233B5F0u   /* CCharacterMgr* (all characters by object type)          */
#define ADDR_PTR_LEVEL         0x0233B5E8u   /* CLevel* in the world, CLevelEmpty* before a map is loaded */
#define VTBL_CLEVELEMPTY       0x00A681ECu

#define VTBL_CHARACTERMGR      0x00A49D00u
#define CHARMGR_LISTS          0x0C          /* std::vector<CCharacter*> per object type, stride 0x10:
                                                +4 first, +8 last (iterators 0x4FADA0/0x4FADC0, ++ = +4) */
#define CHARMGR_LIST_STRIDE    0x10
#define VTBL_COMBAT_PROCESSOR  0x00A4FE70u   /* CNetMsgProcessor_Combat vftable */
#define ADDR_COMBAT_ANALYSIS   0x0055B570u   /* CNetMsgProcessor_Combat::AnalysisServerPacket(BYTE *hdr, BYTE *data),
                                                hdr+2 major, hdr+3 minor, __thiscall ret 8 */
#define VT_ANALYSIS_PACKET     0x04
#define ADDR_GET_TARGET_OBJECT 0x00504110u   /* CTargetMgr::GetTargetObject, CCharacter* __thiscall() */
#define ADDR_CHECK_TARGET      0x00504880u   /* CTargetMgr::CheckTarget(CCharacter*, int info): what a click on a
                                                character does: selects it and sends _set_target_object_request
                                                (13/26); NULL sends _release_target_object_request (13/28) */
#define ADDR_GET_OBJECT        0x004F6E30u   /* CCharacterMgr::GetObject(int type, int index), map lookup */
#define ADDR_KEY_PRESSED       0x0243DE40u   /* DWORD[256] by VK: set by the engine on WM_KEYDOWN (0x7C5250),
                                                consumed by CKeyMap::IsActionTriggered (0x528CB0), which runs the
                                                action bound to that key (belt slots, animus, ...); the key
                                                dispatcher only looks at it after a WM_KEYDOWN (CKeyMap+0x334) */
#define ADDR_KEY_DOWN_SEEN     0x0243EA68u   /* DWORD[256] by VK: WM_KEYDOWN sets 1, WM_KEYUP ORs 0x800, nothing
                                                takes it (read only for the key report in the log) */
#define ADDR_KEY_DOWN_CODE     0x007C5222u   /* engine: cmp [vk*4 + ADDR_KEY_PRESSED], 0 on WM_KEYDOWN */
#define ADDR_KEY_CONSUME_CODE  0x00528D59u   /* CKeyMap::IsActionTriggered: reads/clears the same array */
#define ADDR_PTR_MAINAPP       0x0233B5D8u   /* CMainApp* */
#define MAINAPP_ACTIVE         0x75884       /* DWORD: wParam of the last WM_ACTIVATEAPP (0x7011DA); the key
                                                dispatcher (0x527E10) runs no key action while it is 0 */
#define ADDR_ACTIVE_GETTER     0x0059A400u   /* CMainApp getter of MAINAPP_ACTIVE (called by the key dispatcher) */
#define ADDR_ACTIVE_STORE_CODE 0x007011DAu   /* CMainApp::MsgProc, WM_ACTIVATEAPP: mov [ecx+0x75884], edx */
#define ADDR_PTR_NETWORKMGR    0x0233B5ECu   /* CNetworkMgr* */
#define NETMGR_PROCESSORS      0x43608       /* CNetMsgProcessor*[0x25] (getter 0x52ECB0), [0] = CNetMsgProcessor_Position */
#define ADDR_PROCESSOR_CODE    0x0052ECC4u   /* that getter reading NETMGR_PROCESSORS */
#define NETMGR_PROCESSOR_COUNT 0x25          /* processors[] entries (getter 0x52ECB0 range) */
#define ADDR_PTR_NETWORKMGR    0x0233B5ECu   /* CNetworkMgr* */
#define ADDR_GROUNDMGR         0x00B40738u   /* g_GroundItemManager (static object); list at +4 (std::list node: next +0, data +8) */
#define ADDR_TAKE_ITEM         0x00540360u   /* _itembox_take_request (packet 7/2): void __thiscall(proc, DWORD index, DWORD flag) */

typedef int (__thiscall *FnTakeItem)(void *proc, DWORD index, DWORD flag);
#define ADDR_PTR_MAIN_HWND     0x02455DA4u   /* HWND of the "D3D Window" (its WndProc 0x7ED8C0 -> CMainApp::MsgProc) */
#define ADDR_MAIN_HWND_CODE    0x007EFF75u   /* CreateWindowEx result stored there */
#define ADDR_PTR_GAMEPROCESS   0x0233B5DCu   /* current game process, CGP_MainGame in the world */
#define VTBL_CGP_MAINGAME      0x00A4ADECu
#define GP_KEYMAP              0x80          /* CGP_MainGame: CKeyMap* (the key dispatcher's this, 0x5219FA) */
#define KEYMAP_BINDINGS        0x10          /* CKeyMap: {int modifier, int vk}[76] by action id, -1 = none */
#define KEYMAP_BELT_MODE       0x33C         /* CKeyMap: 0 = belt keys are the actions SLOT_1..SLOT_10, 1 = the
                                                fixed keys ADDR_BELT_KEYS_ALT read from the keyboard state */
#define KEYACTION_SLOT_1       54
#define KEYACTION_COUNT        76
#define ADDR_KEYACTION_NAMES   0x00A4BEC8u   /* char[76][0x20], index = action id */
#define ADDR_BELT_KEYS_ALT     0x00B163ECu   /* BYTE[10] VK of belt slots 1..10 in belt-key mode 1 */
#define ADDR_KEYMAP_CALL_CODE  0x005219F7u   /* CGP_MainGame::vf24: mov ecx, [this+0x80]; call 0x527E10 */
#define ADDR_BELT_MODE_CODE    0x00528820u   /* belt keys: cmp [keymap+0x33C], 0 */
#define ADDR_BELT_ALT_CODE     0x005288C2u   /* belt keys, mode 1: movzx eax, byte [i + 0xB163EC] */
#define ADDR_BOARD_MANAGER     0x023DB090u   /* CBoardManager (static): board[id] at +4 + id*4 (GetBoard 0x493A20) */
#define ADDR_GET_BOARD_CODE    0x00493A45u   /* GetBoard: mov eax, [ecx + eax*4 + 4] */
#define BOARD_LINK             6             /* CLinkBoard: what lies on the belt */
#define VTBL_CLINKBOARD        0x00A4795Cu
#define VT_LINK_USE            0x80
#define ADDR_LINK_USE          0x00496D00u   /* CLinkBoard::UseSlot(BYTE page, BYTE slot), __thiscall ret 8: what a
                                                belt key does (skill / force through CSFBoard, item use) */
#define BOARD_ANIMUS           4             /* CAnimusBoard: your animus (CObjectBoard of entries) */
#define VTBL_CANIMUSBOARD      0x00A46B94u
#define ANIMUSBOARD_TOGGLE     0x00479700u   /* CAnimusBoard::vf74(): summon the selected animus, or recall the
                                                summoned one (the summon / recall button) */
#define ANIMUS_TOGGLE_CODE     0x00479788u   /* vf74: item = Get_E0 (selection) -> 0x4227B0, summon request */
#define BOARDMGR_SELECTED      0xE0          /* CBoardManager: selected board entry (getter 0x40B210) */
#define BOARDMGR_PENDING       0xFC          /* CBoardManager: 1 = a request waits for the server's answer (0x494690;
                                                the summon request 0x54B810 sets it) */
#define BOARDMGR_PENDING_TIME  0x100         /* game time it was set */
#define ADDR_BOARDMGR_SEL_CODE 0x0040B210u
#define OBJBOARD_PAGES         0x0C          /* CObjectBoard: pages, 16 bytes each (0x4911F0) */
#define OBJBOARD_PAGE_COUNT    0x10          /* BYTE */
#define ADDR_OBJBOARD_CODE     0x004911F7u
#define PAGE_SLOTS             0x04          /* page: entry*[] (0x490100) */
#define PAGE_SLOT_COUNT        0x08          /* BYTE */
#define PAGE_VALID             0x0C          /* != 0 */
#define ADDR_PAGE_CODE         0x00490107u
#define ENTRY_ITEM             0x248         /* board entry -> its item (0x4227B0 -> 0x40DD80) */
#define ADDR_ENTRY_ITEM_CODE   0x0040DD80u
#define VTBL_CANIMUSITEM       0x00A45AB4u
#define ITEM_RECORD            0x10          /* CBaseItem: item record, name at +8 (vf18 0x4097D0) */
#define ITEMREC_ITEM_NAME      0x08
#define ADDR_ITEM_NAME_CODE    0x004097D7u
#define ANIMUSITEM_DATA        0x18          /* CAnimusItem: animus record: BYTE +0 level, DWORD +0x10 max HP */
#define ANIMUSDATA_MAX_HP      0x10
#define ANIMUSITEM_HP          0x28          /* CAnimusItem: HP, regenerates while not summoned (22/9, 0x457CB0) */
#define ADDR_ANIMUS_HP_CODE    0x00457CB7u
#define BOARD_ANIMUS_CONTROL   8             /* CAnimusControlBoard: +0x10 = the summoned animus, 0 = none */
#define VTBL_CANIMUSCONTROL    0x00A46B70u
#define ANIMUSCTRL_SUMMONED    0x10
#define ANIMUSCTRL_LIVE        0x0C          /* CAnimusControlBoard: the summoned CAnimus (getter 0x54C2E0) */
#define ADDR_ANIMUS_LIVE_CODE  0x0054C2E0u
#define ADDR_ANIMUS_OUT_CODE   0x0047975Fu   /* CAnimusBoard::vf74 (summon / recall): GetBoard(8)->IsSet (0x40AD00) */
#define ADDR_ANIMUS_SET_GETTER 0x0040AD00u   /* return [this+0x10] != 0 */
#define ADDR_PTR_LINK_WINDOW   0x0233B680u   /* CGUILinkWindow* (the belt window) */
#define LINKWND_PAGE           0xE448        /* BYTE current belt page, 0xFF = none (getter 0x4981C0) */
#define LINKBOARD_PAGE_COUNT   0x10          /* BYTE CObjectBoard page count (5 belt pages, checked at 0x4911F7) */
#define BELT_PAGES             5             /* CGUILinkWindow::SetPage 0x5F0770: page < 5 */
#define BELT_SLOTS             10
#define VT_BOARD_ITEM_KIND     0x88          /* board entry: BOOL __thiscall(int kind): 1 = skill / force, 2 = animus,
                                                0 = item (CLinkBoard::UseSlot 0x496D00) */
#define VT_ITEM_NAME           0x18          /* CItem: const char* __thiscall() */
#define ADDR_ITEM_NAME_BASE    0x004097D0u   /* CBaseItem vf18: record + 8 (items, animus) */
#define ADDR_ITEM_NAME_SF      0x00409E20u   /* CSFItem vf18: record + 0x70 (skills, forces) */
#define VTBL_CSFITEM           0x00A425ECu
#define SF_TYPE                0x18          /* BYTE CSFItem: 0 skill, 1 force, 2 class skill (0x40AC40) */
#define SF_LAST_USE            0x30          /* DWORD CSFItem: game time of the last use (0x412860) */
#define ADDR_CAN_USE_SF        0x00410B20u   /* CAvatar::CanUseSF(BYTE type, CSFItem*), __thiscall ret 8: 1 = usable,
                                                -1 = its own cooldown runs, 0 = shared / global delay */
#define ADDR_SF_BASE_DELAY     0x00410D50u   /* CAvatar: DWORD __thiscall(CSFItem*); the dump had a jmp into a module
                                                outside the image here, the game has the plain function */
#define ADDR_SF_DELAY          0x00410E60u   /* CAvatar: DWORD __thiscall(BYTE type, DWORD base) = the cooldown in ms
                                                (same) */
#define ADDR_LINK_PAGE_GETTER  0x004981C0u
#define ADDR_MOVE_REQUEST      0x00576780u   /* CNetMsgProcessor_Position::MoveRequest(float pos[3], int byMouse,
                                                int skipNear, float stopShort), __thiscall ret 0x10: what a click on
                                                the ground does (CGP_MainGame 0x521EAB): path + _move_request (4/1) */

#define VTBL_CPLAYER           0x00A41FD4u
#define VTBL_CANIMUS           0x00A44A4Cu
#define VTBL_CNPC              0x00A458BCu
#define OBJ_INDEX              0x08          /* DWORD */
#define OBJ_SERIAL             0x0C          /* DWORD */
#define OBJ_TYPE               0x248         /* int, see RF_OBJ_* in rf_client.h */

#define OBJ_ACTION             0x250         /* DWORD current action (CCharacter::IsAction 0x40A8A0) */
#define ACTION_KIND_DIE        0x5           /* action >> 28: dying / dead (0x50000000, CCharacter::vfB8 ->
                                                0x435DF0). The HP rate is no death sign: the client lowers it
                                                itself on hits it sees (0x43EC70), down to 0 for monsters an area
                                                attack touched, and only the target gets its HP from the server */
#define ADDR_IS_ACTION         0x0040A8A0u
#define ADDR_DIE_ACTION_CODE   0x00435DF7u   /* cmp action, 0x50000000 */
#define VT_RENDERNAME          0x24
#define VT_RENDEROVERHEAD      0x84
#define VT_ISSTATE             0x3C          /* returns (flags & mask) != 0 */
#define VT_ISNOTSTATE          0x40          /* returns (flags & mask) == 0 */
#define VT_GETHPRATE           0xEC

#define OBJ_NAME               0x10          /* char[] name                  */
#define OBJ_POS                0x50          /* float[3] world position      */
#define OBJ_ATTACK_RANGE       0x270         /* CAvatar: float melee/attack reach, world units (0x436B80 getter) */
#define OBJ_NAME_BLOCKED       0x31C         /* int, game skips the name if != 0 */
#define OBJ_HIDE_STEALTH       0x5F8         /* BYTE: hidden unless your character detects it (0x4F80A0) */
#define OBJ_HIDE_OTHERS        0x5FB         /* BYTE: hidden from normal players (0x4F8180); both clear state 0x2
                                                and drop the object as the target every frame */
#define AVATAR_OWN_BARS_WIN    0x59BC        /* CAvatar: CGUISelectedPlayerInfoWin* (own HP/FP/SP bars + icon over the head) */
#define TARGETMGR_CHAR_WIN     0x58          /* CTargetMgr: embedded CGUISelectedCharWin (name + bar over the target) */
#define VTBL_SELECTED_CHAR_WIN 0x00A5B41Cu   /* CGUISelectedCharWin vftable        */
#define VTBL_SELECTED_PLAYER_WIN 0x00A5B5FCu /* CGUISelectedPlayerInfoWin vftable  */
#define VT_WIN_SETPOS          0x04          /* CGUIWindow::SetPos(int x, int y), __thiscall */
#define ADDR_WIN_SETPOS        0x005E52F0u   /* CGUIWindow::SetPos, original of both slots */
#define OFFSCREEN_POS          (-20000)

#define STATE_VISIBLE          0x00000002
#define STATE_NO_OVERHEAD      0x00001000

#define TEXT_FLAGS_NAME        0x20          /* flags the game uses for names over heads */

typedef int   (__thiscall *FnRenderName)(void *self);
typedef void  (__thiscall *FnRenderOverhead)(void *self);
typedef int   (__thiscall *FnStateTest)(void *self, DWORD mask);
typedef float (__thiscall *FnGetHPRate)(void *self);
typedef BYTE  (__thiscall *FnGetLevel)(void *self);
typedef int   (__thiscall *FnIsTarget)(void *mgr, void *obj);
typedef int   (__thiscall *FnGetBBox)(void *self, float *out6, int flag);
typedef int   (__cdecl    *FnWorldToScreen)(float *out, const float *pos);
typedef void  (__cdecl    *FnDrawText)(float *pos, const char *text, DWORD color, int flags, float scale);
typedef void  (__cdecl    *FnMeasureText)(const char *text, int *outSize, int len, int flags);
typedef DWORD (__thiscall *FnGetDword)(void *self);
typedef const char *(__thiscall *FnGetString)(void *self);
typedef DWORD (WINAPI     *FnGameTime)(void);
typedef char *(__thiscall *FnFindType5)(void *tables, DWORD code);
typedef int   (__thiscall *FnWinSetPos)(void *win, int x, int y);
typedef char *(__thiscall *FnGetTargetObject)(void *mgr);
typedef void  (__thiscall *FnCheckTarget)(void *mgr, void *obj, int withInfo);
typedef char *(__thiscall *FnGetObject)(void *mgr, int type, int index);
typedef BYTE  (__thiscall *FnAnalysisPacket)(void *self, BYTE *hdr, BYTE *data);
typedef int   (__thiscall *FnMoveRequest)(void *proc, float *pos, int byMouse, int skipNear, float stopShort);
typedef int   (__thiscall *FnLinkUse)(void *board, int page, int slot);
typedef int   (__thiscall *FnBoardItemKind)(void *entry, int kind);
typedef int   (__thiscall *FnCanUseSF)(void *avatar, int type, void *sf);
typedef DWORD (__thiscall *FnSFBaseDelay)(void *avatar, void *sf);
typedef DWORD (__thiscall *FnSFDelay)(void *avatar, int type, DWORD base);

/* Byte signatures of the code the export calls (and of the two unpack indicators), verified before installing
 * the hook. The drawing functions of the removed HP bars are no longer checked: a client where only those
 * differ starts the bot anyway. */
typedef struct {
    const char *name;
    DWORD       addr;
    BYTE        bytes[16];
} CodeSig;

static const CodeSig g_sigs[] = {
    { "RenderName",     ADDR_RENDERNAME,      { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x6A,0x02,0x8B,0x45,0xFC,0x8B,0x10,0x8B,0x4D } },
    { "AvatarOverhead", ADDR_AVATAR_OVERHEAD, { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x4D,0xFC,0xE8,0xC1,0x0E,0x03,0x00,0x8B } },
    { "IsTarget",       ADDR_IS_TARGET,       { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0x08,0x50,0x8B,0x4D,0xFC,0xE8,0x7D } },
    { "GetHPRate",      ADDR_GET_HPRATE,      { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0xD9,0x80,0x74,0x02,0x00,0x00 } },
    { "MonsterLevel",   ADDR_MONSTER_LEVEL,   { 0x55,0x8B,0xEC,0x83,0xEC,0x08,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x83,0xB8,0xBC,0x11 } },
    { "PlayerLevel",    ADDR_PLAYER_LEVEL,    { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x8B,0x80,0x24,0x40,0x00,0x00 } },
    { "SFDuration",     ADDR_SF_DURATION,     { 0x55,0x8B,0xEC,0x51,0x56,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x83,0x78,0x10,0x00,0x75 } },
    { "SFFindType5",    ADDR_SF_FIND_TYPE5,   { 0x55,0x8B,0xEC,0x83,0xEC,0x0C,0x89,0x4D,0xF4,0xC7,0x45,0xF8,0x00,0x00,0x00,0x00 } },
    { "SFGetName",      0x00409E20u,          { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x83,0x78,0x10,0x00,0x74,0x0F } },
};

/* ==================================== Config ==================================== */


typedef struct {
    int vk;
    int ctrl;
    int shift;
    int alt;
    int wasDown;
} Hotkey;

typedef struct {
    /* [HPBars] */
    int    enabled;
    int    width;
    int    height;
    int    offsetY;
    int    border;
    int    opacity;
    int    colorMode;      /* 1 = green -> yellow -> red by HP, 0 = fixed color */
    DWORD  fillColor;      /* RGB, used when colorMode == 0 */
    DWORD  backColor;      /* RGB */
    DWORD  borderColor;    /* RGB */
    int    hideFullHP;
    int    skipTarget;
    int    showDead;
    int    maxDistance;    /* world units, 0 = unlimited */
    int    showPercent;
    int    showName;
    int    showLevel;
    int    labelStyle;     /* 0 = "Name Lv.N", 1 = "Lv.N Name", 2 = "[N] Name" */
    int    labelGap;       /* pixels between label and bar */
    int    replaceGameName;
    int    ignoreOcclusion;  /* 1 = draw even when the game hides overhead info (occlusion flag 0x1000) */
    int    hideTargetWindow; /* 1 = move the game's window above the target off-screen */
    int    hideOwnBars;      /* 1 = move the HP/FP/SP bars + icon above your character off-screen */
    DWORD  labelColor;     /* RGB of the name / level label */
    int    labelBarColor;  /* 1 = the label takes the bar color instead of labelColor */
    int    dot;            /* 1 = filled circle under the middle of the bar */
    int    dotRadius;      /* pixels */
    int    dotGap;         /* pixels between the bar and the circle */
    DWORD  dotColor;       /* RGB */
    int    dotOpacity;
    int    dotOutline;
    Hotkey toggle;

    /* [Markers] */
    int    markersEnabled;
    float  markerRadius;   /* world units */
    float  removeRadius;   /* world units */
    float  markerLift;     /* world units above the ground point */
    int    markerSegments;
    DWORD  markerColor;    /* RGB */
    int    markerOpacity;
    int    markerOutline;
    Hotkey markKey;
    Hotkey clearKey;

    /* [Bot] */
    int    botEnabled;
    int    botInterval;       /* ms between snapshots */
    int    botStartDelay;     /* ms in the world before the first snapshot */
    UINT   codepage;          /* game text codepage, names are converted to UTF-8 */
    int    botKeyHold;        /* ms a key pressed by the bot is held down */
    int    botKeysInactive;   /* 1 = the bot's key presses also work while another window is active */
    char   botBeltKeys[16];   /* keys of belt slots 1..10 in order ("1234567890"), empty = the game's binding */
    char   botName[MAX_PATH]; /* shared memory name */
} Config;

static Config  g_cfg;
static HMODULE g_self;
static char    g_dir[MAX_PATH];
static char    g_iniPath[MAX_PATH];
static char    g_logPath[MAX_PATH];
static char    g_tmpName[64];   /* scratch for masked strings */

/* ================================= Hook state =================================== */

typedef struct {
    const char *name;
    DWORD       vtable;
    DWORD       offset;
    DWORD       expected;     /* original function address */
    DWORD       hook;
    DWORD       original;     /* what was in the slot when we installed (may be another mod) */
    int         installed;
} VtHook;

static void __thiscall Hook_AvatarOverhead(void *self);

/* g_hookMonster is never installed: its slot only tells that the client has unpacked itself (InitThread). */
static VtHook g_hookMonster = { "CMonster::RenderName",     ADDR_CMONSTER_VTBL, VT_RENDERNAME,     ADDR_RENDERNAME,      0, 0, 0 };
static VtHook g_hookAvatar  = { "CAvatar::RenderOverhead",  ADDR_CAVATAR_VTBL,  VT_RENDEROVERHEAD, ADDR_AVATAR_OVERHEAD, 0, 0, 0 };

/* Bot export ([Bot] section): who attacks whom comes from the combat packets */
static BYTE __thiscall Hook_CombatPacket(void *self, BYTE *hdr, BYTE *data);
static VtHook g_hookCombat  = { "CNetMsgProcessor_Combat::AnalysisServerPacket", VTBL_COMBAT_PROCESSOR, VT_ANALYSIS_PACKET,
                                ADDR_COMBAT_ANALYSIS, 0, 0, 0 };

/* ================================ Marker state ================================== */

#define MAX_MARKERS        32
#define MAX_SEGMENTS       48   /* [Markers] Segments upper bound (the ini keeps the setting) */

typedef struct {
    float x, y, z;
} Vec3;

static Vec3 g_markers[MAX_MARKERS];
static int  g_markerCount;

/* ===================================== Log ====================================== */

static void Log(const char *fmt, ...)
{
    char line[1200];
    char body[1100];
    SYSTEMTIME st;
    HANDLE file;
    DWORD written;
    int len;
    __builtin_va_list args;

    __builtin_va_start(args, fmt);
    wvsprintfA(body, fmt, args);
    __builtin_va_end(args);

    GetLocalTime(&st);
    len = wsprintfA(line, "%02u:%02u:%02u.%03u  %s\r\n",
                    st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, body);

    file = CreateFileA(g_logPath, GENERIC_WRITE, FILE_SHARE_READ, NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    SetFilePointer(file, 0, NULL, FILE_END);
    WriteFile(file, line, (DWORD)len, &written, NULL);
    CloseHandle(file);
}

/* ================================ Config loading ================================ */

static char g_defaultIni[sizeof(S_03)];
#define DEFAULT_INI_DECODE() DecodeS(S_03, (int)sizeof(S_03), g_defaultIni)

static DWORD ParseNumber(const char *s, DWORD fallback)
{
    DWORD value = 0;
    int digits = 0;

    while (*s == ' ' || *s == '\t') s++;
    if (*s == '#') s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        s += 2;
        for (; *s; s++) {
            char c = *s;
            int d;
            if (c >= '0' && c <= '9') d = c - '0';
            else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
            else break;
            value = (value << 4) | (DWORD)d;
            digits++;
        }
    } else {
        for (; *s >= '0' && *s <= '9'; s++) {
            value = value * 10 + (DWORD)(*s - '0');
            digits++;
        }
    }
    return digits ? value : fallback;
}

static int ReadInt(const char *section, const char *key, int fallback)
{
    char buf[64];
    int negative = 0;
    const char *p;
    DWORD value;

    GetPrivateProfileStringA(section, key, "", buf, sizeof(buf), g_iniPath);
    p = buf;
    while (*p == ' ' || *p == '\t') p++;
    if (*p == '-') { negative = 1; p++; }
    if (!*p) return fallback;
    value = ParseNumber(p, 0xFFFFFFFFu);
    if (value == 0xFFFFFFFFu) return fallback;
    return negative ? -(int)value : (int)value;
}

static DWORD ReadColor(const char *section, const char *key, DWORD fallback)
{
    char buf[64];
    GetPrivateProfileStringA(section, key, "", buf, sizeof(buf), g_iniPath);
    return ParseNumber(buf, fallback) & 0x00FFFFFF;
}

static int Clamp(int v, int lo, int hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

static void ReadHotkey(Hotkey *hk, const char *section, const char *prefix, int vk, int ctrl, int shift, int alt)
{
    char key[32];

    wsprintfA(key, "%sKey", prefix);   hk->vk    = Clamp(ReadInt(section, key, vk), 0, 0xFE);
    wsprintfA(key, "%sCtrl", prefix);  hk->ctrl  = ReadInt(section, key, ctrl) != 0;
    wsprintfA(key, "%sShift", prefix); hk->shift = ReadInt(section, key, shift) != 0;
    wsprintfA(key, "%sAlt", prefix);   hk->alt   = ReadInt(section, key, alt) != 0;
    hk->wasDown = 0;
}

static void WriteDefaultIni(void)
{
    HANDLE file;
    DWORD written;

    DEFAULT_INI_DECODE();
    file = CreateFileA(g_iniPath, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    WriteFile(file, g_defaultIni, sizeof(g_defaultIni) - 1, &written, NULL);
    CloseHandle(file);
    Log("created default %s", g_iniPath);
}

static void LoadConfig(void)
{
    static const char HB[] = "HPBars";
    static const char MK[] = "Markers";
    static const char EF[] = "Effects";   /* older ini: Codepage was there */
    static const char BT[] = "Bot";

    if (GetFileAttributesA(g_iniPath) == INVALID_FILE_ATTRIBUTES)
        WriteDefaultIni();

    g_cfg.enabled         = ReadInt(HB, "Enabled", 1) != 0;
    g_cfg.width           = Clamp(ReadInt(HB, "Width", 50), 8, 400);
    g_cfg.height          = Clamp(ReadInt(HB, "Height", 5), 2, 40);
    g_cfg.offsetY         = Clamp(ReadInt(HB, "OffsetY", -7), -300, 300);
    g_cfg.border          = ReadInt(HB, "Border", 1) != 0;
    g_cfg.opacity         = Clamp(ReadInt(HB, "Opacity", 220), 0, 255);
    g_cfg.colorMode       = ReadInt(HB, "ColorMode", 1);
    g_cfg.fillColor       = ReadColor(HB, "FillColor", 0xD02020);
    g_cfg.backColor       = ReadColor(HB, "BackColor", 0x202020);
    g_cfg.borderColor     = ReadColor(HB, "BorderColor", 0x000000);
    g_cfg.hideFullHP      = ReadInt(HB, "HideFullHP", 0) != 0;
    g_cfg.skipTarget      = ReadInt(HB, "SkipTarget", 0) != 0;
    g_cfg.showDead        = ReadInt(HB, "ShowDead", 0) != 0;
    g_cfg.maxDistance     = Clamp(ReadInt(HB, "MaxDistance", 0), 0, 100000);
    g_cfg.showPercent     = ReadInt(HB, "ShowPercent", 0) != 0;
    g_cfg.showName        = ReadInt(HB, "ShowName", 1) != 0;
    g_cfg.showLevel       = ReadInt(HB, "ShowLevel", 1) != 0;
    g_cfg.labelStyle      = Clamp(ReadInt(HB, "LabelStyle", 0), 0, 2);
    g_cfg.labelGap        = Clamp(ReadInt(HB, "LabelGap", 1), -20, 50);
    g_cfg.replaceGameName = ReadInt(HB, "ReplaceGameName", 1) != 0;
    g_cfg.ignoreOcclusion = ReadInt(HB, "IgnoreOcclusion", 1) != 0;
    g_cfg.hideTargetWindow = ReadInt(HB, "HideTargetWindow", 1) != 0;
    g_cfg.hideOwnBars     = ReadInt(HB, "HideOwnBars", 1) != 0;
    g_cfg.labelColor      = ReadColor(HB, "LabelColor", 0xFFFFFF);
    g_cfg.labelBarColor   = ReadInt(HB, "LabelBarColor", 0) != 0;
    g_cfg.dot             = ReadInt(HB, "Dot", 0) != 0;
    g_cfg.dotRadius       = Clamp(ReadInt(HB, "DotRadius", 10), 1, 40);
    g_cfg.dotGap          = Clamp(ReadInt(HB, "DotGap", 2), -50, 100);
    g_cfg.dotColor        = ReadColor(HB, "DotColor", 0xFF0000);
    g_cfg.dotOpacity      = Clamp(ReadInt(HB, "DotOpacity", 255), 0, 255);
    g_cfg.dotOutline      = ReadInt(HB, "DotOutline", 1) != 0;
    ReadHotkey(&g_cfg.toggle, HB, "Toggle", 0x48, 1, 1, 0);

    g_cfg.markersEnabled  = ReadInt(MK, "Enabled", 1) != 0;
    g_cfg.markerRadius    = (float)Clamp(ReadInt(MK, "Radius", 150), 1, 10000) * 0.1f;
    g_cfg.removeRadius    = (float)Clamp(ReadInt(MK, "RemoveRadius", 400), 1, 100000) * 0.1f;
    g_cfg.markerLift      = (float)Clamp(ReadInt(MK, "Lift", 3), -1000, 1000) * 0.1f;
    g_cfg.markerSegments  = Clamp(ReadInt(MK, "Segments", 24), 8, MAX_SEGMENTS);
    g_cfg.markerColor     = ReadColor(MK, "Color", 0xFFD800);
    g_cfg.markerOpacity   = Clamp(ReadInt(MK, "Opacity", 200), 0, 255);
    g_cfg.markerOutline   = ReadInt(MK, "Outline", 1) != 0;
    ReadHotkey(&g_cfg.markKey, MK, "Mark", 0x4D, 1, 1, 0);
    ReadHotkey(&g_cfg.clearKey, MK, "Clear", 0x4E, 1, 1, 0);

    Log("config [HPBars]: Enabled=%d Width=%d Height=%d OffsetY=%d Border=%d Opacity=%d ColorMode=%d "
        "HideFullHP=%d SkipTarget=%d ShowDead=%d MaxDistance=%d ShowPercent=%d ShowName=%d ShowLevel=%d "
        "LabelStyle=%d LabelGap=%d LabelColor=0x%06lX LabelBarColor=%d ReplaceGameName=%d IgnoreOcclusion=%d "
        "HideTargetWindow=%d HideOwnBars=%d Dot=%d DotRadius=%d DotGap=%d DotColor=0x%06lX "
        "DotOpacity=%d DotOutline=%d ToggleKey=0x%02X (C%d S%d A%d)",
        g_cfg.enabled, g_cfg.width, g_cfg.height, g_cfg.offsetY, g_cfg.border, g_cfg.opacity, g_cfg.colorMode,
        g_cfg.hideFullHP, g_cfg.skipTarget, g_cfg.showDead, g_cfg.maxDistance, g_cfg.showPercent,
        g_cfg.showName, g_cfg.showLevel, g_cfg.labelStyle, g_cfg.labelGap, g_cfg.labelColor, g_cfg.labelBarColor,
        g_cfg.replaceGameName,
        g_cfg.ignoreOcclusion, g_cfg.hideTargetWindow, g_cfg.hideOwnBars,
        g_cfg.dot, g_cfg.dotRadius, g_cfg.dotGap, g_cfg.dotColor, g_cfg.dotOpacity, g_cfg.dotOutline,
        g_cfg.toggle.vk, g_cfg.toggle.ctrl, g_cfg.toggle.shift, g_cfg.toggle.alt);
    Log("config [Markers]: Enabled=%d Radius=%d RemoveRadius=%d Lift=%d Segments=%d Color=0x%06lX Opacity=%d Outline=%d "
        "MarkKey=0x%02X (C%d S%d A%d) ClearKey=0x%02X (C%d S%d A%d)",
        g_cfg.markersEnabled, (int)(g_cfg.markerRadius * 10.0f), (int)(g_cfg.removeRadius * 10.0f),
        (int)(g_cfg.markerLift * 10.0f), g_cfg.markerSegments, g_cfg.markerColor, g_cfg.markerOpacity,
        g_cfg.markerOutline, g_cfg.markKey.vk, g_cfg.markKey.ctrl, g_cfg.markKey.shift, g_cfg.markKey.alt,
        g_cfg.clearKey.vk, g_cfg.clearKey.ctrl, g_cfg.clearKey.shift, g_cfg.clearKey.alt);

    g_cfg.botEnabled  = ReadInt(BT, "Enabled", 1) != 0;
    g_cfg.botInterval = Clamp(ReadInt(BT, "IntervalMs", 100), 50, 1000);
    g_cfg.botStartDelay = Clamp(ReadInt(BT, "StartDelayMs", 3000), 0, 60000);
    g_cfg.codepage = (UINT)Clamp(ReadInt(BT, "Codepage", ReadInt(EF, "Codepage", 1252)), 0, 65001);
    g_cfg.botKeyHold = Clamp(ReadInt(BT, "KeyHoldMs", 150), 30, 1000);
    g_cfg.botKeysInactive = ReadInt(BT, "KeysWhileInactive", 1) != 0;
    GetPrivateProfileStringA(BT, "BeltKeys", "", g_cfg.botBeltKeys, sizeof(g_cfg.botBeltKeys), g_iniPath);
    if (!g_cfg.botBeltKeys[0])    /* the belt in this client: 1..0 (KeyMap SLOT_x is Ctrl+F1..Ctrl+F10) */
        lstrcpynA(g_cfg.botBeltKeys, "1234567890", sizeof(g_cfg.botBeltKeys));
    if ((g_cfg.botBeltKeys[0] | 0x20) == 'a' && (g_cfg.botBeltKeys[1] | 0x20) == 'u'
        && (g_cfg.botBeltKeys[2] | 0x20) == 't' && (g_cfg.botBeltKeys[3] | 0x20) == 'o' && !g_cfg.botBeltKeys[4])
        g_cfg.botBeltKeys[0] = 0;   /* auto: as the game's KeyMap binds them */
    {
        char shmDef[40];
        MASKSTR(shmDef, S_SHM);
        GetPrivateProfileStringA(BT, "SharedName", shmDef, g_cfg.botName, sizeof(g_cfg.botName), g_iniPath);
        if (!g_cfg.botName[0]) lstrcpynA(g_cfg.botName, shmDef, sizeof(g_cfg.botName));
    }
    Log(MS(S_04), g_cfg.botEnabled, g_cfg.botInterval, g_cfg.botStartDelay, g_cfg.codepage,
        g_cfg.botKeyHold, g_cfg.botKeysInactive,
        g_cfg.botBeltKeys[0] ? g_cfg.botBeltKeys : "(the game's binding)", g_cfg.botName);
}

/* ================================ Memory helpers ================================ */

static int IsReadable(DWORD addr, DWORD size)
{
    MEMORY_BASIC_INFORMATION mbi;
    unsigned long long end;

    if (!VirtualQuery((LPCVOID)addr, &mbi, sizeof(mbi))) return 0;
    if (mbi.State != MEM_COMMIT) return 0;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return 0;
    end = (unsigned long long)(DWORD)(size_t)mbi.BaseAddress + mbi.RegionSize;   /* 64-bit: addr+size may wrap */
    return (unsigned long long)addr + size <= end;
}

static int CheckSignatures(int verbose)
{
    unsigned int i;
    int ok = 1;

    for (i = 0; i < sizeof(g_sigs) / sizeof(g_sigs[0]); i++) {
        const CodeSig *sig = &g_sigs[i];
        const BYTE *code = (const BYTE *)sig->addr;
        int j;
        if (!IsReadable(sig->addr, 16)) { ok = 0; continue; }
        for (j = 0; j < 16; j++) {
            if (code[j] != sig->bytes[j]) {
                if (verbose)
                    Log("signature mismatch: %s @0x%08lX byte %d: %02X != %02X",
                        sig->name, sig->addr, j, code[j], sig->bytes[j]);
                ok = 0;
                break;
            }
        }
    }
    return ok;
}

static int CheckRtti(DWORD vtable, const char *expected)
{
    DWORD col, td;
    const char *name;
    int i, len = lstrlenA(expected);

    if (!IsReadable(vtable - 4, 4)) return 0;
    col = *(DWORD *)(vtable - 4);
    if (!IsReadable(col + 12, 4)) return 0;
    td = *(DWORD *)(col + 12);
    if (!IsReadable(td + 8, (DWORD)len + 1)) return 0;
    name = (const char *)(td + 8);
    for (i = 0; i <= len; i++)
        if (name[i] != expected[i]) return 0;
    return 1;
}

/* ================================ VTable helpers ================================ */

#define VTBL(obj)       (*(void ***)(obj))
#define VCALL(obj, idx) (VTBL(obj)[idx])

/* ================================== Hotkeys ===================================== */

static int IsGameForeground(void)
{
    DWORD pid = 0;
    HWND wnd = GetForegroundWindow();
    if (!wnd) return 0;
    GetWindowThreadProcessId(wnd, &pid);
    return pid == GetCurrentProcessId();
}

static int KeyDown(int vk)
{
    return (GetAsyncKeyState(vk) & 0x8000) != 0;
}

/* Returns 1 once per press (edge), 0 otherwise. */
static int HotkeyPressed(Hotkey *hk, int foreground)
{
    int down;

    if (!hk->vk) return 0;
    down = foreground
        && KeyDown(hk->vk)
        && (!hk->ctrl  || KeyDown(VK_CONTROL))
        && (!hk->shift || KeyDown(VK_SHIFT))
        && (!hk->alt   || KeyDown(VK_MENU));
    if (down && !hk->wasDown) {
        hk->wasDown = 1;
        return 1;
    }
    hk->wasDown = down;
    return 0;
}

static void ToggleMarkerAtAvatar(void);
static void ClearMarkers(void);

/* Called from the avatar hook; rate-limited, so it runs at most every 30 ms. */
static void PollHotkeys(void)
{
    static DWORD lastPoll;
    DWORD now = GetTickCount();
    int fg;

    if (now - lastPoll < 30) return;
    lastPoll = now;
    fg = IsGameForeground();

    if (g_cfg.markersEnabled) {
        if (HotkeyPressed(&g_cfg.markKey, fg)) ToggleMarkerAtAvatar();
        if (HotkeyPressed(&g_cfg.clearKey, fg)) ClearMarkers();
    }
}

static const BYTE g_sigIsAction[16]  = { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x8B,0x88,0x50,0x02,0x00,0x00 };
static const BYTE g_sigDieAction[16] = { 0x81,0x7D,0x08,0x00,0x00,0x00,0x50,0x0F,0x85,0xE6,0x00,0x00,0x00,0x68,0x00,0x09 };
static int g_dieCheck;   /* 1 = the action field and the die action matched: dying is known */

/* 1 = the character is dying / dead (its die action runs), 0 = alive or unknown. */
static int IsDying(const char *obj)
{
    return g_dieCheck && (*(const DWORD *)(obj + OBJ_ACTION) >> 28) == ACTION_KIND_DIE;
}

/* ================================ Ground markers ================================ */

static void ToggleMarkerAtAvatar(void)
{
    char *avatar = *(char **)ADDR_PTR_AVATAR;
    Vec3 p;
    int i, nearest = -1;
    float best = 0.0f;
    float rr = g_cfg.removeRadius * g_cfg.removeRadius;

    if (!avatar) return;
    p.x = *(float *)(avatar + OBJ_POS + 0);
    p.y = *(float *)(avatar + OBJ_POS + 4);
    p.z = *(float *)(avatar + OBJ_POS + 8);

    for (i = 0; i < g_markerCount; i++) {
        float dx = g_markers[i].x - p.x;
        float dz = g_markers[i].z - p.z;
        float d = dx * dx + dz * dz;
        if (d <= rr && (nearest < 0 || d < best)) {
            nearest = i;
            best = d;
        }
    }

    if (nearest >= 0) {
        Log("marker removed at (%d, %d, %d)", (int)g_markers[nearest].x, (int)g_markers[nearest].y, (int)g_markers[nearest].z);
        g_markers[nearest] = g_markers[g_markerCount - 1];
        g_markerCount--;
        return;
    }

    if (g_markerCount >= MAX_MARKERS) {
        Log("marker limit (%d) reached, clear some markers first", MAX_MARKERS);
        return;
    }
    g_markers[g_markerCount++] = p;
    Log("marker added at (%d, %d, %d), total %d", (int)p.x, (int)p.y, (int)p.z, g_markerCount);
}

static void ClearMarkers(void)
{
    if (g_markerCount) Log("all %d markers cleared", g_markerCount);
    g_markerCount = 0;
}

/* ============================ Effects on your character ========================== */

/* Game text (ANSI codepage) -> UTF-8. Falls back to the raw bytes if conversion fails. */
static void ToUtf8(const char *src, char *dst, int dstSize)
{
    WORD wide[512];
    char tmp[1024];
    UINT cp = g_cfg.codepage ? g_cfg.codepage : 1251;
    int n;

    if (dstSize <= 0) return;
    dst[0] = 0;
    if (!src) return;

    /* game text (cp1251) -> UTF-8. A plain cp1251-copy happens only if the conversion really fails. */
    n = MultiByteToWideChar(cp, MB_ERR_INVALID_CHARS, src, -1, wide, 512);
    if (n <= 0)                                   /* the string has bytes undefined in cp: retry lenient */
        n = MultiByteToWideChar(cp, 0, src, -1, wide, 512);
    if (n > 0 && WideCharToMultiByte(CP_UTF8, 0, wide, -1, tmp, sizeof(tmp), NULL, NULL) > 0) {
        int i;
        for (i = 0; i < dstSize - 1 && tmp[i]; i++) dst[i] = tmp[i];
        dst[i] = 0;
        return;
    }
    lstrcpynA(dst, src, dstSize);
}

typedef struct {
    const char *group;      /* "buff", "debuff", "potion" (doping slots), "abnormal" (record kind 4/5 slots) */
    int         slot;
    const char *name;       /* raw game text (item name for potions, effect name otherwise) */
    const char *effect;     /* raw game text, effect name */
    int         level;
    long        remainMs;   /* -1 = no client-side timer */
    DWORD       durationMs;
    int         type;
    DWORD       index;
    DWORD       code;
} EffectRef;

/* Fills an EffectRef from a CSFItem (buff/debuff/abnormal slots). */
static void FillFromSFItem(EffectRef *e, const char *group, int slot, char *item, long remainMs)
{
    void **vt = VTBL(item);

    e->group = group;
    e->slot = slot;
    e->name = ((FnGetString)vt[VT_SF_GETNAME / 4])(item);
    e->effect = e->name;
    e->level = *(BYTE *)(item + SFITEM_LEVEL) + *(BYTE *)(item + SFITEM_LEVEL_BONUS);
    e->remainMs = remainMs;
    e->durationMs = ((FnGetDword)ADDR_SF_DURATION)(item);
    e->type = *(BYTE *)(item + SFITEM_TYPE);
    e->index = ((FnGetDword)vt[VT_SF_GETINDEX / 4])(item);
    e->code = ((FnGetDword)vt[VT_SF_GETCODE / 4])(item);
}

static int SFItemUsed(const char *item)
{
    return *(const long *)(item + SFITEM_INDEX) != -1 && *(void *const *)(item + SFITEM_RECORD) != NULL;
}

static int CollectEffects(char *avatar, EffectRef *out, int max, DWORD now)
{
    char *c = avatar + OBJ_EFFECTS;
    int n = 0, kind, i;
    DWORD elapsed = 0;
    int cap = 0;
    int containerReady = *(void **)(c + EFF_OWNER) != NULL;

    if (containerReady) {
        elapsed = now - *(DWORD *)(c + EFF_LAST_TICK);
        if ((long)elapsed < 0) elapsed = 0;
        cap = *(BYTE *)(c + EFF_CAPACITY);
        if (cap > 32) cap = 32;
    }

    /* Debuffs (kind 0, contKind 2 "damage") and buffs (kind 1, contKind 3 "help"), like the server's m_SFCont[2][8] */
    for (kind = 0; containerReady && kind < 2; kind++) {
        char *items = *(char **)(c + EFF_ITEMS + kind * 4);
        DWORD *remain = *(DWORD **)(c + EFF_REMAIN + kind * 4);
        if (!items) continue;
        for (i = 0; i < cap && n < max; i++) {
            char *item = items + i * SFITEM_SIZE;
            long rem = -1;
            if (!SFItemUsed(item)) continue;
            if (remain) rem = remain[i] > elapsed ? (long)(remain[i] - elapsed) : 0;
            FillFromSFItem(&out[n++], kind == 0 ? "debuff" : "buff", i, item, rem);
        }
    }

    /* Doping potions: two slots in CAvatar, filled when a potion is used (0x41AAB0), cleared on discharge (0x41AE00) */
    for (i = 0; i < AVATAR_DOPING_SLOTS && n < max; i++) {
        char *rec = *(char **)(avatar + AVATAR_DOPING_ITEM + i * 4);
        DWORD end = *(DWORD *)(avatar + AVATAR_DOPING_END + i * 4);
        void *tables = *(void **)ADDR_PTR_SF_TABLES;
        char *eff = NULL;
        EffectRef *e;

        if (!rec) continue;
        if (tables) eff = ((FnFindType5)ADDR_SF_FIND_TYPE5)(tables, *(DWORD *)(rec + ITEMREC_EFFECT_CODE));
        e = &out[n++];
        e->group = "potion";
        e->slot = i;
        e->name = rec + ITEMREC_NAME;
        e->effect = eff ? eff + SFREC_NAME : e->name;
        e->level = 0;
        e->remainMs = (long)(end - now) > 0 ? (long)(end - now) : 0;
        e->durationMs = eff ? *(DWORD *)(eff + SFREC_DURATION) : 0;
        e->type = 5;
        e->index = *(DWORD *)(rec + 0);
        e->code = *(DWORD *)(rec + ITEMREC_EFFECT_CODE);
    }

    /* Abnormal states (record kind 4: two timed slots, kind 5: one slot without a timer) */
    for (i = 0; containerReady && i < 2 && n < max; i++) {
        char *item = c + EFF_SLOT4_ITEMS + i * SFITEM_SIZE;
        DWORD rem = *(DWORD *)(c + EFF_SLOT4_REMAIN + i * 4);
        if (!SFItemUsed(item)) continue;
        FillFromSFItem(&out[n++], "abnormal", i, item, rem > elapsed ? (long)(rem - elapsed) : 0);
    }
    if (containerReady && n < max && SFItemUsed(c + EFF_SLOT5_ITEM))
        FillFromSFItem(&out[n++], "abnormal", 2, c + EFF_SLOT5_ITEM, -1);

    return n;
}

/* =============================== Bot state export =============================== */

/*
 * Binary snapshot for rf.py (its ctypes mirror must match). Every field is a 4-byte value or a char
 * array whose size is a multiple of 4, so the layout has no padding. Bump BOT_VERSION on any change.
 *
 * Writer (game thread): seq becomes odd, the body is copied, seq becomes even again.
 * Reader: copies the snapshot and keeps it only if seq was even and did not change around the copy.
 */
#define BOT_MAGIC          0x53424652u   /* MS(S_05) */
#define BOT_VERSION        10    /* 10: BotStatus.loot (BOT_CMD_LOOT works); older builds lack the loot command */
#define BOT_MAP_SIZE       0x10000
#define BOT_MAX_ENTITIES   256
#define BOT_MAX_EFFECTS    48
#define BOT_NAME_LEN       64

#define BOTF_VISIBLE       0x0001   /* state flag 0x2 (rendered this frame)        */
#define BOTF_TARGET        0x0002   /* CTargetMgr::IsTarget                         */
#define BOTF_NO_OVERHEAD   0x0040   /* state flag 0x1000 (occluded)                 */
#define BOTF_DYING         0x0100   /* its die action runs (HPBars 1.15+); HP 0 alone is no death */
#define BOTF_HIDDEN        0x0200   /* the game hides it from you and drops it as a target (HPBars 1.20+) */

typedef struct {
    DWORD ptr;
    int   type;            /* object type, CCharacter+0x248 */
    DWORD index;
    DWORD serial;
    DWORD flags;           /* BOTF_* */
    DWORD vtable;
    int   level;
    float hp;              /* 0..1 */
    float pos[3];          /* world position (feet) */
    int   victimType;      /* monsters: who it attacked last (_attack_monster_inform_zocl 5/13), -1 = nobody */
    DWORD victimIndex;
    DWORD victimAgeMs;     /* ms since that attack, 0xFFFFFFFF = never */
    char  name[BOT_NAME_LEN];
} BotEntity;

typedef struct {
    char  group[12];       /* "buff", "debuff", "potion", "abnormal" */
    int   slot;
    int   level;
    int   remainMs;        /* -1 = no client-side timer */
    DWORD durationMs;
    int   type;
    DWORD index;
    DWORD code;
    char  name[BOT_NAME_LEN];
    char  effect[BOT_NAME_LEN];
} BotEffect;

typedef struct {
    float pos[3];
} BotMarker;

typedef struct {
    DWORD     magic;
    DWORD     version;
    DWORD     seq;
    DWORD     snapshotSize;
    DWORD     entitySize;
    DWORD     effectSize;
    DWORD     counter;          /* snapshots written since the game started */
    DWORD     tick;             /* GetTickCount() of the write (same clock in every process) */
    DWORD     gameTime;         /* effects clock */
    DWORD     pid;
    DWORD     intervalMs;
    int       targetPresent;
    float     attackRange;      /* your melee/attack reach in world units (CAvatar), 0 if unknown */
    BotEntity avatar;
    BotEntity target;
    DWORD     markerCount;
    BotMarker markers[MAX_MARKERS];
    DWORD     effectCount;
    BotEffect effects[BOT_MAX_EFFECTS];
    DWORD     entityTotal;      /* objects seen, may be more than entityCount */
    DWORD     entityCount;
    BotEntity entities[BOT_MAX_ENTITIES];
} BotSnapshot;

/*
 * Status block at the end of the mapping, written directly (no seqlock) on every check: tells the bot why there
 * is no snapshot (not in the world yet, waiting, export failed with an exception, ...).
 */
#define BOT_STATUS_OFFSET  0xFF00
#define BOT_STATUS_MAGIC   0x51424652u   /* MS(S_06) */

enum { BOT_STATE_WAIT_AVATAR, BOT_STATE_WAIT_LEVEL, BOT_STATE_WAIT_DELAY, BOT_STATE_RUNNING, BOT_STATE_FAILED };

/*
 * Command block (bot -> game): the bot writes op/type/index/serial, then seq. Every new seq is executed
 * once on the game thread; the result goes to the status block (cmdSeq/cmdResult).
 */
#define BOT_COMMAND_OFFSET 0xF100   /* ground list grew (owner field): keep it below BOT_STATUS_OFFSET */

enum { BOT_CMD_NONE, BOT_CMD_SELECT, BOT_CMD_CLEAR, BOT_CMD_KEY, BOT_CMD_MOVE, BOT_CMD_SUMMON, BOT_CMD_SLOT,
       BOT_CMD_ANIMUS_SELECT, BOT_CMD_LOOT, BOT_CMD_UNHOOK, BOT_CMD_EJECT };
enum { BOT_CMDR_NONE, BOT_CMDR_OK, BOT_CMDR_NOT_FOUND, BOT_CMDR_SERIAL, BOT_CMDR_CLASS, BOT_CMDR_UNKNOWN,
       BOT_CMDR_NOT_READY, BOT_CMDR_REFUSED, BOT_CMDR_STALE };

typedef struct {
    DWORD seq;
    DWORD tick;           /* GetTickCount() when the bot wrote the command (staleness: see BOT_CMD_STALE_MS) */
    DWORD op;             /* BOT_CMD_* */
    int   type;           /* BOT_CMD_SELECT: object type (1 = monster), index, serial; BOT_CMD_SLOT: belt page
                             (0 = page 1 ... 4 = page 5), -1 = the page the belt shows */
    DWORD index;          /* BOT_CMD_KEY: virtual-key code of the key to press; BOT_CMD_SUMMON / BOT_CMD_ANIMUS_SELECT:
                             animus entry; BOT_CMD_SLOT: belt slot 0..9 (key 1 ... key 0) */
    DWORD serial;
    DWORD hwnd;           /* BOT_CMD_KEY: the game window (as the bot found it), 0 = the last one */
    float pos[3];         /* BOT_CMD_MOVE: world point to walk to (x, y, z) */
} BotCommand;

/* A command the bot wrote more than this long ago is stale: the game thread was blocked (window minimized,
 * loading) and executing it now would fire a MOVE / KEY out of context. Reported as BOT_CMDR_STALE. */
#define BOT_CMD_STALE_MS  1000   /* the bot waits 1.2 s for an answer: a command it gave up on never runs late */

typedef struct {
    DWORD magic;
    DWORD state;          /* BOT_STATE_* */
    DWORD tick;           /* GetTickCount() of the last check for your own character */
    DWORD hookCalls;      /* CAvatar::RenderOverhead calls seen (any CAvatar) */
    DWORD hookSelf;       /* CAvatar of the last call */
    DWORD avatar;         /* g_pAvatar at the last call */
    DWORD level;          /* g_pLevel */
    DWORD levelVtable;
    DWORD snapshots;      /* snapshots published */
    DWORD exCode;         /* BOT_STATE_FAILED: exception code, address, stage, object */
    DWORD exAddr;
    DWORD exStage;
    DWORD exObject;
    DWORD commands;       /* 1 = commands are executed (signatures of the called functions matched) */
    DWORD cmdSeq;         /* seq of the last executed command */
    DWORD cmdResult;      /* BOT_CMDR_* */
    DWORD cmdTick;
    DWORD keys;           /* BOT_CMD_KEY: 2 = key messages to the game window (1.11+; 1 was the key array alone,
                             which the game ignores without a WM_KEYDOWN), 0 = off (code differs) */
    DWORD moves;          /* 1 = BOT_CMD_MOVE works (MoveRequest code matched) */
    DWORD keysInactive;   /* 1 = key presses also work while another window is active */
    DWORD keyStateHooks;  /* always 0 (the key-state import hooks were removed in HPBars 1.22) */
    DWORD keyHeld;        /* virtual-key code the bot holds down right now, 0 = none */
    DWORD keyWindow;      /* game window the key messages go to */
    DWORD keyPresses;     /* key presses posted */
    DWORD animusOut;      /* 1 = an animus is summoned, 0 = none, 0xFFFFFFFF = unknown (as CAnimusBoard checks it) */
    DWORD animusList;     /* 1 = the animus list (BOT_ANIMUS_OFFSET) and BOT_CMD_SUMMON work */
    DWORD animusIndex;    /* object index of your summoned animus (CAnimus), 0xFFFFFFFF = none / unknown */
    DWORD dyingKnown;     /* 1 = BOTF_DYING is set for dying characters: HP 0 alone is no death */
    DWORD beltPages;      /* BOT_CMD_SLOT: belt pages it can use (CLinkBoard pages, 5), 0 = not supported / no belt */
    DWORD belt;           /* belt export (BOT_BELT_OFFSET): 2 = with skill / force cooldowns, 1 = without, 0 = off */
    DWORD requestPending; /* 1 = a request (e.g. the animus summon) waits for the server's answer (HPBars 1.21+) */
    DWORD requestAgeMs;   /* ms since that request was sent */
    DWORD beltPage;       /* belt page the belt shows (0..4), 0xFFFFFFFF = unknown (HPBars 1.21+) */
    DWORD unhooked;       /* 1 = the vtable hooks are removed (module idle) */
    DWORD ejectWanted;    /* 1 = the injector may free the module now (BOT_CMD_EJECT) */
    DWORD loot;           /* 1 = BOT_CMD_LOOT works (ground item manager and network manager readable) */
    DWORD pid;            /* GetCurrentProcessId() of the game this module runs in (set once at start) */
    DWORD avatarAction;   /* your character's current action (CCharacter+0x250, IsAction 0x40A8A0), every frame;
                             0xFFFFFFFF = unknown. Appended: an older bot just does not read it */
    DWORD actionChanges;  /* times avatarAction changed (the bot samples it and sees whether it missed some) */
} BotStatus;

/*
 * Belt (5 pages x 10 slots, slot = page * 10 + slot): what lies there and, for skills / forces, the game's own
 * cooldown check. Written every IntervalMs with its own seq (odd while writing).
 */
#define BOT_BELT_OFFSET    0xC000
#define BOT_BELT_SLOTS     (BELT_PAGES * BELT_SLOTS)

enum { BELT_EMPTY, BELT_ITEM, BELT_SF, BELT_ANIMUS, BELT_OTHER };

typedef struct {
    DWORD kind;           /* BELT_* */
    DWORD sfType;         /* BELT_SF: 0 skill, 1 force, 2 class skill; 0xFFFFFFFF = no skill / force */
    int   ready;          /* BELT_SF: CAvatar::CanUseSF: 1 = usable now, 0 = not now (shared or global delay),
                             -1 = its own cooldown runs; 2 = unknown */
    DWORD cooldownLeft;   /* BELT_SF: ms of its own cooldown left */
    DWORD cooldownTotal;  /* BELT_SF: its cooldown in ms (with your modifiers), 0 = unknown */
    char  name[BOT_NAME_LEN];  /* UTF-8 (64 bytes: Cyrillic names need up to 2 bytes per char) */
} BotBeltSlot;

typedef struct {
    DWORD seq;
    DWORD pages;          /* belt pages the client has (slots of other pages stay BELT_EMPTY) */
    DWORD tick;
    DWORD state;          /* 1 = read, 0 = belt not found / not recognized */
    BotBeltSlot slots[BOT_BELT_SLOTS];
} BotBelt;

/*
 * Animus list (your animus, as the animus window shows them): written every IntervalMs with its own seq
 * (odd while writing). HP is the stored HP that regenerates while the animus is not summoned.
 */
#define BOT_ANIMUS_OFFSET  0xE000
#define BOT_MAX_ANIMUS     8

typedef struct {
    DWORD entry;          /* board entry: BOT_CMD_SUMMON index */
    DWORD item;           /* CAnimusItem* */
    int   hp;
    int   maxHp;
    DWORD level;          /* BYTE [animus record + 0] */
    DWORD summoned;       /* 1 = this one is out */
    char  name[BOT_NAME_LEN];
} BotAnimusItem;

typedef struct {
    DWORD seq;
    DWORD count;
    DWORD tick;
    DWORD state;          /* 1 = read, 0 = animus board not found / not recognized */
    BotAnimusItem items[BOT_MAX_ANIMUS];
} BotAnimusList;

/*
 * Ground items (the loot on the floor), as the game's own list holds them (g_GroundItemManager). Written every
 * IntervalMs with its own seq. The bot picks the nearest within a radius and sends BOT_CMD_LOOT with its index.
 * Each item also carries its owner (item+0x280): the game tints the drop name green when the owner is you or it is
 * free for all (0xFFFFFFFF), red when someone else owns it, so the bot can skip foreign loot the server would reject.
 */
#define BOT_GROUND_OFFSET  0xE400
#define BOT_MAX_GROUND     48
#define BOT_GROUND_NAME    40

typedef struct {
    DWORD ptr;
    DWORD index;          /* object index (BOT_CMD_LOOT) */
    DWORD owner;          /* item+0x280: owner serial = own index, 0xFFFFFFFF = free for all, 0xFFFFFFFE = party/src */
    float pos[3];
    char  name[BOT_GROUND_NAME];
} BotGroundItem;

typedef struct {
    DWORD seq;
    DWORD count;
    DWORD tick;
    DWORD state;          /* 1 = read, 0 = ground item manager not found / not recognized */
    BotGroundItem items[BOT_MAX_GROUND];
} BotGroundList;

typedef char BotLayoutCheck[(sizeof(BotSnapshot) <= BOT_BELT_OFFSET
                             && BOT_BELT_OFFSET + sizeof(BotBelt) <= BOT_ANIMUS_OFFSET
                             && BOT_ANIMUS_OFFSET + sizeof(BotAnimusList) <= BOT_GROUND_OFFSET
                             && BOT_GROUND_OFFSET + sizeof(BotGroundList) <= BOT_COMMAND_OFFSET
                             && BOT_COMMAND_OFFSET + sizeof(BotCommand) <= BOT_STATUS_OFFSET
                             && BOT_STATUS_OFFSET + sizeof(BotStatus) <= BOT_MAP_SIZE) ? 1 : -1];

#define BOT_FILL_TARGET    0x1   /* call CTargetMgr::IsTarget */

enum { BOT_STAGE_IDLE, BOT_STAGE_HEADER, BOT_STAGE_AVATAR, BOT_STAGE_ENTITIES, BOT_STAGE_MARKERS,
       BOT_STAGE_EFFECTS, BOT_STAGE_PUBLISH, BOT_STAGE_TARGET, BOT_STAGE_COMMAND };
static const char *const g_botStageNames[] = { "idle", "header", "own character", "characters", "markers",
                                               "effects", "publish", "target", "command" };

static BotSnapshot    g_botSnap;
static char *volatile g_botView;
static DWORD          g_botSeq;
static volatile int   g_botStage;      /* what the export was doing, for the error log */
static volatile DWORD g_botObject;     /* object being read, for the error log */
static DWORD          g_botExCode;
static DWORD          g_botExAddr;
static volatile BotStatus *g_botStatus;
static int            g_botLevelCheck; /* 1 = CLevelEmpty RTTI recognized: no export while it is the level */
static int            g_botCommands;   /* 1 = CheckTarget/GetObject signatures matched: commands are executed */
static DWORD          g_botCmdSeq;     /* seq of the last command taken */

/* First bytes of the client functions the commands call (dump of the 2010-03-10 client). */
static const BYTE g_sigCheckTarget[16] = { 0x55,0x8B,0xEC,0x83,0xEC,0x08,0x89,0x4D,0xF8,0x6A,0x02,0x8B,0x0D,0xF8,0xB5,0x33 };
static const BYTE g_sigGetObject[16]   = { 0x55,0x8B,0xEC,0x83,0xEC,0x0C,0x89,0x4D,0xF4,0x83,0x7D,0x08,0x0F,0x74,0x06,0x83 };
static const BYTE g_sigKeyDown[16]     = { 0x83,0x3C,0x85,0x40,0xDE,0x43,0x02,0x00,0x0F,0x85,0x7D,0x02,0x00,0x00,0x3D,0xE5 };
static const BYTE g_sigKeyConsume[16]  = { 0x8B,0x4C,0xD0,0x14,0x83,0x3C,0x8D,0x40,0xDE,0x43,0x02,0x00,0x74,0x1C,0x8B,0x55 };
static const BYTE g_sigActiveGetter[16] = { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x8B,0x80,0x84,0x58,0x07,0x00 };
static const BYTE g_sigActiveStore[16]  = { 0x8B,0x4D,0xF4,0x8B,0x55,0x10,0x89,0x91,0x84,0x58,0x07,0x00,0x8B,0x45,0xF4,0x83 };
static const BYTE g_sigProcessor[16]    = { 0x8B,0x4D,0xFC,0x8B,0x84,0x81,0x08,0x36,0x04,0x00,0x8B,0xE5,0x5D,0xC2,0x04,0x00 };
static const BYTE g_sigMoveRequest[16]  = { 0x55,0x8B,0xEC,0x6A,0xFF,0x68,0x11,0x0B,0xA2,0x00,0x64,0xA1,0x00,0x00,0x00,0x00 };
static const BYTE g_sigKeymapCall[16]   = { 0x8B,0x4D,0xFC,0x8B,0x89,0x80,0x00,0x00,0x00,0xE8,0x0B,0x64,0x00,0x00,0x8B,0x0D };
static const BYTE g_sigBeltMode[16]     = { 0x8B,0x45,0xF4,0x83,0xB8,0x3C,0x03,0x00,0x00,0x00,0x0F,0x85,0x82,0x00,0x00,0x00 };
static const BYTE g_sigBeltAlt[16]      = { 0x8B,0x55,0xF8,0x0F,0xB6,0x82,0xEC,0x63,0xB1,0x00,0x50,0xFF,0x15,0xAC,0x14,0xA4 };
static const BYTE g_sigGetBoard[16]     = { 0x0F,0xB6,0x45,0x08,0x8B,0x4D,0xFC,0x8B,0x44,0x81,0x04,0x8B,0xE5,0x5D,0xC2,0x04 };
static const BYTE g_sigLinkUse[16]      = { 0x55,0x8B,0xEC,0x83,0xEC,0x14,0x89,0x4D,0xF0,0x8A,0x45,0x0C,0x50,0x8A,0x4D,0x08 };
static const BYTE g_sigCanUseSF[16]     = { 0x55,0x8B,0xEC,0x83,0xEC,0x28,0x56,0x89,0x4D,0xF8,0xA1,0x1C,0xEB,0xB3,0x00,0x83 };
static const BYTE g_sigSFBaseDelay[16]  = { 0x55,0x8B,0xEC,0x83,0xEC,0x30,0x89,0x4D,0xF0,0xC7,0x45,0xFC,0x00,0x00,0x00,0x00 };
static const BYTE g_sigSFDelay[16]      = { 0x55,0x8B,0xEC,0x83,0xEC,0x14,0x89,0x4D,0xF0,0x8B,0x45,0x0C,0x89,0x45,0xFC,0x6A };
static const BYTE g_sigLinkPage[16]     = { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x8A,0x80,0x48,0xE4,0x00,0x00 };
static const BYTE g_sigMainHwnd[16]     = { 0x8B,0x86,0xD8,0xB7,0x02,0x00,0xA3,0xA4,0x5D,0x45,0x02,0x75,0x06,0x89,0x86,0xDC };
static const BYTE g_sigAnimusOut[16]    = { 0x6A,0x08,0xB9,0x90,0xB0,0x3D,0x02,0xE8,0xB5,0xA2,0x01,0x00,0x8B,0xC8,0xE8,0x8E };
static const BYTE g_sigAnimusSet[16]    = { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x33,0xC9,0x83,0x78,0x10,0x00 };
static const BYTE g_sigAnimusToggle[16] = { 0xB9,0x90,0xB0,0x3D,0x02,0xE8,0x7E,0x1A,0xF9,0xFF,0x50,0xE8,0x18,0x90,0xFA,0xFF };
static const BYTE g_sigBoardMgrSel[16]  = { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x8B,0x80,0xE0,0x00,0x00,0x00 };
static const BYTE g_sigObjBoard[16]     = { 0x0F,0xB6,0x45,0x08,0x8B,0x4D,0xFC,0x0F,0xB6,0x51,0x10,0x3B,0xC2,0x7C,0x04,0x33 };
static const BYTE g_sigPage[16]         = { 0x8B,0x45,0xFC,0x83,0x78,0x0C,0x00,0x74,0x0F,0x0F,0xB6,0x4D,0x08,0x8B,0x55,0xFC };
static const BYTE g_sigEntryItem[16]    = { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x8B,0x80,0x48,0x02,0x00,0x00 };
static const BYTE g_sigItemName[16]     = { 0x8B,0x45,0xFC,0x83,0x78,0x10,0x00,0x74,0x0F,0x8B,0x4D,0xFC,0xE8,0x18,0x00,0x00 };
static const BYTE g_sigAnimusHp[16]     = { 0x8B,0x45,0xFC,0x83,0x78,0x18,0x00,0x75,0x02,0xEB,0x4E,0x8B,0x4D,0xFC,0x8B,0x55 };
static const BYTE g_sigToggleStart[16]  = { 0x55,0x8B,0xEC,0x83,0xEC,0x08,0x89,0x4D,0xF8,0x8B,0x0D,0xF8,0xB5,0x33,0x02,0xE8 };
static const BYTE g_sigAnimusLive[16]   = { 0x55,0x8B,0xEC,0x51,0x89,0x4D,0xFC,0x8B,0x45,0xFC,0x8B,0x40,0x0C,0x8B,0xE5,0x5D };
static int            g_botAnimusLive; /* 1 = the live summoned animus getter matched: status.animusIndex */
static int            g_botAnimusList; /* 1 = animus board code matched: the animus list and BOT_CMD_SUMMON work */
static int            g_botAnimusLogged;
static int            g_botAnimusOut;  /* 1 = the summoned-animus check matched: status.animusOut is exported */
static int            g_botMainHwnd;   /* 1 = the engine's window handle global matched */
static int            g_botBelt;       /* 1 = keymap / belt / CLinkBoard code matched: belt keys use the slot */
static int            g_botSlots;      /* 1 = CLinkBoard code matched: BOT_CMD_SLOT uses a slot of any belt page */
static int            g_botBeltExport; /* 1 = the belt is exported (BOT_BELT_OFFSET) */
static int            g_botBeltCooldowns; /* 1 = CanUseSF and the cooldown functions matched: cooldowns exported */
static int            g_botBeltLogged;
static DWORD          g_botSlotUsed[8];/* page * 16 + slot of the BOT_CMD_SLOT uses that were logged */
static int            g_botSlotUsedCount;
static int            g_botKeymapLogged;
static DWORD          g_botKeyUsed[8]; /* keys whose route was logged */
static int            g_botKeyUsedCount;
static int            g_botKeyDiagLeft = 8;   /* key messages still to report in the log */
static int            g_botKeyDiagSet;        /* the engine key array got the held key */
static int            g_botKeyDiagTaken;      /* ... and a KeyMap action took it */
static int            g_botKeys;       /* 1 = the key array code matched: BOT_CMD_KEY is executed */
static int            g_botActivate;   /* 1 = the CMainApp active flag matched and [Bot] KeysWhileInactive=1 */
static int            g_botMoves;      /* 1 = MoveRequest and the processor getter matched: BOT_CMD_MOVE is executed */
static int            g_botGround;     /* 1 = the ground item list is there: BOT_CMD_LOOT works */
static void          *g_botMoveProc;   /* position processor whose RTTI was checked */
static volatile DWORD g_botKeyVk;      /* key the bot holds down (0 = none) */
static DWORD          g_botKeyWnd;     /* game window the key messages go to (from the bot, checked) */
static DWORD          g_botKeyPresses; /* key presses posted */
#define BOT_KEY_QUEUE 4
static DWORD          g_botKeyQueue[BOT_KEY_QUEUE];   /* keys asked for while one was held, pressed in order */
static int            g_botKeyQueued;
static DWORD          g_botKeyTick;    /* GetTickCount() of the press */
static DWORD          g_botKeyFrames;  /* frames since the press */
static int            g_botKeyForced;  /* 1 = the bot set the CMainApp active flag for this press */

static int CodeMatchesN(DWORD addr, const BYTE *bytes, int n)
{
    int i;

    if (!IsReadable(addr, (DWORD)n)) return 0;
    for (i = 0; i < n; i++)
        if (((const BYTE *)addr)[i] != bytes[i]) return 0;
    return 1;
}

static int CodeMatches(DWORD addr, const BYTE *bytes)
{
    return CodeMatchesN(addr, bytes, 16);
}

/* Characters read from the CCharacterMgr lists for the next snapshot (copied values only, no pointer kept). */
static BotEntity      g_botFrame[BOT_MAX_ENTITIES];
static DWORD          g_botFrameCount;
static DWORD          g_botFrameTotal;  /* characters seen, may be more than g_botFrameCount */

/* Game text -> UTF-8, cut to `size` bytes and always terminated. */
static void CopyGameText(char *dst, const char *src, int size)
{
    char raw[BOT_NAME_LEN];

    if (size <= 0) return;
    raw[0] = 0;
    raw[sizeof(raw) - 1] = 0;              /* lstrcpynA always terminates, but force it: ToUtf8 reads to NUL */
    dst[0] = 0;
    if (!src) return;
    lstrcpynA(raw, src, sizeof(raw));
    raw[sizeof(raw) - 1] = 0;              /* a failed/truncating copy must not leave raw unterminated */
    ToUtf8(raw, dst, size);
    dst[size - 1] = 0;
}

/* Object size (operator new) of the classes the export reads, 0 = unknown class (not read). */
static DWORD BotClassSize(DWORD vtable)
{
    if (vtable == ADDR_CMONSTER_VTBL) return 0x11D4;
    if (vtable == VTBL_CANIMUS)       return 0x11D8;
    if (vtable == VTBL_CNPC)          return 0x11E0;
    if (vtable == VTBL_CPLAYER)       return 0x47B0;
    return 0;
}

/*
 * Who each monster attacked last, from _attack_monster_inform_zocl (5/13): DWORD monster index at data+0,
 * BYTE victim type at data+6, DWORD victim index at data+7 (see On_attack_monster_inform_zocl 0x55C550).
 */
#define BOT_ATTACKS 128

typedef struct {
    DWORD attacker;
    int   victimType;
    DWORD victimIndex;
    DWORD tick;            /* 0 = empty */
} BotAttack;

static BotAttack g_botAttacks[BOT_ATTACKS];

static const BYTE g_sigCombatAnalysis[16] = { 0x55,0x8B,0xEC,0x83,0xEC,0x08,0x89,0x4D,0xFC,0x8B,0x45,0x08,0x0F,0xB6,0x48,0x02 };

static void BotRecordAttack(DWORD attacker, int victimType, DWORD victimIndex)
{
    DWORD tick = GetTickCount();
    int i, slot = 0;

    for (i = 0; i < BOT_ATTACKS; i++) {
        if (g_botAttacks[i].tick && g_botAttacks[i].attacker == attacker) {
            slot = i;
            break;
        }
        if (tick - g_botAttacks[i].tick > tick - g_botAttacks[slot].tick)
            slot = i;          /* oldest entry (an empty one counts as the oldest) */
    }
    g_botAttacks[slot].attacker = attacker;
    g_botAttacks[slot].victimType = victimType;
    g_botAttacks[slot].victimIndex = victimIndex;
    g_botAttacks[slot].tick = tick ? tick : 1;
}

static void BotFindAttack(BotEntity *e)
{
    int i;

    for (i = 0; i < BOT_ATTACKS; i++) {
        if (g_botAttacks[i].tick && g_botAttacks[i].attacker == e->index) {
            e->victimType = g_botAttacks[i].victimType;
            e->victimIndex = g_botAttacks[i].victimIndex;
            e->victimAgeMs = GetTickCount() - g_botAttacks[i].tick;
            return;
        }
    }
}

/* Only reads the packet (the game handles it as usual): monster attacks for the bot's target priority. */
static int BotExceptionFilter(const EXCEPTION_POINTERS *ep);   /* defined below; used in SEH here */
static BYTE __thiscall Hook_CombatPacket(void *self, BYTE *hdr, BYTE *data)
{
    if (g_botView && hdr && data && hdr[2] == 5 && hdr[3] == 13) {
        __try {
            BotRecordAttack(*(const DWORD *)data, data[6], *(const DWORD *)(data + 7));
        } __except (BotExceptionFilter((const EXCEPTION_POINTERS *)_exception_info())) {
            /* the game reads the same bytes next; a fault here must not break the packet handling */
        }
    }
    return ((FnAnalysisPacket)g_hookCombat.original)(self, hdr, data);
}

static void FillEntity(BotEntity *e, char *obj, void *targetMgr, int fill)
{
    void **vt = VTBL(obj);
    DWORD vtable = (DWORD)vt;
    float hp;

    g_botObject = (DWORD)obj;
    memset(e, 0, sizeof(*e));
    e->ptr    = (DWORD)obj;
    e->vtable = vtable;
    e->type   = *(int *)(obj + OBJ_TYPE);
    e->index  = *(DWORD *)(obj + OBJ_INDEX);
    e->serial = *(DWORD *)(obj + OBJ_SERIAL);
    e->pos[0] = *(float *)(obj + OBJ_POS + 0);
    e->pos[1] = *(float *)(obj + OBJ_POS + 4);
    e->pos[2] = *(float *)(obj + OBJ_POS + 8);

    hp = ((FnGetHPRate)vt[VT_GETHPRATE / 4])(obj);
    if (!(hp >= 0.0f)) hp = 0.0f;   /* also catches NaN */
    if (hp > 1.0f) hp = 1.0f;
    e->hp = hp;
    if (IsDying(obj)) e->flags |= BOTF_DYING;

    e->victimType = -1;
    e->victimIndex = 0xFFFFFFFF;
    e->victimAgeMs = 0xFFFFFFFF;
    if (vtable == ADDR_CMONSTER_VTBL) {
        e->level = (int)((FnGetLevel)ADDR_MONSTER_LEVEL)(obj);
        BotFindAttack(e);
    } else if (vtable == VTBL_CPLAYER || vtable == ADDR_CAVATAR_VTBL) {
        e->level = (int)((FnGetDword)ADDR_PLAYER_LEVEL)(obj);
    }

    if (((FnStateTest)vt[VT_ISSTATE / 4])(obj, STATE_VISIBLE))     e->flags |= BOTF_VISIBLE;
    else if (*(BYTE *)(obj + OBJ_HIDE_STEALTH) || *(BYTE *)(obj + OBJ_HIDE_OTHERS)) e->flags |= BOTF_HIDDEN;
    if (((FnStateTest)vt[VT_ISSTATE / 4])(obj, STATE_NO_OVERHEAD)) e->flags |= BOTF_NO_OVERHEAD;
    if ((fill & BOT_FILL_TARGET) && targetMgr && ((FnIsTarget)ADDR_IS_TARGET)(targetMgr, obj))
        e->flags |= BOTF_TARGET;

    CopyGameText(e->name, obj + OBJ_NAME, BOT_NAME_LEN);
}

static int BotExceptionFilter(const EXCEPTION_POINTERS *ep)
{
    DWORD code = ep->ExceptionRecord->ExceptionCode;

    if (code == EXCEPTION_BREAKPOINT || code == EXCEPTION_SINGLE_STEP)
        return EXCEPTION_CONTINUE_SEARCH;   /* debugger events are not ours */
    g_botExCode = code;
    g_botExAddr = (DWORD)ep->ExceptionRecord->ExceptionAddress;
    return EXCEPTION_EXECUTE_HANDLER;
}

/* After a caught exception the export pauses and is retried later (BOT_RETRY_MIN_MS, doubling per fault up to
 * BOT_RETRY_MAX_MS); g_botFailedView keeps the view meanwhile. */
#define BOT_RETRY_MIN_MS  10000
#define BOT_RETRY_MAX_MS  60000
#define BOT_RETRY_RESET_MS 300000   /* this long without a fault: the next one waits BOT_RETRY_MIN_MS again */
static char *g_botFailedView;
static DWORD g_botRetryAt;
static DWORD g_botRetryDelay;

/* After a caught exception: export paused, reason in the log and the status block, retried later. */
static void BotFail(void)
{
    volatile BotStatus *st = g_botStatus;

    __asm__ __volatile__("emms");   /* drop x87 values a faulting game function may have left */
    if (g_botView) g_botFailedView = g_botView;
    g_botView = NULL;
    g_botRetryDelay = g_botRetryDelay ? g_botRetryDelay * 2 : BOT_RETRY_MIN_MS;
    if (g_botRetryDelay > BOT_RETRY_MAX_MS) g_botRetryDelay = BOT_RETRY_MAX_MS;
    g_botRetryAt = GetTickCount() + g_botRetryDelay;
    if (st) {
        st->exCode = g_botExCode;
        st->exAddr = g_botExAddr;
        st->exStage = (DWORD)g_botStage;
        st->exObject = g_botObject;
        st->state = BOT_STATE_FAILED;
    }
    Log(MS(S_07), g_botExCode, g_botExAddr,
        g_botStageNames[g_botStage], g_botObject);
    Log("bot export: paused after the fault, retried in %lu s", g_botRetryDelay / 1000);
}

/*
 * Every monster and animus of CCharacterMgr (the vectors RenderOverheadAll walks), also the ones the game hides
 * (behind walls, out of view). The pointer array is copied first; each object is read in its own __try, so a
 * character that disappears at the wrong moment is skipped instead of stopping the export.
 */
static DWORD g_botListFaults;

static __declspec(noinline) void BotListObjectUnguarded(char *obj, DWORD vtable, DWORD size, int fill)
{
    g_botStage = BOT_STAGE_ENTITIES;
    g_botObject = (DWORD)obj;
    g_botFrameTotal++;
    if (g_botFrameCount >= BOT_MAX_ENTITIES) return;
    if (!IsReadable((DWORD)obj, 4) || *(DWORD *)obj != vtable || !IsReadable((DWORD)obj, size)) return;
    FillEntity(&g_botFrame[g_botFrameCount], obj, *(void **)ADDR_PTR_TARGETMGR, fill);
    g_botFrameCount++;
}

static void BotListObject(char *obj, DWORD vtable, DWORD size, int fill)
{
    __try {
        BotListObjectUnguarded(obj, vtable, size, fill);
    } __except (BotExceptionFilter((const EXCEPTION_POINTERS *)_exception_info())) {
        __asm__ __volatile__("emms");
        if (!g_botListFaults++)
            Log(MS(S_08),
                g_botExCode, g_botExAddr, (DWORD)obj);
    }
}

static void BotCollectFromLists(char *mgr)
{
    static char *ptrs[1024];
    static const int types[] = { 1, 3 };   /* monsters first, then animus */
    unsigned int t;

    g_botFrameCount = 0;
    g_botFrameTotal = 0;
    for (t = 0; t < sizeof(types) / sizeof(types[0]); t++) {
        char *vec = mgr + CHARMGR_LISTS + types[t] * CHARMGR_LIST_STRIDE;
        char **first = *(char ***)(vec + 4);
        char **last = *(char ***)(vec + 8);
        DWORD bytes, count, i;
        DWORD vtable = types[t] == 1 ? ADDR_CMONSTER_VTBL : VTBL_CANIMUS;
        DWORD size = types[t] == 1 ? 0x11D4 : 0x11D8;

        if (!first || last < first) continue;
        bytes = (DWORD)((char *)last - (char *)first);
        if ((bytes & 3) || bytes / 4 > 1024 || !IsReadable((DWORD)first, bytes)) continue;
        count = bytes / 4;
        for (i = 0; i < count; i++) ptrs[i] = first[i];
        for (i = 0; i < count; i++)
            if (ptrs[i]) BotListObject(ptrs[i], vtable, size, BOT_FILL_TARGET);
    }
}

/* The target from this frame's characters, else from CTargetMgr (a target the game did not draw). */
static void BotFindTarget(BotSnapshot *s, void *targetMgr)
{
    char *obj;
    DWORD i, size;

    for (i = 0; i < s->entityCount; i++) {
        if (s->entities[i].flags & BOTF_TARGET) {
            s->target = s->entities[i];
            s->targetPresent = 1;
            return;
        }
    }
    if (!targetMgr) return;
    g_botStage = BOT_STAGE_TARGET;
    g_botObject = (DWORD)targetMgr;
    obj = ((FnGetTargetObject)ADDR_GET_TARGET_OBJECT)(targetMgr);
    if (!obj || !IsReadable((DWORD)obj, 4)) return;
    size = BotClassSize(*(DWORD *)obj);
    if (!size || !IsReadable((DWORD)obj, size)) return;
    FillEntity(&s->target, obj, NULL, 0);
    s->target.flags |= BOTF_TARGET;
    s->targetPresent = 1;
}

static void CollectBotEffects(BotSnapshot *s, char *avatar, DWORD now)
{
    EffectRef eff[BOT_MAX_EFFECTS];
    int count = CollectEffects(avatar, eff, BOT_MAX_EFFECTS, now);
    int i;

    for (i = 0; i < count; i++) {
        BotEffect *b = &s->effects[i];
        lstrcpynA(b->group, eff[i].group, sizeof(b->group));
        b->slot       = eff[i].slot;
        b->level      = eff[i].level;
        b->remainMs   = (int)eff[i].remainMs;
        b->durationMs = eff[i].durationMs;
        b->type       = eff[i].type;
        b->index      = eff[i].index;
        b->code       = eff[i].code;
        CopyGameText(b->name, eff[i].name, BOT_NAME_LEN);
        CopyGameText(b->effect, eff[i].effect, BOT_NAME_LEN);
    }
    s->effectCount = (DWORD)count;
}

static void CollectBotMarkers(BotSnapshot *s)
{
    int i;

    for (i = 0; i < g_markerCount; i++) {
        s->markers[i].pos[0] = g_markers[i].x;
        s->markers[i].pos[1] = g_markers[i].y;
        s->markers[i].pos[2] = g_markers[i].z;
    }
    s->markerCount = (DWORD)g_markerCount;
}

/* `tick` = start of the frame whose characters were collected. */
static void BuildBotSnapshot(BotSnapshot *s, char *avatar, DWORD tick)
{
    static DWORD counter;
    FnGameTime gameTime = *(FnGameTime *)ADDR_IAT_GAME_TIME;
    char *mgr = *(char **)ADDR_PTR_CHARACTERMGR;
    void *targetMgr = *(void **)ADDR_PTR_TARGETMGR;
    int mgrOk;

    g_botStage = BOT_STAGE_HEADER;
    g_botObject = (DWORD)mgr;
    mgrOk = mgr && IsReadable((DWORD)mgr, CHARMGR_LISTS + 4 * CHARMGR_LIST_STRIDE)
            && *(DWORD *)mgr == VTBL_CHARACTERMGR;
    memset(s, 0, sizeof(*s));
    s->magic         = BOT_MAGIC;
    s->version       = BOT_VERSION;
    s->snapshotSize  = sizeof(BotSnapshot);
    s->entitySize    = sizeof(BotEntity);
    s->effectSize    = sizeof(BotEffect);
    s->counter       = ++counter;
    s->tick          = tick;
    s->gameTime      = gameTime ? gameTime() : 0;
    s->pid           = GetCurrentProcessId();
    s->intervalMs    = (DWORD)g_cfg.botInterval;

    /* Own character: no IsTarget call */
    g_botStage = BOT_STAGE_AVATAR;
    FillEntity(&s->avatar, avatar, NULL, 0);
    if (avatar && IsReadable((DWORD)avatar + OBJ_ATTACK_RANGE, 4)) {
        float r = *(float *)(avatar + OBJ_ATTACK_RANGE);
        s->attackRange = (r > 0.0f && r < 100000.0f) ? r : 0.0f;
    }

    g_botStage = BOT_STAGE_ENTITIES;
    if (mgrOk) BotCollectFromLists(mgr);
    else g_botFrameCount = g_botFrameTotal = 0;
    s->entityTotal = g_botFrameTotal;
    s->entityCount = g_botFrameCount;
    memcpy(s->entities, g_botFrame, g_botFrameCount * sizeof(BotEntity));
    BotFindTarget(s, targetMgr);

    g_botStage = BOT_STAGE_MARKERS;
    CollectBotMarkers(s);
    g_botStage = BOT_STAGE_EFFECTS;
    g_botObject = (DWORD)avatar;
    if (s->gameTime) CollectBotEffects(s, avatar, s->gameTime);
}

static void PublishBotSnapshot(void)
{
    volatile DWORD *seq = (volatile DWORD *)(g_botView + 8);

    g_botSeq += 2;
    *seq = g_botSeq - 1;   /* odd: write in progress */
    __asm__ __volatile__("" ::: "memory");   /* keep the memcpy from being reordered across the seq stores */
    memcpy(g_botView + 12, (const char *)&g_botSnap + 12, sizeof(BotSnapshot) - 12);
    __asm__ __volatile__("" ::: "memory");
    *seq = g_botSeq;
}

static __declspec(noinline) void BuildAndPublishBotSnapshot(char *avatar, DWORD tick)
{
    BuildBotSnapshot(&g_botSnap, avatar, tick);
    g_botStage = BOT_STAGE_PUBLISH;
    PublishBotSnapshot();
    g_botStage = BOT_STAGE_IDLE;
}

/*
 * Key presses of the bot (keys that are not belt keys: those use their belt slot directly):
 *   - the window messages: WM_KEYDOWN goes through the GUI, CGP_MainGame and CKeyMap::MsgProc (0x52B140),
 *     which sets CKeyMap+0x334 = "a key came" (the key dispatcher 0x527E10 runs no KeyMap action without it),
 *     then the engine sets the key arrays (0x7C5250) that CKeyMap::IsActionTriggered takes;
 *   - the CMainApp active flag: while another window is active the key dispatcher runs no action at all.
 * So the bot posts WM_KEYDOWN to the game window (the window the bot found, checked to belong to this
 * process), the game counts as active while the key is held ([Bot] KeyHoldMs, at least two frames), then
 * WM_KEYUP is posted and the active flag gets back what Windows says.
 */
static volatile DWORD *BotActiveFlag(void)
{
    char *app = *(char **)ADDR_PTR_MAINAPP;

    if (!g_botActivate || !app || !IsReadable((DWORD)(app + MAINAPP_ACTIVE), 4)) return NULL;
    return (volatile DWORD *)(app + MAINAPP_ACTIVE);
}

/* 1 = hwnd is a window of the game process (the bot passes the window it found). */
static int IsGameWindow(DWORD hwnd)
{
    DWORD pid = 0;

    if (!hwnd || !IsWindow((HWND)hwnd)) return 0;
    GetWindowThreadProcessId((HWND)hwnd, &pid);
    return pid == GetCurrentProcessId();
}

/* lParam of a key message: repeat count 1, scan code, extended-key bit; key up: previous state + transition. */
static LONG KeyMessageParam(DWORD vk, int up)
{
    DWORD param = 1 | ((MapVirtualKeyA((UINT)vk, 0) & 0xFF) << 16);

    if ((vk >= 0x21 && vk <= 0x28) || vk == 0x2D || vk == 0x2E) param |= 1u << 24;   /* PgUp..arrows, Ins, Del */
    if (up) param |= 0xC0000000u;
    return (LONG)param;
}

static void BotKeyDown(DWORD vk)
{
    volatile DWORD *active = BotActiveFlag();

    g_botKeyTick = GetTickCount();
    g_botKeyFrames = 0;
    g_botKeyForced = 0;
    if (active && *active == 0) {
        *active = 1;
        g_botKeyForced = 1;
    }
    g_botKeyDiagSet = 0;
    g_botKeyDiagTaken = 0;
    g_botKeyVk = vk;
    PostMessageA((HWND)g_botKeyWnd, WM_KEYDOWN, vk, KeyMessageParam(vk, 0));
    g_botKeyPresses++;
}

static void BotKeyUp(void)
{
    volatile DWORD *active;
    DWORD vk = g_botKeyVk;

    g_botKeyVk = 0;
    if (vk) PostMessageA((HWND)g_botKeyWnd, WM_KEYUP, vk, KeyMessageParam(vk, 1));
    if (g_botKeyForced) {
        g_botKeyForced = 0;
        active = BotActiveFlag();
        if (active) *active = IsGameForeground() ? 1 : 0;   /* what WM_ACTIVATEAPP says for the window now */
    }
    if (vk && g_botKeyDiagLeft > 0) {   /* what the game did with the first presses, for the log */
        g_botKeyDiagLeft--;
        Log(MS(S_09), vk, g_botKeyDiagSet ? "yes" : "NO", g_botKeyDiagTaken ? "yes" : "no",
            IsGameForeground() ? "active" : "inactive");
    }
}

/* 1 = an animus is summoned, 0 = none, 0xFFFFFFFF = unknown: the check of the summon / recall button. */
static DWORD BotAnimusOut(void)
{
    char *board = *(char **)(ADDR_BOARD_MANAGER + 4 + BOARD_ANIMUS_CONTROL * 4);

    if (!g_botAnimusOut || !board || !IsReadable((DWORD)board, ANIMUSCTRL_SUMMONED + 4)
        || *(DWORD *)board != VTBL_CANIMUSCONTROL)
        return 0xFFFFFFFFu;
    return *(DWORD *)(board + ANIMUSCTRL_SUMMONED) ? 1u : 0u;
}

/*
 * Your animus as the animus window shows them: CAnimusBoard (board 4) is a CObjectBoard, pages of entries;
 * an entry leads to its CAnimusItem (name, stored HP that regenerates while it rests, max HP).
 */
static char *BotAnimusBoard(void)
{
    char *board = *(char **)(ADDR_BOARD_MANAGER + 4 + BOARD_ANIMUS * 4);

    if (!board || !IsReadable((DWORD)board, OBJBOARD_PAGE_COUNT + 1) || *(DWORD *)board != VTBL_CANIMUSBOARD)
        return NULL;
    return board;
}

/* The CAnimusItem of a board entry (the entry itself or what it links to), NULL = no animus. */
static char *AnimusItemOf(char *entry)
{
    char *item = entry;

    if (!entry || !IsReadable((DWORD)entry, 4)) return NULL;
    if (*(DWORD *)entry != VTBL_CANIMUSITEM) {
        if (!IsReadable((DWORD)(entry + ENTRY_ITEM), 4)) return NULL;
        item = *(char **)(entry + ENTRY_ITEM);
        if (!item || !IsReadable((DWORD)item, 4) || *(DWORD *)item != VTBL_CANIMUSITEM) return NULL;
    }
    return IsReadable((DWORD)item, ANIMUSITEM_HP + 4) ? item : NULL;
}

/* Entries of your animus, -1 = no animus board. */
static int BotAnimusEntries(char **entries, int max)
{
    char *board = BotAnimusBoard();
    char *pages, *page, **slots;
    int p, s, n = 0, pageCount, slotCount;

    if (!board) return -1;
    pages = *(char **)(board + OBJBOARD_PAGES);
    pageCount = *(BYTE *)(board + OBJBOARD_PAGE_COUNT);
    if (!pages || pageCount > 16 || !IsReadable((DWORD)pages, (DWORD)pageCount * 16)) return 0;
    for (p = 0; p < pageCount; p++) {
        page = pages + p * 16;
        if (!*(DWORD *)(page + PAGE_VALID)) continue;
        slots = *(char ***)(page + PAGE_SLOTS);
        slotCount = *(BYTE *)(page + PAGE_SLOT_COUNT);
        if (!slots || !IsReadable((DWORD)slots, (DWORD)slotCount * 4)) continue;
        for (s = 0; s < slotCount && n < max; s++)
            if (AnimusItemOf(slots[s])) entries[n++] = slots[s];
    }
    return n;
}

/* The summoned animus (its CAnimusItem), NULL = none or unknown. */
static char *BotSummonedAnimus(void)
{
    char *ctrl = *(char **)(ADDR_BOARD_MANAGER + 4 + BOARD_ANIMUS_CONTROL * 4);

    if (!g_botAnimusOut || !ctrl || !IsReadable((DWORD)ctrl, ANIMUSCTRL_SUMMONED + 4)
        || *(DWORD *)ctrl != VTBL_CANIMUSCONTROL)
        return NULL;
    return *(char **)(ctrl + ANIMUSCTRL_SUMMONED);
}

static __declspec(noinline) void BotPublishAnimusUnguarded(void)
{
    volatile BotAnimusList *list = (volatile BotAnimusList *)(g_botView + BOT_ANIMUS_OFFSET);
    volatile BotAnimusItem *out;
    char *entries[BOT_MAX_ANIMUS];
    char *summoned = BotSummonedAnimus();
    char *item, *data, *record;
    int n, i, k;

    n = BotAnimusEntries(entries, BOT_MAX_ANIMUS);
    list->seq++;                   /* odd: writing */
    list->state = n >= 0 ? 1u : 0u;
    if (n < 0) n = 0;
    for (i = 0; i < n; i++) {
        item = AnimusItemOf(entries[i]);
        out = &list->items[i];
        out->entry = (DWORD)entries[i];
        out->item = (DWORD)item;
        out->hp = item ? *(int *)(item + ANIMUSITEM_HP) : 0;
        data = item ? *(char **)(item + ANIMUSITEM_DATA) : NULL;
        if (data && IsReadable((DWORD)data, ANIMUSDATA_MAX_HP + 4)) {
            out->maxHp = *(int *)(data + ANIMUSDATA_MAX_HP);
            out->level = *(BYTE *)data;
        } else {
            out->maxHp = 0;
            out->level = 0;
        }
        out->summoned = (item && item == summoned) ? 1u : 0u;
        record = item ? *(char **)(item + ITEM_RECORD) : NULL;
        out->name[0] = 0;
        if (record && IsReadable((DWORD)(record + ITEMREC_ITEM_NAME), sizeof(out->name))) {
            char tmp[BOT_NAME_LEN];
            for (k = 0; k < (int)sizeof(tmp) - 1 && record[ITEMREC_ITEM_NAME + k]; k++)
                tmp[k] = record[ITEMREC_ITEM_NAME + k];
            tmp[k] = 0;
            ToUtf8(tmp, (char *)out->name, sizeof(out->name));   /* game cp1251 -> utf-8, the bot reads utf-8 */
        }
    }
    list->count = (DWORD)n;
    list->tick = GetTickCount();
    list->seq++;                   /* even: done */
    if (!g_botAnimusLogged) {
        g_botAnimusLogged = 1;
        for (i = 0; i < n; i++)
            Log(MS(S_10), i + 1, (const char *)list->items[i].name,
                list->items[i].hp, list->items[i].maxHp, list->items[i].level,
                list->items[i].summoned ? " (summoned)" : "");
        if (!n) Log(MS(S_11), BotAnimusBoard() ? "" : " (board not recognized)");
    }
}

static int   g_botAnimusSigOk;   /* the animus code matched at start (g_botAnimusList may be paused after a fault) */
static int   g_botAnimusFaults;
static DWORD g_botAnimusRetryAt;
#define BOT_ANIMUS_RETRIES   3
#define BOT_ANIMUS_RETRY_MS  30000

static void BotPublishAnimus(void)
{
    if (!g_botView) return;
    if (!g_botAnimusList && g_botAnimusSigOk && g_botAnimusFaults < BOT_ANIMUS_RETRIES
        && (long)(GetTickCount() - g_botAnimusRetryAt) >= 0) {
        g_botAnimusList = 1;       /* retry after a fault */
        if (g_botStatus) g_botStatus->animusList = 1;
        Log("bot animus: retrying the animus list (try %d of %d)", g_botAnimusFaults + 1, BOT_ANIMUS_RETRIES);
    }
    if (!g_botAnimusList) return;
    __try {
        BotPublishAnimusUnguarded();
    } __except (BotExceptionFilter((const EXCEPTION_POINTERS *)_exception_info())) {
        __asm__ __volatile__("emms");
        g_botAnimusList = 0;       /* the animus list pauses, the rest of the export goes on */
        g_botAnimusFaults++;
        g_botAnimusRetryAt = GetTickCount() + BOT_ANIMUS_RETRY_MS;
        if (g_botStatus) g_botStatus->animusList = 0;
        /* the fault may have left seq odd (write in progress): readers wait for an even seq */
        if (((volatile BotAnimusList *)(g_botView + BOT_ANIMUS_OFFSET))->seq & 1)
            ((volatile BotAnimusList *)(g_botView + BOT_ANIMUS_OFFSET))->seq++;
        Log(MS(S_12), g_botExCode,
            g_botExAddr);
    }
}

/* Loot on the floor: walk the game's own ground item list (g_GroundItemManager+0x4, std::list: next at +0, data at +8). */
static __declspec(noinline) void BotPublishGroundUnguarded(void)
{
    volatile BotGroundList *list = (volatile BotGroundList *)(g_botView + BOT_GROUND_OFFSET);
    char *mgr = (char *)ADDR_GROUNDMGR;   /* the static manager OBJECT itself (list head at +8) */
    char *head, *cur;
    DWORD i, n = 0;

    list->seq++;                 /* odd: writing */
    list->state = 0;
    if (mgr && IsReadable((DWORD)mgr, 16)) {
        head = *(char **)(mgr + 8);
        if (head && IsReadable((DWORD)head, 8)) {
            cur = *(char **)head;
            for (i = 0; cur && cur != head && n < BOT_MAX_GROUND && i < 4096; i++) {
                char *item;
                if (!IsReadable((DWORD)cur, 12)) break;
                item = *(char **)(cur + 8);
                cur = *(char **)cur;
                if (!item || !IsReadable((DWORD)item, 0x288)) continue;
                list->items[n].ptr = (DWORD)item;
                list->items[n].index = *(DWORD *)(item + 0x08);
                list->items[n].owner = *(DWORD *)(item + 0x280);   /* 0xFFFFFFFF = free, 0xFFFFFFFE = party */
                list->items[n].pos[0] = *(float *)(item + 0x50);
                list->items[n].pos[1] = *(float *)(item + 0x54);
                list->items[n].pos[2] = *(float *)(item + 0x58);
                CopyGameText((char *)list->items[n].name, item + 0x10, BOT_GROUND_NAME);
                n++;
            }
            list->state = 1;
        }
    }
    list->count = n;
    list->tick = GetTickCount();
    list->seq++;                 /* even: done */
}

static void BotPublishGround(void)
{
    if (!g_botView) return;
    __try {
        BotPublishGroundUnguarded();
    } __except (BotExceptionFilter((const EXCEPTION_POINTERS *)_exception_info())) {
        __asm__ __volatile__("emms");
        /* the fault left seq odd (write in progress): make it even again, else every reader waits/returns
         * None forever (seq parity is flipped for good) and the loot silently stops until a game restart. */
        if (((volatile BotGroundList *)(g_botView + BOT_GROUND_OFFSET))->seq & 1)
            ((volatile BotGroundList *)(g_botView + BOT_GROUND_OFFSET))->seq++;
        Log(MS(S_13), g_botExCode,
            g_botExAddr);
    }
}

/* Summons this animus like the animus window: select it, press summon. Never while one is out. */
static DWORD BotSummonAnimus(DWORD entry)
{
    char *entries[BOT_MAX_ANIMUS];
    char *board = BotAnimusBoard();
    int n, i, found = 0;

    if (!g_botAnimusList || !board || !*(void **)ADDR_PTR_AVATAR) return BOT_CMDR_NOT_READY;
    if (BotAnimusOut() != 0) return BOT_CMDR_REFUSED;   /* one is out (the button would recall it) or unknown */
    n = BotAnimusEntries(entries, BOT_MAX_ANIMUS);
    for (i = 0; i < n; i++)
        if ((DWORD)entries[i] == entry) found = 1;
    if (!found) return BOT_CMDR_NOT_FOUND;
    g_botObject = (DWORD)board;
    *(DWORD *)(ADDR_BOARD_MANAGER + BOARDMGR_SELECTED) = entry;      /* the animus window selection */
    return ((FnGetDword)ANIMUSBOARD_TOGGLE)(board) ? BOT_CMDR_OK : BOT_CMDR_REFUSED;
}

/* Object index of your summoned animus (the CAnimus of the summon / recall button), 0xFFFFFFFF = none. */
static DWORD BotAnimusIndex(void)
{
    char *ctrl = *(char **)(ADDR_BOARD_MANAGER + 4 + BOARD_ANIMUS_CONTROL * 4);
    char *anim;

    if (!g_botAnimusLive || !ctrl || !IsReadable((DWORD)ctrl, ANIMUSCTRL_SUMMONED + 4)
        || *(DWORD *)ctrl != VTBL_CANIMUSCONTROL || !*(DWORD *)(ctrl + ANIMUSCTRL_SUMMONED))
        return 0xFFFFFFFFu;
    anim = *(char **)(ctrl + ANIMUSCTRL_LIVE);
    if (!anim || !IsReadable((DWORD)anim, OBJ_SERIAL + 4) || *(DWORD *)anim != VTBL_CANIMUS) return 0xFFFFFFFFu;
    return *(DWORD *)(anim + OBJ_INDEX);
}

/* The belt (CLinkBoard), NULL = not there / not recognized. */
static char *BotLinkBoard(void)
{
    char *board = *(char **)(ADDR_BOARD_MANAGER + 4 + BOARD_LINK * 4);

    if (!board || !IsReadable((DWORD)board, LINKBOARD_PAGE_COUNT + 1) || *(DWORD *)board != VTBL_CLINKBOARD
        || !IsReadable(*(DWORD *)board + VT_LINK_USE, 4) || *(DWORD *)(*(DWORD *)board + VT_LINK_USE) != ADDR_LINK_USE)
        return NULL;
    return board;
}

/* Belt pages BOT_CMD_SLOT can use (the CLinkBoard page count), 0 = none. */
static DWORD BotBeltPages(void)
{
    char *board;

    if (!g_botSlots || !*(void **)ADDR_PTR_AVATAR) return 0;
    board = BotLinkBoard();
    return board ? (DWORD)(BYTE)board[LINKBOARD_PAGE_COUNT] : 0;
}

/* 1 = the function starts with a jmp to readable code (the dump had the cooldown functions redirected so). */
static int IsJmpStub(DWORD addr)
{
    DWORD target;

    if (!IsReadable(addr, 5) || *(BYTE *)addr != 0xE9) return 0;
    target = addr + 5 + *(DWORD *)(addr + 1);
    return IsReadable(target, 16);
}

static void LogCodeBytes(const char *what, DWORD addr)
{
    const BYTE *b = (const BYTE *)addr;

    if (!IsReadable(addr, 16)) {
        Log("%s 0x%08lX: not readable", what, addr);
        return;
    }
    Log("%s 0x%08lX: %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X", what, addr,
        b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
}

/* Name of an item on a board (UTF-8), "" when its class has no known name getter. */
static void BotItemName(char *item, char *dst, int size)
{
    DWORD getter;
    const char *name;

    dst[0] = 0;
    if (!item || !IsReadable((DWORD)item, ITEM_RECORD + 4) || !IsReadable(*(DWORD *)item + VT_ITEM_NAME, 4)) return;
    getter = *(DWORD *)(*(DWORD *)item + VT_ITEM_NAME);
    if (getter != ADDR_ITEM_NAME_BASE && getter != ADDR_ITEM_NAME_SF) return;   /* only the two known getters */
    if (!*(DWORD *)(item + ITEM_RECORD)) return;
    name = ((FnGetString)getter)(item);
    if (name && IsReadable((DWORD)name, 1)) CopyGameText(dst, name, size);
}

/*
 * The belt: kind and name of every slot of the 5 pages and, for skills / forces, the game's own check whether
 * it can be used now (CAvatar::CanUseSF, what using it checks) and its cooldown: CAvatar::SFDelay(type,
 * SFBaseDelay(sf)) (your modifiers included) since its last use (CSFItem+0x30, game time).
 */
static __declspec(noinline) void BotPublishBeltUnguarded(void)
{
    volatile BotBelt *belt = (volatile BotBelt *)(g_botView + BOT_BELT_OFFSET);
    char *board = BotLinkBoard();
    char *avatar = *(char **)ADDR_PTR_AVATAR;
    char *pages = NULL, *page, **slots, *entry, *item;
    DWORD now = (*(FnGameTime *)ADDR_IAT_GAME_TIME)();
    char name[BOT_NAME_LEN];
    int p, s, pageCount = 0, slotCount, kind;

    if (board) {
        pages = *(char **)(board + OBJBOARD_PAGES);
        pageCount = *(BYTE *)(board + OBJBOARD_PAGE_COUNT);
        if (pageCount > BELT_PAGES) pageCount = BELT_PAGES;
        if (!pages || !IsReadable((DWORD)pages, (DWORD)pageCount * 16)) pageCount = 0;
    }
    belt->seq++;                   /* odd: writing */
    belt->state = board ? 1u : 0u;
    belt->pages = (DWORD)pageCount;
    for (p = 0; p < BELT_PAGES; p++) {
        page = p < pageCount ? pages + p * 16 : NULL;
        slots = page && *(DWORD *)(page + PAGE_VALID) ? *(char ***)(page + PAGE_SLOTS) : NULL;
        slotCount = slots ? *(BYTE *)(page + PAGE_SLOT_COUNT) : 0;
        if (slots && !IsReadable((DWORD)slots, (DWORD)slotCount * 4)) slotCount = 0;
        for (s = 0; s < BELT_SLOTS; s++) {
            volatile BotBeltSlot *out = &belt->slots[p * BELT_SLOTS + s];

            out->kind = BELT_EMPTY;
            out->sfType = 0xFFFFFFFFu;
            out->ready = 2;
            out->cooldownLeft = 0;
            out->cooldownTotal = 0;
            out->name[0] = 0;
            entry = s < slotCount ? slots[s] : NULL;
            if (!entry || !IsReadable((DWORD)entry, ENTRY_ITEM + 4)
                || !IsReadable(*(DWORD *)entry + VT_BOARD_ITEM_KIND, 4))
                continue;
            g_botObject = (DWORD)entry;
            kind = ((FnBoardItemKind)VTBL(entry)[VT_BOARD_ITEM_KIND / 4])(entry, 1) ? BELT_SF
                 : ((FnBoardItemKind)VTBL(entry)[VT_BOARD_ITEM_KIND / 4])(entry, 2) ? BELT_ANIMUS
                 : ((FnBoardItemKind)VTBL(entry)[VT_BOARD_ITEM_KIND / 4])(entry, 0) ? BELT_ITEM : BELT_OTHER;
            out->kind = (DWORD)kind;
            item = *(char **)(entry + ENTRY_ITEM);
            BotItemName(item, name, sizeof(name));
            lstrcpynA((char *)out->name, name, sizeof(out->name));
            if (kind != BELT_SF || !item || !IsReadable((DWORD)item, SF_LAST_USE + 4)
                || *(DWORD *)item != VTBL_CSFITEM)
                continue;
            out->sfType = *(BYTE *)(item + SF_TYPE);
            if (!g_botBeltCooldowns || !avatar) continue;
            g_botObject = (DWORD)item;
            {
                int type = *(BYTE *)(item + SF_TYPE);
                DWORD base = ((FnSFBaseDelay)ADDR_SF_BASE_DELAY)(avatar, item);
                DWORD total = ((FnSFDelay)ADDR_SF_DELAY)(avatar, type, base);
                DWORD elapsed = now - *(DWORD *)(item + SF_LAST_USE);

                out->ready = ((FnCanUseSF)ADDR_CAN_USE_SF)(avatar, type, item);
                out->cooldownTotal = total;
                out->cooldownLeft = elapsed < total ? total - elapsed : 0;
            }
        }
    }
    belt->tick = GetTickCount();
    belt->seq++;                   /* even: done */
    if (!g_botBeltLogged && pageCount) {
        static const char *const kinds[] = { "empty", "item", "skill/force", "animus", "other" };
        g_botBeltLogged = 1;
        for (p = 0; p < BELT_PAGES * BELT_SLOTS; p++) {
            const volatile BotBeltSlot *b = &belt->slots[p];
            if (b->kind == BELT_EMPTY) continue;
            if (b->kind == BELT_SF)
                Log(MS(S_14),
                    p / BELT_SLOTS + 1, (p + 1) % BELT_SLOTS, kinds[b->kind], (const char *)b->name, b->sfType,
                    b->ready, b->cooldownLeft, b->cooldownTotal);
            else
                Log(MS(S_15), p / BELT_SLOTS + 1, (p + 1) % BELT_SLOTS, kinds[b->kind],
                    (const char *)b->name);
        }
    }
}

static void BotPublishBelt(void)
{
    if (!g_botBeltExport || !g_botView) return;
    __try {
        BotPublishBeltUnguarded();
    } __except (BotExceptionFilter((const EXCEPTION_POINTERS *)_exception_info())) {
        __asm__ __volatile__("emms");
        if (g_botBeltCooldowns) {
            g_botBeltCooldowns = 0;   /* the cooldown calls are the risky part: names and kinds go on */
            Log(MS(S_16),
                g_botExCode, g_botExAddr, g_botObject);
        } else {
            g_botBeltExport = 0;
            Log(MS(S_17),
                g_botExCode, g_botExAddr, g_botObject);
        }
        if (g_botStatus) g_botStatus->belt = g_botBeltExport ? (g_botBeltCooldowns ? 2u : 1u) : 0u;
        if (((volatile BotBelt *)(g_botView + BOT_BELT_OFFSET))->seq & 1)   /* readers wait for an even seq */
            ((volatile BotBelt *)(g_botView + BOT_BELT_OFFSET))->seq++;
    }
}

/* Selects an animus in the animus window (what a click on it does), e.g. before a skill that works on it. */
static DWORD BotSelectAnimus(DWORD entry)
{
    char *entries[BOT_MAX_ANIMUS];
    int n, i;

    if (!g_botAnimusList || !*(void **)ADDR_PTR_AVATAR) return BOT_CMDR_NOT_READY;
    n = BotAnimusEntries(entries, BOT_MAX_ANIMUS);
    for (i = 0; i < n; i++) {
        if ((DWORD)entries[i] == entry) {
            *(DWORD *)(ADDR_BOARD_MANAGER + BOARDMGR_SELECTED) = entry;
            return BOT_CMDR_OK;
        }
    }
    return BOT_CMDR_NOT_FOUND;
}

/* Every frame of the own character: releases a held key after KeyHoldMs and presses the next queued one. */
static void BotKeyTick(volatile BotStatus *st)
{
    int i;

    if (g_botKeyVk) {
        if (((volatile DWORD *)ADDR_KEY_DOWN_SEEN)[g_botKeyVk] == 1) {   /* WM_KEYDOWN reached the engine */
            g_botKeyDiagSet = 1;
            if (((volatile DWORD *)ADDR_KEY_PRESSED)[g_botKeyVk] == 0) g_botKeyDiagTaken = 1;   /* an action took it */
        }
        g_botKeyFrames++;
        if (g_botKeyFrames >= 2 && GetTickCount() - g_botKeyTick >= (DWORD)g_cfg.botKeyHold) {
            BotKeyUp();
            if (g_botKeyQueued) {
                BotKeyDown(g_botKeyQueue[0]);
                g_botKeyQueued--;
                for (i = 0; i < g_botKeyQueued; i++) g_botKeyQueue[i] = g_botKeyQueue[i + 1];
            }
        }
    }
    st->keyHeld = g_botKeyVk;
    st->keyWindow = g_botKeyWnd;
    st->keyPresses = g_botKeyPresses;
    st->animusOut = BotAnimusOut();
    st->animusIndex = BotAnimusIndex();
    st->beltPages = BotBeltPages();
    {
        char *wnd = *(char **)ADDR_PTR_LINK_WINDOW;
        BYTE page = (wnd && IsReadable((DWORD)(wnd + LINKWND_PAGE), 1)) ? (BYTE)wnd[LINKWND_PAGE] : 0xFF;
        st->beltPage = page < BELT_PAGES ? page : 0xFFFFFFFFu;
    }
    st->requestPending = *(DWORD *)(ADDR_BOARD_MANAGER + BOARDMGR_PENDING) ? 1u : 0u;
    st->requestAgeMs = st->requestPending
        ? (*(FnGameTime *)ADDR_IAT_GAME_TIME)() - *(DWORD *)(ADDR_BOARD_MANAGER + BOARDMGR_PENDING_TIME) : 0u;
    {
        /* your character's action every frame (the bot learns which values mean "casting") */
        static DWORD lastAction = 0xFFFFFFFFu;
        char *av = *(char **)ADDR_PTR_AVATAR;

        if (av && IsReadable((DWORD)(av + OBJ_ACTION), 4)) {
            DWORD action = *(DWORD *)(av + OBJ_ACTION);
            if (action != lastAction) {
                lastAction = action;
                st->actionChanges++;
            }
            st->avatarAction = action;
        } else {
            st->avatarAction = 0xFFFFFFFFu;
        }
    }
}

static void BotKeyTickGuarded(volatile BotStatus *st)
{
    static int logged;

    __try {
        BotKeyTick(st);
    } __except (BotExceptionFilter((const EXCEPTION_POINTERS *)_exception_info())) {
        __asm__ __volatile__("emms");
        if (!logged) {
            logged = 1;
            Log("bot keys: exception 0x%08lX at 0x%08lX in the per-frame key / status update (skipped this frame)",
                g_botExCode, g_botExAddr);
        }
    }
}

/*
 * Belt keys. The belt (quick slots) is read by virtualized code in the main game; its plain copy in the
 * tutorial (0x528780) shows the rule: belt-key mode 0 uses the KeyMap actions SLOT_1..SLOT_10, mode 1 the
 * fixed keys ADDR_BELT_KEYS_ALT read from the keyboard state, and a slot runs CLinkBoard::UseSlot(page, slot).
 * A key of a belt slot therefore calls UseSlot directly: the same action, without any key.
 */
static char *BotKeymap(void)
{
    char *gp = *(char **)ADDR_PTR_GAMEPROCESS;
    char *keymap;

    if (!gp || !IsReadable((DWORD)gp, GP_KEYMAP + 4) || *(DWORD *)gp != VTBL_CGP_MAINGAME) return NULL;
    keymap = *(char **)(gp + GP_KEYMAP);
    if (!keymap || !IsReadable((DWORD)keymap, KEYMAP_BELT_MODE + 4)) return NULL;
    return keymap;
}

/* Belt slot (0..9) of a key, -1 = none: [Bot] BeltKeys, else as the game binds the belt keys now. */
static int BeltSlotOfKey(DWORD vk)
{
    char *keymap;
    const int *binding;
    int i;

    if (g_cfg.botBeltKeys[0]) {
        for (i = 0; i < 10 && g_cfg.botBeltKeys[i]; i++) {
            char c = g_cfg.botBeltKeys[i];
            if (c >= 'a' && c <= 'z') c = (char)(c - 32);
            if ((DWORD)(BYTE)c == vk) return i;
        }
        return -1;
    }
    keymap = BotKeymap();
    if (!keymap) return -1;
    if (*(int *)(keymap + KEYMAP_BELT_MODE) == 1) {
        for (i = 0; i < 10; i++)
            if (((const BYTE *)ADDR_BELT_KEYS_ALT)[i] == vk) return i;
        return -1;
    }
    for (i = 0; i < 10; i++) {
        binding = (const int *)(keymap + KEYMAP_BINDINGS + (KEYACTION_SLOT_1 + i) * 8);
        if (binding[1] == (int)vk && binding[0] == -1) return i;   /* no modifier key */
    }
    return -1;
}

/* Uses belt slot 0..9 of belt page 0..4 (what the belt key does on that page), page -1 = the page shown. */
static DWORD BotUseSlot(int page, int slot)
{
    char *board = *(char **)(ADDR_BOARD_MANAGER + 4 + BOARD_LINK * 4);
    char *wnd = *(char **)ADDR_PTR_LINK_WINDOW;

    if (!board || !wnd || !*(void **)ADDR_PTR_AVATAR) return BOT_CMDR_NOT_READY;
    g_botObject = (DWORD)board;
    board = BotLinkBoard();
    if (!board) return BOT_CMDR_CLASS;
    if (page < 0) {
        if (!IsReadable((DWORD)(wnd + LINKWND_PAGE), 1)) return BOT_CMDR_NOT_READY;
        page = (BYTE)wnd[LINKWND_PAGE];
        if (page == 0xFF) return BOT_CMDR_NOT_READY;
    }
    if (page >= (BYTE)board[LINKBOARD_PAGE_COUNT] || slot < 0 || slot >= 10) return BOT_CMDR_UNKNOWN;
    return ((FnLinkUse)ADDR_LINK_USE)(board, page, slot) ? BOT_CMDR_OK : BOT_CMDR_REFUSED;
}

static void KeyLabel(char *out, DWORD vk)
{
    if ((vk >= '0' && vk <= '9') || (vk >= 'A' && vk <= 'Z')) wsprintfA(out, "%c", (int)vk);
    else if (vk >= 0x70 && vk <= 0x87) wsprintfA(out, "F%d", (int)(vk - 0x6F));
    else wsprintfA(out, "0x%02X", (int)vk);
}

/* The game's key bindings, once, for the log: what each key does in this client. */
static void BotLogKeymap(void)
{
    char *keymap = BotKeymap();
    char line[1024];
    char key[16];
    const int *binding;
    int i, len, mode;

    if (!keymap) {
        Log(MS(S_18));
        return;
    }
    mode = *(int *)(keymap + KEYMAP_BELT_MODE);
    len = wsprintfA(line, MS(S_19), mode,
                    mode == 1 ? "fixed keys read from the keyboard" : "KeyMap SLOT_1..SLOT_10");
    for (i = 0; i < 10; i++) {
        if (mode == 1) {
            KeyLabel(key, ((const BYTE *)ADDR_BELT_KEYS_ALT)[i]);
        } else {
            binding = (const int *)(keymap + KEYMAP_BINDINGS + (KEYACTION_SLOT_1 + i) * 8);
            if (binding[1] == -1) lstrcpynA(key, "-", sizeof(key)); else KeyLabel(key, (DWORD)binding[1]);
        }
        len += wsprintfA(line + len, " %d=%s", i + 1, key);
    }
    Log("%s", line);
    len = wsprintfA(line, MS(S_20), ADDR_BELT_KEYS_ALT);
    for (i = 0; i < 24; i++) len += wsprintfA(line + len, " %02X", ((const BYTE *)ADDR_BELT_KEYS_ALT)[i]);
    {
        char *wnd = *(char **)ADDR_PTR_LINK_WINDOW;
        int page = (wnd && IsReadable((DWORD)(wnd + LINKWND_PAGE), 1)) ? (BYTE)wnd[LINKWND_PAGE] : -1;
        len += wsprintfA(line + len, MS(S_21), page,
                         g_cfg.botBeltKeys[0] ? g_cfg.botBeltKeys : "auto");
    }
    Log("%s", line);
    len = wsprintfA(line, MS(S_22));
    for (i = 0; i < KEYACTION_COUNT; i++) {
        binding = (const int *)(keymap + KEYMAP_BINDINGS + i * 8);
        if (binding[1] == -1) continue;
        KeyLabel(key, (DWORD)binding[1]);
        if (len > (int)sizeof(line) - 80) {
            Log("%s", line);
            len = wsprintfA(line, MS(S_22));
        }
        len += wsprintfA(line + len, " %s=%s%s%s", (const char *)(ADDR_KEYACTION_NAMES + i * 0x20),
                         binding[0] == VK_SHIFT ? "Shift+" : binding[0] == VK_CONTROL ? "Ctrl+" : "",
                         binding[0] == VK_MENU ? "Alt+" : "", key);
    }
    Log("%s", line);
}

/* Walks to a world point with the client's own MoveRequest, the call a click on the ground ends in. */
static DWORD BotMoveTo(const float *pos)
{
    char *net = *(char **)ADDR_PTR_NETWORKMGR;
    void *proc;
    float to[3];
    int i;

    if (!g_botMoves || !net || !*(void **)ADDR_PTR_AVATAR) return BOT_CMDR_NOT_READY;
    for (i = 0; i < 3; i++) {
        if (pos[i] != pos[i] || pos[i] > 1.0e6f || pos[i] < -1.0e6f) return BOT_CMDR_UNKNOWN;   /* NaN / garbage */
        to[i] = pos[i];
    }
    g_botObject = (DWORD)net;
    if (!IsReadable((DWORD)(net + NETMGR_PROCESSORS), 4)) return BOT_CMDR_NOT_READY;
    proc = *(void **)(net + NETMGR_PROCESSORS);
    if (!proc) return BOT_CMDR_NOT_READY;
    if (proc != g_botMoveProc) {   /* the class is checked once per processor object */
        if (!IsReadable((DWORD)proc, 4) || !CheckRtti(*(DWORD *)proc, ".?AVCNetMsgProcessor_Position@@"))
            return BOT_CMDR_CLASS;
        g_botMoveProc = proc;
    }
    g_botObject = (DWORD)proc;
    return ((FnMoveRequest)ADDR_MOVE_REQUEST)(proc, to, 1, 1, 0.0f) ? BOT_CMDR_OK : BOT_CMDR_REFUSED;
}

/* 1 = a drop with this object index is still in the game's ground item list. */
static int BotGroundHasIndex(DWORD index)
{
    char *mgr = (char *)ADDR_GROUNDMGR;
    char *head, *cur, *item;
    DWORD i;

    if (!IsReadable((DWORD)mgr, 16)) return 0;
    head = *(char **)(mgr + 8);
    if (!head || !IsReadable((DWORD)head, 8)) return 0;
    cur = *(char **)head;
    for (i = 0; cur && cur != head && i < 4096; i++) {
        if (!IsReadable((DWORD)cur, 12)) return 0;
        item = *(char **)(cur + 8);
        cur = *(char **)cur;
        if (item && IsReadable((DWORD)item, 0x0C) && *(DWORD *)(item + 0x08) == index) return 1;
    }
    return 0;
}

/* RTTI class name of a vtable for the log ("?" when unreadable). */
static const char *RttiName(DWORD vtable)
{
    DWORD col, td;

    if (!IsReadable(vtable - 4, 4)) return "?";
    col = *(DWORD *)(vtable - 4);
    if (!IsReadable(col + 12, 4)) return "?";
    td = *(DWORD *)(col + 12);
    if (!IsReadable(td + 8, 64)) return "?";
    return (const char *)(td + 8);
}

static void *g_botItemProc;      /* the CNetMsgProcessor_Item found in processors[] */
static int   g_botItemProcIdx = -1;

/*
 * The item packet processor (CNetMsgProcessor_Item), found by its RTTI among the network manager's processors:
 * its index is not the packet major (processors[7] turned out to be CNetMsgProcessor_Map in this client).
 * NULL when none has that class (then every processor class is logged once, so the right one can be named).
 */
static void *BotItemProcessor(void)
{
    static int listLogged;
    char *net = *(char **)ADDR_PTR_NETWORKMGR;
    void **procs;
    int i;

    if (!net || !IsReadable((DWORD)(net + NETMGR_PROCESSORS), NETMGR_PROCESSOR_COUNT * 4)) return NULL;
    procs = (void **)(net + NETMGR_PROCESSORS);
    if (g_botItemProcIdx >= 0 && g_botItemProc && procs[g_botItemProcIdx] == g_botItemProc)
        return g_botItemProc;    /* same object as last time: its class was checked */
    for (i = 0; i < NETMGR_PROCESSOR_COUNT; i++) {
        void *p = procs[i];
        if (p && IsReadable((DWORD)p, 4) && CheckRtti(*(DWORD *)p, ".?AVCNetMsgProcessor_Item@@")) {
            if (i != g_botItemProcIdx)
                Log("bot loot: item processor = processors[%d] (CNetMsgProcessor_Item)", i);
            g_botItemProcIdx = i;
            g_botItemProc = p;
            return p;
        }
    }
    if (!listLogged) {
        char line[1000];
        int len = 0;

        listLogged = 1;
        Log("bot loot: no CNetMsgProcessor_Item among the %d processors: no pickup (send these lines)",
            NETMGR_PROCESSOR_COUNT);
        for (i = 0; i < NETMGR_PROCESSOR_COUNT; i++) {
            void *p = procs[i];
            if (len > (int)sizeof(line) - 90) {
                Log("bot loot: processors:%s", line);
                len = 0;
            }
            len += wsprintfA(line + len, " %d=%.60s", i,
                             !p ? "-" : IsReadable((DWORD)p, 4) ? RttiName(*(DWORD *)p) : "unreadable");
        }
        if (len) Log("bot loot: processors:%s", line);
    }
    g_botItemProc = NULL;
    g_botItemProcIdx = -1;
    return NULL;
}

/* Picks up a ground item (packet 7/2), the same call the game's pickup does. */
static DWORD BotLootItem(DWORD index)
{
    char *net = *(char **)ADDR_PTR_NETWORKMGR;
    void *proc;

    if (!g_botGround || !*(void **)ADDR_PTR_AVATAR || !net) return BOT_CMDR_NOT_READY;
    proc = BotItemProcessor();
    if (!proc) return BOT_CMDR_CLASS;
    if (!BotGroundHasIndex(index)) return BOT_CMDR_NOT_FOUND;   /* taken or gone meanwhile: nothing to send */
    g_botObject = (DWORD)proc;
    ((FnTakeItem)ADDR_TAKE_ITEM)(proc, index, 0xFFFFFFFFu);
    return BOT_CMDR_OK;
}

/*
 * Removes the vtable hooks and, when eject is set and every hook is back to what it was, marks the module for
 * freeing by the injector. A held key is released first (else the game keeps it down). A hook another mod
 * chained after ours cannot be removed: that mod still calls into us, so the module must stay mapped.
 */
static int RemoveVtHook(VtHook *h);
static void BotUnhook(int eject);
static volatile int g_unhooked;   /* 1 = hooks removed, the module does nothing per frame anymore */
static volatile int g_ejectWanted; /* 1 = the injector may free us once we stop touching the game */

static void BotUnhook(int eject)
{
    int clean;

    g_botKeyQueued = 0;
    if (g_botKeyVk) BotKeyUp();   /* WM_KEYUP for the held key, active flag back to what Windows says */
    clean = RemoveVtHook(&g_hookAvatar);
    clean = RemoveVtHook(&g_hookCombat) && clean;
    g_unhooked = 1;
    if (eject && clean) g_ejectWanted = 1;
    if (g_botStatus) {
        g_botStatus->unhooked = 1;
        g_botStatus->keyHeld = 0;
        if (eject && clean) g_botStatus->ejectWanted = 1;
    }
    if (eject && !clean)
        Log("module EJECT: hooks removed where possible, but another mod chained after ours: the module must "
            "stay mapped (idle)");
    else
        Log("module %s: hooks removed%s", eject ? "EJECT" : "UNHOOK",
            eject ? ", the injector may free it now" : " (the module stays mapped but idle)");
}

/* Executes one bot command on the game thread with the client's own functions. Returns BOT_CMDR_*. */
static __declspec(noinline) DWORD BotRunCommandUnguarded(DWORD op, int type, DWORD index, DWORD serial,
                                                         DWORD hwnd, const float *pos)
{
    void *targetMgr = *(void **)ADDR_PTR_TARGETMGR;
    void *mgr = *(void **)ADDR_PTR_CHARACTERMGR;
    char *obj;

    g_botStage = BOT_STAGE_COMMAND;
    g_botObject = (DWORD)targetMgr;
    if (op == BOT_CMD_UNHOOK || op == BOT_CMD_EJECT) {
        BotUnhook(op == BOT_CMD_EJECT);
        return BOT_CMDR_OK;
    }
    if (op == BOT_CMD_KEY) {      /* like the keyboard: the game runs the action bound to the key */
        int slot, i, logged = 0;
        DWORD result;

        if (!g_botKeys) return BOT_CMDR_NOT_READY;
        if (index == 0 || index >= 0xFF) return BOT_CMDR_UNKNOWN;
        if (g_botBelt) {
            if (!g_botKeymapLogged) {
                g_botKeymapLogged = 1;
                BotLogKeymap();
            }
            slot = BeltSlotOfKey(index);
            for (i = 0; i < g_botKeyUsedCount; i++)
                if (g_botKeyUsed[i] == index) logged = 1;
            if (slot >= 0) {      /* a belt key: use the slot itself */
                result = BotUseSlot(-1, slot);
                if (!logged && g_botKeyUsedCount < 8) {
                    g_botKeyUsed[g_botKeyUsedCount++] = index;
                    Log(MS(S_23), index,
                        slot + 1, result);
                }
                if (result == BOT_CMDR_OK || result == BOT_CMDR_REFUSED) {
                    g_botKeyPresses++;
                    return BOT_CMDR_OK;   /* REFUSED = empty slot or not usable now, like the key */
                }
                return result;
            }
            if (!logged && g_botKeyUsedCount < 8) {
                g_botKeyUsed[g_botKeyUsedCount++] = index;
                if (index == 0x79 || index == VK_MENU || index == 0xA4 || index == 0xA5)
                    Log(MS(S_24), index);
                else
                    Log(MS(S_25), index);
            }
        }
        if (index == 0x79 || index == VK_MENU || index == 0xA4 || index == 0xA5)
            return BOT_CMDR_UNKNOWN;   /* F10 / Alt press + release = SC_KEYMENU: the game stalls */
        if (g_botMainHwnd && IsGameWindow(*(DWORD *)ADDR_PTR_MAIN_HWND))
            hwnd = *(DWORD *)ADDR_PTR_MAIN_HWND;   /* the engine's own window, whatever the bot found */
        if (hwnd && hwnd != g_botKeyWnd && !g_botKeyVk) {   /* a held key ends on the window it went to */
            if (!IsGameWindow(hwnd)) return BOT_CMDR_CLASS;
            if (!g_botKeyWnd) Log(MS(S_26), hwnd);
            g_botKeyWnd = hwnd;
        }
        if (!IsGameWindow(g_botKeyWnd)) return BOT_CMDR_NOT_READY;
        if (!g_botKeyVk) {
            BotKeyDown(index);
        } else {                  /* one key at a time: this one follows (a double press stays two presses) */
            if (g_botKeyQueued >= BOT_KEY_QUEUE) return BOT_CMDR_NOT_READY;
            g_botKeyQueue[g_botKeyQueued++] = index;
        }
        return BOT_CMDR_OK;
    }
    if (op == BOT_CMD_SLOT) {     /* a slot of any belt page, without switching the page the belt shows */
        DWORD result, used = (DWORD)(type & 0xFF) * 16 + index;
        int i, logged = 0;

        if (!g_botSlots) return BOT_CMDR_NOT_READY;
        if (type < -1 || type > 15 || index >= 10) return BOT_CMDR_UNKNOWN;
        result = BotUseSlot(type, (int)index);
        for (i = 0; i < g_botSlotUsedCount; i++)
            if (g_botSlotUsed[i] == used) logged = 1;
        if (!logged && g_botSlotUsedCount < 8) {
            g_botSlotUsed[g_botSlotUsedCount++] = used;
            if (type < 0) Log(MS(S_27), index + 1, result);
            else          Log(MS(S_28),
                              type + 1, index + 1, result);
        }
        if (result == BOT_CMDR_OK || result == BOT_CMDR_REFUSED) {
            g_botKeyPresses++;
            return BOT_CMDR_OK;   /* REFUSED = empty slot or not usable now, like the key */
        }
        return result;
    }
    if (op == BOT_CMD_MOVE) return BotMoveTo(pos);
    if (op == BOT_CMD_SUMMON) return BotSummonAnimus(index);
    if (op == BOT_CMD_ANIMUS_SELECT) return BotSelectAnimus(index);
    if (op == BOT_CMD_LOOT) return BotLootItem(index);
    if (!targetMgr || !mgr) return BOT_CMDR_NOT_READY;
    if (!g_botCommands) return BOT_CMDR_NOT_READY;
    if (op == BOT_CMD_CLEAR) {
        ((FnCheckTarget)ADDR_CHECK_TARGET)(targetMgr, NULL, 0);
        return BOT_CMDR_OK;
    }
    if (op != BOT_CMD_SELECT) return BOT_CMDR_UNKNOWN;
    if (type != 1) return BOT_CMDR_CLASS;                         /* monsters only */
    g_botObject = (DWORD)mgr;
    obj = ((FnGetObject)ADDR_GET_OBJECT)(mgr, type, (int)index);   /* the live object, not a stored pointer */
    if (!obj) return BOT_CMDR_NOT_FOUND;
    g_botObject = (DWORD)obj;
    if (!IsReadable((DWORD)obj, 4) || *(DWORD *)obj != ADDR_CMONSTER_VTBL || !IsReadable((DWORD)obj, 0x11D4))
        return BOT_CMDR_CLASS;
    if (*(DWORD *)(obj + OBJ_SERIAL) != serial) return BOT_CMDR_SERIAL;
    ((FnCheckTarget)ADDR_CHECK_TARGET)(targetMgr, obj, 0);         /* same call as a click on the monster */
    g_botStage = BOT_STAGE_IDLE;
    return BOT_CMDR_OK;
}

static void BotPollCommand(volatile BotStatus *st)
{
    const volatile BotCommand *cmd = (const volatile BotCommand *)(g_botView + BOT_COMMAND_OFFSET);
    DWORD seq = cmd->seq;
    DWORD op, index, serial, hwnd, result, cmdTick;
    float pos[3];
    int type;

    if (seq == g_botCmdSeq) return;
    op = cmd->op;
    cmdTick = cmd->tick;
    type = cmd->type;
    index = cmd->index;
    serial = cmd->serial;
    hwnd = cmd->hwnd;
    pos[0] = cmd->pos[0];
    pos[1] = cmd->pos[1];
    pos[2] = cmd->pos[2];
    if (cmd->seq != seq) return;   /* the bot is writing a new command right now */
    g_botCmdSeq = seq;

    if (!(g_botCommands || g_botKeys || g_botMoves || g_botSlots || g_botAnimusList)
        || st->state != BOT_STATE_RUNNING) {
        result = BOT_CMDR_NOT_READY;
    } else if (cmdTick && (DWORD)(GetTickCount() - cmdTick) > BOT_CMD_STALE_MS) {
        result = BOT_CMDR_STALE;   /* the game thread was blocked; do not fire an out-of-context MOVE / KEY */
    } else {
        __try {
            result = BotRunCommandUnguarded(op, type, index, serial, hwnd, pos);
        } __except (BotExceptionFilter((const EXCEPTION_POINTERS *)_exception_info())) {
            BotFail();
            result = BOT_CMDR_NOT_READY;   /* answered: the bot does not wait for its timeout */
        }
    }
    st->cmdResult = result;
    st->cmdTick = GetTickCount();
    st->cmdSeq = seq;              /* last: the bot waits for this */
}

/* Builds and publishes one snapshot under SEH; returns 0 when the export failed (and is now off). */
static int BotPublish(volatile BotStatus *st, char *avatar, DWORD tick, DWORD avatarSince, int *firstLogged)
{
    __try {
        BuildAndPublishBotSnapshot(avatar, tick);
    } __except (BotExceptionFilter((const EXCEPTION_POINTERS *)_exception_info())) {
        BotFail();
        return 0;
    }
    st->snapshots++;
    st->state = BOT_STATE_RUNNING;
    if (g_botRetryDelay && tick - g_botRetryAt > BOT_RETRY_RESET_MS)
        g_botRetryDelay = 0;      /* running fine for a while: the next fault waits the shortest pause again */
    if (!*firstLogged) {
        *firstLogged = 1;
        Log(MS(S_29), tick - avatarSince, g_botSnap.entityTotal,
            g_botSnap.entityCount, g_botSnap.targetPresent, g_botSnap.effectCount, g_botSnap.markerCount);
    }
    return 1;
}

/*
 * Runs in the avatar hook. Every IntervalMs it reads the character lists and publishes the snapshot, the
 * animus list and the belt. A fault in the export is caught, logged with the stage/object and switches the
 * export off instead of closing the game.
 */
static void ExportBotState(char *self)
{
    static DWORD lastCheck;
    static char *lastAvatar;
    static DWORD avatarSince;
    static DWORD notLoadedSince;
    static int firstLogged;
    static int waitLogged;
    static int otherLogged;
    volatile BotStatus *st = g_botStatus;
    char *avatar = *(char **)ADDR_PTR_AVATAR;
    DWORD tick, level;

    if (!st) return;
    st->hookCalls++;
    st->hookSelf = (DWORD)self;
    st->avatar = (DWORD)avatar;
    if (self != avatar) {         /* the hook also runs for other CAvatar objects */
        if (!otherLogged) {
            otherLogged = 1;
            Log(MS(S_30),
                (DWORD)self, (DWORD)avatar);
        }
        return;
    }
    BotKeyTickGuarded(st);        /* also after a failure: a held key is always released */
    if (!g_botView && g_botFailedView && (long)(GetTickCount() - g_botRetryAt) >= 0) {
        g_botView = g_botFailedView;   /* retry the export after a fault */
        g_botFailedView = NULL;
        lastAvatar = NULL;             /* waits StartDelayMs again, like entering the world */
        Log("bot export: retrying after the fault");
    }
    if (!g_botView) return;       /* paused after a fault: the state stays BOT_STATE_FAILED until the retry */
    BotPollCommand(st);
    if (!g_botView) return;

    tick = GetTickCount();
    if (tick - lastCheck < (DWORD)g_cfg.botInterval) return;
    lastCheck = tick;
    level = *(DWORD *)ADDR_PTR_LEVEL;
    st->tick = tick;
    st->level = level;
    st->levelVtable = (level && IsReadable(level, 4)) ? *(DWORD *)level : 0;

    if (g_botLevelCheck && st->levelVtable == VTBL_CLEVELEMPTY) {   /* no map loaded yet */
        st->state = BOT_STATE_WAIT_LEVEL;
        if (!notLoadedSince) {
            notLoadedSince = tick;
        } else if (!waitLogged && tick - notLoadedSince > 30000) {
            waitLogged = 1;
            Log(MS(S_31), level);
        }
        lastAvatar = NULL;
        return;
    }
    notLoadedSince = 0;
    if (avatar != lastAvatar) {   /* character just entered the world: let the client finish loading */
        lastAvatar = avatar;
        avatarSince = tick;
        st->state = BOT_STATE_WAIT_DELAY;
        return;
    }
    if (tick - avatarSince < (DWORD)g_cfg.botStartDelay) {
        st->state = BOT_STATE_WAIT_DELAY;
        return;
    }

    if (BotPublish(st, avatar, tick, avatarSince, &firstLogged)) {   /* reads the character lists now */
        BotPublishAnimus();
        BotPublishBelt();
        BotPublishGround();
    }
}

/* Called once from InitThread after the hooks are installed; the mapping stays open until the game exits. */
static void OpenBotShared(void)
{
    HANDLE map;
    char *view;
    volatile BotStatus *st;

    if (!g_cfg.botEnabled) return;
    if (!CheckRtti(VTBL_CHARACTERMGR, ".?AVCCharacterMgr@@"))
        Log(MS(S_32));
    map = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, BOT_MAP_SIZE, g_cfg.botName);
    if (!map) {
        Log(MS(S_33), g_cfg.botName);
        return;
    }
    view = (char *)MapViewOfFile(map, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, BOT_MAP_SIZE);
    if (!view) {
        Log(MS(S_34), g_cfg.botName);
        CloseHandle(map);
        return;
    }
    *(volatile DWORD *)(view + 8) = 0;   /* seq 0 = no snapshot of this game run yet */
    *(volatile DWORD *)(view + 0) = BOT_MAGIC;
    *(volatile DWORD *)(view + 4) = BOT_VERSION;
    g_botLevelCheck = CheckRtti(VTBL_CLEVELEMPTY, ".?AVCLevelEmpty@@");
    if (!g_botLevelCheck)
        Log(MS(S_35));
    memset(view + BOT_COMMAND_OFFSET, 0, sizeof(BotCommand));
    g_botCmdSeq = 0;
    g_botCommands = CodeMatches(ADDR_CHECK_TARGET, g_sigCheckTarget) && CodeMatches(ADDR_GET_OBJECT, g_sigGetObject);
    g_botKeys = CodeMatches(ADDR_KEY_DOWN_CODE, g_sigKeyDown) && CodeMatches(ADDR_KEY_CONSUME_CODE, g_sigKeyConsume);
    g_botActivate = g_botKeys && g_cfg.botKeysInactive && CodeMatches(ADDR_ACTIVE_GETTER, g_sigActiveGetter)
                    && CodeMatches(ADDR_ACTIVE_STORE_CODE, g_sigActiveStore);
    g_botMoves = CodeMatches(ADDR_MOVE_REQUEST, g_sigMoveRequest) && CodeMatches(ADDR_PROCESSOR_CODE, g_sigProcessor);
    g_botGround = IsReadable(ADDR_GROUNDMGR, 12) && IsReadable(ADDR_PTR_NETWORKMGR, 4);
    g_botMainHwnd = CodeMatches(ADDR_MAIN_HWND_CODE, g_sigMainHwnd);
    g_botAnimusOut = CodeMatches(ADDR_ANIMUS_OUT_CODE, g_sigAnimusOut) && CodeMatches(ADDR_ANIMUS_SET_GETTER, g_sigAnimusSet)
                     && CodeMatches(ADDR_GET_BOARD_CODE, g_sigGetBoard);
    g_botAnimusLive = g_botAnimusOut && CodeMatches(ADDR_ANIMUS_LIVE_CODE, g_sigAnimusLive);
    g_botAnimusList = g_botAnimusOut && CodeMatches(ANIMUSBOARD_TOGGLE, g_sigToggleStart)
                      && CodeMatches(ANIMUS_TOGGLE_CODE, g_sigAnimusToggle)
                      && CodeMatches(ADDR_BOARDMGR_SEL_CODE, g_sigBoardMgrSel)
                      && CodeMatches(ADDR_OBJBOARD_CODE, g_sigObjBoard) && CodeMatches(ADDR_PAGE_CODE, g_sigPage)
                      && CodeMatches(ADDR_ENTRY_ITEM_CODE, g_sigEntryItem)
                      && CodeMatches(ADDR_ITEM_NAME_CODE, g_sigItemName)
                      && CodeMatches(ADDR_ANIMUS_HP_CODE, g_sigAnimusHp);
    g_botBelt = g_botKeys && CodeMatches(ADDR_KEYMAP_CALL_CODE, g_sigKeymapCall)
                && CodeMatches(ADDR_BELT_MODE_CODE, g_sigBeltMode) && CodeMatches(ADDR_BELT_ALT_CODE, g_sigBeltAlt)
                && CodeMatches(ADDR_GET_BOARD_CODE, g_sigGetBoard) && CodeMatches(ADDR_LINK_USE, g_sigLinkUse)
                && CodeMatches(ADDR_LINK_PAGE_GETTER, g_sigLinkPage);
    g_botSlots = CodeMatches(ADDR_GET_BOARD_CODE, g_sigGetBoard) && CodeMatches(ADDR_LINK_USE, g_sigLinkUse)
                 && CodeMatches(ADDR_LINK_PAGE_GETTER, g_sigLinkPage) && CodeMatches(ADDR_OBJBOARD_CODE, g_sigObjBoard);
    g_botBeltExport = g_botSlots;
    g_botBeltCooldowns = g_botBeltExport && CodeMatches(ADDR_CAN_USE_SF, g_sigCanUseSF)
                         && (CodeMatches(ADDR_SF_BASE_DELAY, g_sigSFBaseDelay) || IsJmpStub(ADDR_SF_BASE_DELAY))
                         && (CodeMatches(ADDR_SF_DELAY, g_sigSFDelay) || IsJmpStub(ADDR_SF_DELAY));
    if (g_botBeltExport && !g_botBeltCooldowns) {
        LogCodeBytes(MS(S_36), ADDR_CAN_USE_SF);
        LogCodeBytes(MS(S_37), ADDR_SF_BASE_DELAY);
        LogCodeBytes(MS(S_38), ADDR_SF_DELAY);
    }
    Log(MS(S_39),
        g_botCommands ? "on" : "OFF (signatures differ)", g_botBelt ? "on" : "OFF (signatures differ)",
        g_botSlots ? "on" : "OFF (signatures differ)",
        g_botKeys ? "on" : "OFF (signatures differ)",
        g_botActivate ? "on" : (g_botKeys && g_cfg.botKeysInactive ? "OFF (signatures differ)" : "off"),
        g_botMoves ? "on" : "OFF (signatures differ)", g_botAnimusOut ? "on" : "OFF (signatures differ)",
        g_botAnimusList ? "on" : "OFF (signatures differ)",
        !g_botBeltExport ? "OFF (signatures differ)" : g_botBeltCooldowns ? "on, with skill / force cooldowns"
                                                                         : "on, without cooldowns (signatures differ)");
    /* filled through st and published (g_botStatus) only when complete: the avatar hook already runs on
     * the game thread and uses g_botStatus as soon as it is set */
    st = (volatile BotStatus *)(view + BOT_STATUS_OFFSET);
    memset((void *)st, 0, sizeof(BotStatus));   /* the mapping may survive from a previous game run */
    st->pid = GetCurrentProcessId();
    st->avatarAction = 0xFFFFFFFFu;
    st->commands = (DWORD)g_botCommands;
    st->keys = g_botKeys ? 2u : 0u;
    st->moves = (DWORD)g_botMoves;
    st->keysInactive = (DWORD)g_botActivate;
    st->animusOut = 0xFFFFFFFFu;
    st->animusList = (DWORD)g_botAnimusList;
    st->animusIndex = 0xFFFFFFFFu;
    st->dyingKnown = (DWORD)g_dieCheck;
    st->belt = g_botBeltExport ? (g_botBeltCooldowns ? 2u : 1u) : 0u;
    st->beltPage = 0xFFFFFFFFu;
    st->unhooked = 0;
    st->ejectWanted = 0;
    st->loot = (DWORD)g_botGround;
    Log("bot export: loot %s", g_botGround ? "on (BOT_CMD_LOOT)" : "OFF (ground item manager not readable)");
    memset(view + BOT_ANIMUS_OFFSET, 0, sizeof(BotAnimusList));
    memset(view + BOT_BELT_OFFSET, 0, sizeof(BotBelt));
    memset(view + BOT_GROUND_OFFSET, 0, sizeof(BotGroundList));   /* stale ground list from a previous run */
    st->state = BOT_STATE_WAIT_AVATAR;
    st->magic = BOT_STATUS_MAGIC;
    g_botAnimusSigOk = g_botAnimusList;
    __asm__ __volatile__("" ::: "memory");
    g_botStatus = st;
    __asm__ __volatile__("" ::: "memory");
    g_botView = view;
    Log(MS(S_40),
        g_cfg.botName, (unsigned)sizeof(BotSnapshot), (unsigned)sizeof(BotEntity), (unsigned)sizeof(BotEffect),
        g_cfg.botInterval);
}

static void __thiscall Hook_AvatarOverhead(void *self)
{
    ((FnRenderOverhead)g_hookAvatar.original)(self);

    PollHotkeys();
    if (g_cfg.botEnabled && self)
        ExportBotState((char *)self);
}

/* ================================= Hook install ================================= */

static void InstallVtHook(VtHook *h)
{
    DWORD *slot = (DWORD *)(h->vtable + h->offset);
    DWORD current = *slot;
    DWORD oldProtect;

    if (h->installed || current == h->hook) return;
    if (current != h->expected)
        Log("note: %s slot already = 0x%08lX (another mod?), chaining to it", h->name, current);

    h->original = current;
    if (!VirtualProtect(slot, 4, PAGE_READWRITE, &oldProtect)) {
        Log("ERROR: VirtualProtect on %s slot 0x%08lX failed", h->name, (DWORD)slot);
        return;
    }
    *slot = h->hook;
    VirtualProtect(slot, 4, oldProtect, &oldProtect);
    h->installed = 1;
    Log("hooked %s: slot 0x%08lX 0x%08lX -> 0x%08lX", h->name, (DWORD)slot, current, h->hook);
}

/* 1 = the slot no longer leads into this module (restored, or never hooked), 0 = it still does. */
static int RemoveVtHook(VtHook *h)
{
    DWORD *slot = (DWORD *)(h->vtable + h->offset);
    DWORD oldProtect;

    if (!h->installed) return 1;
    if (*slot != h->hook) {         /* someone chained after us: their hook still calls ours */
        Log("unhook %s: slot 0x%08lX = 0x%08lX, another mod chained after ours: left as it is",
            h->name, (DWORD)slot, *slot);
        return 0;
    }
    if (!VirtualProtect(slot, 4, PAGE_READWRITE, &oldProtect)) {
        Log("ERROR: VirtualProtect on %s slot 0x%08lX failed: still hooked", h->name, (DWORD)slot);
        return 0;
    }
    *slot = h->original;
    VirtualProtect(slot, 4, oldProtect, &oldProtect);
    h->installed = 0;
    return 1;
}

static int HasProtectorSection(void)
{
    /* The RF client is packed: its exe has a ".gpt0" section (renamed VMProtect section). */
    const BYTE *base = (const BYTE *)GetModuleHandleA(NULL);
    const BYTE *nt;
    const BYTE *sec;
    WORD count, optSize, i;

    if (!base || base[0] != 'M' || base[1] != 'Z') return 0;
    nt = base + *(const DWORD *)(base + 0x3C);
    if (nt[0] != 'P' || nt[1] != 'E') return 0;
    count   = *(const WORD *)(nt + 6);
    optSize = *(const WORD *)(nt + 20);
    sec = nt + 24 + optSize;
    for (i = 0; i < count; i++, sec += 40)
        if (sec[0] == '.' && sec[1] == 'g' && sec[2] == 'p' && sec[3] == 't' && sec[4] == '0' && sec[5] == 0)
            return 1;
    return 0;
}

static int IsGameProcess(void)
{
    char path[MAX_PATH];
    const char *name;
    const char *p;
    static const char target[] = "rf_online";
    static const char target2[] = "cerberus-games";
    int i;

    if (HasProtectorSection()) return 1;

    GetModuleFileNameA(NULL, path, sizeof(path));
    name = path;
    for (p = path; *p; p++)
        if (*p == '\\' || *p == '/') name = p + 1;

    /* matches RF_Online.bin, RF_Online_4gb.bin, and the CERBERUS launcher exe */
    for (i = 0; target[i]; i++) {
        char c = name[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
        if (c != target[i]) {
            for (i = 0; target2[i]; i++) {
                char d = name[i];
                if (d >= 'A' && d <= 'Z') d = (char)(d + 32);
                if (d != target2[i]) return 0;
            }
            return 1;
        }
    }
    return 1;
}

static int SlotReady(const VtHook *h)
{
    DWORD addr = h->vtable + h->offset;
    return IsReadable(addr, 4) && *(DWORD *)addr != 0;
}

static DWORD WINAPI InitThread(LPVOID param)
{
    DWORD start = GetTickCount();
    int loggedWait = 0;
    (void)param;

    /* The client is packed: code and vtables appear only after it unpacks itself. */
    for (;;) {
        if (SlotReady(&g_hookAvatar) && SlotReady(&g_hookMonster)
            && CheckSignatures(0)
            && CheckRtti(ADDR_CAVATAR_VTBL, ".?AVCAvatar@@"))
            break;
        if (!loggedWait && GetTickCount() - start > 15000) {
            loggedWait = 1;
            Log("still waiting for the client to unpack...");
        }
        if (GetTickCount() - start > 600000) {
            CheckSignatures(1);
            Log(MS(S_41));
            return 0;
        }
        Sleep(200);
    }

    Log("client unpacked after %lu ms, signatures OK, RTTI CAvatar OK", GetTickCount() - start);
    g_dieCheck = CodeMatches(ADDR_IS_ACTION, g_sigIsAction) && CodeMatches(ADDR_DIE_ACTION_CODE, g_sigDieAction);
    Log("dying monsters: %s", g_dieCheck ? "known by their die action (HPBars 1.15+): HP 0 alone is no death"
                                         : "UNKNOWN (signatures differ), HP 0 counts as dead");
    InstallVtHook(&g_hookAvatar);
    if (g_cfg.botEnabled) {
        if (!CheckRtti(VTBL_CANIMUS, ".?AVCAnimus@@"))
            Log(MS(S_42));
        if (SlotReady(&g_hookCombat) && CheckRtti(VTBL_COMBAT_PROCESSOR, ".?AVCNetMsgProcessor_Combat@@")
            && CodeMatches(ADDR_COMBAT_ANALYSIS, g_sigCombatAnalysis))
            InstallVtHook(&g_hookCombat);
        else
            Log(MS(S_43));
    }
    OpenBotShared();
    return 0;
}

/* ============================ dinput8 proxy exports ============================= */

static HMODULE g_realDinput;

static FARPROC RealProc(const char *name)
{
    if (!g_realDinput) {
        char path[MAX_PATH];
        UINT len = GetSystemDirectoryA(path, MAX_PATH);
        if (len == 0 || len > MAX_PATH - 16) return NULL;
        lstrcatA(path, "\\dinput8.dll");
        g_realDinput = LoadLibraryA(path);
        if (!g_realDinput) {
            Log("ERROR: cannot load system %s", path);
            return NULL;
        }
    }
    return GetProcAddress(g_realDinput, name);
}

#define E_FAIL_HR ((HRESULT)0x80004005L)

typedef HRESULT (WINAPI *PFN_DirectInput8Create)(HINSTANCE, DWORD, const void *, LPVOID *, void *);
typedef HRESULT (WINAPI *PFN_NoArgs)(void);
typedef HRESULT (WINAPI *PFN_GetClassObject)(const void *, const void *, LPVOID *);

HRESULT WINAPI Proxy_DirectInput8Create(HINSTANCE inst, DWORD version, const void *riid, LPVOID *out, void *outer)
{
    PFN_DirectInput8Create fn = (PFN_DirectInput8Create)RealProc("DirectInput8Create");
    return fn ? fn(inst, version, riid, out, outer) : E_FAIL_HR;
}

HRESULT WINAPI Proxy_DllCanUnloadNow(void)
{
    PFN_NoArgs fn = (PFN_NoArgs)RealProc("DllCanUnloadNow");
    return fn ? fn() : 1 /* S_FALSE */;
}

HRESULT WINAPI Proxy_DllGetClassObject(const void *clsid, const void *riid, LPVOID *out)
{
    PFN_GetClassObject fn = (PFN_GetClassObject)RealProc("DllGetClassObject");
    return fn ? fn(clsid, riid, out) : E_FAIL_HR;
}

HRESULT WINAPI Proxy_DllRegisterServer(void)
{
    PFN_NoArgs fn = (PFN_NoArgs)RealProc("DllRegisterServer");
    return fn ? fn() : E_FAIL_HR;
}

HRESULT WINAPI Proxy_DllUnregisterServer(void)
{
    PFN_NoArgs fn = (PFN_NoArgs)RealProc("DllUnregisterServer");
    return fn ? fn() : E_FAIL_HR;
}

/* ================================== DllMain ===================================== */

static void BuildPaths(HMODULE self, const char *dllPath)
{
    char *slash = NULL;
    char *p;

    g_dir[0] = 0;
    if (dllPath && dllPath[0]) {
        lstrcpynA(g_dir, dllPath, MAX_PATH);
    } else {
        GetModuleFileNameA(self, g_dir, MAX_PATH);
    }
    for (p = g_dir; *p; p++)
        if (*p == '\\' || *p == '/') slash = p;
    if (slash) slash[1] = 0; else g_dir[0] = 0;

    lstrcpynA(g_iniPath, g_dir, MAX_PATH);
    MASKSTR(g_tmpName, S_INI);
    lstrcatA(g_iniPath, g_tmpName);
    lstrcpynA(g_logPath, g_dir, MAX_PATH);
    MASKSTR(g_tmpName, S_LOG);
    lstrcatA(g_logPath, g_tmpName);
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_ATTACH) {
        g_self = inst;
        DisableThreadLibraryCalls(inst);
        /* reserved = the DLL path the manual mapper passes (GetModuleFileNameA fails for an
         * unlinked module); NULL when loaded by LoadLibrary (then the real path is used). */
        BuildPaths(inst, (const char *)reserved);

        {
            char dbg[400];
            char dbgPath[MAX_PATH];
            HANDLE dh;
            lstrcpynA(dbgPath, g_dir, MAX_PATH);
            MASKSTR(g_tmpName, S_DBG);
            lstrcatA(dbgPath, g_tmpName);
            dh = CreateFileA(dbgPath, GENERIC_WRITE,
                                    FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                                    FILE_ATTRIBUTE_NORMAL, NULL);
            if (dh != INVALID_HANDLE_VALUE) {
                DWORD w, len;
                SetFilePointer(dh, 0, NULL, FILE_END);
                /* %.300s: the path the mapper passes may be up to MAX_PATH long, dbg must not overflow */
                len = wsprintfA(dbg, "DllMain attach inst=0x%08lX reason=%lu reserved=%.300s\r\n",
                                (DWORD)inst, reason, reserved ? (const char *)reserved : "(null)");
                WriteFile(dh, dbg, len, &w, NULL);
                CloseHandle(dh);
            }
        }

        if (!IsGameProcess())
            return TRUE;   /* launcher or another tool */

        {
            HANDLE log = CreateFileA(g_logPath, GENERIC_WRITE, FILE_SHARE_READ, NULL,
                                     CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
            if (log != INVALID_HANDLE_VALUE) CloseHandle(log);
        }
        Log(MS(S_44), (DWORD)inst);
        LoadConfig();

        g_hookAvatar.hook  = (DWORD)&Hook_AvatarOverhead;
        g_hookCombat.hook  = (DWORD)&Hook_CombatPacket;

        {
            HANDLE thread = CreateThread(NULL, 0, InitThread, NULL, 0, NULL);
            if (thread) CloseHandle(thread);
        }
    } else if (reason == DLL_PROCESS_DETACH) {
        if (reserved == NULL) {   /* FreeLibrary, not process exit */
            RemoveVtHook(&g_hookAvatar);
            RemoveVtHook(&g_hookCombat);
        }
    }
    return TRUE;
}
