#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <limits.h>
#include <time.h>
#include <math.h>
#include <ctype.h>
#include <stdint.h>
#include "EApi.h"

/*-----------------------------------------------------------------------------------------------------------*/
#define GPIO_NUM 8
#define MAX_USB_POWER_PIN 3

enum SHOW_HELP
{
    SHOW_ALL    = 0,
    SHOW_WDT,
    SHOW_GPIO,
    SHOW_FAN,
    SHOW_BACKLIGHT,
    SHOW_SMBUS,
    SHOW_USB_POWER,
};

enum FAN_TYPE
{
    CPUFAN    = 0,
    SYSFAN1,
    SYSFAN2,
    SYSFAN3,
    SYSFAN4,
    SYSFAN5,
};

typedef struct
{
    int timeout;
    int unit;
    int heartbeat;
} WDT_INFO;

typedef struct
{
    int pin;
    int direction;
    int value;
} GPIO_INFO;

typedef struct
{
    int index;
    int mode;
    int speed;
} FAN_INFO;

typedef struct
{
    int brt;        // brightness
} BACKLIGHT_INFO;

typedef struct
{
    int op;         
    int addr;       
    int offset;     
    int length;     
    char *data;     
} SMBUS_INFO;

typedef struct
{
    int pin;       // USB power pin (0-2)
    int ctrl;      // Control value (0=OFF, 1=ON)     
} USB_POWER_INFO;

/*-----------------------------------------------------------------------------------------------------------*/
static void fan_ctrl(FAN_INFO fan);
static void gpio_set(GPIO_INFO gpio);
static void usb_power_set(USB_POWER_INFO usb_power);

int handle_smbus_command(int argc, char *argv[]);
int smbus_ctrl(SMBUS_INFO *smbus, int argc, char *argv[], int optind);


/*-----------------------------------------------------------------------------------------------------------*/
static const struct option long_opt[] =
{
    { "watchdog",  1, NULL, 'w' },   
    { "trigger",   1, NULL, 't' },   
    { "unit",      1, NULL, 'u' },

    { "gpio",      1, NULL, 'g' },   
    { "direction", 1, NULL, 'd' },   
    { "value",     1, NULL, 'v' },   


    { "fan",       1, NULL, 'f' }, 
    { "fanmode",   1, NULL, 'm' },   
    { "speed",     1, NULL, 's' },   

    { "backlight", 1, NULL, 'b' },

    
    { "usbpwrpin"   , 1, NULL, 'p' },
    { "usbpwronoff" , 1, NULL, 'c' },

    { "smbus",     no_argument, NULL, 'S' },

    { "help",      1, NULL, 'h' },   
    { NULL,        0, NULL, '0' },
};

/*-----------------------------------------------------------------------------------------------------------*/
void help(char *name, int show)
{
    printf("usage: \n");

    if(show == SHOW_ALL)
        printf("%s%11s%s \n", name, "", "board information");    

    if(show == SHOW_ALL || show == SHOW_WDT)
    {
        printf("\n%s [-w timeout] [-u unit] [-t trigger] \n", name);    
        printf("    -%s, --%-12s%-29s%s\n", "w", "watchdog", "watchdog timeout",       "[0:disable, 1~255:timeout]");
        printf("    -%s, --%-12s%-29s%s\n", "u", "unit",     "timeout unit",           "[0:second, 1:minute]"      );
        printf("    -%s, --%-12s%-29s%s\n", "t", "trigger",  "reset timeout interval", "[0 ~ 255]"                 );
    }

    if(show == SHOW_ALL || show == SHOW_FAN)
    {
        printf("\n%s [-f Normal_mode] [-s speed] ", name);
        printf("\n%s [-f Smart_Fan_mode] \n", name);
        printf("    -%s, --%-12s%-29s%s\n", "f", "fan",     "select a fan to control",      "[0:CPU fan, 1~5:SYS Fan]"  );
        printf("    -%s, --%-12s%-29s%s\n", "m", "fanmode", "switch fan mode",              "[0:Normal,  1:Smart Fan]"  );
        printf("    -%s, --%-12s%-29s%s\n", "s", "speed",   "switch fan speed",             "[0 ~ 255]"                 );
    }

    if(show == SHOW_ALL || show == SHOW_GPIO)
    {
        printf("\n%s [-g pin] [-d direction] [-v value] \n", name);    
        printf("    -%s, --%-12s%-29s%s\n", "g","gpio",      "select a GPIO pin to control", "[0~7:DIO, 8:AI Button, 9:AI LED]" );
        printf("    -%s, --%-12s%-29s%s\n", "d","direction", "set the GPIO pin direction",   "[0:output, 1:input]"              );
        printf("    -%s, --%-12s%-29s%s\n", "v","value",     "set the GPO pin value",        "[0:low,    1:high]"               );
    }

    if(show == SHOW_ALL || show == SHOW_BACKLIGHT)
    {
        printf("\n%s [-b brightness] \n", name);    
        printf("    -%s, --%-12s%-29s%s\n", "b","backlight", "set the backlight brightness", "[0 ~ 100]");
    }

    if(show == SHOW_ALL || show == SHOW_USB_POWER)
    {
        printf("\n%s [-p usb_power_pin] [-c usb_power_value] \n", name);    
        printf("    -%s, --%-12s%-29s%s\n", "p","usb_power_pin", "select the usb_power_pin", "[0:rear I/O USB3.2, 1:rear I/O USB2.0, 2:Internal USB2.0]");
        printf("    -%s, --%-12s%-29s%s\n", "c","usb_power_pin", "set the usb_power_pin", "[0:OFF, 1:ON]");
    }

    if (show == SHOW_ALL || show == SHOW_SMBUS) 
    {
        printf("SMBUS Command Test:\n");
        printf("  %s SMBus [-r/-w] [addr] [offset] [length/data]\n", name);
        printf("    -r           Perform read operation\n");
        printf("    -w           Perform write operation\n");
        printf("    addr         Device address (7-bit, hexadecimal, e.g.: 50)\n");
        printf("    offset       Command/offset (hexadecimal, e.g.: 00)\n");
        printf("    length       Number of bytes to read (for -r)\n");
        printf("    data         Data to write (for -w, space-separated hexadecimal bytes, e.g.: \"11 22 33\")\n");
        printf("Examples:\n");
        printf("  %s SMBus -r 50 00 16          # Read 16 bytes from address 0x50, offset 0x00\n", name);
        printf("  %s SMBus -w 50 00 \"11 22 33\"  # Write 3 bytes to address 0x50, offset 0x00\n", name);
    }
}

/*-----------------------------------------------------------------------------------------------------------*/

static void boardinfo(void)
{
    EApiStatus_t res = EAPI_STATUS_SUCCESS;

    char         buf[128] = { 0 };
    float        val;
    unsigned int len = sizeof(buf);
    unsigned int tmp = 0;
    unsigned int dir;
    unsigned int level;

    /*------------------------------------------------------------*/
    printf("[Board information] \n");

    res = EApiBoardSupport();
    if(res == EAPI_STATUS_SUCCESS)
        printf("\t%-24s%s \n", "Board Support:", "Support");
    else if(res == EAPI_BOARD_UNSUPPORTED) 
    {
        printf("\t%-24s%s \n", "Board Support:", "Not Support");
    }

    memset(buf, 0, len);
    res = EApiDLLVersion(buf);
    printf("\t%-24s%s \n", "EAPI Version:", 
            (res == EAPI_STATUS_SUCCESS) ? buf : "Can't get EAPI Version.");

    memset(buf, 0, len);
    res = EApiBoardGetStringA(EAPI_ID_BOARD_MANUFACTURER_STR, buf, &len);
    printf("\t%-24s%s \n", "manufacturer:", 
            (res == EAPI_STATUS_SUCCESS) ? buf : "Can't get Board manufacturer.");

    memset(buf, 0, len);
    res = EApiBoardGetStringA(EAPI_ID_BOARD_NAME_STR, buf, &len);
    printf("\t%-24s%s \n", "Product Name:", 
            (res == EAPI_STATUS_SUCCESS) ? buf : "Can't get Board name.");

    memset(buf, 0, len);
    res = EApiBoardGetStringA(EAPI_ID_BOARD_HW_REVISION_STR, buf, &len);
    printf("\t%-24s%s \n", "Version:", 
            (res == EAPI_STATUS_SUCCESS) ? buf : "Can't get Board version.");

    memset(buf, 0, len);
    res = EApiBoardGetStringA(EAPI_ID_BOARD_SERIAL_STR, buf, &len);
    printf("\t%-24s%s \n", "Serial number:", 
            (res == EAPI_STATUS_SUCCESS) ? buf : "Can't get Board serial number.");

    /*------------------------------------------------------------*/
    printf("\n[BIOS information] \n");

    memset(buf, 0, len);
    res = EApiBoardGetStringA(EAPI_ID_BOARD_BIOS_REVISION_STR, buf, &len);
    printf("\t%-24s%s \n", "Version:", 
            (res == EAPI_STATUS_SUCCESS) ? buf : "Can't get BIOS release.");


    /*------------------------------------------------------------*/
    // Exit if unrecognised board
    res = EApiBoardSupport();
    if(res == EAPI_BOARD_UNSUPPORTED) 
    {
        printf("\t%-24s%s \n", "Board Support:", "Not Support");
        return;
    }

    /*------------------------------------------------------------*/
    printf("\n[HW monitor] \n");

    res = EApiBoardGetValue(EAPI_ID_HWMON_CPU_TEMP, &val);
    printf("\t%-24s", "CPU temperature:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.3f °C \n", val)
                                 : printf("%s \n", "Can't get CPU temperature.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_SYSTEM_TEMP, &val);
    printf("\t%-24s", "System temperature:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.3f °C \n", val)
                                 : printf("%s \n", "Can't get System temperature.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_VOLTAGE_VCORE, &val);
    if(res != EAPI_STATUS_UNSUPPORTED)
    {
        printf("\t%-24s", "VCORE:");
        (res == EAPI_STATUS_SUCCESS) ? printf("%.3f V \n", val)
                                    : printf("%s \n", "Can't get VCORE. UNSUPPORTED!");
    }

    res = EApiBoardGetValue(EAPI_ID_HWMON_VOLTAGE_12V, &val);
    printf("\t%-24s", "12V:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.3f V \n", val)
                                 : printf("%s \n", "Can't get 12V.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_VOLTAGE_5VSB, &val);
    printf("\t%-24s", "5V Dual :");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.3f V \n", val)
                                 : printf("%s \n", "Can't get 5V Dual.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_VOLTAGE_3VSB, &val);
    printf("\t%-24s", "V3.3 DUAL:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.3f V \n", val)
                                 : printf("%s \n", "V3.3 DUAL.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_VOLTAGE_VBAT, &val);
    printf("\t%-24s", "VBAT:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.3f V \n", val)
                                 : printf("%s \n", "Can't get VBAT.");

    /*------------------------------------------------------------*/
    printf("\nFan Status\n"); 
    
    res = EApiCPUFanModeGet(&tmp);
    printf("\t%-24s", "CPU Fan mode:");   
    (res == EAPI_STATUS_SUCCESS) ? printf("%s \n", (tmp==EAPI_FAN_MODE_MANUAL)
                                        ? "Normal Mode" : "SMART FAN Mode")
                                 : printf("%s \n", "Can't get fan mode.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_FAN_CPU, &val);
    printf("\t%-24s", "CPU Fan speed:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.0f rpm \n", val)
                                 : printf("%s \n", "Can't get fan speed.");

    /************************************************************************/
    res = EApiSYSFanModeGet(EAPI_ID_SYS_FAN_1, &tmp);
    printf("\t%-24s", "System Fan 1 mode:");   
    (res == EAPI_STATUS_SUCCESS) ? printf("%s \n", (tmp==EAPI_FAN_MODE_MANUAL)
                                        ? "Normal Mode" : "SMART FAN Mode")
                                 : printf("%s \n", "Can't get fan mode.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_FAN_SYSTEM, &val);
    printf("\t%-24s", "System Fan 1 speed:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.0f rpm \n", val)
                                 : printf("%s \n", "Can't get fan speed.");

    /*----------------------*/ 
    res = EApiSYSFanModeGet(EAPI_ID_SYS_FAN_2, &tmp);
    printf("\t%-24s", "System Fan 2 mode:");   
    (res == EAPI_STATUS_SUCCESS) ? printf("%s \n", (tmp==EAPI_FAN_MODE_MANUAL)
                                        ? "Normal Mode" : "SMART FAN Mode")
                                 : printf("%s \n", "Can't get fan mode.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_FAN_SYSTEM2, &val);
    printf("\t%-24s", "System Fan 2 speed:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.0f rpm \n", val)
                                 : printf("%s \n", "Can't get fan speed.");

    /*----------------------*/ 
    res = EApiSYSFanModeGet(EAPI_ID_SYS_FAN_3, &tmp);
    printf("\t%-24s", "System Fan 3 mode:");   
    (res == EAPI_STATUS_SUCCESS) ? printf("%s \n", (tmp==EAPI_FAN_MODE_MANUAL)
                                        ? "Normal Mode" : "SMART FAN Mode")
                                 : printf("%s \n", "Can't get fan mode.");

    res = EApiBoardGetValue(EAPI_ID_HWMON_FAN_SYSTEM3, &val);
    printf("\t%-24s", "System Fan 3 speed:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.0f rpm \n", val)
                                 : printf("%s \n", "Can't get fan speed.");
                                         
    /*----------------------*/                          
    res = EApiSYSFanModeGet(EAPI_ID_SYS_FAN_4, &tmp);
    printf("\t%-24s", "System Fan 4 mode:");   
    (res == EAPI_STATUS_SUCCESS) ? printf("%s \n", (tmp==EAPI_FAN_MODE_MANUAL)
                                        ? "Normal Mode" : "SMART FAN Mode")
                                 : printf("%s \n", "Can't get fan mode.");
    res = EApiBoardGetValue(EAPI_ID_HWMON_FAN_SYSTEM4, &val);
    printf("\t%-24s", "System Fan 4 speed:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.0f rpm \n", val)
                                 : printf("%s \n", "Can't get fan speed.");

    /*----------------------*/                          
    res = EApiSYSFanModeGet(EAPI_ID_SYS_FAN_5, &tmp);
    printf("\t%-24s", "System Fan 5 mode:");   
    (res == EAPI_STATUS_SUCCESS) ? printf("%s \n", (tmp==EAPI_FAN_MODE_MANUAL)
                                        ? "Normal Mode" : "SMART FAN Mode")
                                 : printf("%s \n", "Can't get fan mode.");
    res = EApiBoardGetValue(EAPI_ID_HWMON_FAN_SYSTEM5, &val);
    printf("\t%-24s", "System Fan 5 speed:");
    (res == EAPI_STATUS_SUCCESS) ? printf("%.0f rpm \n", val)
                                 : printf("%s \n", "Can't get fan speed.");

    /*------------------------------------------------------------*/
    printf("\nGPIO Status\n");
    printf("\t+------+--------+-------+\n");
    printf("\t| GPIO |   Dir  | Level |\n");
    printf("\t+------+--------+-------+\n");
    for(tmp=0; tmp < GPIO_NUM; tmp++)
    {
        res = EApiGPIOGetDirection(tmp, &dir);
        res = EApiGPIOGetLevel(tmp, &level);
        if(res == EAPI_STATUS_SUCCESS)
            printf("\t|%3s%d%2s|%7s |%3s%d%3s|\n", "", tmp,"", 
                    (dir==1) ? "input" : "output", "", level, "");
    }
    printf("\t+------+--------+-------+\n");
    
    /*------------------------------------------------------------*/
    if(EApiUSB_Power_Support() == EAPI_STATUS_SUCCESS)
    {
        printf("\nUSB Power Status\n");
        printf("\t+------------------+-------+\n");
        printf("\t|      I/O         | Power |\n");
        printf("\t+------------------+-------+\n");
        
        for(tmp=0; tmp < MAX_USB_POWER_PIN; tmp++)
        {
            res = EApiUSB_Power_Status(tmp, &level);
            if(res == EAPI_STATUS_SUCCESS)
            {
                if(tmp == 0)
                    printf("\t| rear I/O USB3.2  |%6s |\n", 
                        (level==1) ? " on" : " off");
                else if(tmp == 1)
                    printf("\t| rear I/O USB2.0  |%6s |\n", 
                        (level==1) ? " on" : " off");
                else if(tmp == 2)
                    printf("\t| Internal USB2.0  |%6s |\n", 
                        (level==1) ? " on" : " off");
            }
            else
                printf("Get USB power status fail\n");
        }
        printf("\t+------------------+-------+\n");

    }
    
    //    res = EApiGPIOGetDirection(tmp, &dir);
    /*------------------------------------------------------------*/
    printf("\nCase open\n");

    dir = 0x00; //normal close
    tmp = 0x00; 

    if(EApiCaseOpenDetect(&tmp) != EAPI_STATUS_SUCCESS)
    {
        printf("CaseOpenDetect fail !! \n");
        res = EAPI_STATUS_ERROR;
    }
    else
    {
        if(dir == 0x00)
        {
            printf("\t%-24s%s\n","Mode:", "normal close");
            printf("\t%-24s%s\n","Status:", (tmp==0x01) ? "close" : "open");
        }
        else if(dir == 0x01)
        {
            printf("\t%-24s%s\n","Mode:", "normal open");
            printf("\t%-24s%s\n","Status:", (tmp==0x00) ? "open" : "close");
        }
    }

    /*------------------------------------------------------------*/
    printf("\nBacklight\n");

    tmp = 0x00;

    res = EApiGetLVDSBacklightBrightness(&tmp);
    if(res != EAPI_STATUS_SUCCESS)
        printf("Can't get backlight brightness !! \n");
    else
        printf("\t%-24s%d %%\n","Brightness:", (int)tmp);
}

/*-----------------------------------------------------------------------------------------------------------*/
static void fan_ctrl(FAN_INFO fan)
{
    EApiStatus_t res = EAPI_STATUS_SUCCESS;

    printf("Fan Control start... \n\n");

    unsigned int fan_type;
    switch (fan.index)
    {
        case CPUFAN:
            fan_type = CPUFAN;
            break;
        case SYSFAN1:
            fan_type = EAPI_ID_SYS_FAN_1;
            break;
        case SYSFAN2:
            fan_type = EAPI_ID_SYS_FAN_2;
            break;
        case SYSFAN3:
            fan_type = EAPI_ID_SYS_FAN_3;
            break;
        case SYSFAN4:
            fan_type = EAPI_ID_SYS_FAN_4;
            break;
        case SYSFAN5:
            fan_type = EAPI_ID_SYS_FAN_5;
            break;
        default:
            res = EAPI_STATUS_UNSUPPORTED;
            goto EXIT;
    }

    /*------------------------------------------------------------*/
    if(fan.index == CPUFAN)
    {
        res = EApiCPUFanModeSet(fan.mode); 

        if(res == EAPI_STATUS_SUCCESS)
            printf("Set CPU Fan Mode to %s\n", (fan.mode == 0) 
                                        ? "Normal Mode" : "SMART FAN Mode" );
        else
            goto EXIT;

        
        res = EApiCPUFanSpeedSet(fan.speed);
        if(res == EAPI_STATUS_SUCCESS)
        {   
            printf("Set fan speed to %d.\n", fan.speed);
        }
        else if(res == EAPI_STATUS_INVALID_PARAMETER)
        {
            printf("Warning: Fan Speed must be set 0~255\n");
            goto EXIT;
        }
        else
            goto EXIT;
        
    }
    else     
    {
        res = EApiSYSFanModeSet(fan_type, fan.mode); 
        if(res == EAPI_STATUS_SUCCESS)
            printf("Set Fan Mode to %s\n", (fan.mode == 0) 
                                        ? "Normal Mode" : "SMART FAN Mode" );
        else
            goto EXIT;

        
        res = EApiSYSFanSpeedSet(fan_type, fan.speed);
        if(res == EAPI_STATUS_SUCCESS)
        {   
            printf("Set fan speed to %d.\n", fan.speed);
        }
        else if(res == EAPI_STATUS_INVALID_PARAMETER)
        {
            printf("Warning: Fan Speed must be set 0~255\n");
            goto EXIT;
        }
        else
            goto EXIT;
    }

    

EXIT:
    printf(" \n");
    (res == EAPI_STATUS_SUCCESS) ? printf("Fan Control Success. \n")
                                 : printf("Fan Control fail. \n");
}

/*-----------------------------------------------------------------------------------------------------------*/
static void gpio_set(GPIO_INFO gpio)
{
    EApiStatus_t res = EAPI_STATUS_SUCCESS;
    EApiStatus_t res_read = EAPI_STATUS_SUCCESS;

    unsigned int tmp;
    unsigned int dir[GPIO_NUM];
    unsigned int level[GPIO_NUM];

    /*------------------------------------------------------------*/
    /* Get all GPIO pin status */
    for(tmp=0; tmp < GPIO_NUM; tmp++)
    {
        res_read = EApiGPIOGetDirection(tmp, &dir[tmp]);
        if(res_read != EAPI_STATUS_SUCCESS)
        {
            printf("GPIO read direction fail... \n");
            res = EAPI_STATUS_ERROR;
            goto EXIT;
        } 

        res_read = EApiGPIOGetLevel(tmp, &level[tmp]);
        if(res_read != EAPI_STATUS_SUCCESS)
        {
            printf("GPIO read level fail... \n");
            res = EAPI_STATUS_ERROR;
            goto EXIT;
        }            
    }

    printf("GPIO setting start... \n\n");

    /*------------------------------------------------------------*/
    /* Set gpio direction */
    if(gpio.direction >= 0)
    {
        printf("Set direction... \n");
        
        res = EApiGPIOSetDirection(gpio.pin, gpio.direction);
        if(res == EAPI_STATUS_SUCCESS)
            printf("GPIO pin %d direct is set to %s.\n", gpio.pin, 
                        (gpio.direction == 0) ? "output" : "input");
        else
        {
            printf("Set GPIO direction fail. \n");
            goto EXIT;
        }
    }

    /*------------------------------------------------------------*/
    /* Set gpio level value */
    if(gpio.value >= 0)
    {    
        printf("Set level...\n");

        res = EApiGPIOSetLevel(gpio.pin, gpio.value);
        if(res == EAPI_STATUS_SUCCESS)
            printf("GPO pin %d level is set to %s. \n", gpio.pin, 
                        (gpio.value == 0) ? "low" : "high");
        else
        {
            printf("Set GPO level fail. \n");
            goto EXIT;
        }
    }

    /*------------------------------------------------------------*/
    /* show different */
    printf("\nGPIO Status\n");
    printf("\t+------+--------+-------+         +------+--------+-------+\n");
    printf("\t| GPIO |   Dir  | Level |         | GPIO |   Dir  | Level |\n");
    printf("\t+------+--------+-------+         +------+--------+-------+\n"); 
    for(tmp=0; tmp < GPIO_NUM; tmp++)
    {
        printf("\t|%3s%d%2s|%7s |%3s%d%3s|", "", tmp,"", 
                    (dir[tmp]==1) ? "input" : "output", "", level[tmp], "");
        
        res_read = EApiGPIOGetDirection(tmp, &dir[tmp]);
        if(res_read != EAPI_STATUS_SUCCESS)
        {
            printf("GPIO read direction fail... \n");
            goto EXIT;
        } 

        res_read = EApiGPIOGetLevel(tmp, &level[tmp]);
        if(res_read != EAPI_STATUS_SUCCESS)
        {
            printf("GPIO read level fail... \n");
            goto EXIT;
        } 

        if(res_read != EAPI_STATUS_SUCCESS)
            printf("GPIO read fail... \n");
        
        if(tmp == ((GPIO_NUM)/2))
            printf("  ====>  ");
        else
            printf("         ");

        if(tmp == gpio.pin)
            printf("|%3s%d%2s|%7s |%3s%d%3s|\n", "-> ", tmp,"", 
                    (dir[tmp]==1) ? "input" : "output", "", level[tmp], "");
        else
            printf("|%3s%d%2s|%7s |%3s%d%3s|\n", "", tmp,"", 
                    (dir[tmp]==1) ? "input" : "output", "", level[tmp], "");
    }
    printf("\t+------+--------+-------+         +------+--------+-------+\n");

    /*------------------------------------------------------------*/
EXIT:
    printf(" \n");
    (res == EAPI_STATUS_SUCCESS && res == EAPI_STATUS_SUCCESS)
                                 ? printf("GPIO setting success. \n")
                                 : printf("GPIO setting fail. \n");
}

/*-----------------------------------------------------------------------------------------------------------*/

static void usb_power_set(USB_POWER_INFO usb_power)
{
    EApiStatus_t res = EAPI_STATUS_SUCCESS;

    if(usb_power.ctrl >= 0)
    {    
        printf("Set level...\n");

        res = EApiUSB_Power_Ctrl(usb_power.pin, usb_power.ctrl);
        if(res == EAPI_STATUS_SUCCESS)
        {
            printf("USB power pin %d is set to %s. \n", usb_power.pin, 
                        (usb_power.ctrl == 0) ? "Off" : "On");
        }
        else
        {
            printf("Set GPO level fail. \n");
            // goto EXIT;
        }
    }
}

/*-----------------------------------------------------------------------------------------------------------*/

static void backlight_test(char *name, BACKLIGHT_INFO backlight_test)
{
    EApiStatus_t res = EAPI_STATUS_SUCCESS;
    unsigned int pBright;
    printf("Backlight testing start... \n\n");

    res = EApiSetLVDSBacklightBrightness(backlight_test.brt);
    if(res == EAPI_STATUS_SUCCESS) 
        printf("Set backlight to %d \n", backlight_test.brt);
    else
    {
        printf("Set backlight brightness fail.\n");
        goto EXIT;
    }
    
    res = EApiGetLVDSBacklightBrightness(&pBright);
    if(res == EAPI_STATUS_SUCCESS)
        printf("\nBacklight : %d \n", (int)pBright);
    else
    {
        printf("Get backlight brightness fail.\n");
        goto EXIT;
    }

EXIT:
    if(res == EAPI_STATUS_SUCCESS)
        printf("Backlight testing finished. \n");
    else
        printf("Backlight testing fail! \n");
    
}

/*-----------------------------------------------------------------------------------------------------------*/

static void wdt_test(char *name, WDT_INFO wdt)
{
    EApiStatus_t res = EAPI_STATUS_SUCCESS;
    int loop  = 0;
    int count = 0;
    unsigned int timeout_unit = 0;
    unsigned int timeout_setting = 0;
    printf("WDT testing start... \n\n");

    /*------------------------------------------------------------*/
    /* stop watchdog if set timeout = 0 */
    if(wdt.timeout == 0) 
    {
        res = EApiWDogStop();
        (res == EAPI_STATUS_SUCCESS) ? printf("Disable Watchdog! \n" )
                                     : printf("Stop watchdog fail! \n");
        goto EXIT;
    }

    /*------------------------------------------------------------*/
    /* do loops 5 times if set timeout > 0 */
    if(wdt.timeout > 0) 
    {
        /* set timeout and start watchddog */
        res = EApiWDogStart(wdt.unit, wdt.timeout);
        if(res == EAPI_STATUS_SUCCESS)
        {
            /* get timeout */ 
            res = EApiWDogGetCap(&timeout_unit, &timeout_setting);
            printf("timeout_unit:%u, timeout_setting:%u", timeout_unit, timeout_setting);
            if(res != EAPI_STATUS_SUCCESS)
            {
                printf("Watchdog read error. \n" );
                goto EXIT;
            }
            else
            {
                /* timeout unit convert to second */ 
                if(timeout_unit == 1) 
                    timeout_setting = timeout_setting * 60;    
                printf("Timeout: %d seconds\n", timeout_setting);                            
            }

            if(wdt.heartbeat <= 0)
            {
                printf("No timeout reset interval. \n\nUse the following command to stop watchdog.\n");
                printf("%s -w 0\n\n", name);
                goto EXIT;
            }
            else           
                printf("Timeout reset interval: %d seconds \n\n", wdt.heartbeat); 
    

            /* loops 5 times */    
            printf("loop 5 times: \n"); 
            for(loop = 0; loop < 5; loop++)
            {
                count = wdt.heartbeat;
                printf("loop %d: \n", loop+1);
                while(count > 0)
                {
                    printf("%d seconds remaining reset timeout. \n", count);
                    count--;
                    sleep(1);
                }
                printf("reset timeout ! \n\n");
            }

            /* stop watchdog */ 
            printf("loop end ! \n");
            res = EApiWDogStop();
            if(res == EAPI_STATUS_SUCCESS)
                printf("\nDisable Watchdog! \n" );
            else
                printf("\nStop watchdog fail! \n");
            goto EXIT;
            
        }
        else 
        {
            printf("Watchdog start error. \n" );
            goto EXIT;
        }
    }

EXIT:
    if(res == EAPI_STATUS_SUCCESS)
        printf("WDT testing finished. \n");
    else
        printf("WDT testing fail! \n");
}


/*-----------------------------------------------------------------------------------------------------------*/

// SMBUS 命令處理函數
int handle_smbus_command(int argc, char *argv[]) 
{
    SMBUS_INFO smbus = { -1, -1, -1, -1, NULL };
    
    // 檢查參數數量
    if (argc < 5) {
        printf("Error: SMBUS command requires more parameters\n");
        help(argv[0], SHOW_SMBUS);
        return -1;
    }

    // 解析操作類型
    const char *op_str = argv[2];
    if (strcmp(op_str, "-r") == 0) {
        smbus.op = 0; // 讀操作
        smbus.addr = strtol(argv[3], NULL, 16);
        smbus.offset = strtol(argv[4], NULL, 16);
        
        if (argc > 5) {
            smbus.length = atoi(argv[5]);
            // 調用 smbus_ctrl 執行讀取操作
            if (smbus_ctrl(&smbus, argc, argv, 2)) {
                return 0; // 成功返回
            } else {
                return -1; // 失敗返回
            }
        } else {
            printf("Error: SMBUS read operation requires length parameter\n");
            help(argv[0], SHOW_SMBUS);
            return -1;
        }
    } else if (strcmp(op_str, "-w") == 0) {
        smbus.op = 1; // 寫操作
        smbus.addr = strtol(argv[3], NULL, 16);
        smbus.offset = strtol(argv[4], NULL, 16);
        
        if (argc > 5) {
            smbus.data = argv[5];
            // 調用 smbus_ctrl 執行寫入操作
            if (smbus_ctrl(&smbus, argc, argv, 2)) {
                return 0; // 成功返回
            } else {
                return -1; // 失敗返回
            }
        } else {
            printf("Error: SMBUS write operation requires data parameter\n");
            help(argv[0], SHOW_SMBUS);
            return -1;
        }
    } else {
        printf("Error: Invalid SMBUS operation, must be '-r' or '-w'\n");
        help(argv[0], SHOW_SMBUS);
        return -1;
    }
}

// SMBUS control function - Return value: 0=failure, 1=success
int smbus_ctrl(SMBUS_INFO *smbus, int argc, char *argv[], int optind) {
    EApiStatus_t status;
    
    if (smbus->op == 0) { // Read operation
        unsigned char readBuffer[256] = {0};
        
        // Execute read operation using EAPI
        status = EApiI2CReadTransfer(
            0,              // bus_id = 0
            smbus->addr,    // device address
            smbus->offset,  // command/offset
            readBuffer,     // receive buffer
            smbus->length,  // buffer length
            smbus->length   // bytes to read
        );
        
        if (status == EAPI_STATUS_SUCCESS) {
            printf("SMBUS read successful:\n");
            for (int i = 0; i < smbus->length; i++) {
                printf("%02X ", readBuffer[i]);
            }
            if (smbus->length % 16 != 0) printf("\n");
            return 1;
        } else {
            printf("SMBUS read failed, status code: 0x%08X\n", status);
            return 0;
        }
    } else { // Write operation
        unsigned char writeBuffer[256] = {0};
        int bytecnt = 0;
        
        // Parse write data (space-separated hexadecimal bytes)
        char *data_copy = strdup(smbus->data);
        char *token = strtok(data_copy, " ,");
        
        while (token != NULL && bytecnt < 256) {
            writeBuffer[bytecnt++] = (unsigned char)strtol(token, NULL, 16);
            token = strtok(NULL, " ,");
        }
        
        free(data_copy);
        
        // Ensure there is data to write
        if (bytecnt == 0) {
            printf("No data to write\n");
            return 0;
        }
        
        // Execute write operation using EAPI
        status = EApiI2CWriteTransfer(
            0,              // bus_id = 0
            smbus->addr,    // device address
            smbus->offset,  // command/offset
            writeBuffer,    // write buffer
            bytecnt         // bytes to write
        );
        
        if (status == EAPI_STATUS_SUCCESS) {
            printf("SMBUS write successful\n");
            return 1;
        } else {
            printf("SMBUS write failed, status code: 0x%08X\n", status);
            return 0;
        }
    }
    
    return 0; // Operation failed
}

/*-----------------------------------------------------------------------------------------------------------*/

int main(int argc, char **argv)
{
    EApiStatus_t        res         = EAPI_STATUS_SUCCESS;
    FAN_INFO            fan         = { -1, -1, -1 };
    GPIO_INFO           gpio        = { -1, -1, -1 };
    WDT_INFO            wdt         = { -1, -1, -1 };
    BACKLIGHT_INFO      backlight   = { -1};
    SMBUS_INFO          smbus       = { -1, -1, -1, -1, NULL };
    USB_POWER_INFO      usb_power   = { -1, -1};

    int use_smbus = 0;
    int opt;

    printf("*********************************************************** \n");
    printf("* Innodisk EApi                                           * \n");
    printf("*********************************************************** \n");

    if(getuid())
    {
        printf("Permission denied !!\nYou are not logged as root. \n\n");
        goto EXIT;
    }

    if (argc > 1 && strcasecmp(argv[1], "SMBUS") == 0) {
        if((res = EApiLibInitialize()) != EAPI_STATUS_SUCCESS)
        {
            printf("EApiLibInitialize error ... error code: %X \n", res);
            goto EXIT;
        }
        return handle_smbus_command(argc, argv);
    }

    while((opt = getopt_long(argc, argv, ":?hg:d:v:w:t:f:m:s:b:up:c:", long_opt, NULL)) != -1)
    {
        switch(opt)
        {   
            case 'g': gpio.pin          = atoi(optarg); break;
            case 'd': gpio.direction    = atoi(optarg); break;
            case 'v': gpio.value        = atoi(optarg); break;
            case 'w': wdt.timeout       = atoi(optarg); break;
            case 't': wdt.heartbeat     = atoi(optarg); break;
            case 'u': wdt.unit          = atoi(optarg); break;
            case 'f': fan.index         = atoi(optarg); break;
            case 'm': fan.mode          = atoi(optarg); break;
            case 's': fan.speed         = atoi(optarg); break;
            case 'b': backlight.brt     = atoi(optarg); break;
            case 'p': usb_power.pin     = atoi(optarg); break;  // USB Power Status pin (0-2)
            case 'c': usb_power.ctrl    = atoi(optarg); break;  // USB Power Control (0=OFF, 1=ON)       
            case 'h':
            case '?':
            default:
                      help(argv[0], SHOW_ALL);
                      goto EXIT;
        }
                                          
    }

    if(argc != 1 && argv[1][0] != '-' )
    {
        help(argv[0], SHOW_ALL);
        goto EXIT;
    }

    /*----------------------------------------------------------------------*/
    if((res = EApiLibInitialize()) != EAPI_STATUS_SUCCESS)
    {
        printf("EApiLibInitialize error ... error code: %X \n", res);
        goto EXIT;
    }

    if(argc == 1)
        boardinfo();

    if(fan.mode >= 0)
            fan_ctrl(fan);
    else if(fan.speed != -1)
    {
        printf("fan mode:%d\n",fan.mode);
        printf("fan speed:%d\n",fan.speed);
        help(argv[0], SHOW_FAN);
    }

    /* gpio */
    if(gpio.pin >= 0)
        gpio_set(gpio);
    else if (gpio.direction != -1 || gpio.value != -1)
        help(argv[0], SHOW_GPIO);

    /* wdt */
    if(wdt.timeout >= 0)
        wdt_test(argv[0], wdt);
    else if(wdt.unit != -1 || wdt.heartbeat != -1)
        help(argv[0], SHOW_WDT);

    /* backlight */
    if(backlight.brt >= 0)
        backlight_test(argv[0], backlight);
    else if(backlight.brt != -1)
        help(argv[0], SHOW_BACKLIGHT);

    /* USB Power Ctrl */
    if(EApiUSB_Power_Support() == EAPI_STATUS_SUCCESS)
    {
        if((usb_power.pin) >= 0)  // 只有當使用者輸入 -p 參數時才會執行
        {
            usb_power_set(usb_power);
        }
    }
    

    /* smbus */
    // if (use_smbus) {
    //     if (!smbus_ctrl(&smbus, argc, argv, optind)) {
    //         help(argv[0], SHOW_SMBUS); 
    //     }
    // }
    if (use_smbus) {
        // 檢查是否有足夠的非選項參數
        if (optind + 3 < argc) {
            const char *op_str = argv[optind];
            if (strcmp(op_str, "r") == 0 || strcmp(op_str, "read") == 0) {
                smbus.op = 0; // 讀操作
                smbus.addr = strtol(argv[optind+1], NULL, 16);
                smbus.offset = strtol(argv[optind+2], NULL, 16);
                
                if (optind + 4 <= argc) {
                    smbus.length = atoi(argv[optind+3]);
                    smbus_ctrl(&smbus, argc, argv, optind);
                } else {
                    printf("Error: SMBUS read operation requires length parameter\n");
                    help(argv[0], SHOW_SMBUS);
                }
            } else if (strcmp(op_str, "w") == 0 || strcmp(op_str, "write") == 0) {
                smbus.op = 1; // 寫操作
                smbus.addr = strtol(argv[optind+1], NULL, 16);
                smbus.offset = strtol(argv[optind+2], NULL, 16);
                
                if (optind + 4 <= argc) {
                    smbus.data = argv[optind+3];
                    smbus_ctrl(&smbus, argc, argv, optind);
                } else {
                    printf("Error: SMBUS write operation requires data parameter\n");
                    help(argv[0], SHOW_SMBUS);
                }
            } else {
                printf("Error: Invalid SMBUS operation, must be 'r' or 'w'\n");
                help(argv[0], SHOW_SMBUS);
            }
        } else {
            printf("Error: SMBUS command requires more parameters\n");
            help(argv[0], SHOW_SMBUS);
        }
    }

    if((res = EApiLibUnInitialize()) != EAPI_STATUS_SUCCESS)
        printf("EApiLibUnInitialize error ... error code: %X\n", res);

EXIT:

    return res;
}
