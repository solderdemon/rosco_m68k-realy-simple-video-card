#include "video.h"

#ifdef VIDEO_HOST_TEST
void video_hw_write(uint32_t addr, uint8_t v);
uint8_t video_hw_read(uint32_t addr);
#else
static inline void video_hw_write(uint32_t addr, uint8_t v) { *(volatile uint8_t *)(uintptr_t)addr = v; }
static inline uint8_t video_hw_read(uint32_t addr) { return *(volatile uint8_t *)(uintptr_t)addr; }
#endif

static uint8_t ctrl;           /* write-only register: shadow copy */
static unsigned draw;

static void ctrl_write(uint8_t v)
{
    ctrl = v;
    video_hw_write(VIDEO_REG, v);
}

void video_show(unsigned page, bool on)
{
    ctrl_write((uint8_t)(((page & 1) ? VIDEO_CTRL_PAGE : 0) | (on ? VIDEO_CTRL_ON : 0)));
}

unsigned video_shown_page(void) { return (ctrl & VIDEO_CTRL_PAGE) ? 1 : 0; }
void video_draw_page(unsigned page) { draw = page & 1; }
unsigned video_drawn_page(void) { return draw; }

void video_init(void)
{
    video_show(0, false);
    video_draw_page(0);
}

uint8_t video_status(void)
{
    return (uint8_t)(video_hw_read(VIDEO_REG) & (VIDEO_STAT_VBLANK | VIDEO_STAT_HBLANK));
}

void video_wait_vblank(void)
{
    while (video_status() & VIDEO_STAT_VBLANK)
        ;
    while (!(video_status() & VIDEO_STAT_VBLANK))
        ;
}

void video_flip(void)
{
    unsigned shown = video_shown_page();

    video_wait_vblank();
    video_show(draw, (ctrl & VIDEO_CTRL_ON) != 0);
    draw = shown;
}

/* ---- byte level ------------------------------------------------------------------------- */

/* Replace the bits of the byte at (x, y) on the drawn page that `mask` selects. */
static void poke(unsigned x, unsigned y, uint8_t mask, unsigned c)
{
    uint32_t a = VIDEO_ADDR(draw, x, y);
    uint8_t v = video_hw_read(a);

    video_hw_write(a, (uint8_t)(c ? (v | mask) : (v & (uint8_t)~mask)));
}

void video_pixel(unsigned x, unsigned y, unsigned c)
{
    if (x < VIDEO_WIDTH && y < VIDEO_HEIGHT)
        poke(x, y, (uint8_t)(0x80u >> (x & 7)), c);
}

unsigned video_get(unsigned x, unsigned y)
{
    if (x >= VIDEO_WIDTH || y >= VIDEO_HEIGHT)
        return 0;
    return (video_hw_read(VIDEO_ADDR(draw, x, y)) >> (7 - (x & 7))) & 1;
}

void video_hline(unsigned x, unsigned y, unsigned w, unsigned c)
{
    unsigned end;

    if (y >= VIDEO_HEIGHT || x >= VIDEO_WIDTH || w == 0)
        return;
    end = x + w > VIDEO_WIDTH ? VIDEO_WIDTH : x + w;        /* last pixel + 1 */

    while (x < end) {
        unsigned bit = x & 7;
        unsigned run = 8 - bit;
        uint8_t mask;

        if (x + run > end)
            run = end - x;
        mask = (uint8_t)(((0xFFu >> bit) & (0xFFu << (8 - bit - run))) & 0xFFu);
        poke(x, y, mask, c);
        x += run;
    }
}

void video_vline(unsigned x, unsigned y, unsigned h, unsigned c)
{
    unsigned end = y + h > VIDEO_HEIGHT ? VIDEO_HEIGHT : y + h;
    uint8_t mask;

    if (x >= VIDEO_WIDTH || y >= VIDEO_HEIGHT || h == 0)
        return;
    mask = (uint8_t)(0x80u >> (x & 7));
    for (; y < end; y++)
        poke(x, y, mask, c);
}

void video_fill(unsigned x, unsigned y, unsigned w, unsigned h, unsigned c)
{
    unsigned end = y + h > VIDEO_HEIGHT ? VIDEO_HEIGHT : y + h;

    for (; y < end; y++)
        video_hline(x, y, w, c);
}

void video_rect(unsigned x, unsigned y, unsigned w, unsigned h, unsigned c)
{
    if (w == 0 || h == 0)
        return;
    video_hline(x, y, w, c);
    video_hline(x, y + h - 1, w, c);
    video_vline(x, y, h, c);
    video_vline(x + w - 1, y, h, c);
}

void video_clear(unsigned c)
{
    uint8_t v = c ? 0xFF : 0x00;
    unsigned y;

    for (y = 0; y < VIDEO_HEIGHT; y++) {
        uint32_t a = VIDEO_ADDR(draw, 0, y);
        unsigned i;

        for (i = 0; i < VIDEO_WIDTH / 8; i++, a += 2)
            video_hw_write(a, v);
    }
}

void video_line(int x0, int y0, int x1, int y1, unsigned c)
{
    int dx = x1 > x0 ? x1 - x0 : x0 - x1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0;          /* negative magnitude, Bresenham style */
    int sx = x0 < x1 ? 1 : -1;
    int sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;

    for (;;) {
        int e2;

        video_pixel((unsigned)x0, (unsigned)y0, c);
        if (x0 == x1 && y0 == y1)
            return;
        e2 = 2 * err;
        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}

/* ---- text ------------------------------------------------------------------------------- */

void video_char(unsigned col, unsigned row, char ch, bool inv)
{
    const uint8_t *glyph;
    uint32_t a;
    unsigned i;

    if (col >= VIDEO_COLS || row >= VIDEO_ROWS)
        return;
    if ((unsigned char)ch < 32 || (unsigned char)ch > 126)
        ch = ' ';
    glyph = video_font8x8[(unsigned char)ch - 32];
    a = VIDEO_ADDR(draw, col * 8, row * 8);
    for (i = 0; i < 8; i++, a += VIDEO_STRIDE * 2)
        video_hw_write(a, (uint8_t)(inv ? ~glyph[i] : glyph[i]));
}

void video_text(unsigned col, unsigned row, const char *s)
{
    for (; *s; s++) {
        if (*s == '\n') {
            col = 0;
            row++;
            continue;
        }
        video_char(col, row, *s, false);
        if (++col >= VIDEO_COLS) {
            col = 0;
            row++;
        }
    }
}

/* ---- self test -------------------------------------------------------------------------- */

uint32_t video_selftest(void)
{
    unsigned page, y, i;

    /* Write both pages completely before reading either back: a stuck or swapped address line --
     * including the page bit, which lives in the other CPLD -- then shows up as one page
     * overwriting the other instead of passing cell by cell. */
    for (page = 0; page < VIDEO_PAGES; page++)
        for (y = 0; y < VIDEO_HEIGHT; y++) {
            uint32_t a = VIDEO_ADDR(page, 0, y);

            for (i = 0; i < VIDEO_WIDTH / 8; i++, a += 2)
                video_hw_write(a, (uint8_t)(i ^ (y << 1) ^ (y >> 7) ^ (page << 6)));
        }
    for (page = 0; page < VIDEO_PAGES; page++)
        for (y = 0; y < VIDEO_HEIGHT; y++) {
            uint32_t a = VIDEO_ADDR(page, 0, y);

            for (i = 0; i < VIDEO_WIDTH / 8; i++, a += 2)
                if (video_hw_read(a) != (uint8_t)(i ^ (y << 1) ^ (y >> 7) ^ (page << 6)))
                    return ((uint32_t)page << 16 | y << 7 | i) + 1;
        }
    return 0;
}
