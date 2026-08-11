/**
 * @file <file_name>.h
 * @brief <このファイルが提供するものを1行で>
 *
 * @note 本ファイルは Next Design 詳細設計「<設計書名>」の <クラス名> に対応する。
 */

#ifndef <PROJECT>_<PATH>_<FILE_NAME>_H_
#define <PROJECT>_<PATH>_<FILE_NAME>_H_

/* 1. 標準ヘッダ */
#include <cstdint>

/* 2. 外部ライブラリ */

/* 3. プロジェクト内ヘッダ */

namespace <project_ns> {

/**
 * @brief <クラスの責務を1〜2行で。設計の brief をそのまま使ってよい>
 *
 * @note 依存する <IDependency> はコンストラクタで注入する。
 *       所有権は保持せず、参照先の寿命は呼び出し側が保証すること。
 */
class <ClassName> final
{
public:
    /** @brief 設定可能な最大値 [単位]。 */
    static constexpr std::int32_t kMaxSpeed = 10000;

    /**
     * @brief コンストラクタ。
     * @param[in] dependency 依存先。呼び出し側が本オブジェクトより長く保持すること。
     */
    explicit <ClassName>(<IDependency>& dependency) noexcept;

    ~<ClassName>() = default;

    <ClassName>(const <ClassName>&) = delete;
    <ClassName>& operator=(const <ClassName>&) = delete;
    <ClassName>(<ClassName>&&) = delete;
    <ClassName>& operator=(<ClassName>&&) = delete;

    /**
     * @brief <この関数が何をするか。1行で言い切る>
     *
     * <補足が要る場合のみ、副作用・反映タイミングをここに書く>
     *
     * @param[in] <arg> <意味と単位>。有効範囲は <下限> 以上 <上限> 以下。
     * @retval true  <成功した条件>
     * @retval false <失敗した条件。テストの異常系はここから起こす>
     * @pre <この関数を呼ぶ前に成立していなければならない条件。無ければ「なし」と書く>
     * @post <呼び出し後に保証される状態>
     * @note <規約からの逸脱がある場合、その内容と理由>
     */
    bool <FunctionName>(std::int32_t <arg>) noexcept;

protected:
    /* protected な関数はここ */

private:
    /**
     * @brief <private 関数の説明。public と同じ密度で書く>
     * @param[in] <arg> <意味>
     * @return <戻り値の意味>
     */
    std::int32_t <PrivateFunction>(std::int32_t <arg>) const noexcept;

    <IDependency>& dependency_;          /**< 注入された依存先。 */
    std::int32_t   target_speed_{0};     /**< 目標値 [単位]。既定は 0。 */
    bool           initialized_{false};  /**< Initialize() の成否。 */
};

}  // namespace <project_ns>

#endif  /* <PROJECT>_<PATH>_<FILE_NAME>_H_ */
