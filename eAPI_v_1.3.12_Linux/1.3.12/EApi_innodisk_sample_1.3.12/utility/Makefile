Q               := @
CC				:= $(CROSS_COMPILE)gcc	
SRCS            := $(wildcard *.c)
OBJS            := $(SRCS:.c=.o)
TARGET          := EApi_Test
LIBS			:= EApi.a
CFLAGS          += -Wall -I ./include -std=gnu99
LDFLAGS         := $(LIBS) -static -Wl,--no-export-dynamic
LIB_PACKAGE		:= 
XINSTALL		:=

.PHONY: all clean distclean	xinstall

all: .depend $(TARGET)

%.o: %.c Makefile
	$(Q)echo "  Compiling '$<' ..."
	$(Q)$(CC) $(CFLAGS) -o $@ -c $<

$(TARGET): $(OBJS)
	$(Q)echo "  Building '$@' ..."
	$(Q)$(CC) -o $@ $(OBJS) $(LDFLAGS)
	$(Q)cp $(TARGET) ../

xinstall:
	$(Q)echo "  Install $(TARGET) -> $(XINSTALL)"
	$(Q)cp -rf $(TARGET) $(XINSTALL)

clean distclean: 
	$(Q)echo "  Cleaning '$(TARGET)' ..."
	$(Q)rm -f .depend *~ $(OBJS) $(TARGET) a.out*
	$(Q)rm -f $(TARGET) ../$(TARGET)

.depend dep depend:
	$(Q)echo "  Generating '$@' ..."
	$(Q)$(CC) $(CFLAGS) -M *.c > $@

ifeq (.depend, $(wildcard .depend))
    include .depend
endif
