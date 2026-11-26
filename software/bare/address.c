/* Standalone M-mode payload, never run under an OS. Reservation: four 4 KiB
 * scratch windows at 0x81000000 + n*512MiB in the 2 GiB physical DDR aperture.
 * Loader, image, DTB and both stacks are outside these windows in this profile. */
#include <stdint.h>
#define UART ((volatile uint32_t *)0x64000000ul)
#define CACHE_CONFIG (*(volatile const uint32_t *)0x02010000ul)
#define FLUSH64 (*(volatile uint64_t *)0x02010200ul)
static void line(const char *s) {
    for (; *s; ++s) { while ((int32_t)UART[0] < 0) {} UART[0]=(uint8_t)*s; }
    while ((int32_t)UART[0] < 0) {} UART[0]='\r';
    while ((int32_t)UART[0] < 0) {} UART[0]='\n';
}
static uintptr_t addr(unsigned w, unsigned ln) { return 0x81000000ul + ((uintptr_t)w << 29) + 64ul*ln; }
static uint64_t pattern(uintptr_t a, unsigned pass) {
    return ((uint64_t)a * UINT64_C(0x9e3779b97f4a7c15)) ^ (pass ? UINT64_MAX : 0);
}
static void barrier(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
void diagnose(void) {
    UART[6]=867; UART[2]=1; line("VCU118_ADDR_START v1");
    /* One bank, 8 ways, 1024 sets, 64 B lines: pinned InclusiveCacheControl. */
    if (CACHE_CONFIG != 0x060a0801u) { line("VCU118_ADDR_FAIL cache-config"); return; }
    for (unsigned pass=0; pass!=2; ++pass) {
        for (unsigned w=0; w!=4; ++w) for (unsigned l=0; l!=64; ++l) {
            volatile uint64_t *p=(volatile uint64_t *)addr(w,l);
            for (unsigned k=0; k!=8; ++k) p[k]=pattern((uintptr_t)&p[k],pass);
        }
        /* fence only orders. Flush64 explicitly probes and evicts the named
         * inclusive-cache line; wait on ordered MMIO before issuing reloads. */
        barrier(); for (unsigned w=0; w!=4; ++w) for (unsigned l=0; l!=64; ++l) FLUSH64=addr(w,l);
        barrier();
        for (unsigned w=0; w!=4; ++w) for (unsigned l=0; l!=64; ++l) {
            volatile const uint64_t *p=(volatile const uint64_t *)addr(w,l);
            for (unsigned k=0; k!=8; ++k) if (p[k]!=pattern((uintptr_t)&p[k],pass)) { line("VCU118_ADDR_FAIL data"); return; }
        }
    }
    line("VCU118_ADDR_PASS windows=4 bytes_each=4096 passes=2 flush_lines=512");
}
