/* Linux UAPI, layout identical for ILP32/LP64. */
#ifndef VCU_DOT4_UAPI_H
#define VCU_DOT4_UAPI_H
#include <linux/types.h>
#include <linux/ioctl.h>
struct vcu_dot4_request { __u32 a,b; __s32 result; __u32 reserved; };
#define VCU_DOT4_EXEC _IOWR('V',0x41,struct vcu_dot4_request)
#endif
