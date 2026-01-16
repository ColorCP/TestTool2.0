sudo update-rc.d -f run_eapidriver remove
sudo rm -f /usr/sbin/EApi_Test
sudo rm -f /etc/init.d/run_eapidriver
sudo rm -f /lib/modules/$(uname -r)/kernel/drivers/innoeapi.ko
