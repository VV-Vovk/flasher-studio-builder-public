#include "stm32f0xx.h"
volatile unsigned int heartbeat;
int main(void) { for (;;) { heartbeat++; __NOP(); } }
