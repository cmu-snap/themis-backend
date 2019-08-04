obj-m += tcp_bbr_1cap.o
obj-m += tcp_bbr_3cap.o
obj-m += tcp_bbr_4cap.o
obj-m += tcp_bbr_5cap.o
obj-m += tcp_bbr_6cap.o

all:
		make -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
		make -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean
