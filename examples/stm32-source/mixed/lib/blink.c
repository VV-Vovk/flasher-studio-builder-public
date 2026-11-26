#include "blink.h"
#include "stm32f0xx_ll_gpio.h"
void blink_init(void) {
    HAL_Init();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    GPIO_InitTypeDef gpio = {0};
    gpio.Pin = GPIO_PIN_4;
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOA, &gpio);
}
void blink_step(void) { LL_GPIO_TogglePin(GPIOA, LL_GPIO_PIN_4); HAL_Delay(10); }
