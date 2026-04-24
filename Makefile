OUTPUT=kernelcompiledmannual.iso
TARGET=kernel.c
CFGRUB=grub.cfg
LINKLD=linker.ld
HD=disk.img
WKDIR=iso

.PHONY: build emul all

build:
	gcc -m32 -ffreestanding -fno-stack-protector -fno-pic -nostdlib -c $(TARGET) -o kernel.o
	ld -m elf_i386 -T $(LINKLD) kernel.o -o kernel.elf
	cp $(CFGRUB) $(WKDIR)/boot/grub
	cp kernel.elf $(WKDIR)/boot
	grub-mkrescue -o $(OUTPUT) $(WKDIR)

emul:
	qemu-system-i386 -cdrom $(OUTPUT) -hda $(HD)

all: build emul