/* BOOM v3 Medium only: set ID in bits 7:0, single event bit above bit 7.
 * Count cycles with an event, not number of retired branches or stall cycles.
 * Do not use these BOOM selectors on Rocket or on a core without the CSRs. */
#define HPM_SELECT(n, event) do { unsigned long in=(event), out; \
    __asm__ volatile ("csrw mhpmevent" #n ",%1\n\tcsrr %0,mhpmevent" #n : "=r"(out) : "r"(in) : "memory"); \
    if (out!=in) return 0; } while (0)
static int hpm_setup(void) {
    HPM_SELECT(3,0x201); HPM_SELECT(4,0x401); HPM_SELECT(5,0x801);
    HPM_SELECT(6,0x102); HPM_SELECT(7,0x202); return 1;
}
struct hpm_values { uint64_t br, jalr, flush, ic, dc; };
#define HPM_GET(n, dst) __asm__ volatile ("csrr %0,mhpmcounter" #n : "=r"(dst) :: "memory")
static inline __attribute__((always_inline)) struct hpm_values hpm_read(void) {
    struct hpm_values v;
    HPM_GET(3,v.br); HPM_GET(4,v.jalr); HPM_GET(5,v.flush); HPM_GET(6,v.ic); HPM_GET(7,v.dc); return v;
}
