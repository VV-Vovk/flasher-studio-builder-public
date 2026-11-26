#include "example.h"
#ifndef STM32F030x6
#error MCU define missing
#endif
volatile unsigned counter;
int main(void) { for (;;) counter = IMPORTED_VALUE; }
