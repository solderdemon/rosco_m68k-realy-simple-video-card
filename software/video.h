/*
 * SolderDemon m68k Really Simple Video r3 driver: 640 x 480, 1 bit per pixel, 2 pages.
 *
 * Byte access only (/LDS), odd addresses:
 *   $A00001 + 2n   VRAM byte n = page << 16 | y << 7 | x >> 3   (128 bytes per row, 80 of them
 *                  visible; bit 7 of a byte is its leftmost pixel)
 *   $B00001        write: b0 video on, b1 page shown      system reset: 0 = black screen, page 0
 *                  read:  b0 VBLANK, b1 HBLANK (1 = in blanking); b2-b7 are not driven, mask them
 * The register repeats over $B00001-$BFFFFF; even addresses in $A00000-$BFFFFF end in a bus error.
 * The control register cannot be read back, so the driver keeps a copy.
 *
 * Any CPU access while the picture is on steals one byte fetch and shows up as eight wrong pixels
 * on the current scanline. Draw on the hidden page and video_flip(), or draw inside
 * video_wait_vblank().
 */
#ifndef ROSCO_VIDEO_H
#define ROSCO_VIDEO_H

#include <stdbool.h>
#include <stdint.h>

#define VIDEO_VRAM_BASE   0xA00001UL
#define VIDEO_REG         0xB00001UL

#define VIDEO_WIDTH       640
#define VIDEO_HEIGHT      480
#define VIDEO_STRIDE      128          /* VRAM bytes per row; 80 of them are on screen */
#define VIDEO_PAGES       2
#define VIDEO_COLS        (VIDEO_WIDTH / 8)     /* 80 characters */
#define VIDEO_ROWS        (VIDEO_HEIGHT / 8)    /* 60 lines */

#define VIDEO_CTRL_ON     0x01
#define VIDEO_CTRL_PAGE   0x02
#define VIDEO_STAT_VBLANK 0x01
#define VIDEO_STAT_HBLANK 0x02

/* CPU address of the byte holding pixel (x, y) on a page; the card sees only odd addresses. */
#define VIDEO_ADDR(page, x, y) (VIDEO_VRAM_BASE + ((uint32_t)(page) << 17) \
                                + ((uint32_t)(y) << 8) + (((uint32_t)(x) >> 3) << 1))

/* Video off, page 0 shown and drawn on. Does not clear VRAM -- call video_clear. */
void video_init(void);

/* Control register. `on` false blanks the screen without disturbing VRAM. */
void video_show(unsigned page, bool on);
unsigned video_shown_page(void);

/* Which page the drawing calls below write to; independent of the page on screen. */
void video_draw_page(unsigned page);
unsigned video_drawn_page(void);

/* Raw status byte, already masked to VIDEO_STAT_*. */
uint8_t video_status(void);

/* Return at the start of the next vertical blanking interval. */
void video_wait_vblank(void);

/* Show the page being drawn at the next VBLANK and start drawing on the one that was shown. */
void video_flip(void);

/* c: 0 = black, anything else = lit. Coordinates outside the screen are ignored. */
void video_pixel(unsigned x, unsigned y, unsigned c);
unsigned video_get(unsigned x, unsigned y);
void video_clear(unsigned c);
void video_hline(unsigned x, unsigned y, unsigned w, unsigned c);
void video_vline(unsigned x, unsigned y, unsigned h, unsigned c);
void video_fill(unsigned x, unsigned y, unsigned w, unsigned h, unsigned c);
void video_rect(unsigned x, unsigned y, unsigned w, unsigned h, unsigned c);
void video_line(int x0, int y0, int x1, int y1, unsigned c);

/* 8 x 8 text on an 80 x 60 grid. `inv` swaps ink and paper. */
extern const uint8_t video_font8x8[95][8];
void video_char(unsigned col, unsigned row, char ch, bool inv);
void video_text(unsigned col, unsigned row, const char *s);

/* Walk every VRAM cell of both pages; 0 = pass, otherwise the failing byte number + 1.
 * Destroys the framebuffer. */
uint32_t video_selftest(void);

#endif
