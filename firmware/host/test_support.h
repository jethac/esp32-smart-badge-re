#ifndef E87_HOST_TEST_SUPPORT_H
#define E87_HOST_TEST_SUPPORT_H

#include <stddef.h>
#include <stdint.h>

struct e87_test_case {
    const char *name;
    void (*run)(void);
};

struct e87_test_suite {
    const char *name;
    const struct e87_test_case *cases;
    size_t count;
};

extern const struct e87_test_suite e87_test_suite;

void e87_test_record_assertion(void);
void e87_test_record_failure(const char *file,
                             unsigned int line,
                             const char *expression,
                             uint32_t expected,
                             uint32_t actual);

#define E87_TEST(name) static void name(void)
#define E87_TEST_CASE(name) { #name, name }

#define E87_ASSERT_TRUE(expression)                                           \
    do {                                                                      \
        const int e87_test_actual_ = ((expression) ? 1 : 0);                 \
        e87_test_record_assertion();                                          \
        if (!e87_test_actual_) {                                              \
            e87_test_record_failure(__FILE__,                                 \
                                    (unsigned int)__LINE__,                    \
                                    #expression,                              \
                                    UINT32_C(1),                              \
                                    UINT32_C(0));                             \
            return;                                                           \
        }                                                                     \
    } while (0)

#define E87_ASSERT_EQ_U32(expected, actual)                                   \
    do {                                                                      \
        const uint32_t e87_test_expected_ = (uint32_t)(expected);             \
        const uint32_t e87_test_actual_ = (uint32_t)(actual);                 \
        e87_test_record_assertion();                                          \
        if (e87_test_expected_ != e87_test_actual_) {                         \
            e87_test_record_failure(__FILE__,                                 \
                                    (unsigned int)__LINE__,                    \
                                    #actual,                                  \
                                    e87_test_expected_,                       \
                                    e87_test_actual_);                        \
            return;                                                           \
        }                                                                     \
    } while (0)

#endif
