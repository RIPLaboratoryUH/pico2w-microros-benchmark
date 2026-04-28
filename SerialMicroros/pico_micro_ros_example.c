#include <stdio.h>
#include <string.h>
#include <inttypes.h>  // for PRIu64

#include <rcl/rcl.h>
#include <rcl/error_handling.h>
#include <rclc/rclc.h>
#include <rclc/executor.h>
#include <std_msgs/msg/string.h>
#include <std_msgs/msg/u_int64.h>
#include <rmw_microros/rmw_microros.h>

#include "pico/stdlib.h"
#include "hardware/i2c.h"
#include "pico_uart_transports.h"

// --- ADS1115 definitions ---
#define ADS1115_ADDR 0x48
#define ADS1115_REG_CONVERSION 0x00
#define ADS1115_REG_CONFIG     0x01

#define ADS1115_CONFIG_OS_SINGLE      (1 << 15)
#define ADS1115_CONFIG_MUX_DIFF_2_3   (0x3 << 12)  // AIN2 - AIN3
#define ADS1115_CONFIG_PGA_1          (0x1 << 9)   // Gain +/-4.096V (LSB = 125uV)
#define ADS1115_CONFIG_MODE_SINGLE    (1 << 8)
#define ADS1115_CONFIG_DR_1600SPS     (0x4 << 5)
#define ADS1115_CONFIG_COMP_QUE_DISABLE (0x3)

#define ADS1115_CONFIG_DEFAULT ( \
    ADS1115_CONFIG_OS_SINGLE | \
    ADS1115_CONFIG_MUX_DIFF_2_3 | \
    ADS1115_CONFIG_PGA_1 | \
    ADS1115_CONFIG_MODE_SINGLE | \
    ADS1115_CONFIG_DR_1600SPS | \
    ADS1115_CONFIG_COMP_QUE_DISABLE \
)

// --- Global micro-ROS objects ---
rcl_publisher_t publisher;
rcl_subscription_t subscriber;
std_msgs__msg__String pub_msg;
std_msgs__msg__UInt64 sub_msg;
rcl_node_t node;
rcl_allocator_t allocator;
rclc_support_t support;
rclc_executor_t executor;

// Buffer for building reply string
char pub_msg_buffer[128];

// I2C instance (using i2c0)
i2c_inst_t *i2c = i2c0;

// --- Function Prototypes ---
void setup_transport();
bool wait_for_agent();
void setup_ros();
void i2c_init_ads1115();
int16_t ads1115_read_raw();
float ads1115_raw_to_voltage(int16_t raw);
float read_sensor_voltage();
void subscription_callback(const void *msgin);

// --- Implementations ---

void setup_transport()
{
    rmw_uros_set_custom_transport(
        true,
        NULL,
        pico_serial_transport_open,
        pico_serial_transport_close,
        pico_serial_transport_write,
        pico_serial_transport_read
    );
}

bool wait_for_agent()
{
    const int timeout_ms = 1000;
    const uint8_t attempts = 120;
    return rmw_uros_ping_agent(timeout_ms, attempts) == RCL_RET_OK;
}

void setup_ros()
{
    allocator = rcl_get_default_allocator();
    rclc_support_init(&support, 0, NULL, &allocator);
    rclc_node_init_default(&node, "pico_node", "", &support);

    // Publisher: String topic "voltage_reading" (Best Effort)
    rclc_publisher_init_best_effort(
        &publisher,
        &node,
        ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, String),
        "voltage_reading"
    );

    // Subscriber: UInt64 topic "voltage_request" (Best Effort)
    rclc_subscription_init_best_effort(
        &subscriber,
        &node,
        ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, UInt64),
        "voltage_request"
    );

    rclc_executor_init(&executor, &support.context, 1, &allocator);
    rclc_executor_add_subscription(
        &executor,
        &subscriber,
        &sub_msg,
        &subscription_callback,
        ON_NEW_DATA
    );
}

void i2c_init_ads1115()
{
    i2c_init(i2c, 400000);
    gpio_set_function(4, GPIO_FUNC_I2C); // SDA
    gpio_set_function(5, GPIO_FUNC_I2C); // SCL
    gpio_pull_up(4);
    gpio_pull_up(5);
}

int16_t ads1115_read_raw()
{
    // Write config to start single conversion
    uint8_t config_data[3] = {
        ADS1115_REG_CONFIG,
        (uint8_t)(ADS1115_CONFIG_DEFAULT >> 8),
        (uint8_t)(ADS1115_CONFIG_DEFAULT & 0xFF)
    };

    if (i2c_write_blocking(i2c, ADS1115_ADDR, config_data, 3, false) != 3) {
        printf("Failed to write ADS1115 config\n");
        return 0;
    }

    // Wait ~1ms for conversion
    sleep_ms(1);

    // Set pointer to conversion register
    uint8_t reg = ADS1115_REG_CONVERSION;
    if (i2c_write_blocking(i2c, ADS1115_ADDR, &reg, 1, true) != 1) {
        printf("Failed to write ADS1115 conversion register pointer\n");
        return 0;
    }

    // Read 2 bytes conversion result
    uint8_t read_data[2];
    if (i2c_read_blocking(i2c, ADS1115_ADDR, read_data, 2, false) != 2) {
        printf("Failed to read ADS1115 conversion data\n");
        return 0;
    }

    return (int16_t)((read_data[0] << 8) | read_data[1]);
}

float ads1115_raw_to_voltage(int16_t raw)
{
    // Gain +/-4.096V, LSB = 125uV
    return (float)raw * 0.000125f;
}

float read_sensor_voltage()
{
    int16_t raw = ads1115_read_raw();
    return ads1115_raw_to_voltage(raw);
}

void subscription_callback(const void *msgin)
{
    const std_msgs__msg__UInt64 *msg = (const std_msgs__msg__UInt64 *)msgin;
    uint64_t timestamp = msg->data;

    float voltage = read_sensor_voltage();

    int len = snprintf(pub_msg_buffer, sizeof(pub_msg_buffer),
        "voltage reading reply with timestamp: %" PRIu64 ", voltage: %.3f V", timestamp, voltage);

    pub_msg.data.data = pub_msg_buffer;
    pub_msg.data.size = len;
    pub_msg.data.capacity = sizeof(pub_msg_buffer);

    rcl_publish(&publisher, &pub_msg, NULL);

    printf("Received timestamp: %" PRIu64 ", voltage: %.3f V\n", timestamp, voltage);
}

// --- Main ---

int main()
{
    stdio_init_all();

    i2c_init_ads1115();

    setup_transport();

    if (!wait_for_agent())
    {
        printf("Agent not found, exiting\n");
        return 1;
    }

    setup_ros();

    while (true)
    {
        rclc_executor_spin_some(&executor, RCL_MS_TO_NS(100));
    }

    return 0;
}
