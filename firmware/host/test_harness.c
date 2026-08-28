#include "test_support.h"
#include "e87/e87_types.h"

E87_TEST(display_geometry)
{
    E87_ASSERT_EQ_U32(UINT32_C(360), E87_DISPLAY_WIDTH);
    E87_ASSERT_EQ_U32(UINT32_C(360), E87_DISPLAY_HEIGHT);
    E87_ASSERT_EQ_U32(UINT32_C(2), E87_RGB565_BYTES_PER_PIXEL);
}

E87_TEST(strip_buffer_budget)
{
    E87_ASSERT_EQ_U32(UINT32_C(30), E87_STRIP_ROWS);
    E87_ASSERT_EQ_U32(UINT32_C(12), E87_STRIP_COUNT);
    E87_ASSERT_EQ_U32(UINT32_C(0x5460), E87_STRIP_BUFFER_BYTES);
    E87_ASSERT_EQ_U32(UINT32_C(0xA8C0), E87_TWO_STRIP_BUFFERS_BYTES);
    E87_ASSERT_EQ_U32(UINT32_C(0x6000), E87_LCD_TAIL_RESERVATION_BYTES);
    E87_ASSERT_EQ_U32(UINT32_C(0x0BA0), E87_LCD_TAIL_SLACK_BYTES);
    E87_ASSERT_TRUE(
        E87_TWO_STRIP_BUFFERS_BYTES > E87_LCD_TAIL_RESERVATION_BYTES);
}

static const struct e87_test_case harness_cases[] = {
    E87_TEST_CASE(display_geometry),
    E87_TEST_CASE(strip_buffer_budget),
};

const struct e87_test_suite e87_test_suite = {
    "buffer-budget",
    harness_cases,
    sizeof(harness_cases) / sizeof(harness_cases[0]),
};
