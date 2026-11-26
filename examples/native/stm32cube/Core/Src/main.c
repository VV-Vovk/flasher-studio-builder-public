#include <stdint.h>
void Reset_Handler(void) { for (;;) { __asm volatile("nop"); } }
__attribute__((section(".isr_vector"),used)) const uintptr_t vectors[] = {0x20005000, (uintptr_t)Reset_Handler};
