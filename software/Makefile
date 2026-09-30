SOLDERDEMON_M68K_DIR=../../solderdemon_m68k
# The SolderDemon m68k SDK (software.mk) is rosco_m68k compatible and keeps the upstream variable name.
ifndef ROSCO_M68K_DIR
ROSCO_M68K_DIR=$(SOLDERDEMON_M68K_DIR)
endif
include $(ROSCO_M68K_DIR)/code/software/software.mk

font8x8.c: ../tools/make_font.py
	python ../tools/make_font.py

HOSTCC ?= clang
host-test: ../tests/test_driver.c video.c video.h font8x8.c
	$(HOSTCC) -std=c99 -Wall -Wextra -DVIDEO_HOST_TEST -I. ../tests/test_driver.c video.c font8x8.c -o ../tests/test_driver
	../tests/test_driver
