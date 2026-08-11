/**
 * @file test_<class_name>.cpp
 * @brief <ClassName> の単体テスト。
 *
 * 各テストは work/test-design.md の1行に対応する。
 * テスト名は観点表のテストIDと完全に一致させること
 * （scripts/check_traceability.py がこの一致で突合する）。
 */

#include "<project_path>/<class_name>.h"

#include <cstdint>

#include <gmock/gmock.h>
#include <gtest/gtest.h>

namespace <project_ns> {
namespace {

/** @brief 依存先インタフェースのモック。 */
class Mock<IDependency> : public <IDependency>
{
public:
    MOCK_METHOD(std::int32_t, Read, (), (const, noexcept, override));
    MOCK_METHOD(bool, Reset, (), (noexcept, override));
};

/** @brief <ClassName> 用フィクスチャ。テスト間で状態を共有しない。 */
class <ClassName>Test : public ::testing::Test
{
protected:
    void SetUp() override
    {
        /* 各テストの直前に毎回実行される。共通の事前条件のみをここに置く */
    }

    ::testing::NiceMock<Mock<IDependency>> dependency_;
    <ClassName>                            sut_{dependency_};
};

/* UT_<Class>_<Func>_001 : 正常 — 有効値を設定できる */
TEST_F(<ClassName>Test, UT_<Class>_<Func>_001)
{
    // Arrange: 事前条件
    ASSERT_TRUE(sut_.Initialize());

    // Act: 入力
    const bool result = sut_.<Func>(100);

    // Assert: 期待結果
    EXPECT_TRUE(result);
    EXPECT_EQ(100, sut_.GetTargetSpeed());
}

/* UT_<Class>_<Func>_003 : 境界 — 上限超過を拒否する */
TEST_F(<ClassName>Test, UT_<Class>_<Func>_003)
{
    ASSERT_TRUE(sut_.Initialize());
    const std::int32_t before = sut_.GetTargetSpeed();

    const bool result = sut_.<Func>(<ClassName>::kMaxSpeed + 1);

    EXPECT_FALSE(result);
    EXPECT_EQ(before, sut_.GetTargetSpeed());
}

/* UT_<Class>_<Func>_004 : 異常 — 未初期化での呼び出しを拒否する */
TEST_F(<ClassName>Test, UT_<Class>_<Func>_004)
{
    /* Initialize() を呼ばない状態が事前条件 */

    const bool result = sut_.<Func>(100);

    EXPECT_FALSE(result);
}

/* UT_<Class>_<Func>_005 : 相互作用 — 依存先を決められた順に1回ずつ呼ぶ */
TEST_F(<ClassName>Test, UT_<Class>_<Func>_005)
{
    ASSERT_TRUE(sut_.Initialize());

    ::testing::InSequence seq;
    EXPECT_CALL(dependency_, Read()).Times(1).WillOnce(::testing::Return(100));
    EXPECT_CALL(dependency_, Reset()).Times(1).WillOnce(::testing::Return(true));

    sut_.Update();
}

}  // namespace
}  // namespace <project_ns>
