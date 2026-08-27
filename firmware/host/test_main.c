#include "test_support.h"

#include <inttypes.h>
#include <stdio.h>

static size_t assertion_count;
static int assertion_failed;
static const char *failure_file;
static unsigned int failure_line;
static const char *failure_expression;
static uint32_t failure_expected;
static uint32_t failure_actual;

void e87_test_record_assertion(void)
{
    assertion_count += 1U;
}

void e87_test_record_failure(const char *file,
                             unsigned int line,
                             const char *expression,
                             uint32_t expected,
                             uint32_t actual)
{
    if (assertion_failed) {
        return;
    }
    assertion_failed = 1;
    failure_file = file;
    failure_line = line;
    failure_expression = expression;
    failure_expected = expected;
    failure_actual = actual;
}

static void reset_test_state(void)
{
    assertion_count = 0U;
    assertion_failed = 0;
    failure_file = "";
    failure_line = 0U;
    failure_expression = "";
    failure_expected = UINT32_C(0);
    failure_actual = UINT32_C(0);
}

int main(void)
{
    size_t index;
    size_t passed = 0U;
    size_t failed = 0U;
    size_t total_assertions = 0U;

    for (index = 0U; index < e87_test_suite.count; index += 1U) {
        const struct e87_test_case *test_case = &e87_test_suite.cases[index];

        reset_test_state();
        printf("RUN %s::%s\n", e87_test_suite.name, test_case->name);
        test_case->run();
        if (assertion_count == 0U) {
            e87_test_record_failure("<test>", 0U, "at least one assertion",
                                    UINT32_C(1), UINT32_C(0));
        }
        total_assertions += assertion_count;
        if (assertion_failed) {
            failed += 1U;
            printf("FAIL %s::%s file=%s line=%u expression=%s expected=%" PRIu32
                   " actual=%" PRIu32 " assertions=%zu\n",
                   e87_test_suite.name, test_case->name, failure_file,
                   failure_line, failure_expression, failure_expected,
                   failure_actual, assertion_count);
        } else {
            passed += 1U;
            printf("PASS %s::%s assertions=%zu\n",
                   e87_test_suite.name, test_case->name, assertion_count);
        }
    }

    printf("SUMMARY %s tests=%zu passed=%zu failed=%zu assertions=%zu\n",
           e87_test_suite.name, e87_test_suite.count, passed, failed,
           total_assertions);
    return failed == 0U ? 0 : 1;
}
