import os
import re
import shutil
import shlex
import subprocess

# ==============================
# CONFIG
# ==============================
GCC = "gcc"
LD = "ld"
QEMU = "qemu-system-i386"
ISO_DIR = "iso"

generated_functions = ""
generated_main = ""
inside_function = False

# track declared variables and their types
variables = {}

# ==============================
# TEMPLATE DO KERNEL
# ==============================
KERNEL_TEMPLATE_START = r"""
#include <stdint.h>
#include <string.h>

__attribute__((section(".multiboot"), used))
const uint32_t multiboot_header[] = {
    0x1BADB002,
    0x00000000,
    0xE4524FFE
};

typedef unsigned short u16;
u16* video = (u16*)0xB8000;
int cursor = 0;

void kprint(const char* str) {
    int i = 0;
    while (str[i]) {
        video[cursor++] = (0x0F << 8) | str[i++];
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

    // reverse
    for (int j = 0; j < i / 2; j++) {
        char t = buf[j];
        buf[j] = buf[i - 1 - j];
        buf[i - 1 - j] = t;
    }

    kprint(buf);
}

static inline uint8_t inb(uint16_t port) {
    uint8_t ret;
    __asm__ volatile ("inb %1, %0" : "=a"(ret) : "Nd"(port));
    return ret;
}

static inline uint8_t kb_read() {
    // wait until keyboard output buffer is full
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
        case 0x0C: return '-';
        case 0x0D: return '=';
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
        case 0x39: return ' ';
        case 0x1C: return '\n';
        case 0x0E: return '\b';
        case 0x0F: return '\t';
        default: return 0;
    }
}

char getch() {
    while (1) {
        uint8_t sc = kb_read();

        // ignore key release and extended scancodes
        if (sc & 0x80 || sc == 0xE0 || sc == 0xE1) {
            continue;
        }

        char c = scancode_to_ascii(sc);
        if (c) {
            return c;
        }
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

        if (c == '\b') {
            if (i > 0) {
                i--;
                kprint("\b \b");
            }
            continue;
        }

        buf[i++] = c;
        char tmp[2] = {c, 0};
        kprint(tmp);
    }
    buf[i] = 0;
}

int read_int() {
    char buf[32];
    read_line(buf, sizeof(buf));
    int i = 0;
    int sign = 1;
    int value = 0;

    if (buf[0] == '-') {
        sign = -1;
        i = 1;
    }

    while (buf[i]) {
        if (buf[i] >= '0' && buf[i] <= '9') {
            value = value * 10 + (buf[i] - '0');
        } else {
            break;
        }
        i++;
    }

    return value * sign;
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

# ==============================
# COMANDOS .kci
# ==============================

def cmd_var(args):
    global generated_functions, generated_main, variables

    if len(args) < 2:
        print("Uso: var <tipo> <nome> [= <valor>]")
        return

    var_type = args[0]
    var_name = args[1]

    init_value = None
    if len(args) > 2:
        # allow: var int x = 5  or var string s = "hi"
        if args[2] == "=" and len(args) > 3:
            init_value = " ".join(args[3:])
        else:
            init_value = " ".join(args[2:])

    variables[var_name] = var_type

    if var_type == "int":
        if init_value:
            generated_functions += f"int {var_name} = {init_value};\n"
        else:
            generated_functions += f"int {var_name};\n"
    elif var_type == "char":
        if init_value:
            v = init_value.strip()
            if v.startswith('"') and v.endswith('"'):
                v = "'" + v[1:-1] + "'"
            generated_functions += f"char {var_name} = {v};\n"
        else:
            generated_functions += f"char {var_name};\n"
    elif var_type == "string":
        generated_functions += f"char {var_name}[256];\n"
        if init_value:
            val = init_value
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            generated_main += f'    strcpy({var_name}, "{val}");\n'
    else:
        print(f"Tipo desconhecido: {var_type}. Suportado: int, char, string")


def cmd_set(args):
    global generated_main, variables

    if len(args) < 2:
        print("Uso: set <variavel> <valor>")
        return

    name = args[0]
    if name not in variables:
        print(f"Variável não declarada: {name}")
        return

    t = variables[name]
    val = " ".join(args[1:])

    if t == "int":
        generated_main += f"    {name} = {val};\n"
    elif t == "char":
        v = val.strip()
        if v.startswith('"') and v.endswith('"'):
            v = "'" + v[1:-1] + "'"
        generated_main += f"    {name} = {v};\n"
    elif t == "string":
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        generated_main += f'    strcpy({name}, "{val}");\n'


def cmd_input(args):
    global generated_main, variables

    if len(args) != 1:
        print("Uso: input <variavel>")
        return

    name = args[0]
    if name not in variables:
        print(f"Variável não declarada: {name}")
        return

    t = variables[name]
    if t == "int":
        generated_main += f"    {name} = read_int();\n"
    elif t == "char":
        generated_main += f"    {name} = getch();\n"
    elif t == "string":
        generated_main += f"    read_line({name}, sizeof({name}));\n"


def cmd_imports(args, name):
    global generated_functions
    generated_functions += f"#include \"./libs/{name}.c\"\n"
def cmd_print(args):
    global generated_functions, generated_main, inside_function, variables

    if not args:
        return

    # If only a single variable is printed, use the correct primitive printer
    if len(args) == 1 and args[0] in variables:
        var = args[0]
        t = variables[var]

        if t == "int":
            line = f"    kprint_int({var});\n"
        elif t == "char":
            line = f"    kprint_char({var});\n"
        else:
            line = f"    kprint({var});\n"

        line += "    kprint(\"\\n\");\n"
        if inside_function:
            generated_functions += line
        else:
            generated_main += line
        return

    # Mixed literals and variables: concatenate by emitting multiple prints
    out_lines = []
    pending_literal = ""

    def flush_literal():
        nonlocal pending_literal
        if not pending_literal:
            return

        # substitute {var} placeholders
        parts = re.split(r'(\{[^}]+\})', pending_literal)
        for part in parts:
            if not part:
                continue
            if part.startswith("{") and part.endswith("}"):
                name = part[1:-1]
                if name in variables:
                    t = variables[name]
                    if t == "int":
                        out_lines.append(f"    kprint_int({name});")
                    elif t == "char":
                        out_lines.append(f"    kprint_char({name});")
                    else:
                        out_lines.append(f"    kprint({name});")
                    continue
            escaped = part.replace('"', '\\"')
            out_lines.append(f'    kprint("{escaped}");')

        pending_literal = ""

    for tok in args:
        if tok in variables:
            flush_literal()
            t = variables[tok]
            if t == "int":
                out_lines.append(f"    kprint_int({tok});")
            elif t == "char":
                out_lines.append(f"    kprint_char({tok});")
            else:
                out_lines.append(f"    kprint({tok});")
        else:
            # allow quoted strings to be written normally
            if (tok.startswith('"') and tok.endswith('"')) or (tok.startswith("'") and tok.endswith("'")):
                tok = tok[1:-1]

            if pending_literal:
                pending_literal += " "
            pending_literal += tok

    flush_literal()
    out_lines.append('    kprint("\\n");')

    line = "\n".join(out_lines) + "\n"
    if inside_function:
        generated_functions += line
    else:
        generated_main += line


def cmd_func(args):
    global generated_functions, inside_function
    name = args[0]
    generated_functions += f"\nvoid {name}() {{\n"
    inside_function = True


def cmd_raw(args):
    global generated_functions, generated_main, inside_function
    line = " ".join(args)

    if inside_function:
        generated_functions += f"    {line}\n"
    else:
        generated_main += f"    {line}\n"


def cmd_end(args):
    global generated_functions, inside_function
    generated_functions += "}\n"
    inside_function = False

def cmd_delay(args):
    global generated_code
    seconds = int(args[0])
    loops = seconds * 100_000_000
    generated_code += f"""
    for (volatile int i = 0; i < {loops}; i++) {{
        __asm__("nop");
    }}
"""



COMMANDS = {
    "print": cmd_print,
    "var": cmd_var,
    "set": cmd_set,
    "input": cmd_input,
    "func": cmd_func,
    "raw": cmd_raw,
    "end": cmd_end,
    "delay": cmd_delay,
    "inject": cmd_imports,
}

# ==============================
# INTERPRETADOR
# ==============================
def interpretar():
    for file in os.listdir("."):
        if file.endswith(".kci"):
            with open(file) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    parts = shlex.split(line)
                    if not parts:
                        continue

                    cmd = parts[0]

                    if cmd in COMMANDS:
                        COMMANDS[cmd](parts[1:])
                    else:
                        print(f"Comando desconhecido: {cmd}")

# ==============================
# BUILD
# ==============================
def build():
    # 1. Gerar kernel.c
    print("Gerando kernel.c...")
    with open("kernel.c", "w") as f:
        f.write(KERNEL_TEMPLATE_START)
        f.write(generated_functions)
        f.write(KERNEL_TEMPLATE_MIDDLE)
        f.write(generated_main)
        f.write(KERNEL_TEMPLATE_END)

    # 2. Compilar
    print("Compilando kernel.o...")
    subprocess.run([
        GCC, "-m32", "-ffreestanding",
        "-nostdlib", "-fno-pic",
        "-O0",
        "-c", "kernel.c", "-o", "kernel.o"
    ], check=True)

    # 3. Linker
    print("Criando linker.ld...")
    with open("linker.ld", "w") as f:
        f.write("""ENTRY(_start)

SECTIONS
{
    . = 1M;

    .text : { *(.multiboot*) *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    .bss : { *(COMMON) *(.bss*) }
}
""")

    print("Linkando kernel.elf...")
    subprocess.run([
        LD, "-m", "elf_i386",
"-T", "linker.ld",
"-nostdlib",
"kernel.o",
"-o", "kernel.elf"
    ], check=True)

    # 4. Estrutura ISO
    if os.path.exists(ISO_DIR):
        shutil.rmtree(ISO_DIR)

    os.makedirs(os.path.join(ISO_DIR, "boot", "grub"), exist_ok=True)
    shutil.copy("kernel.elf", os.path.join(ISO_DIR, "boot", "kernel.elf"))

    # 5. grub.cfg
    print("Criando grub.cfg...")
    with open(os.path.join(ISO_DIR, "boot", "grub", "grub.cfg"), "w") as f:
        f.write("""
set timeout=0
set default=0

menuentry "MeuKernel" {
    multiboot /boot/kernel.elf
    boot
}
""")

    # 6. ISO
    print("Gerando ISO...")
    subprocess.run([
        "grub-mkrescue",
        "-o", "kernel.iso",
        ISO_DIR,
        
    ], check=True)

    print("Build finalizado!")

    if input("Rodar no QEMU? (s/n): ").lower() == "s":
        subprocess.run([QEMU, "-cdrom", "kernel.iso"])

# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    interpretar()
    build()
