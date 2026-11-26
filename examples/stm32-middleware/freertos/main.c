#include "FreeRTOS.h"
#include "task.h"
static volatile unsigned counter;
static void task(void *arg) { (void)arg; for (;;) { counter++; vTaskDelay(10); } }
int main(void) { if (xTaskCreate(task,"test",128,0,1,0)==pdPASS) vTaskStartScheduler(); for (;;) {} }
