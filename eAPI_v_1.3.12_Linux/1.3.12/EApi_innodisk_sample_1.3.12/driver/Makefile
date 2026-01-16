CONFIG_MODULE_SIG = n
Q                := @
PWD              ?= $(shell pwd)
KERNEL_SRC       ?= /lib/modules/`uname -r`/build
CFILES           := innoeapi.c
TARGET           := innoeapi.ko
obj-m            := innoeapi.o

default:
	$(MAKE) -C$(KERNEL_SRC) M=$(PWD) modules
	$(Q)cp $(TARGET) ../

clean:
	$(MAKE) -C$(KERNEL_SRC) M=$(PWD) clean
	$(Q)rm -f ../$(TARGET)
