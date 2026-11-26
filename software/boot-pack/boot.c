#include <stddef.h>
#include <stdint.h>
#include "payload.h"
extern const uint8_t packed_start[],packed_end[];
int unpack_block(const uint8_t*,size_t,uint8_t*,size_t);
uint32_t unpack_crc32(const uint8_t*,size_t);
static void text(const char *p){volatile uint32_t *tx=(volatile uint32_t *)0x64000000ul;while(*p){while((int32_t)*tx<0){} *tx=(unsigned char)*p++;}}
int unpack_boot(uintptr_t dtb){
    uint8_t *const dst=(uint8_t*)0x80000000ul;
    const int board=dtb>=0x10000 && dtb<0x12000;
    int ok=(uintptr_t)packed_end-(uintptr_t)packed_start==PACK_BYTES && unpack_block(packed_start,PACK_BYTES,dst,RAW_BYTES) && unpack_crc32(dst,RAW_BYTES)==RAW_CRC;
    if(board)text(ok?"UART5_PACK1_OK " PACK_LABEL "\r\n":"UART5_PACK1_STOP\r\n");
    return ok;
}
