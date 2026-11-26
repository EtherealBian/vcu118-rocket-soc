/* Bounded, one-block LZ4 reader for the fixed-destination UART boot experiment.
 * Counts never exceed the caller-provided buffers. Overlapping matches must be
 * copied forward, byte by byte. This is not a general ELF or LZ4 frame loader. */
#include <stddef.h>
#include <stdint.h>
static int length(const uint8_t *s, size_t n, size_t *i, size_t *v, size_t cap) {
    if (*v == 15) {
        unsigned x;
        do { if (*i >= n) return 0; x=s[(*i)++];
             if (*v>cap || x>cap-*v) return 0;
             *v+=x;
        } while(x==255);
    }
    return *v<=cap;
}
int unpack_block(const uint8_t *s,size_t n,uint8_t *d,size_t size) {
    size_t i=0,o=0;
    if(!size || size>(30u<<20) || !n || n>(30u<<20))return 0;
    while(i<n){
        uint8_t token=s[i++]; size_t count=token>>4;
        if(!length(s,n,&i,&count,size-o) || count>n-i)return 0;
        for(size_t j=0;j<count;j++) d[o++]=s[i++];
        if(i==n)return o==size;
        if(n-i<2)return 0;
        size_t back=(size_t)s[i]|((size_t)s[i+1]<<8);i+=2;
        if(!back || back>o || size-o<4)return 0;
        count=token&15;
        if(!length(s,n,&i,&count,size-o-4))return 0;
        for(size_t j=0;j<count+4;j++,o++)d[o]=d[o-back];
    }
    return 0; /* the final sequence contains only literals */
}
uint32_t unpack_crc32(const uint8_t *data,size_t n) {
    uint32_t s=~0u;
    for(size_t i=0;i<n;i++){s^=data[i]; for(unsigned j=0;j<8;j++)s=(s>>1)^((0u-(s&1u))&0xedb88320u);}
    return ~s;
}
