// SPDX-License-Identifier: GPL-2.0-only
/* One transaction at a time; no raw physical addresses, DMA or user mappings. */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/kref.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/compat.h>
#include "vcu_dot4_uapi.h"
#define ID 0x00
#define STATUS 0x04
#define AREG 0x08
#define BREG 0x0c
#define CMD 0x10
#define RESULT 0x14
#define READY BIT(0)
#define VALID BIT(1)
#define BAD BIT(2)
#define PENDING BIT(3)
struct vcu_dot4 { struct miscdevice misc; struct kref refs; struct mutex lock; void __iomem *base; bool gone; };
static void release_ref(struct kref *r){kfree(container_of(r,struct vcu_dot4,refs));}
static int dot_open(struct inode *ino,struct file *f){struct vcu_dot4 *d=container_of(f->private_data,struct vcu_dot4,misc);kref_get(&d->refs);f->private_data=d;return nonseekable_open(ino,f);}
static int dot_release(struct inode *ino,struct file *f){struct vcu_dot4 *d=f->private_data;kref_put(&d->refs,release_ref);return 0;}
static long dot_ioctl(struct file *f,unsigned int cmd,unsigned long arg){struct vcu_dot4 *d=f->private_data;struct vcu_dot4_request req;u32 s;int ret;
 if(cmd!=VCU_DOT4_EXEC)return -ENOTTY;
 if(copy_from_user(&req,(void __user*)arg,sizeof(req)))return -EFAULT;
 if(req.reserved)return -EINVAL;
 if(mutex_lock_interruptible(&d->lock))return -ERESTARTSYS;
 if(d->gone){ret=-ENODEV;goto out;}
 /* Recover the result of a previous timeout without returning it for this request. */
 ret=readl_poll_timeout(d->base+STATUS,s,s&(READY|VALID),1,10000);if(ret)goto out;
 if(s&VALID)writel(2,d->base+CMD);
 if(s&BAD)writel(4,d->base+CMD);
 ret=readl_poll_timeout(d->base+STATUS,s,(s&(READY|VALID|PENDING|BAD))==READY,1,10000);if(ret)goto out;
 writel(req.a,d->base+AREG);writel(req.b,d->base+BREG);writel(1,d->base+CMD);
 ret=readl_poll_timeout(d->base+STATUS,s,s&(VALID|BAD),1,10000);if(ret)goto out;
 if(s&BAD){ret=-EIO;goto out;}req.result=(s32)readl(d->base+RESULT);writel(2,d->base+CMD);
 ret=readl_poll_timeout(d->base+STATUS,s,(s&(READY|VALID|PENDING|BAD))==READY,1,10000);
out: mutex_unlock(&d->lock);if(ret)return ret;
 return copy_to_user((void __user*)arg,&req,sizeof(req))?-EFAULT:0;
}
static const struct file_operations ops={.owner=THIS_MODULE,.open=dot_open,.release=dot_release,.unlocked_ioctl=dot_ioctl,
#ifdef CONFIG_COMPAT
 .compat_ioctl=compat_ptr_ioctl,
#endif
 .llseek=no_llseek};
static int dot_probe(struct platform_device *p){struct vcu_dot4 *d;int ret;void __iomem *base=devm_platform_ioremap_resource(p,0);if(IS_ERR(base))return PTR_ERR(base);if(readl(base+ID)!=0x34544f44)return -ENODEV;
 d=kzalloc(sizeof(*d),GFP_KERNEL);if(!d)return -ENOMEM;kref_init(&d->refs);mutex_init(&d->lock);d->base=base;
 d->misc.minor=MISC_DYNAMIC_MINOR;d->misc.name="vcu-dot4";d->misc.fops=&ops;d->misc.parent=&p->dev;d->misc.mode=0600;
 ret=misc_register(&d->misc);if(ret){kref_put(&d->refs,release_ref);return ret;}platform_set_drvdata(p,d);dev_info(&p->dev,"DOT4 MMIO v1 ready\n");return 0;}
static void dot_remove(struct platform_device *p){struct vcu_dot4 *d=platform_get_drvdata(p);misc_deregister(&d->misc);mutex_lock(&d->lock);d->gone=true;mutex_unlock(&d->lock);kref_put(&d->refs,release_ref);}
static const struct of_device_id ids[]={{.compatible="vcu118lab,dot4-i8-v1"},{}};MODULE_DEVICE_TABLE(of,ids);
static struct platform_driver drv={.probe=dot_probe,.remove_new=dot_remove,.driver={.name="vcu-dot4",.of_match_table=ids}};module_platform_driver(drv);
MODULE_LICENSE("GPL");MODULE_DESCRIPTION("VCU118 four-lane signed INT8 dot product");
