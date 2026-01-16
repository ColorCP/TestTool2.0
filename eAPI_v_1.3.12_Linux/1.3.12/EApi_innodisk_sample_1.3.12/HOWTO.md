[needed_library]
1. utility: EApi.a
2. multi-lib: $ sudo apt-get install gcc-12-multilib
3. build-essential: $ sudo apt-get install build-essential

[notice]
1. build with root

[build]
(use root)
1. $ make clean
2. $ make

[install]
1. Method (a) is preferred. If module "innoeapi" is currently loaded, choose to use method (b).
    a) sudo cp innoeapi.ko /lib/modules/$(uname -r)/kernel/drivers
       sudo depmod -a
       sudo modprobe innoeapi
	   echo "innoeapi" | sudo tee /etc/modules-load.d/innoeapi.conf
    b) sudo insmod innoeapi.ko

[test]
1. show EApi information
    $ sudo ./EApi_Test
2. show EApi usage
    $ sudo ./EApi_Test -h

[remove]
1. sudo pkill -2 EApi_Test
2. sudo rmmod innoeapi.ko

[notice]
