/* Linux-user workload diagnostic; no timer, guest patch, PMU or hardware access. */
#include <stddef.h>
#include <qemu-plugin.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;
static const uint64_t start = 0x106ac, begin = 0x106b0, end = 0x10f3a,
                      clock_pc = 0x147ac, next = 0x10af0, list = 0x13b0c;
/* The flexible array records the real PCs, including compressed instructions. */
struct span { struct span *link; uint64_t hits; size_t len; uint64_t pc[]; };
static struct span *spans;
static uint64_t count, last, list_calls;
static int phase, clocks, vcpus, rounds, expected, scalar;
static FILE *report, *order;

static void require(int ok) {
    if (!ok) { fputs("inconsistent workload window\n", stderr); abort(); }
}
static int marker(uint64_t p) {
    return p == start || p == begin || p == end || p == clock_pc || p == next || p == list;
}
static void close_round(void) {
    require(count > last && list_calls == 2 && ++rounds <= expected);
    require(fprintf(report,"R %d %" PRIu64 "\n",rounds,count-last) > 0);
    last = count; list_calls = 0;
}
static void trace_span(unsigned cpu, void *opaque) {
    struct span *s = opaque; require(cpu == 0);
    if (phase != 2) return;
    for (size_t i = 0; i < s->len; i++) {
        uint64_t pc = s->pc[i]; require(pc <= UINT32_MAX);
        for (unsigned b = 0; b < 4; b++) require(fputc((pc >> (8*b)) & 255,order) != EOF);
    }
}
static void special(unsigned cpu, void *opaque) {
    struct span *s = opaque; uint64_t p = s->pc[0]; require(cpu == 0);
    if (p == start) { require(phase == 0); phase = 1; }
    if (p == clock_pc) { require((phase == 1 && clocks == 0) || (phase == 3 && clocks == 1)); clocks++; }
    if (p == begin) {
        require(phase == 1 && clocks == 1); phase = 2; count = last = 0;
        for (struct span *a = spans; a; a = a->link) a->hits = 0;
    }
    if (p == next) { require(phase == 2); close_round(); }
    if (p == list) { require(phase == 2 && ++list_calls <= 2); }
    if (p == end) {
        require(phase == 2); close_round(); require(rounds == expected); phase = 3;
        for (struct span *a = spans; a; a = a->link) if (a->hits) {
            require(fprintf(report,"S %" PRIu64, a->hits) > 0);
            for (size_t i = 0; i < a->len; i++) require(fprintf(report," %" PRIx64,a->pc[i]) > 0);
            require(fputc('\n',report) != EOF);
        }
    }
    if (phase == 2) {
        count += s->len; s->hits++;
        if (order) trace_span(cpu,s);
    }
}
static void translate(qemu_plugin_id_t id, struct qemu_plugin_tb *tb) {
    (void)id; size_t n = qemu_plugin_tb_n_insns(tb);
    for (size_t i = 0; i < n;) {
        struct qemu_plugin_insn *first = qemu_plugin_tb_get_insn(tb,i);
        uint64_t p = qemu_plugin_insn_vaddr(first); size_t j = i + 1;
        /* Never charge an instruction on the other side of a fence/round to this span. */
        while (!scalar && j < n && !marker(qemu_plugin_insn_vaddr(qemu_plugin_tb_get_insn(tb,j)))) j++;
        struct span *s = calloc(1,sizeof(*s)+(j-i)*sizeof(*s->pc)); require(s != NULL);
        s->len = j-i; s->link = spans; spans = s;
        for (size_t k = i; k < j; k++) s->pc[k-i] = qemu_plugin_insn_vaddr(qemu_plugin_tb_get_insn(tb,k));
        if (marker(p)) qemu_plugin_register_vcpu_insn_exec_cb(first,special,QEMU_PLUGIN_CB_NO_REGS,s);
        else {
            if (order) qemu_plugin_register_vcpu_insn_exec_cb(first,trace_span,QEMU_PLUGIN_CB_NO_REGS,s);
            qemu_plugin_register_vcpu_insn_exec_inline(first,QEMU_PLUGIN_INLINE_ADD_U64,&count,s->len);
            qemu_plugin_register_vcpu_insn_exec_inline(first,QEMU_PLUGIN_INLINE_ADD_U64,&s->hits,1);
        }
        i = j;
    }
}
static void init_cpu(qemu_plugin_id_t id, unsigned cpu) { (void)id; require(cpu == 0 && ++vcpus == 1); }
static void finish(qemu_plugin_id_t id, void *ud) {
    (void)id; (void)ud; require(vcpus == 1 && phase == 3 && clocks == 2 && rounds == expected);
    require(fputs("DONE\n",report) >= 0 && fclose(report) == 0);
    if (order) require(fclose(order) == 0);
}
QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id, const qemu_info_t *info,int argc,char **argv) {
    (void)argv; const char *m = getenv("VCU_WINDOW_MODE"), *n = getenv("VCU_WINDOW_ROUNDS");
    if (argc || info->system_emulation || strcmp(info->target_name,"riscv64") || !m || !n) return -1;
    if (!strcmp(m,"insn")) scalar = 1; else if (strcmp(m,"span")) return -1;
    if (!strcmp(n,"4")) expected = 4; else if (!strcmp(n,"24000")) expected = 24000; else return -1;
    report = fopen("counts.txt","wx"); require(report != NULL);
    if (expected == 4) { order = fopen("short.pcs","wbx"); require(order != NULL); }
    qemu_plugin_register_vcpu_init_cb(id,init_cpu); qemu_plugin_register_vcpu_tb_trans_cb(id,translate);
    qemu_plugin_register_atexit_cb(id,finish,NULL); return 0;
}
