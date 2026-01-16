sudo rm -f /usr/sbin/EApi_Test
sudo rm -f /etc/init.d/run_eapidriver
sudo rm -f /lib/modules/$(uname -r)/kernel/drivers/innoeapi.ko
sudo cp ../EApi_Test /usr/sbin
sudo cp ./run_eapidriver /etc/init.d
sudo cp ../innoeapi.ko /lib/modules/$(uname -r)/kernel/drivers
sudo depmod -a
sudo chmod +x /etc/init.d/run_eapidriver
sudo update-rc.d run_eapidriver defaults
