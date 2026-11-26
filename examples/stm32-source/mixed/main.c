#include "blink.h"
int main(void) { blink_init(); for (;;) blink_step(); }
void SysTick_Handler(void) { HAL_IncTick(); }
