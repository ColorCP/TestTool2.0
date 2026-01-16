#include <linux/init.h>
#include <linux/module.h>
#include <linux/cdev.h>
#include <linux/blkdev.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <asm/uaccess.h>
#include <asm/ioctl.h>
#include <linux/delay.h>
#include <linux/version.h>

MODULE_LICENSE("Dual BSD/GPL");

#define DevName "innoeapi"
#define ClassName "class_innoeapi"

/*********************************************************************************************/
#define GET_BIT(x, bit) ((x & (1 << bit)) >> bit)

#define INNO_IOCTL_SET_DATA _IOW('k', 0, struct ioctl_data)
#define INNO_IOCTL_GET_DATA _IOR('k', 1, struct ioctl_data)

struct class *mem_class;
struct Pci_dev *inno_devices;
struct cdev _cdev;
dev_t dev;

struct ioctl_data 
{
    unsigned long physical_address;
    u32 value;
};

/*********************************************************************************************/

#define GPIO_TX_State               (1 << 0)
#define GPIO_RX_State               (1 << 1)
#define GPIO_TX_Disable             (1 << 8)
#define GPIO_RX_Disable             (1 << 9)
#define PM_MODE                     (1 << 10)

/*********************************************************************************************/
static int board = 0;

module_param(board, int, S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH);

/*********************************************************************************************/
static int innoeapi_open(struct inode *inode, struct file *filp)
{
    return 0;
}

static int innoeapi_release(struct inode *inode, struct file *filp)
{   
    return 0;
}

static ssize_t innoeapi_read(struct file *file, char __user *buffer, size_t length, loff_t *offset)
{    
    return 0; 
}

static ssize_t innoeapi_write(struct file *filp, const char __user *buf, size_t count, loff_t *ppos)
{
    return count;
}

static long innoeapi_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    struct ioctl_data data;
    unsigned long physical_address;
    u32 value;

    if (copy_from_user(&data, (struct ioctl_data *)arg, sizeof(struct ioctl_data)) != 0)
                return -EFAULT;

    physical_address = data.physical_address;
    value = data.value; 

    void __iomem *mapped_address = ioremap(physical_address, 0x100);
    if (!mapped_address) {
        printk(KERN_ERR "Failed to map physical address\n");
        return -ENOMEM;
    }

    printk("after mapped data.value: 0x%08X\n", data.value);
    
    printk("after mapped value: 0x%08X\n", value);
    switch (cmd)
    {
        case INNO_IOCTL_SET_DATA:           

            writel(value, (void __iomem *)mapped_address);

            //mdelay(10);

            value = readl((void __iomem *)mapped_address); 
            iounmap(mapped_address);

            return 0;

        case INNO_IOCTL_GET_DATA:
            value = readl((void __iomem *)mapped_address); 
            //msleep(10);
            data.value = value;

            if (copy_to_user((struct ioctl_data *)arg, &data, sizeof(struct ioctl_data)) != 0)
            {
                iounmap(mapped_address);
                return -EFAULT;
            }
            
            iounmap(mapped_address);
            return 0;

        default:
            return -EINVAL;
    }

    return -EINVAL;  
}

const struct file_operations my_fops = {
    .owner   = THIS_MODULE,
    .open    = innoeapi_open,
    .write   = innoeapi_write,
    .read    = innoeapi_read,
    .release = innoeapi_release,
    .unlocked_ioctl = innoeapi_ioctl,
};

static __init int innoeapi_init(void)
{
    int result = alloc_chrdev_region(&dev, 0 , 2, DevName);
    if(result < 0)
    {
        printk("Err:failed in alloc_chrdev_region.\n");
        return result;
    }

    // mem_class = class_create(THIS_MODULE, ClassName);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 4, 0)
    mem_class = class_create(ClassName);
#else
    mem_class = class_create(THIS_MODULE, ClassName);
#endif
    if(IS_ERR(mem_class))
        printk("Err:failed in class_create.\n");

    device_create(mem_class, NULL, dev, NULL, DevName);

    cdev_init(&_cdev, &my_fops);
    _cdev.owner = THIS_MODULE;
    _cdev.ops = &my_fops;
    result = cdev_add(&_cdev, dev, 1);

    // printk("eapi init\n");

    return result;
}

static void __exit innoeapi_exit(void)
{
	// printk(KERN_INFO "Goodbye\n");
    if(0 != mem_class)
    {
        device_destroy(mem_class, dev);
        class_destroy(mem_class);
        mem_class = 0;
    }
    cdev_del(&_cdev);
}

module_init(innoeapi_init);
module_exit(innoeapi_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("innodisk");