import os
import re
import shutil
import shlex
import subprocess

GCC = "gcc"
LD = "ld"
QEMU = "qemu-system-i386"
ISO_DIR = "iso"

generated_functions = ""
generated_main = ""
inside_function = False

variables = {}

block_stack = []

KERNEL_TEMPLATE_START = r"""

#include <stdint.h>

__attribute__((section(".multiboot"), used))
const uint32_t multiboot_header[] = {
    0x1BADB002,
    0x00000000,
    0xE4524FFE
};

typedef unsigned short u16;
typedef uint32_t size_t;
u16* video = (u16*)0xB8000;
int cursor = 0;

void* memset(void* s, int c, uint32_t n) {
    unsigned char* p = s;
    while (n--) *p++ = (unsigned char)c;
    return s;
}

void* memcpy(void* dest, const void* src, uint32_t n) {
    unsigned char* d = dest;
    const unsigned char* s = src;
    while (n--) *d++ = *s++;
    return dest;
}

size_t strlen(const char* s) {
    size_t len = 0;
    while (s[len]) len++;
    return len;
}

void clear_screen() {
    for (int i = 0; i < 80 * 25; i++) {
        video[i] = (0x0F << 8) | ' ';
    }
    cursor = 0;
}

void kprint(const char* str) {
    int i = 0;
    while (str[i]) {
        if (str[i] == '\n') {
            cursor = (cursor / 80 + 1) * 80; // próxima linha
        } else {
            video[cursor++] = (0x0F << 8) | str[i];
        }
        i++;
    }

    if (cursor == 80 * 25) {
    cursor = 0;
    clear_screen();

    }
}

void kprint_char(char c) {
    char buf[2] = {c, 0};
    kprint(buf);
}

void kprint_int(int value) {
    char buf[12];
    int i = 0;
    int negative = 0;

    if (value == 0) {
        kprint("0");
        return;
    }

    if (value < 0) {
        negative = 1;
        value = -value;
    }

    while (value > 0 && i < (int)sizeof(buf) - 1) {
        buf[i++] = '0' + (value % 10);
        value /= 10;
    }

    if (negative) {
        buf[i++] = '-';
    }

    buf[i] = 0;

    for (int j = 0; j < i / 2; j++) {
        char t = buf[j];
        buf[j] = buf[i - 1 - j];
        buf[i - 1 - j] = t;
    }

    kprint(buf);
}

int strcmp(const char *s1, const char *s2) {
    while (*s1 && (*s1 == *s2)) {
        s1++;
        s2++;
    }
    return (unsigned char)*s1 - (unsigned char)*s2;
}

static inline void outb(uint16_t port, uint8_t val) {
    __asm__ volatile ("outb %0, %1" : : "a"(val), "Nd"(port));
}

static inline uint8_t inb(uint16_t port) {
    uint8_t ret;
    __asm__ volatile ("inb %1, %0" : "=a"(ret) : "Nd"(port));
    return ret;
}

static inline uint8_t kb_read() {
    while (!(inb(0x64) & 1)) {}
    return inb(0x60);
}

char scancode_to_ascii(uint8_t sc) {
    switch (sc) {
        case 0x02: return '1';
        case 0x03: return '2';
        case 0x04: return '3';
        case 0x05: return '4';
        case 0x06: return '5';
        case 0x07: return '6';
        case 0x08: return '7';
        case 0x09: return '8';
        case 0x0A: return '9';
        case 0x0B: return '0';
        case 0x10: return 'q';
        case 0x11: return 'w';
        case 0x12: return 'e';
        case 0x13: return 'r';
        case 0x14: return 't';
        case 0x15: return 'y';
        case 0x16: return 'u';
        case 0x17: return 'i';
        case 0x18: return 'o';
        case 0x19: return 'p';
        case 0x1E: return 'a';
        case 0x1F: return 's';
        case 0x20: return 'd';
        case 0x21: return 'f';
        case 0x22: return 'g';
        case 0x23: return 'h';
        case 0x24: return 'j';
        case 0x25: return 'k';
        case 0x26: return 'l';
        case 0x2C: return 'z';
        case 0x2D: return 'x';
        case 0x2E: return 'c';
        case 0x2F: return 'v';
        case 0x30: return 'b';
        case 0x31: return 'n';
        case 0x32: return 'm';
        case 0x0E: return '\b';
        case 0x39: return ' ';
        default: return 0;
    }
}

#define ATA_PRIMARY_IO 0x1F0
#define ATA_PRIMARY_CTRL 0x3F6

int ata_wait_bsy() {
    uint32_t timeout = 1000000;
    while ((inb(ATA_PRIMARY_IO + 7) & 0x80) && --timeout);
    if (timeout == 0) return -1;
    return 0;
}

int ata_wait_drq() {
    uint32_t timeout = 1000000;
    while (!(inb(ATA_PRIMARY_IO + 7) & 0x08) && --timeout);
    if (timeout == 0) return -1;
    return 0;
}

void write_sector(uint32_t lba, uint16_t* buffer) {
    // 1. Select Drive and send bits 24-27 of LBA
    outb(ATA_PRIMARY_IO + 6, 0xE0 | ((lba >> 24) & 0x0F));
    
    // 2. Send Null byte (for compatibility) and Sector Count (1)
    outb(ATA_PRIMARY_IO + 1, 0x00);
    outb(ATA_PRIMARY_IO + 2, 1);
    
    // 3. Send LBA bits 0-7, 8-15, 16-23
    outb(ATA_PRIMARY_IO + 3, (uint8_t)lba);
    outb(ATA_PRIMARY_IO + 4, (uint8_t)(lba >> 8));
    outb(ATA_PRIMARY_IO + 5, (uint8_t)(lba >> 16));
    
    // 4. Send Command 0x30 (Write Sectors)
    outb(ATA_PRIMARY_IO + 7, 0x30);

    // 5. Wait for the drive to be ready to receive data
    if (ata_wait_bsy() < 0 || ata_wait_drq() < 0) {
        kprint("Error: ATA Write Timeout\n");
        return;
    }

    // 6. Transfer the data
    for (int i = 0; i < 256; i++) {
        __asm__ volatile ("outw %w0, %w1" : : "a"(buffer[i]), "d"((uint16_t)ATA_PRIMARY_IO));
    }
}

void read_sector(uint32_t lba, uint16_t* buffer) {
    outb(ATA_PRIMARY_IO + 6, 0xE0 | ((lba >> 24) & 0x0F));
    outb(ATA_PRIMARY_IO + 1, 0x00);
    outb(ATA_PRIMARY_IO + 2, 1);
    outb(ATA_PRIMARY_IO + 3, (uint8_t)lba);
    outb(ATA_PRIMARY_IO + 4, (uint8_t)(lba >> 8));
    outb(ATA_PRIMARY_IO + 5, (uint8_t)(lba >> 16));
    outb(ATA_PRIMARY_IO + 7, 0x20);

    if (ata_wait_bsy() < 0 || ata_wait_drq() < 0) {
        kprint("Error: ATA Read Timeout\n");
        return;
    }

    for (int i = 0; i < 256; i++) {
        uint16_t data;
        __asm__ volatile ("inw %w1, %w0" : "=a"(data) : "d"((uint16_t)ATA_PRIMARY_IO));
        buffer[i] = data;
    }
}

char scancode_to_ascii_fixed(uint8_t sc) {
    if (sc == 0x1C) return '\n';
    char c = scancode_to_ascii(sc);
    return c;
}

char getch() {
    while (1) {
        uint8_t sc = kb_read();
        if (sc & 0x80) continue;
        char c = scancode_to_ascii_fixed(sc);
        if (c) return c;
    }
}

void read_line(char* buf, int max) {
    int i = 0;
    while (i < max - 1) {
        char c = getch();
        if (c == '\n') {
            buf[i] = 0;
            kprint("\n");
            return;
        }
        buf[i++] = c;
        char tmp[2] = {c,0};
        kprint(tmp);
    }
    buf[i] = 0;
}

int read_int() {
    char buf[32];
    read_line(buf,sizeof(buf));
    int v = 0;
    int i=0;
    while(buf[i]){
        v = v*10 + (buf[i]-'0');
        i++;
    }
    return v;
}

/* ==== FUNÇÕES GERADAS ==== */
"""

KERNEL_TEMPLATE_MIDDLE = r"""

void _start() {

/* ==== CÓDIGO GERADO ==== */
"""

KERNEL_TEMPLATE_END = r"""

    while (1) { __asm__("hlt"); }
}
"""

def emit(line):
    global generated_main, generated_functions, inside_function
    if inside_function:
        generated_functions += line + "\n"
    else:
        generated_main += line + "\n"

def translate_condition(tokens):
    # Keep C-style comparisons for numeric values, but use strcmp for string comparisons.
    if len(tokens) == 3 and tokens[1] in ("==", "!="):
        left, op, right = tokens
        left_is_str = left in variables and variables[left] == "string"
        right_is_str = right in variables and variables[right] == "string"
        left_is_lit = len(left) >= 2 and ((left[0] == '"' and left[-1] == '"') or (left[0] == "'" and left[-1] == "'"))
        right_is_lit = len(right) >= 2 and ((right[0] == '"' and right[-1] == '"') or (right[0] == "'" and right[-1] == "'"))

        if (left_is_str and (right_is_lit or right_is_str)) or (right_is_str and (left_is_lit or left_is_str)):
            # Always compare strings using strcmp (C string compare)
            if left_is_str:
                var = left
                other = right
            else:
                var = right
                other = left
            cmp = f"strcmp({var}, {other})"
            return f"{cmp} == 0" if op == "==" else f"{cmp} != 0"

    return " ".join(tokens)


def cmd_if(args):
    global block_stack
    condition = translate_condition(args)
    emit(f"    if ({condition}) {{")
    block_stack.append("if")


def cmd_else(args):
    emit("    } else {")


def cmd_while(args):
    global block_stack
    condition = translate_condition(args)
    emit(f"    while ({condition}) {{")
    block_stack.append("while")

def cmd_end(args):
    global block_stack
    if not block_stack:
        return
    block_stack.pop()
    emit("    }")

def cmd_var(args):
    global generated_functions, variables
    t = args[0]
    n = args[1]
    variables[n] = t
    if t == "int":
        generated_functions += f"int {n};\n"
    if t == "string":
        generated_functions += f"char {n}[256];\n"

def cmd_input(args):
    n = args[0]
    t = variables[n]
    if t == "int":
        emit(f"    {n} = read_int();")
    else:
        emit(f"    read_line({n}, sizeof({n}));")

def cmd_set(args):
    emit(f"    {args[0]} = {' '.join(args[1:])};")

def cmd_print(args):
    for a in args:
        if a in variables:
            if variables[a] == "int":
                emit(f"    kprint_int({a});")
            else:
                emit(f"    kprint({a});")
        else:
            txt=a.strip('"')
            emit(f'    kprint("{txt}");')



COMMANDS = {
    "print":cmd_print,
    "var":cmd_var,
    "input":cmd_input,
    "set":cmd_set,
    "if":cmd_if,
    "else":cmd_else,
    "while":cmd_while,
    "end":cmd_end
}

def split_tokens(line):
    # Split by whitespace, but keep quoted strings as single tokens.
    return re.findall(r'"[^"]*"|\'[^\']*\'|\S+', line)


def interpretar():
    for file in os.listdir("."):
        if file.endswith(".kci"):
            with open(file) as f:
                for line in f:
                    line=line.strip()
                    if not line: continue
                    parts=split_tokens(line)
                    cmd=parts[0]
                    if cmd in COMMANDS:
                        COMMANDS[cmd](parts[1:])

def build():
    print("Gerando kernel.c...")
    with open("kernel.c","w") as f:
        f.write(KERNEL_TEMPLATE_START)
        f.write(generated_functions)
        f.write(KERNEL_TEMPLATE_MIDDLE)
        f.write(generated_main)
        f.write(KERNEL_TEMPLATE_END)

    subprocess.run([
    GCC,
    "-m32",
    "-ffreestanding",
    "-nostdlib",
    "-fno-pic",
    "-fno-stack-protector",
    "-c",
    "kernel.c",
    "-o",
    "kernel.o"
], check=True)

    with open("linker.ld","w") as f:
        f.write("""ENTRY(_start)
SECTIONS{
. = 1M;
.text : { *(.multiboot*) *(.text*) }
.rodata : { *(.rodata*) }
.data : { *(.data*) }
.bss : { *(COMMON) *(.bss*) }
}""")

    subprocess.run([LD,"-m","elf_i386","-T","linker.ld","kernel.o","-o","kernel.elf"],check=True)

    if os.path.exists(ISO_DIR):
        shutil.rmtree(ISO_DIR)

    os.makedirs("iso/boot/grub",exist_ok=True)
    shutil.copy("kernel.elf","iso/boot/kernel.elf")

    with open("iso/boot/grub/grub.cfg","w") as f:
        f.write("""
set timeout=0
set default=0

menuentry "MeuKernel" {
multiboot /boot/kernel.elf
boot
}
""")

    subprocess.run(["grub-mkrescue","-o","kernel.iso","iso"],check=True)

    if input("Rodar? s/n: ")=="s":
        # Create a 10MB disk image if it doesn't exist
        if not os.path.exists("disk.img"):
            subprocess.run(["qemu-img", "create", "-f", "raw", "disk.img", "10M"])
        subprocess.run([QEMU, "-cdrom", "kernel.iso", "-hda", "disk.img", "-boot", "d"])

if __name__=="__main__":
    interpretar()
    build()
