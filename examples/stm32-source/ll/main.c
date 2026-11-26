#include "stm32f0xx_ll_gpio.h"
#include "stm32f0xx_ll_bus.h"
int main(void) {
    LL_GPIO_InitTypeDef gpio;
    LL_GPIO_StructInit(&gpio);
#if defined(STM32F103xB)
    LL_APB2_GRP1_EnableClock(LL_APB2_GRP1_PERIPH_GPIOA);
#else
    LL_AHB1_GRP1_EnableClock(LL_AHB1_GRP1_PERIPH_GPIOA);
#endif
    gpio.Pin = LL_GPIO_PIN_4;
    gpio.Mode = LL_GPIO_MODE_OUTPUT;
    LL_GPIO_Init(GPIOA, &gpio);
    for (;;) { LL_GPIO_TogglePin(GPIOA, LL_GPIO_PIN_4); }
}
