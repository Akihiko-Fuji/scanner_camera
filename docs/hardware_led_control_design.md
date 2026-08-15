# fi-65F LED制御回路設計

この文書は、fi-65Fをscanner cameraとして使用するために、**初期化時だけ内蔵RGB LEDを発光させ、本スキャン中はLEDを遮断する**ための電気設計案をまとめたものです。

実機応答の根拠は[`hardware_response_validation.md`](hardware_response_validation.md)、ソフトウェアの使用方法は[`../README.md`](../README.md)を参照してください。

> **設計状態**: 回路方針は定義済みですが、pin 2の極性・電圧・電流方向が未測定のため、MOSFETのhigh-side / low-side方式は未確定です。実装前に本書4章の測定を完了してください。

## 1. 設計目的

fi-65Fでは、LED/導光ユニットを外した場合だけでなく、LEDを電気的に接続したままCISへ光を入れない場合にもPaperStream IPが「フラットベッドの光量異常」を報告しました。

また、初期化時にはRGB LEDが強く発光します。

したがって、LEDを恒久的に取り外すのではなく、次のシーケンスを実現します。

```text
待機
  ↓
LED path = ON
  ↓
スキャン開始
  ↓
初期化時の強い発光
  ↓
光量チェック/初期化成立
  ↓
LED path = OFF
  ↓
本スキャン
  ↓
外部レンズ像のみ取得
  ↓
スキャン終了
  ↓
LED path = ONへ戻す
```

## 2. ハードウェア介入点

LED boardの`C`端子が、CIS基板側15-pinコネクタの**pin 2**へ導通することを実測で確認しています。

したがって、LED遮断の介入点は15-pin信号のpin 2とします。

```text
MAIN BOARD
15-pin pin 2
      │
      │
 [ MOSFET switch ]
      │
      │
CIS BOARD pin 2
      │
      └── LED board C
```

他の14本はそのまま直結します。

### 2.1 配線方法

細ピッチコネクタのランドへ直接ジャンパーを付ける方法は使用しません。実機試行でランド損傷が発生したため、次のいずれかを使用します。

優先順：

1. **15-pin FFC/FPC interposer / breakout board**
2. FFC延長基板でpin 2だけを分離
3. CIS/MAIN基板上で同一ネットの十分な面積を持つtest point / viaを利用

15-pin FFCのピッチ・接点面向き・上接点/下接点は、現物測定後に部品を選定します。

## 3. なぜMOSFETでpin 2を切るのか

機械式シャッターは、LED出射部と導光板端面のクリアランスが1 mm未満であり、既存構造へ追加する余地がほぼありません。

一方、pin 2はLED board `C`へ接続しているため、ここを電気的に開閉できれば、導光板を加工せずにLED発光のON/OFFを試せます。

設計上の要求は次です。

- 初期化開始時は導通状態
- 初期化完了後に遮断
- 次回スキャン前には再び導通
- MOSFET OFF時にpin 2へ大きな漏れ電流を流さない
- MOSFET ON時の電圧降下を小さくする
- MAIN/CIS間の他14信号へ影響を与えない
- 実験段階では手動制御を可能にする

## 4. 実装前に必須の測定

現時点では`C`がcommon anode / common cathode / その他の共通制御線のどれか確定していません。

正常個体で次を測定します。

| 測定 | 待機 | 初期化発光中 | 本スキャン中 |
|---|---:|---:|---:|
| pin 2 - MAIN GND電圧 | 要測定 | 要測定 | 要測定 |
| R - MAIN GND電圧 | 要測定 | 要測定 | 要測定 |
| G - MAIN GND電圧 | 要測定 | 要測定 | 要測定 |
| B - MAIN GND電圧 | 要測定 | 要測定 | 要測定 |
| pin 2電流方向 | 要確認 | 要確認 | 要確認 |

判定：

- pin 2が正電源側として振る舞う場合 → **P-channel MOSFET high-side方式**
- pin 2が0 V側/common returnとして振る舞う場合 → **N-channel MOSFET low-side方式**

極性を確認するまではMOSFETを実装しません。

## 5. 推奨回路A: pin 2が正電源側の場合

pin 2がLED共通正電源であることを確認できた場合は、P-channel MOSFETをhigh-side switchとして使います。

### 5.1 回路

```text
                      Q1 P-MOSFET
MAIN pin 2 -----------S       D----------- CIS pin 2 -> LED C
                       \     /
                        \___/
                          |
                          G
                          |
                    Rg 1kΩ
                          |
               +----------+----------+
               |                     |
             R1 100kΩ              U1 photo-coupler
               |                 transistor side
MAIN GND -------+                C -------- Q1 Source
                                  E
                                  |
                                  +-------- Q1 Gate

U1 LED side:
OFF_CTRL ---- R2 ----|>|---- CTRL_GND
```

動作：

- `OFF_CTRL=LOW`またはU1消灯 → R1がgateをGND側へ引く → `VGS<0` → **Q1 ON** → LED使用可能
- `OFF_CTRL=HIGH`でU1点灯 → U1 transistorがgateをsourceへ引き上げる → `VGS≈0` → **Q1 OFF** → pin 2遮断

この構成は、制御回路が動いていない場合にLED pathがONとなるため、初期化を妨げにくい構成です。

### 5.2 部品例

| Ref | 部品 | 要求/例 |
|---|---|---|
| Q1 | P-channel MOSFET | AO3401A相当、`VDS` 20 V以上、低`RDS(on)` |
| U1 | フォトカプラ | PC817 / LTV-817相当 |
| R1 | Gate pull-down | 100 kΩ |
| Rg | Gate series | 1 kΩ |
| R2 | U1 LED電流制限 | 3.3 V制御なら390～470 Ω、5 V制御なら680～820 Ωを目安 |
| SW1 | 手動OFF試験 | SPSTスイッチ、U1 LEDをON/OFFできる構成 |
| J1/J2 | FFC/FPC中継 | 15-pin、現物ピッチ/接点向きに合わせる |

Q1はLED電流を十分流せる低オン抵抗品を選びます。実機電流を測定してから定格を確定します。

## 6. 推奨回路B: pin 2がcommon returnの場合

pin 2がLED共通return/0 V側であることを確認した場合は、N-channel MOSFETをlow-side switchとして使用します。

### 6.1 回路

```text
CIS pin 2 -> LED C --------D  Q1 N-MOSFET  S-------- MAIN pin 2
                            \            /
                             \__________/
                                  |
                                  G
                                  |
                         +--------+--------+
                         |                 |
                      R1 100kΩ          U1 transistor
                         |              C
                      VCTRL             E
                                         |
                                         +------ Q1 Source

U1 LED side:
OFF_CTRL ---- R2 ----|>|---- CTRL_GND
```

動作：

- U1消灯 → R1がgateを`VCTRL`へ引き上げる → **Q1 ON**
- U1点灯 → gateをsourceへ引き下げる → **Q1 OFF**

この方式では、Q1を確実にONできる`VCTRL`をscanner側から取得する必要があります。`VCTRL`は測定済みの3.3 V/5 V系のみを使用し、未確認の電源点へ接続しません。

### 6.2 部品例

| Ref | 部品 | 要求/例 |
|---|---|---|
| Q1 | N-channel MOSFET | AO3400A相当、logic-level、`VDS` 20 V以上、低`RDS(on)` |
| U1 | フォトカプラ | PC817 / LTV-817相当 |
| R1 | Gate pull-up | 100 kΩ |
| R2 | U1 LED電流制限 | 制御電圧に合わせ390～820 Ω程度 |
| J1/J2 | FFC/FPC中継 | 15-pin、現物仕様に合わせる |

## 7. pin 2極性が不明のまま試さない

P-MOS high-sideとN-MOS low-sideは、pin 2の実回路が分からない状態では互換ではありません。

そのため、次の順序を固定します。

```text
pin 2電圧/極性測定
       ↓
high-side / low-side決定
       ↓
interposer作成
       ↓
手動ON/OFF試験
       ↓
本スキャン継続確認
       ↓
自動制御
```

もしpin 2に双方向電流や極性反転が見られる場合は、単一MOSFETではなくback-to-back MOSFETまたは双方向analog switch/load switchへ設計変更します。

## 8. 最初に行う手動試験

自動制御回路を先に作らず、まずMOSFETを手動で切り替えます。

### 8.1 試験手順

1. MOSFET ONで起動
2. scannerが通常待機できることを確認
3. スキャン開始
4. 初期化時の強いLED発光を確認
5. 強い発光が終了した直後に`OFF_CTRL`を切替
6. LEDが消灯することを確認
7. キャリッジが本スキャンを継続するか確認
8. 画像が保存されるか確認
9. 光量異常が出る場合は、異常発生位置/時間を記録
10. 次回スキャン前にMOSFETをONへ戻す

### 8.2 成功条件

```text
初期化発光: あり
光量異常:   なし
本スキャン: 完走
本スキャン中LED: 消灯
画像保存:   成功
```

この試験が成立するまで、自動化へ進みません。

## 9. 自動制御案

手動試験が成立した後にのみ、自動化を行います。

### 9.1 第一候補: 外部controller + OFF_CTRL

小型MCUまたはUSB接続controllerからフォトカプラU1を駆動します。

制御は次の状態機械とします。

```text
IDLE
  LED path ON
    ↓ scan start
INITIALIZE
  LED path ON
    ↓ initialization complete
CAPTURE
  LED path OFF
    ↓ scan end / error
IDLE
  LED path ON
```

スキャンAPI呼び出し中はWIA/TWAIN driverがblockingする場合があるため、ソフトウェアから自動制御する場合はLED controllerを別thread/processまたは独立MCUとして扱います。

### 9.2 初期化完了検出

現時点ではfi-65Fから「初期化完了」の専用信号を取得していません。

候補は次です。

1. 手動切替で必要タイミングを実測し、固定delayを評価
2. LEDの強い初期化発光をphototransistorで検出し、発光シーケンス終了後にOFF
3. キャリッジ位置を検出し、初期位置を離れた時点でOFF
4. driver/API側に利用可能な状態通知が見つかった場合はそれを使用

固定delayだけに依存すると環境差・driver差に弱いため、最終設計では実イベント検出を優先します。

## 10. 推奨部品構成

最小のbench prototypeは次の構成です。

| 数量 | 部品 | 用途 |
|---:|---|---|
| 1 | 15-pin FFC/FPC interposer / breakout | pin 2だけを分離 |
| 1 | P-MOSFETまたはN-MOSFET | pin 2主回路の開閉 |
| 1 | PC817/LTV-817相当フォトカプラ | scanner側と制御側の分離 |
| 1 | 100 kΩ抵抗 | MOSFET gate default状態 |
| 1 | 1 kΩ抵抗 | gate series / transient抑制 |
| 1 | 390～820 Ω抵抗 | フォトカプラLED電流制限 |
| 1 | SPSTスイッチ | 初回の手動ON/OFF試験 |
| 適量 | 細線/コネクタ | interposerと制御基板接続 |
| 任意 | phototransistor | 初期化発光検出による自動化 |
| 任意 | 小型MCU | 自動状態制御 |

MOSFET型式はpin 2の極性測定後に確定します。

## 11. レイアウト上の注意

- MOSFETはFFC interposer近傍へ配置し、pin 2の追加配線を短くする
- 他14信号と交差する長いジャンパーを避ける
- gate線は高インピーダンスなので、モータ/LED駆動配線から距離を取る
- FFCの抜き差し荷重をMOSFET基板のはんだ接合へ直接掛けない
- CIS移動部へ追加基板を載せる場合は、質量増加と干渉を確認する
- 可能であれば制御回路は固定側へ置き、移動部にはFFC/interposerだけを追加する

## 12. 現個体について

最初のジャンパー試行ではmain board側細ピッチランドを損傷し、組み戻し後に赤LEDが常時点灯する状態となりました。

そのため、この個体はMOSFET設計の検証用baselineには使用しません。

次の実装は、正常個体または修復後に正常待機/正常スキャンを再確認した個体で実施します。

## 13. 現時点の結論

- LED/導光板は初期化光量チェックに必要であり、単純撤去できない
- 機械式遮光はクリアランス不足のため採用しない
- LED board `C`は15-pin pin 2へ接続している
- **pin 2へMOSFET switchを挿入し、初期化時ON / 本スキャン時OFFとする方針**
- pin 2極性未確定のため、P-MOS high-side / N-MOS low-sideは実測後に決定する
- 細ピッチランド直付けは避け、FFC/FPC interposerを使用する
- まず手動試験で本スキャン継続を確認し、その後に自動制御へ進む
