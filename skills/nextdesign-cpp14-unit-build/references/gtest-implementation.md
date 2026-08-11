# GoogleTest 実装と CMake 構成

フェーズ4で読む。`work/test-design.md` の全行をテストコードに落とす。

## テスト名の規約

観点表のテストIDをそのまま使う。`check_traceability.py` はこの文字列一致で突合するので、崩さない。

```cpp
// UT_MotorController_SetSpeed_001
TEST_F(MotorControllerTest, UT_MotorController_SetSpeed_001)
{
    ...
}
```

- フィクスチャを使う場合は `TEST_F`、使わない場合は `TEST`
- テストスイート名は `<クラス名>Test`
- テストIDをコメントとしても直前行に置く（表とコードを目で追うため）

## 1テスト1観点

観点表の1行に対してテスト関数1個。**1つのテスト関数に複数の観点を詰めない**。失敗したときにどの観点が壊れたのか分からなくなる。

テスト本体は Arrange / Act / Assert の3ブロックに分け、観点表の「事前条件 / 入力 / 期待結果」がそれぞれに対応する形で書く。

```cpp
TEST_F(MotorControllerTest, UT_MotorController_SetSpeed_003)
{
    // Arrange: 事前条件 — Initialize 済み
    ASSERT_TRUE(sut_.Initialize());

    // Act: 入力 — 上限値 kMaxSpeed
    const bool result = sut_.SetSpeed(MotorController::kMaxSpeed);

    // Assert: 期待結果 — true、かつ目標値が反映される
    EXPECT_TRUE(result);
    EXPECT_EQ(MotorController::kMaxSpeed, sut_.GetTargetSpeed());
}
```

事前条件の成立は `ASSERT_*` で書く（成立しなければ以降の検証に意味がないため）。本題の検証は `EXPECT_*` で書く（複数の期待結果をまとめて確認できる）。

## アサーションの選び方

| 場面 | 使うもの |
|---|---|
| 等値 | `EXPECT_EQ(期待値, 実測値)`。引数の順を逆にしない（失敗メッセージが逆になる） |
| 浮動小数 | `EXPECT_NEAR(期待値, 実測値, 許容誤差)`。`EXPECT_EQ` を使わない |
| 真偽 | `EXPECT_TRUE` / `EXPECT_FALSE`。`EXPECT_EQ(true, x)` にしない |
| 文字列 | `EXPECT_STREQ`（C 文字列）/ `EXPECT_EQ`（`std::string`） |
| 死ぬこと | `EXPECT_DEATH`。例外禁止構成でアサート停止を検証するとき |

## モック化

依存先は gmock でモックにする。フェーズ1で依存注入の形にしてあることが前提。

```cpp
class MockSpeedSensor : public ISpeedSensor
{
public:
    MOCK_METHOD(std::int32_t, Read, (), (const, noexcept, override));
    MOCK_METHOD(bool, Reset, (), (noexcept, override));
};
```

- `MOCK_METHOD` は gmock 1.10 以降の書式を使う（`MOCK_CONSTx_METHOD` 系は使わない）
- 戻り値を使わない呼び出しは `ON_CALL` + `NiceMock` で黙らせ、**検証したい呼び出しだけ `EXPECT_CALL`** にする。すべてを `EXPECT_CALL` にすると、関係ない変更で大量に壊れる

### 相互作用のテスト（呼び出し順）

観点表で「区分 = 相互作用」の行は、順序または回数を検証する。

```cpp
TEST_F(MotorControllerTest, UT_MotorController_Update_007)
{
    ::testing::InSequence seq;
    EXPECT_CALL(sensor_, Read()).Times(1).WillOnce(::testing::Return(100));
    EXPECT_CALL(driver_, Apply(100)).Times(1);

    sut_.Update();
}
```

## フィクスチャ

```cpp
class MotorControllerTest : public ::testing::Test
{
protected:
    void SetUp() override { /* 各テスト前に毎回実行される */ }
    void TearDown() override { /* 後始末 */ }

    ::testing::NiceMock<MockSpeedSensor> sensor_;
    ::testing::NiceMock<MockMotorDriver> driver_;
    MotorController sut_{sensor_, driver_};
};
```

- テスト対象は `sut_`（system under test）で統一する
- **フィクスチャ間で状態を共有しない**。`static` なメンバや global を使わない。テストの実行順に依存すると、単体で走らせたときだけ落ちる

## CMake 構成

```cmake
cmake_minimum_required(VERSION 3.14)
project(<project> CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_compile_options(-Wall -Wextra -Werror)

# 製品コード（テストから参照するためライブラリにする）
add_library(<project>_lib STATIC src/motor_controller.cpp ...)
target_include_directories(<project>_lib PUBLIC include)

enable_testing()
find_package(GTest REQUIRED)          # 見つからない場合は FetchContent で取得する

add_executable(<project>_test test/test_motor_controller.cpp ...)
target_link_libraries(<project>_test PRIVATE <project>_lib GTest::gtest_main GTest::gmock)

include(GoogleTest)
gtest_discover_tests(<project>_test)
```

要点。

- 製品コードは**ライブラリにしてから**テストとリンクする。テスト実行ファイルに `.cpp` を直接並べない
- `gtest_discover_tests` を使う。`add_test` に手で1件ずつ書かない
- `find_package(GTest REQUIRED)` が失敗する環境では `FetchContent_Declare` で取得する。どちらを使ったかは完了報告に書く

### カバレッジ

構成に含める場合のみ。GCC / Clang なら:

```cmake
option(ENABLE_COVERAGE "Enable coverage" OFF)
if(ENABLE_COVERAGE)
  target_compile_options(<project>_lib PRIVATE --coverage -O0 -g)
  target_link_options(<project>_lib PRIVATE --coverage)
endif()
```

計測ツールが環境に無ければ**無理に導入しない**。省略したことをフェーズ6の報告に明記する。

## 実行

```
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

## やってはいけないこと

- 失敗するテストを `DISABLED_` にする、`GTEST_SKIP()` で飛ばす、アサーションを消す
- 実測値を期待値として書き直す（期待値は設計から決まる。実装から決めない）
- テストのために製品コードの可視性を緩める（`#define private public` を含む）
- 1つのテストに `EXPECT_CALL` を大量に並べ、実装の呼び出し順をそのまま写す（実装の写像はテストではない）
