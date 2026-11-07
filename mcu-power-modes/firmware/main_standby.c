/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : STANDBY mode current measurement test
  *
  * Cycle: 5s active (LED on, PA8 LOW) -> 5s Standby (LED off, PA8 HIGH) -> reset -> repeat
  *
  * Measurement setup:
  *  - PPK2 in Source Meter mode at 3.3V across JP4 (IDD jumper removed)
  *  - PPK2 digital input D0 connected to PA8 (Arduino D7 pin on CN9)
  *
  * In Standby the CPU fully resets on wake, so each cycle is a fresh main() run.
  * PA8 is configured BEFORE anything else and driven LOW immediately on boot,
  * so the PPK2 sees the falling edge as the wake marker.
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private defines -----------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define LED_PORT        GPIOA
#define LED_PIN         GPIO_PIN_5    // LD2, on during the active phase
#define TRIG_PORT       GPIOA
#define TRIG_PIN        GPIO_PIN_8    // PPK2 digital input D0: LOW = awake, HIGH = asleep
#define ACTIVE_MS       5000U         // duration of the active phase
#define WAKEUP_COUNTS   10240U        // RTC wake-up: LSE 32768 Hz / 16 = 2048 Hz -> 10240 = 5 s
/* USER CODE END PD */

/* Private variables ---------------------------------------------------------*/
RTC_HandleTypeDef hrtc;
UART_HandleTypeDef huart1;

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_RTC_Init(void);
/* USER CODE BEGIN PFP */
void Enter_Standby_5s(void);
/* USER CODE END PFP */


int main(void)
{
  /* USER CODE BEGIN 1 */
  HAL_PWR_EnableBkUpAccess();
  /* USER CODE END 1 */

  HAL_Init();
  SystemClock_Config();

  MX_GPIO_Init();
  // Drive trigger LOW immediately - this is our "wake instant" marker
  HAL_GPIO_WritePin(TRIG_PORT, TRIG_PIN, GPIO_PIN_RESET);

  MX_USART1_UART_Init();
  MX_RTC_Init();

  /* USER CODE BEGIN 2 */

  // Distinguish cold boot vs wake-from-standby (just for debugging visibility)
  if (__HAL_PWR_GET_FLAG(PWR_FLAG_SBF) != RESET)
  {
      __HAL_PWR_CLEAR_FLAG(PWR_FLAG_SBF);
      // Wake from standby - go straight to active phase, no boot blink
  }
  else
  {
      // Cold boot - 3 quick blinks
      for (int i = 0; i < 3; i++)
      {
          HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);
          HAL_Delay(100);
          HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
          HAL_Delay(100);
      }
  }

  /* USER CODE END 2 */

  while (1)
  {
    // ----- AWAKE PHASE (5 s) -----
    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_SET);    // LED on
    HAL_GPIO_WritePin(TRIG_PORT, TRIG_PIN, GPIO_PIN_RESET);  // Trigger LOW = awake
    HAL_Delay(ACTIVE_MS);

    // ----- SLEEP PHASE (5 s in Standby) -----
    Enter_Standby_5s();
    // Never returns - standby exit causes a full reset
  }
}


void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  if (HAL_PWREx_ConfigSupply(PWR_SMPS_SUPPLY) != HAL_OK) Error_Handler();

  if (HAL_RCCEx_EpodBoosterClkConfig(RCC_EPODBOOSTER_SOURCE_MSIS, RCC_EPODBOOSTER_DIV1) != HAL_OK) Error_Handler();
  if (HAL_PWREx_EnableEpodBooster() != HAL_OK) Error_Handler();

  if (HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1) != HAL_OK) Error_Handler();

  __HAL_FLASH_SET_LATENCY(FLASH_LATENCY_2);

  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_LSE|RCC_OSCILLATORTYPE_MSIS;
  RCC_OscInitStruct.LSEState = RCC_LSE_ON;
  RCC_OscInitStruct.MSISState = RCC_MSI_ON;
  RCC_OscInitStruct.MSISSource = RCC_MSI_RC0;
  RCC_OscInitStruct.MSISDiv = RCC_MSI_DIV1;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) Error_Handler();

  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2|RCC_CLOCKTYPE_PCLK3;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_MSIS;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB3CLKDivider = RCC_HCLK_DIV1;
  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK) Error_Handler();
}


static void MX_RTC_Init(void)
{
  RTC_PrivilegeStateTypeDef privilegeState = {0};

  hrtc.Instance = RTC;
  hrtc.Init.HourFormat = RTC_HOURFORMAT_24;
  hrtc.Init.AsynchPrediv = 127;
  hrtc.Init.SynchPrediv = 255;
  hrtc.Init.OutPut = RTC_OUTPUT_DISABLE;
  hrtc.Init.OutPutRemap = RTC_OUTPUT_REMAP_NONE;
  hrtc.Init.OutPutPolarity = RTC_OUTPUT_POLARITY_HIGH;
  hrtc.Init.OutPutType = RTC_OUTPUT_TYPE_OPENDRAIN;
  hrtc.Init.OutPutPullUp = RTC_OUTPUT_PULLUP_NONE;
  hrtc.Init.BinMode = RTC_BINARY_NONE;
  if (HAL_RTC_Init(&hrtc) != HAL_OK) Error_Handler();

  privilegeState.rtcPrivilegeFull = RTC_PRIVILEGE_FULL_NO;
  privilegeState.backupRegisterPrivZone = RTC_PRIVILEGE_BKUP_ZONE_NONE;
  privilegeState.backupRegisterStartZone2 = RTC_BKP_DR0;
  privilegeState.backupRegisterStartZone3 = RTC_BKP_DR0;
  if (HAL_RTCEx_PrivilegeModeSet(&hrtc, &privilegeState) != HAL_OK) Error_Handler();
}


static void MX_USART1_UART_Init(void)
{
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart1) != HAL_OK) Error_Handler();
  if (HAL_UARTEx_SetTxFifoThreshold(&huart1, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK) Error_Handler();
  if (HAL_UARTEx_SetRxFifoThreshold(&huart1, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK) Error_Handler();
  if (HAL_UARTEx_DisableFifoMode(&huart1) != HAL_OK) Error_Handler();
}


static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  HAL_GPIO_WritePin(GPIOA, LED_PIN | TRIG_PIN, GPIO_PIN_RESET);

  // LED and PPK2 trigger as push-pull outputs
  GPIO_InitStruct.Pin = LED_PIN | TRIG_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
}


/* USER CODE BEGIN 4 */
void Enter_Standby_5s(void)
{
    // Mark sleep entry: LED off, trigger HIGH
    HAL_GPIO_WritePin(LED_PORT, LED_PIN, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(TRIG_PORT, TRIG_PIN, GPIO_PIN_SET);

    // Stop SysTick so it doesn't immediately wake us
    HAL_SuspendTick();

    // Route the RTC to wakeup line 7 (needed to leave Standby)
    HAL_PWR_EnableWakeUpLine(PWR_WAKEUP_LINE7, PWR_WAKEUP_SELECT_3, PWR_WAKEUP_POLARITY_HIGH);

    // Disable the wakeup timer and clear stale flags
    HAL_RTCEx_DeactivateWakeUpTimer(&hrtc);
    __HAL_PWR_CLEAR_FLAG(PWR_FLAG_SBF);
    __HAL_PWR_CLEAR_FLAG(PWR_WAKEUP_ALL_FLAG);
    __HAL_RTC_WAKEUPTIMER_CLEAR_FLAG(&hrtc, RTC_FLAG_WUTF);

    // Arm the wakeup timer for 5 s
    if (HAL_RTCEx_SetWakeUpTimer_IT(&hrtc, WAKEUP_COUNTS, RTC_WAKEUPCLOCK_RTCCLK_DIV16, 0) != HAL_OK)
    {
        HAL_ResumeTick();  // HAL_Delay needs SysTick, which is suspended here
        while (1) { HAL_GPIO_TogglePin(LED_PORT, LED_PIN); HAL_Delay(100); }
    }

    HAL_PWR_EnterSTANDBYMode();
    // Never returns - standby exit causes a full reset
}
/* USER CODE END 4 */


void Error_Handler(void)
{
  __disable_irq();
  while (1) { }
}
#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line) { }
#endif
