/*
 * Host test for software/video.c: the real driver against a model of the card.
 *
 *   clang -std=c99 -Wall -Wextra -DVIDEO_HOST_TEST -I../software test_driver.c \
 *         ../software/video.c ../software/font8x8.c -o test_driver && ./test_driver
 *
 * The model implements exactly what the hardware does -- byte n of a page at $A00001 + 2n with
 * n = page << 16 | y << 7 | x >> 3, a write-only control register and a status byte -- so a
 * driver that only works because of a matching mistake in both still fails here.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "video.h"

static uint8_t vram[VIDEO_PAGES][1 << 16];
static uint8_t reg;
static unsigned reads;              /* the status bits move on their own, as the raster does */
static int stuck_page;              /* fault injection: the page address line (SRAM A16) tied low */
static unsigned bus_errors;

static uint8_t *cell(uint32_t addr)
{
    uint32_t n;

    if ((addr & 1) == 0) {
        bus_errors++;
        return NULL;
    }
    n = (addr - VIDEO_VRAM_BASE) / 2;
    if (stuck_page)
        n &= ~(uint32_t)(1 << 16);
    return &vram[(n >> 16) & 1][n & 0xFFFF];
}

void video_hw_write(uint32_t addr, uint8_t v)
{
    if ((addr & 0xF00000UL) == 0xB00000UL) {
        reg = v;
        return;
    }
    if ((addr & 0xF00000UL) == 0xA00000UL) {
        uint8_t *p = cell(addr);

        if (p)
            *p = v;
        return;
    }
    abort();                        /* the driver must never touch anything else */
}

uint8_t video_hw_read(uint32_t addr)
{
    if ((addr & 0xF00000UL) == 0xB00000UL)
        return (uint8_t)(0xFC | ((reads++ / 400) & 1));    /* b0 VBLANK, b2-b7 float high */
    if ((addr & 0xF00000UL) == 0xA00000UL) {
        uint8_t *p = cell(addr);

        return p ? *p : 0xFF;
    }
    abort();
}

static int fails;

static void check(int cond, const char *what)
{
    printf("%s %s\n", cond ? "PASS" : "FAIL", what);
    if (!cond)
        fails++;
}

static unsigned count_lit(unsigned page)
{
    unsigned n = 0, y, i;

    for (y = 0; y < VIDEO_HEIGHT; y++)
        for (i = 0; i < VIDEO_WIDTH / 8; i++) {
            uint8_t v = vram[page][y << 7 | i];

            while (v) {
                n += v & 1;
                v >>= 1;
            }
        }
    return n;
}

int main(void)
{
    check(VIDEO_ADDR(0, 0, 0) == 0xA00001UL, "pixel (0,0) page 0 is at $A00001");
    check(VIDEO_ADDR(0, 8, 0) == 0xA00003UL, "the next byte across is two CPU addresses on");
    check(VIDEO_ADDR(0, 7, 0) == 0xA00001UL, "eight pixels share one byte");
    check(VIDEO_ADDR(0, 0, 1) == 0xA00101UL, "a row is 128 bytes = $100 of CPU address");
    check(VIDEO_ADDR(1, 0, 0) == 0xA20001UL, "page 1 starts $20000 further on");
    check(VIDEO_ADDR(0, 639, 479) == 0xA1DF9FUL, "the last visible pixel is inside $A00000-$AFFFFF");

    video_init();
    check(reg == 0, "video_init leaves the register at 0: video off, page 0");

    video_clear(0);
    video_pixel(0, 0, 1);
    check(vram[0][0] == 0x80, "pixel (0,0) is bit 7 -- the 74AC166 shifts that one out first");
    video_pixel(7, 0, 1);
    check(vram[0][0] == 0x81, "pixel (7,0) is bit 0");
    video_pixel(8, 0, 1);
    check(vram[0][1] == 0x80, "pixel (8,0) starts the next byte");
    check(video_get(0, 0) == 1 && video_get(1, 0) == 0 && video_get(8, 0) == 1, "video_get reads bits back");
    video_pixel(0, 0, 0);
    check(vram[0][0] == 0x01, "clearing a pixel leaves its neighbours alone");

    video_clear(1);
    check(count_lit(0) == VIDEO_WIDTH * VIDEO_HEIGHT, "video_clear(1) lights all 307200 pixels");
    check(vram[0][80] == 0 && vram[0][127] == 0, "video_clear leaves the 48 off-screen bytes of each row alone");
    video_clear(0);
    check(count_lit(0) == 0, "video_clear(0) blanks them again");

    video_hline(3, 10, 20, 1);
    check(vram[0][10 << 7] == 0x1F && vram[0][(10 << 7) + 1] == 0xFF && vram[0][(10 << 7) + 2] == 0xFE,
          "video_hline builds the partial end bytes correctly");
    check(count_lit(0) == 20, "and lights exactly 20 pixels");
    video_clear(0);
    video_hline(4, 5, 3, 1);
    check(vram[0][5 << 7] == 0x0E && count_lit(0) == 3, "a run inside a single byte");

    video_clear(0);
    video_pixel(640, 0, 1);
    video_pixel(0, 480, 1);
    video_hline(600, 20, 200, 1);
    video_vline(3, 470, 50, 1);
    check(count_lit(0) == 40 + 10, "drawing off the right and bottom edges is clipped, not wrapped");

    video_clear(0);
    video_rect(0, 0, VIDEO_WIDTH, VIDEO_HEIGHT, 1);
    check(count_lit(0) == 2 * VIDEO_WIDTH + 2 * VIDEO_HEIGHT - 4, "a border rectangle is hollow");

    video_clear(0);
    video_line(0, 0, 639, 479, 1);
    check(video_get(0, 0) && video_get(639, 479) && count_lit(0) == 640, "video_line spans both ends");

    video_clear(0);
    video_char(0, 0, 'A', false);
    check(vram[0][0] == video_font8x8['A' - 32][0] && vram[0][7 << 7] == video_font8x8['A' - 32][7],
          "video_char puts the eight glyph rows on eight consecutive scanlines");
    video_char(1, 0, 'A', true);
    check(vram[0][1] == (uint8_t)~video_font8x8['A' - 32][0], "inverse video flips the glyph");
    video_clear(0);
    video_text(0, 0, "Hi\nthere");
    check(vram[0][0] == video_font8x8['H' - 32][0] && vram[0][8 << 7] == video_font8x8['t' - 32][0],
          "video_text wraps on a newline");

    /* Pages are independent, and drawing follows video_draw_page rather than what is shown. */
    video_clear(0);
    video_draw_page(1);
    video_clear(0);
    video_pixel(100, 100, 1);
    check(vram[1][100 << 7 | 12] == 0x08 && vram[0][100 << 7 | 12] == 0, "drawing lands on the hidden page only");
    video_show(0, true);
    check(reg == VIDEO_CTRL_ON, "video_show(0, true) writes b0 only");
    video_flip();
    check(reg == (VIDEO_CTRL_ON | VIDEO_CTRL_PAGE) && video_drawn_page() == 0,
          "video_flip shows the drawn page and hands the other one back");
    video_flip();
    check(reg == VIDEO_CTRL_ON && video_drawn_page() == 1, "and flips back");

    check(bus_errors == 0, "the driver never touches an even address");
    check(video_selftest() == 0, "video_selftest passes on a good card");
    stuck_page = 1;
    check(video_selftest() != 0, "and catches the page address line stuck low");
    stuck_page = 0;

    printf("\n%d failed\n", fails);
    return fails ? 1 : 0;
}
