/*
 * SolderDemon m68k Really Simple Video demo: self test, a text page, then a bouncing box drawn on the
 * hidden page and flipped at VBLANK, so nothing tears and no CPU access ever shows as snow.
 *
 * Build with the rosco_m68k toolchain (see docs/BUILD.md) and load the .bin over the serial
 * bootloader. Progress goes to the serial console as well as to the screen.
 */
#include <stdio.h>
#include <stdbool.h>
#include "video.h"

static void draw_frame(int bx, int by, int w, int h)
{
    video_clear(0);
    video_rect(0, 0, VIDEO_WIDTH, VIDEO_HEIGHT, 1);
    video_rect(2, 2, VIDEO_WIDTH - 4, VIDEO_HEIGHT - 4, 1);
    video_text(2, 1, "SolderDemon m68k Really Simple Video r3  --  640 x 480 mono, 2 pages");
    video_fill((unsigned)bx, (unsigned)by, (unsigned)w, (unsigned)h, 1);
    video_rect((unsigned)bx - 2, (unsigned)by - 2, (unsigned)w + 4, (unsigned)h + 4, 1);
}

int main(void)
{
    uint32_t bad;
    int bx = 100, by = 100, dx = 3, dy = 2;
    unsigned frame;

    printf("Really Simple Video: testing 2 x 60K of VRAM...\n");
    video_init();
    bad = video_selftest();
    if (bad) {
        printf("VRAM FAILED at byte %lu (page %lu, y %lu, byte %lu)\n",
               (unsigned long)(bad - 1), (unsigned long)((bad - 1) >> 16),
               (unsigned long)(((bad - 1) >> 7) & 0x1FF), (unsigned long)((bad - 1) & 0x7F));
        return 1;
    }
    printf("VRAM ok. 640x480 should now be on the VGA output.\n");

    /* A still text page first, so a monitor that needs a moment to lock has something to lock to. */
    video_draw_page(0);
    video_clear(0);
    video_rect(0, 0, VIDEO_WIDTH, VIDEO_HEIGHT, 1);
    video_text(2, 2, "SolderDemon m68k Really Simple Video r3");
    video_text(2, 4, "640 x 480 @ 60 Hz, 1 bit per pixel, 80 x 60 characters");
    video_text(2, 5, "VRAM  $A00001 + 2n,  n = page << 16 | y << 7 | x >> 3");
    video_text(2, 6, "control / status at $B00001, two ATF1502AS-10JU44");
    for (frame = 0; frame < 16; frame++) {
        char line[65];
        unsigned i;

        for (i = 0; i < 64; i++)
            line[i] = (char)(32 + ((frame * 64 + i) % 95));
        line[64] = 0;
        video_text(2, 9 + frame, line);
    }
    video_line(0, 0, VIDEO_WIDTH - 1, VIDEO_HEIGHT - 1, 1);
    video_line(VIDEO_WIDTH - 1, 0, 0, VIDEO_HEIGHT - 1, 1);
    video_show(0, true);

    for (frame = 0; frame < 120; frame++)
        video_wait_vblank();

    /* Then the moving box, double buffered. */
    video_draw_page(1);
    for (;;) {
        draw_frame(bx, by, 96, 64);
        video_flip();
        bx += dx;
        by += dy;
        if (bx < 4 || bx + 96 > VIDEO_WIDTH - 4)
            dx = -dx;
        if (by < 4 || by + 64 > VIDEO_HEIGHT - 4)
            dy = -dy;
    }
}
