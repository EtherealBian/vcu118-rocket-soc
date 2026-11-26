/* The external JTAG debugger uploads this program AND all input words via SBA.
 * No SD, preloaded RAM, cache flushes or host-assisted guest result. */
#include <stdint.h>
#define UART ((volatile uint32_t *)0x64000000ul)
#define MAIL ((volatile uint32_t *)0x81000000ul)
void diagnose(void) {
    uint32_t acc = 0x7f4a7c15u;
    for (unsigned i = 0; i < 32; ++i) {
        acc = (acc << 5) | (acc >> 27);
        acc += MAIL[i] ^ (0x9e3779b9u + i);
    }
    MAIL[64] = acc;
    __asm__ volatile ("fence rw,rw" ::: "memory");
    UART[6] = 867; UART[2] = 1;
    for (const char *s = "\r\nSBA_GUEST_REPLIED v1\r\n"; *s; ++s) {
        while ((int32_t)UART[0] < 0) {}
        UART[0] = (uint8_t)*s;
    }
}
