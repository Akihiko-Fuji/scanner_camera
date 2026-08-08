# fi-65F Scanner Camera CLI v0.3

Fujitsu/Ricoh fi-65Fを、通常の原稿スキャナとしてだけでなく、外部レンズで結像した像を取得するscanner camera実験に使用するためのWindows向けCLIです。

現在は、同じ保存・設定契約を持つ2つのバックエンドを並行して保持します。

- `scanner_capture.py`: WIA診断 + WIA制御
- `twain_capture.py`: TWAIN Capability診断 + TWAIN制御

共通仕様は以下です。

- CLIまたは`config.ini`で設定
- CLI指定を`config.ini`より優先
- Driver / Data Sourceが公開する設定能力を診断
- 診断結果をJSON/TXTへ保存
- 画像を`./jpeg/DSC_0001.jpeg`形式で連番保存
- 既存画像を上書きしない排他的な採番
- strict / non-strictによる未対応設定の扱い切替
- 64-bit Windowsのみ対象

Linux/macOSは対象外です。

## 1. 動作環境

### 1.1 対象OS

本プロジェクトの実行対象は64-bit Windowsです。

想定環境：

- Windows 10 64-bit
- Windows 11 64-bit
- fi-65F用WIA/TWAINドライバーが正常にインストールされていること

実機確認済みのWIA環境では、Windows上のPython 3.9.13 64-bitからfi-65Fの認識、WIA診断、600 dpi取り込み、brightness変更、JPEG保存まで確認しています。

GitHub Actionsでは実機を接続せず、Windows x64 + Python 3.11 / 3.12で単体テストを実行します。

TWAIN実機経路は64-bit TWAIN Data Sourceと64-bit TWAIN DSMを前提としており、fi-65F実機でのCapability確認は`twain_diagnostic_*.json/.txt`を正本として扱います。

### 1.2 Python

64-bit Pythonを使用してください。

```bat
py -c "import struct; print(struct.calcsize('P') * 8)"
```

`64`と表示されることを確認します。

セットアップ：

```bat
py -m pip install -r requirements.txt
```

主な依存パッケージ：

- `pywin32`: WIA / COM制御
- `Pillow`: BMPからJPEGへの変換
- `pytwain>=2.3.0,<3.0`: TWAIN DSM / Data Source制御

### 1.3 WIA側の要件

WIA版はWindowsのWIA COMインターフェースを使用します。

必要条件：

- fi-65FがWindowsからWIA Scannerとして見えていること
- `pywin32`がインストールされていること
- 64-bit Pythonであること

確認：

```bat
py scanner_capture.py --list-devices
```

### 1.4 TWAIN側の要件

TWAIN版は`pytwain`からTWAIN Source Managerを開きます。

必要条件：

- 64-bit Python
- 64-bit TWAIN DSM (`TWAINDSM.dll`)
- 64-bit fi-65F TWAIN Data Source
- `pytwain`がインストールされていること

Python、DSM、Data Sourceのbitnessが一致しない場合、Windows上でTWAIN対応アプリからfi-65Fが使用できても、このCLIからSourceを列挙できない場合があります。

まず次を実行してください。

```bat
py twain_capture.py --list-devices
```

Sourceが列挙されない場合は、最初に64/32-bitの組み合わせを確認します。DSM自動検出で動作しない場合のみ`--dsm`または`config.ini`の`dsm_name`で明示的に指定します。

## 2. ファイル構成とコードの役割

主要ファイルは次の責務を持ちます。

```text
scanner_camera/
├─ scanner_capture.py          WIA診断・WIA制御・WIA画像取得
├─ twain_capture.py            TWAIN診断・Capability制御・TWAIN画像取得
├─ config.ini                  共通設定 + TWAIN固有設定
├─ requirements.txt            実行時依存パッケージ
├─ requirements-dev.txt        pytest等の開発依存パッケージ
├─ README.md                   動作環境・利用方法・コード構成
├─ TESTING.md                  自動試験と実機試験の責務
├─ tests/                      実機不要の単体テスト
├─ jpeg/                       DSC_####.jpeg出力先
└─ diagnostics/                WIA/TWAIN診断結果
```

### 2.1 `scanner_capture.py`

WIA経路を担当します。

主な処理：

1. WIA Scanner列挙
2. 名前の部分一致によるfi-65F選択
3. WIA Propertyの列挙
4. Propertyの範囲・リスト・read-only状態確認
5. no-change write/read-back probe
6. DPI / mode / brightness / contrast / scan region設定
7. WIA転送
8. JPEG変換
9. `DSC_####.jpeg`採番

WIA診断では、ドライバーが公開する全Propertyを記録します。WIAで公開されない設定をコード側で推測して操作することはしません。

### 2.2 `twain_capture.py`

TWAIN経路を担当します。

TWAINではWIAのPropertyとは異なり、Data Sourceが公開するCapabilityを問い合わせます。処理は概ね次の順です。

1. 64-bit TWAIN Source Managerを開く
2. TWAIN Data Sourceを列挙
3. fi-65F Sourceを選択
4. `CAP_SUPPORTEDCAPS`から公開Capability IDを取得
5. scanner cameraで重要なCapabilityを追加照会
6. `GET` / `GETCURRENT` / `GETDEFAULT` / `MSG_QUERYSUPPORT`を診断
7. 必要なCapabilityだけno-change SET/read-back probe
8. Pixel Type / DPI / brightness等を設定
9. `DAT_IMAGELAYOUT`で読み取り範囲を設定
10. native transferで1画像を取得
11. BMPを中間形式としてJPEGへ変換
12. WIA版と共通の`DSC_####.jpeg`契約で保存

TWAINではData SourceごとにCapabilityの実装状況、値型、範囲が異なるため、コード側で有効範囲を決め打ちしません。実機診断結果を確認してから値を指定する設計です。

### 2.3 共通採番処理

TWAIN版はWIA版の以下の処理を再利用します。

- `read_config()`
- `config_value()`
- `reserve_output_path()`
- `remove_empty_reservation()`

これにより、WIA/TWAINのどちらを使っても出力ファイル契約は同一です。

```text
./jpeg/DSC_0001.jpeg
./jpeg/DSC_0002.jpeg
./jpeg/DSC_0003.jpeg
```

採番時は空ファイルを排他的に作成して番号を予約し、同時実行による上書きを避けます。取り込み失敗時は空の予約ファイルだけを削除します。

## 3. WIA診断と取り込み

### 3.1 デバイス確認

```bat
py scanner_capture.py --list-devices
```

### 3.2 WIA診断

```bat
py scanner_capture.py --device fi-65F --diagnose
```

出力：

```text
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.txt
```

診断では、対象設定ごとに公開状態、read-only状態、設定可能範囲、no-change write/read-back結果を記録します。

実機では以下を確認済みです。

- X/Y解像度: 75～600 dpi
- brightness: -128～127
- contrast: -128～127
- threshold: 1～255
- 24 bit RGB出力

brightnessは画像へ影響することを確認していますが、物理的なCIS積分時間や露光時間そのものを制御しているとは断定しません。

### 3.3 WIA取り込み

```bat
py scanner_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness -128 ^
  --contrast 0
```

## 4. TWAIN診断と取り込み

### 4.1 Source確認

```bat
py twain_capture.py --list-devices
```

fi-65Fが列挙されたら、Source名の一部を`--device`へ指定できます。

### 4.2 最初のTWAIN診断

初回はData SourceへのSETを行わない診断を推奨します。

```bat
py twain_capture.py --device fi-65F --diagnose --no-probe-writes
```

出力：

```text
./diagnostics/twain_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/twain_diagnostic_YYYYMMDD_HHMMSS.txt
```

Sourceが安定して応答することを確認後、no-change write/read-back probeを実行します。

```bat
py twain_capture.py --device fi-65F --diagnose
```

### 4.3 TWAIN診断で重点確認するCapability

基本画像設定：

- `ICAP_PIXELTYPE`
- `ICAP_XRESOLUTION`
- `ICAP_YRESOLUTION`
- `ICAP_BITDEPTH`
- `ICAP_BRIGHTNESS`
- `ICAP_CONTRAST`
- `ICAP_THRESHOLD`
- `ICAP_UNITS`
- `ICAP_XFERMECH`

scanner cameraとして重要な項目：

- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_HIGHLIGHT`
- `ICAP_SHADOW`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`
- `ICAP_PHYSICALWIDTH`
- `ICAP_PHYSICALHEIGHT`
- `ICAP_XNATIVERESOLUTION`
- `ICAP_YNATIVERESOLUTION`
- `DAT_IMAGELAYOUT`

TWAIN標準にCapability名が存在することと、fi-65F/PaperStream Data Sourceが実装していることは別です。`NOT_EXPOSED_BY_TWAIN`であれば、その機能は現在のData Source経路からは使用できません。

### 4.4 TWAINの診断ステータス

代表的な状態：

- `NOT_EXPOSED_BY_TWAIN`: GET/CURRENT/DEFAULTのいずれからも取得できない
- `EXPOSED_READABLE`: 読み出せるが、SET probeをしていない
- `EXPOSED_AND_SETTABLE`: 現在値のno-change SETとread-backに成功
- `EXPOSED_BUT_WRITE_REJECTED`: 読み出せるがSETを拒否された
- `EXPOSED_SUPPORT_UNCERTAIN`: 一部の問い合わせにだけ応答した

`--no-probe-writes`では値の変更を伴う確認を行いません。

通常の`--diagnose`でも、Sourceが公開する全Capabilityへ無差別にSETすることはしません。scanner_cameraで意味があり、現在値をそのまま再設定できる対象だけをprobeします。

### 4.5 基本取り込み

```bat
py twain_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness -128 ^
  --contrast 0
```

### 4.6 TWAIN固有設定

診断でCapabilityが公開・設定可能と確認された場合だけ指定します。

```bat
py twain_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --autobright off ^
  --exposure-time 1.0 ^
  --gamma 1.0 ^
  --lamp-state off
```

対応CLI：

- `--autobright on|off`
- `--exposure-time <value>`
- `--gamma <value>`
- `--lamp-state on|off`
- `--light-source <raw-value>`
- `--bit-depth <value>`

`ICAP_EXPOSURETIME`などの単位、有効範囲、値型はData Source依存です。WIAのbrightness値やカメラのEV/シャッター速度と同じ意味だと仮定しないでください。

## 5. 読み取り範囲

WIA/TWAINともCLIではピクセル単位で指定します。

```bat
--xpos 0 --ypos 0 --width 2480 --height 3496
```

処理方法はバックエンドで異なります。

- WIA: WIA Propertyへピクセル値を設定
- TWAIN: 指定DPIでピクセルからインチへ換算し`DAT_IMAGELAYOUT`へ設定

例として600 dpiで`width=600`を指定すると、TWAINでは1.0 inch幅としてData Sourceへ設定します。

指定しない項目は現在のlayoutを維持します。

## 6. config.ini

両バックエンドは同じ`config.ini`を利用できます。

```bat
py scanner_capture.py --config config.ini
py twain_capture.py --config config.ini
```

共通設定：

```ini
[scanner]
device = fi-65F
show_ui = false
strict_settings = true

[scan]
dpi = 600
mode = color
brightness = 0
contrast = 0

[region]
xpos =
ypos =
width =
height =

[output]
directory = ./jpeg
jpeg_quality = 95

[diagnostics]
directory = ./diagnostics
probe_writes = true
```

TWAIN固有設定：

```ini
[twain]
dsm_name =
autobright =
exposure_time =
gamma =
lamp_state =
light_source =
bit_depth =
```

空欄は、可能な限りData Source / Driverの現在値を維持することを意味します。

## 7. strict / non-strict

`strict_settings = true`では、明示的に要求した設定が公開されていない、またはSETに失敗した場合に取り込みを中止します。

試験的に未対応Capabilityを無視して取得だけ継続する場合：

```bat
py twain_capture.py --non-strict
```

scanner camera用途では、設定が黙って無視されると露出比較の再現性を失うため、通常はstrictを推奨します。

## 8. 露出・LED制御の位置づけ

WIAでは、fi-65F実機の診断で物理露光時間、CIS積分時間、アナログゲイン、LED ON/OFFに相当するPropertyは確認できていません。

TWAINでは、WIAで見えなかった以下を追加確認します。

- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`

実際に使用可能かどうかは実機Data Sourceの診断結果で判断します。

`ICAP_LAMPSTATE`等が公開されない、またはSETを拒否される場合、内蔵LED停止はハード側改造の対象です。

## 9. テスト

開発用依存関係：

```bat
python -m pip install -r requirements-dev.txt
```

全テスト：

```bat
python -m pytest
```

カバレッジ：

```bat
python -m pytest ^
  --cov=scanner_capture ^
  --cov=twain_capture ^
  --cov-report=term-missing
```

WIA/TWAINとも、実機や実DSMを必要としない範囲はテストダブルで検証します。

TWAIN側では以下を自動試験対象に含みます。

- CLI引数解析
- Source Manager生成
- Source列挙・部分一致選択・曖昧一致拒否
- Capability戻り値の正規化
- `CAP_SUPPORTEDCAPS`解析
- `GET` / `GETCURRENT` / `GETDEFAULT`
- `MSG_QUERYSUPPORT`
- no-change SET/read-back probe
- strict / non-strict
- scanner camera向けCapability設定
- `DAT_IMAGELAYOUT`変換
- color / grayscale / bw JPEG変換
- native transfer callback
- `DSC_####.jpeg`連番保存
- 失敗時の空予約ファイル削除
- CLI診断フロー
- CLI通常取得フロー
- Source / Source Managerのclose

GitHub ActionsではWindows x64 + Python 3.11 / 3.12で検証します。

実機固有の次の事項はCIでは保証できません。

- fi-65F Data Sourceが実際に列挙されること
- PaperStream TWAINが公開するCapability
- `ICAP_EXPOSURETIME`等の値範囲・単位
- LED制御の可否
- 実際のnative transfer完了
- 実画像の画質・露出変化

詳細は`TESTING.md`を参照してください。

## 10. 推奨する実機確認順序

WIA：

```bat
py scanner_capture.py --list-devices
py scanner_capture.py --device fi-65F --diagnose
```

TWAIN：

```bat
py twain_capture.py --list-devices
py twain_capture.py --device fi-65F --diagnose --no-probe-writes
py twain_capture.py --device fi-65F --diagnose
```

TWAIN診断結果を確認してから、WIAと同条件で撮影比較を行います。

## 11. 参考

- TWAIN 2.x Specification: https://twain.org/specification/
- pytwain: https://pypi.org/project/pytwain/
