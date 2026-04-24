
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
        case 0x1A: return '[';
        case 0x1B: return ']';
        case 0x27: return ';';
        case 0x28: return '\'';
        case 0x33: return ',';
        case 0x34: return '.';
        case 0x35: return '/';
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
        if (c == '\n' || c == '\r') {
            buf[i] = 0;
            kprint("\n");
            return;
        }
        if (c == '\b') {
            if (i > 0) {
                i--;
                cursor--;
                video[cursor] = (0x0F << 8) | ' ';
            }
            continue;
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
char sh[256];


void _start() {

    while (1) {
        /* ==== CÓDIGO GERADO ==== */
        kprint("ENZOS>");
        read_line(sh, sizeof(sh));
        if (strcmp(sh, "info") == 0) {
            kprint("Directly, Security, Fastly, ENZOS 1.0\nPROC:QEMU X86\n");
        }

        else if (strcmp(sh, "write") == 0) {
            kprint("LBA Sector: ");
            int lba = read_int();
            kprint("Content (max 512 chars): ");
            char content[512];
            read_line(content, 512);

            if (lba < 0) {
                kprint("Error: Invalid LBA sector.\n");
            } else if (strlen(content) == 0) {
                kprint("Error: Content cannot be empty.\n");
            } else {
                uint16_t buffer[256];
                memset(buffer, 0, 512);
                memcpy(buffer, content, strlen(content));
                write_sector(lba, buffer);
                kprint("Sector written successfully.\n");
            }
            
        }
        else if (strcmp(sh, "read") == 0) {
            kprint("LBA Sector: ");
            int lba = read_int();
            uint16_t buffer[256];
            read_sector(lba, buffer);
            
            // Ensure the data is treated as a string safely
            char display_buf[513];
            memcpy(display_buf, buffer, 512);
            display_buf[512] = 0; // Null terminate

            kprint("Data: ");
            kprint(display_buf);
            kprint("\n");

        } else if (strcmp(sh, "clear") == 0) {
            clear_screen();
        } else if (strcmp(sh, "exit") == 0) {
            break;
         } else {
            kprint("UNKNOWN COMMAND!\n");
         }
    }
    while (1) { __asm__("hlt"); }
}