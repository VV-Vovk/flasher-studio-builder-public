.syntax unified
.cpu cortex-m0
.thumb
.section .isr_vector,"a",%progbits
.word _estack
.word Reset_Handler
.section .text.Reset_Handler,"ax",%progbits
.global Reset_Handler
.type Reset_Handler,%function
.thumb_func
Reset_Handler:
  bl main
1: b 1b
