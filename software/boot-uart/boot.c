/* ROM5 is an explicitly selected recovery configuration, not an SD auto-detect.
 * No loader-selected address, no flash writes, single hart; this CRC detects
 * transfer errors. It does not authenticate the person connected to the board. */
#include <stdint.h>
#define UART ((volatile uint32_t *)0x64000000ul)
#define MTIME (*(volatile const uint64_t *)0x0200bff8ul)
#define DDR ((uint8_t *)0x80000000ul)
#define MAX_BYTES (30u * 1024u * 1024u)
#ifndef UART_PBUS_HZ
#define UART_PBUS_HZ 100000000u
#endif
#ifndef UART_TIMEBASE_HZ
#define UART_TIMEBASE_HZ 100000u
#endif
#define RX_TIMEOUT_TICKS (2u * UART_TIMEBASE_HZ) /* 2 s at this board's 100 kHz */

static void line(const char *s) {
    while (*s) { while ((int32_t)UART[0] < 0) {} UART[0] = (uint8_t)*s++; }
}

/* Native tests replace just the two MMIO reads; ROM builds use plain volatile loads. */
#ifndef UART5_TEST_MMIO
#define UART5_RX_READ() ((int32_t)UART[1])
#define UART5_NOW() MTIME
#endif

/* Only the very first byte waits indefinitely: the PC may still be finishing
 * JTAG DONE/CRC checks. Once a frame starts, silence is a terminal error. */
static int byte_in(int first) {
    uint64_t start = UART5_NOW();
    for (;;) {
        int32_t v = UART5_RX_READ();
        if (v >= 0) return v & 255;
        if (!first && UART5_NOW() - start >= RX_TIMEOUT_TICKS) return -1;
    }
}

static uint32_t le32(const uint8_t *p) {
    return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}

/* The destination is fixed; never invoke partially transferred code. */
static const char *receive(uint8_t *dst) {
    uint8_t h[16];
    for (unsigned i=0; i<sizeof(h); ++i) {
        int v=byte_in(i==0);
        if (v<0) return "TIMEOUT";
        h[i]=(uint8_t)v;
    }
    for (unsigned i=0; i<8; ++i) if (h[i] != "VCU118U5"[i]) return "MAGIC";
    uint32_t n=le32(h+8), expected=le32(h+12), crc=~0u;
    if (!n || n>MAX_BYTES) return "LENGTH";
    for (uint32_t i=0; i<n; ++i) {
        int v=byte_in(0);
        if (v<0) return "TIMEOUT";
        dst[i]=(uint8_t)v;
        crc ^= (uint8_t)v;
        for (unsigned k=0; k<8; ++k) crc=(crc>>1) ^ ((0u-(crc&1u)) & 0xedb88320u);
    }
    return ~crc == expected ? 0 : "CRC";
}

int load_uart(void) {
    UART[6]=(UART_PBUS_HZ+57600u)/115200u-1u; UART[2]=1; UART[3]=1;
    line("UART5_READY v1\r\n");
    const char *err=receive(DDR);
    if (err) { line("UART5_STOP "); line(err); line("\r\n"); return -1; }
    line("UART5_HANDOFF\r\n");
    return 0;
}
