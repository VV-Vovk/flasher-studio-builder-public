BUILD_DIR ?= build
CC = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
.PHONY: all
all: $(BUILD_DIR)/studio_smoke.hex $(BUILD_DIR)/studio_smoke.bin
$(BUILD_DIR)/studio_smoke.elf: Core/Src/main.c flash.ld
	mkdir -p $(BUILD_DIR)
	$(CC) -mcpu=cortex-m3 -mthumb -Os -ffreestanding -nostdlib -Wl,--gc-sections -Tflash.ld $< -o $@
$(BUILD_DIR)/studio_smoke.hex: $(BUILD_DIR)/studio_smoke.elf
	$(OBJCOPY) -O ihex $< $@
$(BUILD_DIR)/studio_smoke.bin: $(BUILD_DIR)/studio_smoke.elf
	$(OBJCOPY) -O binary $< $@
