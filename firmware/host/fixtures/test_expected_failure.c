#include "test_support.h"

E87_TEST(intentional_failure)
{
    E87_ASSERT_EQ_U32(UINT32_C(1), UINT32_C(2));
}

E87_TEST(zero_assertions)
{
}

static const struct e87_test_case failure_cases[] = {
    E87_TEST_CASE(intentional_failure),
    E87_TEST_CASE(zero_assertions),
};

const struct e87_test_suite e87_test_suite = {
    "expected-failure",
    failure_cases,
    sizeof(failure_cases) / sizeof(failure_cases[0]),
};
